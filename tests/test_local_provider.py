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


class _SplitJsonResponse:
    def raise_for_status(self):
        return None

    def iter_lines(self, decode_unicode=False):
        assert decode_unicode
        event = json.dumps(
            {
                "choices": [
                    {
                        "delta": {
                            "content": "PROGRAM MAIN\nEND_PROGRAM",
                        }
                    }
                ]
            }
        )
        split_at = event.index("PROGRAM") + 7
        yield "data: " + event[:split_at]
        yield "data: " + event[split_at:]
        yield "data: [DONE]"


class _SplitLiteralResponse:
    def raise_for_status(self):
        return None

    def iter_lines(self, decode_unicode=False):
        assert decode_unicode
        yield 'data: {"choices":[{"delta":{"content":null},"finish'
        yield 'data: _reason":null}]}'
        yield "data: [DONE]"


class _Utf8Response:
    encoding = "ISO-8859-1"

    def raise_for_status(self):
        return None

    def iter_lines(self, decode_unicode=False):
        assert decode_unicode
        assert self.encoding == "utf-8"
        event = {
            "choices": [
                {
                    "delta": {
                        "content": "總啟動訊號與人工復歸",
                    }
                }
            ]
        }
        wire_data = ("data: " + json.dumps(event, ensure_ascii=False)).encode(
            "utf-8"
        )
        yield wire_data.decode(self.encoding)
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


def test_llamacpp_adapter_reassembles_split_streaming_json(monkeypatch):
    monkeypatch.setattr(
        "local_provider.requests.post",
        lambda *args, **kwargs: _SplitJsonResponse(),
    )

    chunks = list(
        LlamaCppClient("http://127.0.0.1:8082/v1").chat(
            model="Qwen3.6-27B",
            think=False,
            messages=[{"role": "user", "content": "generate"}],
            stream=True,
        )
    )

    assert chunks[0].message.content == "PROGRAM MAIN\nEND_PROGRAM"


def test_llamacpp_adapter_reassembles_split_json_literal(monkeypatch):
    monkeypatch.setattr(
        "local_provider.requests.post",
        lambda *args, **kwargs: _SplitLiteralResponse(),
    )

    chunks = list(
        LlamaCppClient("http://127.0.0.1:8082/v1").chat(
            model="Qwen3.6-27B",
            think=False,
            messages=[{"role": "user", "content": "generate"}],
            stream=True,
        )
    )

    assert chunks == []


def test_llamacpp_adapter_rejects_balanced_malformed_json(monkeypatch):
    class MalformedResponse:
        def raise_for_status(self):
            return None

        def iter_lines(self, decode_unicode=False):
            yield 'data: {"choices":]}'

    monkeypatch.setattr(
        "local_provider.requests.post",
        lambda *args, **kwargs: MalformedResponse(),
    )

    with pytest.raises(ValueError, match="malformed streaming JSON"):
        list(
            LlamaCppClient("http://127.0.0.1:8082/v1").chat(
                model="model",
                think=False,
                messages=[],
                stream=True,
            )
        )


def test_llamacpp_adapter_forces_utf8_for_chinese_stream(monkeypatch):
    monkeypatch.setattr(
        "local_provider.requests.post",
        lambda *args, **kwargs: _Utf8Response(),
    )

    chunks = list(
        LlamaCppClient("http://127.0.0.1:8082/v1").chat(
            model="Qwen3.6-27B",
            think=False,
            messages=[{"role": "user", "content": "產生程式"}],
            stream=True,
        )
    )

    assert chunks[0].message.content == "總啟動訊號與人工復歸"


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
