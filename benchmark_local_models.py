"""Repeatable PLC generation benchmark for Ollama and llama.cpp.

Examples:
  python benchmark_local_models.py --backend ollama
  python benchmark_local_models.py --backend llamacpp --base-url http://127.0.0.1:8082
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import time
from pathlib import Path

import requests

from compiler import compile_st_code
from validator import validate_st_code


ROOT = Path(__file__).resolve().parent

CASES = {
    "jog": (
        "請建立一個控制功能區塊。設定如下：\n"
        "- 啟用緊急停止: True\n"
        "- 運行模式: JOG\n"
        "- 目標速度: 1500 rpm\n"
        "- 目標位置: 100 mm\n"
        "- 方向: Forward\n"
        "極限與緊急停止由系統提供的 MC_* 函式方塊內建處理；CODE 不得直接讀寫 "
        "EStopActive、LimitPos、LimitNeg、HomeSwitch。請另外宣告一般輸入 "
        "bResetReq，並用 MC_Reset(Execute := bResetReq, Axis := Axis1) 提供人工復歸。"
    ),
    "absolute": (
        "請建立一個控制功能區塊。設定如下：\n"
        "- 啟用緊急停止: True\n"
        "- 運行模式: Absolute Position\n"
        "- 目標速度: 800 rpm\n"
        "- 目標位置: 250 mm\n"
        "- 方向: Forward\n"
        "極限與緊急停止由系統提供的 MC_* 函式方塊內建處理；CODE 不得直接讀寫 "
        "EStopActive、LimitPos、LimitNeg、HomeSwitch。請另外宣告一般輸入 "
        "bResetReq，並用 MC_Reset(Execute := bResetReq, Axis := Axis1) 提供人工復歸。"
    ),
}


def load_system_prompt() -> str:
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(
                isinstance(target, ast.Name)
                and target.id == "DEFAULT_SYSTEM_PROMPT"
                for target in node.targets
            ):
                return ast.literal_eval(node.value)
    raise RuntimeError("DEFAULT_SYSTEM_PROMPT not found in app.py")


def extract_code(text: str) -> str:
    match = re.search(
        r"### CODE\s*```(?:iec|st|structured[_ ]?text)?\s*\n(.*?)```",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    return match.group(1).strip() if match else text.strip()


def generate_ollama(args, messages):
    payload = {
        "model": args.model,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {
            "temperature": 0.2,
            "num_predict": args.max_tokens,
            "num_ctx": args.context,
        },
    }
    response = requests.post(
        f"{args.base_url.rstrip('/')}/api/chat",
        json=payload,
        timeout=args.timeout,
    )
    response.raise_for_status()
    data = response.json()
    eval_count = data.get("eval_count", 0)
    eval_seconds = data.get("eval_duration", 0) / 1e9
    return {
        "text": data["message"]["content"],
        "prompt_tokens": data.get("prompt_eval_count"),
        "completion_tokens": eval_count,
        "generation_tps": eval_count / eval_seconds if eval_seconds else None,
    }


def generate_llamacpp(args, messages):
    payload = {
        "model": args.model,
        "messages": messages,
        "stream": False,
        "temperature": 0.2,
        "max_tokens": args.max_tokens,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    response = requests.post(
        f"{args.base_url.rstrip('/')}/v1/chat/completions",
        json=payload,
        timeout=args.timeout,
    )
    response.raise_for_status()
    data = response.json()
    timings = data.get("timings") or {}
    usage = data.get("usage") or {}
    return {
        "text": data["choices"][0]["message"]["content"],
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "generation_tps": timings.get("predicted_per_second"),
        "draft_tokens": timings.get("draft_n"),
        "accepted_draft_tokens": timings.get("draft_n_accepted"),
    }


def run(args) -> dict:
    system_prompt = load_system_prompt()
    results = []
    generate = generate_ollama if args.backend == "ollama" else generate_llamacpp

    for case_name in args.cases:
        started = time.perf_counter()
        generated = generate(
            args,
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": CASES[case_name]},
            ],
        )
        elapsed = time.perf_counter() - started
        code = extract_code(generated.pop("text"))
        validation = validate_st_code(
            code,
            "Motion control with safety interlocks.",
            "motor_control",
        )
        compiled = compile_st_code(code)
        results.append(
            {
                "case": case_name,
                "elapsed_seconds": round(elapsed, 2),
                **generated,
                "validation_status": validation["status"],
                "validation_issue_count": len(validation.get("issues", [])),
                "compile_status": compiled["status"],
                "compile_issue_count": len(compiled.get("issues", [])),
                "code": code,
            }
        )

    return {
        "backend": args.backend,
        "model": args.model,
        "base_url": args.base_url,
        "context": args.context,
        "max_tokens": args.max_tokens,
        "results": results,
    }


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=("ollama", "llamacpp"), required=True)
    parser.add_argument("--base-url")
    parser.add_argument("--model")
    parser.add_argument("--context", type=int, default=8192)
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--timeout", type=float, default=1800)
    parser.add_argument(
        "--cases",
        nargs="+",
        choices=tuple(CASES),
        default=list(CASES),
    )
    args = parser.parse_args()
    if args.base_url is None:
        args.base_url = (
            "http://127.0.0.1:11434"
            if args.backend == "ollama"
            else "http://127.0.0.1:8082"
        )
    if args.model is None:
        args.model = (
            "qwen3.5:9b"
            if args.backend == "ollama"
            else "Qwen3.6-27B-Q3_K_M.gguf"
        )
    return args


if __name__ == "__main__":
    print(json.dumps(run(parse_args()), ensure_ascii=False, indent=2))
