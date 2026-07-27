"""Local model clients used by PLC-Assist.

The llama.cpp adapter intentionally mirrors the tiny subset of Ollama's
streaming response API that app.py consumes.  This keeps model selection
reversible and avoids adding an OpenAI SDK dependency.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Iterator

import requests


class LlamaCppClient:
    """Stream chat completions from llama-server's OpenAI-compatible API."""

    def __init__(self, base_url: str, timeout: float = 900.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def chat(
        self,
        *,
        model: str,
        think: bool,
        messages: list[dict],
        options: dict | None = None,
        stream: bool = True,
    ) -> Iterator[SimpleNamespace]:
        if not stream:
            raise ValueError("PLC-Assist requires streaming local responses")

        options = options or {}
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "temperature": options.get("temperature", 0.2),
            "max_tokens": options.get("num_predict", 24576),
            "chat_template_kwargs": {"enable_thinking": bool(think)},
        }
        response = requests.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            stream=True,
            timeout=self.timeout,
        )
        response.raise_for_status()

        for line in response.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            event = json.loads(data)
            choices = event.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            content = delta.get("content") or ""
            thinking = (
                delta.get("reasoning_content")
                or delta.get("reasoning")
                or ""
            )
            if content or thinking:
                yield SimpleNamespace(
                    message=SimpleNamespace(
                        content=content,
                        thinking=thinking,
                    )
                )
