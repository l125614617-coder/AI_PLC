"""Codex CLI provider for the second PLC-Assist web application.

The provider uses the user's existing Codex login, runs an ephemeral read-only
turn, and consumes JSONL events.  Only Codex-authored summaries/progress are
shown; private hidden chain-of-thought is neither requested nor exposed.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable


CODEX_MODEL = os.environ.get("PLC_ASSIST_CODEX_MODEL", "gpt-5.6-sol")
CODEX_TIMEOUT_S = int(os.environ.get("PLC_ASSIST_CODEX_TIMEOUT_S", "300"))


def _event_progress(event: dict) -> str | None:
    event_type = event.get("type")
    if event_type == "thread.started":
        return "Codex 工作階段已建立。"
    if event_type == "turn.started":
        return "Codex 正在分析 PLC 需求與輸出規範。"

    item = event.get("item") or {}
    item_type = item.get("type")
    if event_type == "item.completed" and item_type == "reasoning":
        text = (item.get("text") or "").strip()
        return text or "Codex 已完成一個推理階段。"
    if event_type == "turn.completed":
        usage = event.get("usage") or {}
        reasoning_tokens = usage.get("reasoning_output_tokens", 0)
        return f"Codex 推理完成（reasoning tokens: {reasoning_tokens}）。"
    return None


def generate_with_codex(
    system_prompt: str,
    user_prompt: str,
    on_progress: Callable[[str], None] | None = None,
) -> dict:
    """Return ``raw_text``, safe progress summaries, model, and token usage."""
    if shutil.which("codex") is None:
        raise RuntimeError("找不到 Codex CLI。請先安裝 Codex 並執行 `codex login`。")

    prompt = (
        "你是 PLC-Assist 第二版的唯讀程式生成引擎。只回答要求的內容，不要讀寫檔案、"
        "不要執行命令、不要修改工作區。請先在內部完成推理與自我檢查，再輸出最終答案。\n\n"
        "<system_instructions>\n"
        f"{system_prompt}\n"
        "</system_instructions>\n\n"
        "<user_request>\n"
        f"{user_prompt}\n"
        "</user_request>"
    )

    command = [
        "codex",
        "exec",
        "--ephemeral",
        "--ignore-user-config",
        "--sandbox",
        "read-only",
        "--model",
        CODEX_MODEL,
        "--cd",
        str(Path.cwd()),
        "--json",
        "-",
    ]

    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creation_flags,
    )
    try:
        stdout, stderr = process.communicate(prompt, timeout=CODEX_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        raise RuntimeError(f"Codex 生成逾時（{CODEX_TIMEOUT_S} 秒）。") from None

    progress: list[str] = []
    final_text = ""
    usage: dict = {}
    parse_errors = 0

    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            parse_errors += 1
            continue

        summary = _event_progress(event)
        if summary:
            progress.append(summary)
            if on_progress is not None:
                on_progress("\n\n".join(progress))

        item = event.get("item") or {}
        if event.get("type") == "item.completed" and item.get("type") == "agent_message":
            final_text = (item.get("text") or "").strip()
        if event.get("type") == "turn.completed":
            usage = event.get("usage") or {}

    if process.returncode != 0:
        detail = stderr.strip() or stdout.strip() or f"exit code {process.returncode}"
        raise RuntimeError(f"Codex CLI 執行失敗：{detail[-1200:]}")
    if not final_text:
        detail = f"（另有 {parse_errors} 行無法解析）" if parse_errors else ""
        raise RuntimeError(f"Codex 沒有回傳最終答案。{detail}")

    return {
        "raw_text": final_text,
        "thinking": "\n\n".join(progress),
        "model": CODEX_MODEL,
        "usage": usage,
    }
