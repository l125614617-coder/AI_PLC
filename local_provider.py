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


def _json_structure_open(data: str) -> bool:
    """Return whether an object/array prefix still needs closing JSON tokens."""
    stack: list[str] = []
    in_string = False
    escaped = False

    for character in data:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue

        if character == '"':
            in_string = True
        elif character in "{[":
            stack.append(character)
        elif character in "}]":
            if not stack:
                return False
            opening = stack.pop()
            if (opening, character) not in {("{", "}"), ("[", "]")}:
                return False

    return in_string or escaped or bool(stack)


def _iter_sse_json(lines) -> Iterator[dict]:
    """Decode llama.cpp SSE events, including JSON split across lines.

    llama-server normally emits one complete JSON object per ``data:`` line,
    but long-running generations can occasionally expose a partial event to
    the client. Keep incomplete JSON until the following line arrives instead
    of terminating an otherwise healthy generation.
    """
    buffered = ""

    for line in lines:
        if isinstance(line, bytes):
            line = line.decode("utf-8")
        line = line.rstrip("\r")
        if not line:
            continue

        if line.startswith("data:"):
            fragment = line[5:]
            if fragment.startswith(" "):
                fragment = fragment[1:]
        elif buffered:
            # Be tolerant of a continuation that omitted the SSE ``data:``
            # prefix. The HTTP response contains only SSE payload lines here.
            fragment = line
        else:
            continue

        if fragment.strip() == "[DONE]":
            if buffered:
                raise ValueError(
                    "llama.cpp stream ended with an incomplete JSON event"
                )
            return

        candidate = buffered + fragment
        try:
            event = json.loads(candidate)
        except json.JSONDecodeError as error:
            if _json_structure_open(candidate):
                buffered = candidate
                continue
            raise ValueError(
                "llama.cpp returned malformed streaming JSON"
            ) from error

        buffered = ""
        if isinstance(event, dict):
            yield event

    if buffered:
        raise ValueError("llama.cpp stream ended with an incomplete JSON event")


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
        # Some llama.cpp builds omit ``charset=utf-8`` from the SSE
        # Content-Type. requests then falls back to ISO-8859-1 and turns
        # Traditional Chinese into mojibake such as ``ç¸½å...``.
        response.encoding = "utf-8"

        events = _iter_sse_json(response.iter_lines(decode_unicode=True))
        for event in events:
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
