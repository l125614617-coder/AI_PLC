import json

import pytest

from local_provider import LlamaCppClient


class _FakeResponse:
    def raise_for_status(self):
        return None

    def iter_lines(self, decode_unicode=False):
        assert decode_unicode
        events = [
            {"choices": [{"delta": {"reasoning_content": "plan"}}]},
            {"choices": [{"delta": {"content": "PROGRAM MAIN"}}]},
        ]
        for event in events:
            yield "data: " + json.dumps(event)
        yield "data: [DONE]"


def test_llamacpp_adapter_maps_stream_to_ollama_shape(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return _FakeResponse()

    monkeypatch.setattr("local_provider.requests.post", fake_post)
    chunks = list(
        LlamaCppClient("http://127.0.0.1:8082/v1").chat(
            model="Qwen3.6-27B",
            think=False,
            messages=[{"role": "user", "content": "generate"}],
            options={"temperature": 0.1, "num_predict": 123},
            stream=True,
        )
    )

    assert captured["url"] == "http://127.0.0.1:8082/v1/chat/completions"
    assert captured["json"]["max_tokens"] == 123
    assert captured["json"]["chat_template_kwargs"]["enable_thinking"] is False
    assert chunks[0].message.thinking == "plan"
    assert chunks[1].message.content == "PROGRAM MAIN"


def test_llamacpp_adapter_rejects_non_streaming():
    with pytest.raises(ValueError):
        list(
            LlamaCppClient("http://127.0.0.1:8082/v1").chat(
                model="model",
                think=False,
                messages=[],
                stream=False,
            )
        )
