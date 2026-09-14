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

    def test_scheduled_topics_keep_the_intended_mix(self):
        first_day = automation.datetime(2026, 9, 14, 9, tzinfo=automation.ET)
        topics = []
        for day in range(10):
            for hour in (9, 12, 18):
                topics.append(automation.scheduled_topic(first_day.replace(day=first_day.day + day, hour=hour)))
        self.assertEqual(topics.count("a recent practical AI idea"), 15)
        self.assertEqual(topics.count("a funny everyday AI observation"), 9)
        self.assertEqual(topics.count("robotics or humanoid technology"), 6)

    def test_daily_reply_limit_counts_reserved_and_sent_replies(self):
        state = automation.default_state()
        day = "2026-09-14"
        for index in range(automation.MAX_AUTOMATED_REPLIES_PER_DAY):
            state["replies"][str(index)] = {"status": "reserved", "reply_day": day}
        self.assertEqual(automation.reply_count_for_day(state, day), automation.MAX_AUTOMATED_REPLIES_PER_DAY)

    def test_reply_classifier_accepts_only_explicit_reply_decision(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
            writer = automation.Writer()
        writer.text = Mock(return_value="REPLY")
        self.assertTrue(writer.should_reply("What practical tool would you use?"))
        writer.text = Mock(return_value="SKIP")
        self.assertFalse(writer.should_reply("Nice!"))

    def test_image_post_has_a_public_image_url(self):
        with patch.dict(os.environ, {"THREADS_ACCESS_TOKEN": "test-token"}):
            api = automation.Meta()
        api.call = Mock(return_value={"id": "container"})
        api.create_post("1", "caption", image_url="https://raw.githubusercontent.com/example/image.png")
        self.assertEqual(api.call.call_args.kwargs["media_type"], "IMAGE")
        self.assertEqual(api.call.call_args.kwargs["image_url"], "https://raw.githubusercontent.com/example/image.png")

    def test_manual_post_time_can_select_a_topic(self):
        manual_time = automation.datetime(2026, 9, 14, 0, tzinfo=automation.ET)
        self.assertIn(automation.scheduled_topic(manual_time), automation.POST_TOPICS)


if __name__ == "__main__":
    unittest.main()
