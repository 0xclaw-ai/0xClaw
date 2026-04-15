from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "0xclaw"))

import main


class MainHandoffTests(unittest.TestCase):
    def test_subagent_started_message_counts_as_background_handoff(self) -> None:
        self.assertTrue(
            main._is_background_handoff_progress(
                "Subagent [coder] started (id: abc123, backend=default_llm). I'll notify you when it completes."
            )
        )

    def test_spawn_tool_hint_does_not_count_as_background_handoff(self) -> None:
        self.assertFalse(main._is_background_handoff_progress('spawn("coder-E5-API前端")'))

    def test_other_progress_messages_do_not_count_as_handoff(self) -> None:
        self.assertFalse(main._is_background_handoff_progress("message(\"E5 已启动 ~\")"))


if __name__ == "__main__":
    unittest.main()
