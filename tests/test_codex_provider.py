import json
from unittest.mock import patch

from codex_provider import _event_progress, generate_with_codex


class FakeProcess:
    returncode = 0

    def communicate(self, prompt, timeout):
        assert "<system_instructions>" in prompt
        assert "<user_request>" in prompt
        events = [
            {"type": "thread.started", "thread_id": "test"},
            {"type": "turn.started"},
            {
                "type": "item.completed",
                "item": {"type": "reasoning", "text": "已檢查輸出格式。"},
            },
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": "### CODE\n```st\nPROGRAM MAIN\nEND_PROGRAM\n```"},
            },
            {
                "type": "turn.completed",
                "usage": {"input_tokens": 10, "output_tokens": 20, "reasoning_output_tokens": 5},
            },
        ]
        return "\n".join(json.dumps(event, ensure_ascii=False) for event in events), ""


def test_generate_with_codex_extracts_final_message_progress_and_usage():
    updates = []
    with patch("codex_provider.subprocess.Popen", return_value=FakeProcess()):
        result = generate_with_codex("system", "user", updates.append)

    assert result["raw_text"].startswith("### CODE")
    assert "已檢查輸出格式" in result["thinking"]
    assert result["usage"]["reasoning_output_tokens"] == 5
    assert updates


def test_private_event_types_are_not_exposed_as_progress():
    assert _event_progress({"type": "private_chain_of_thought", "text": "secret"}) is None
