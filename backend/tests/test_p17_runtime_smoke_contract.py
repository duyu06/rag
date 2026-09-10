from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class P17RuntimeSmokeContractsTest(unittest.TestCase):
    def test_release_smoke_exercises_real_conversation_sse(self):
        script = (ROOT / "scripts/release_smoke.py").read_text(encoding="utf-8")
        self.assertIn('"--stream"', script)
        self.assertIn('f"/conversations/{conversation_id}/messages/stream"', script)
        self.assertIn('"Accept": "text/event-stream"', script)
        self.assertIn("response.readline()", script)
        self.assertIn('event == "token"', script)
        self.assertIn('event == "done"', script)
        self.assertIn('event == "error"', script)

    def test_release_smoke_checks_incremental_delivery_and_persistence(self):
        script = (ROOT / "scripts/release_smoke.py").read_text(encoding="utf-8")
        self.assertIn("len(token_chunks) >= min_token_events", script)
        self.assertIn("first_token_seconds < done_seconds", script)
        self.assertIn('timings.get("native_stream") is True', script)
        self.assertIn("message.get(\"id\") == message_id", script)
        self.assertIn("streamed_text == persisted_text", script)
        self.assertIn("restored_message.get(\"status\") == \"completed\"", script)
        self.assertIn("restored_message.get(\"sources\")", script)
        self.assertIn('trace_timings.get("native_stream") is True', script)

    def test_ttft_sla_is_optional_and_hardware_specific(self):
        script = (ROOT / "scripts/release_smoke.py").read_text(encoding="utf-8")
        self.assertIn('"--max-ttft"', script)
        self.assertIn("default=0.0", script)
        self.assertIn("if max_ttft > 0:", script)
        self.assertIn("TTFT", script)


if __name__ == "__main__":
    unittest.main()
