import os
import unittest
from unittest.mock import Mock, patch

import threads_automation as automation


class AutomationSafetyTests(unittest.TestCase):
    def test_obvious_spam_is_skipped(self):
        self.assertTrue(automation.obvious_spam("Earn $500 today — click here"))
        self.assertFalse(automation.obvious_spam("That robot joke made my day."))

    def test_wrong_account_blocks_automation(self):
        with patch.dict(os.environ, {"THREADS_ACCESS_TOKEN": "test-token"}):
            api = automation.Meta()
        api.call = Mock(return_value={"id": "1", "username": "someoneelse"})
        with self.assertRaisesRegex(RuntimeError, "Wrong Threads account"):
            api.identity()

    def test_outside_schedule_does_not_post(self):
        fake_time = Mock(hour=7)
        with patch.object(automation, "now_et", return_value=fake_time):
            automation.run_post()

    def test_existing_slot_blocks_duplicate(self):
        fake_time = Mock(hour=9)
        fake_time.strftime.return_value = "2026-09-14-"
        state = automation.default_state()
        state["scheduled_slots"]["2026-09-14-9"] = {"status": "posted"}
        with patch.object(automation, "now_et", return_value=fake_time), patch.object(automation, "load_state", return_value=state), patch.object(automation, "Meta") as meta:
            automation.run_post()
        meta.assert_not_called()

    def test_openai_key_never_appears_in_safe_output(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "secret-openai-key"}):
            self.assertNotIn("secret-openai-key", automation.safe("Authorization: secret-openai-key"))


if __name__ == "__main__":
    unittest.main()
