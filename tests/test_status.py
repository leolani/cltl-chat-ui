"""The status bar's server half: which events are kept, and which one the bar shows."""
import unittest

from cltl.chatui.status import StatusLog
from cltl.combot.event.status import StatusEvent

from tests.support import (STATUS_TOPIC, _await, ServiceHarness, publish_status, start_scenario,
                           stop_scenario)


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class StatusLogTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.log = StatusLog(3, self.clock)

    def message(self):
        current = self.log.current()
        return current.message if current else None

    def test_newest_wins_at_equal_level(self):
        self.log.add("a", "x")
        self.log.add("b", "x")

        self.assertEqual("b", self.message())

    def test_higher_level_beats_newer(self):
        self.log.add("bad", "x", "error")
        self.log.add("fine", "x", "info")

        self.assertEqual("bad", self.message())

    def test_ttl_expires_from_receipt(self):
        self.log.add("short", "x", ttl=5)
        self.clock.now += 4.9
        self.assertEqual("short", self.message())
        self.clock.now += 0.2

        self.assertIsNone(self.message())

    def test_expired_falls_back_to_the_previous_one(self):
        self.log.add("steady", "x")
        self.log.add("blip", "x", "warning", ttl=1)
        self.clock.now += 2

        self.assertEqual("steady", self.message())

    def test_resolved_ends_the_status_but_stays_in_the_timeline(self):
        self.log.add("loading", "asr", key="asr.load")
        self.log.add("loaded", "asr", key="asr.load", resolved=True)

        self.assertIsNone(self.log.current())
        self.assertEqual(["loading", "loaded"], [e.message for e in self.log.since(0)])

    def test_resolved_falls_back_to_another_status(self):
        self.log.add("steady", "vad")
        self.log.add("loading", "asr", "warning", key="asr.load")
        self.log.add("loaded", "asr", key="asr.load", resolved=True)

        self.assertEqual("steady", self.message())

    def test_same_key_replaces_in_the_bar(self):
        self.log.add("loading 10%", "asr", "error", progress=.1, key="asr.load")
        self.log.add("loading 50%", "asr", "info", progress=.5, key="asr.load")

        self.assertEqual("loading 50%", self.message())

    def test_resolve_of_unknown_key_is_only_a_row(self):
        self.log.add("steady", "vad")
        self.log.add("done", "asr", key="never.seen", resolved=True)

        self.assertEqual("steady", self.message())
        self.assertEqual(2, len(self.log.since(0)))

    def test_reopening_after_resolve(self):
        self.log.add("loading", "asr", key="k")
        self.log.add("loaded", "asr", key="k", resolved=True)
        self.log.add("loading again", "asr", key="k")

        self.assertEqual("loading again", self.message())

    def test_ring_is_bounded_and_sequence_keeps_counting(self):
        for i in range(5):
            self.log.add(str(i), "x")

        self.assertEqual(["2", "3", "4"], [e.message for e in self.log.since(0)])
        self.assertEqual(4, self.log.last_sequence)
        self.assertEqual(["4"], [e.message for e in self.log.since(4)])

    def test_clear_keeps_sequence_counting(self):
        self.log.add("a", "x")
        self.log.clear()
        self.log.add("b", "x")

        self.assertEqual([1], [e.sequence for e in self.log.since(0)])


class PersistentStatusLogTest(unittest.TestCase):
    def setUp(self):
        self.log = StatusLog(10, FakeClock())

    def test_a_persistent_entry_is_a_row_and_never_the_bar(self):
        self.log.add("kept", "x", level="error", persistent=True)

        self.assertIsNone(self.log.current())
        self.assertTrue(self.log.since(0)[0].to_dict()["persistent"])

    def test_its_key_neither_replaces_nor_ends_a_status(self):
        self.log.add("working", "x", key="k")
        self.log.add("kept", "x", key="k", persistent=True)

        self.assertEqual("working", self.log.current().message)


class StatusEventTest(unittest.TestCase):
    def test_validation(self):
        for kwargs in ({"level": "fatal"}, {"progress": 1.5}, {"ttl": -1}, {"resolved": True}):
            with self.subTest(**kwargs):
                with self.assertRaises(ValueError):
                    StatusEvent("m", "s", **kwargs)

        StatusEvent("m", "s", key="k", resolved=True)


class StatusServiceTest(unittest.TestCase):
    def start(self, **kwargs):
        kwargs.setdefault("status_topic", STATUS_TOPIC)
        harness = ServiceHarness(**kwargs)
        self.addCleanup(harness.stop)

        return harness

    def test_it_is_off_without_a_topic(self):
        harness = self.start(status_topic=None)

        self.assertFalse(harness.client.get("/config").get_json()["status_enabled"])
        self.assertEqual(404, harness.client.get("/chat/status").status_code)

    def test_it_reports_when_on(self):
        self.assertTrue(self.start().client.get("/config").get_json()["status_enabled"])

    def test_status_of_the_active_scenario_is_kept(self):
        harness = self.start()
        scenario = start_scenario(harness.event_bus)
        harness.await_scenario()

        publish_status(harness.event_bus, scenario.id, "loading", "asr", level="warning", key="k")
        status = harness.await_status(1)

        self.assertEqual("loading", status["current"]["message"])
        self.assertEqual("asr", status["events"][0]["source"])
        self.assertEqual(0, status["last_sequence"])

    def test_from_returns_only_newer_rows(self):
        harness = self.start()
        scenario = start_scenario(harness.event_bus)
        harness.await_scenario()
        publish_status(harness.event_bus, scenario.id, "one")
        publish_status(harness.event_bus, scenario.id, "two")
        harness.await_status(2)

        self.assertEqual(["two"], [e["message"] for e in harness.status(1)["events"]])

    def test_other_scenarios_unscoped_and_early_events_are_dropped(self):
        harness = self.start()
        publish_status(harness.event_bus, "whatever", "before any scenario")
        scenario = start_scenario(harness.event_bus)
        harness.await_scenario()

        publish_status(harness.event_bus, "another-scenario", "wrong one")
        publish_status(harness.event_bus, None, "no scenario id")
        publish_status(harness.event_bus, scenario.id, "right one")

        status = harness.await_status(1)
        self.assertEqual(["right one"], [e["message"] for e in status["events"]])

    def test_timeline_is_cleared_when_the_scenario_stops(self):
        harness = self.start()
        scenario = start_scenario(harness.event_bus)
        harness.await_scenario()
        publish_status(harness.event_bus, scenario.id, "hello")
        harness.await_status(1)

        stop_scenario(harness.event_bus, scenario)
        harness.await_no_scenario()

        status = harness.status()
        self.assertEqual([], status["events"])
        self.assertIsNone(status["current"])

    def persistent(self, harness, scenario, message="Went offline", source="asr", **kwargs):
        publish_status(harness.event_bus, scenario.id, message, source, persistent=True, **kwargs)

    def test_a_persistent_status_lands_in_the_chat_and_not_the_bar(self):
        harness = self.start()
        scenario = start_scenario(harness.event_bus)
        harness.await_scenario()
        chat_id = harness.chat_id()

        self.persistent(harness, scenario, level="warning")

        utterance, = harness.await_utterances(chat_id, 1)
        self.assertEqual("text/html", utterance["content_type"])
        self.assertEqual("", utterance["speaker"])
        self.assertIn("Went offline", utterance["text"])
        self.assertIn("cltl-status-warning", utterance["text"])
        status = harness.status()
        self.assertIsNone(status["current"])
        self.assertTrue(status["events"][0]["persistent"])

    def test_the_markup_of_a_persistent_status_is_escaped(self):
        harness = self.start()
        scenario = start_scenario(harness.event_bus)
        harness.await_scenario()
        chat_id = harness.chat_id()

        self.persistent(harness, scenario, "<script>alert(1)</script>", "<b>src</b>")

        text = harness.await_utterances(chat_id, 1)[0]["text"]
        self.assertNotIn("<script>", text)
        self.assertNotIn("<b>", text)
        self.assertIn("&lt;script&gt;", text)

    def test_a_persistent_status_is_ordered_among_the_utterances(self):
        harness = self.start()
        scenario = start_scenario(harness.event_bus)
        harness.await_scenario()
        chat_id = harness.chat_id()
        harness.client.post(f"/chat/{chat_id}", data="before")
        harness.await_utterances(chat_id, 1)

        self.persistent(harness, scenario)
        harness.await_utterances(chat_id, 2)
        harness.client.post(f"/chat/{chat_id}", data="after")

        texts = [u["text"] for u in harness.await_utterances(chat_id, 3)]
        self.assertEqual("before", texts[0])
        self.assertIn("Went offline", texts[1])
        self.assertEqual("after", texts[2])

    def test_a_persistent_status_creates_the_chat_and_survives_the_scenario(self):
        harness = self.start()
        scenario = start_scenario(harness.event_bus)
        harness.await_scenario()

        self.persistent(harness, scenario)
        chat_id = _await(lambda: harness.chats.current_chat(False)[0], 5.0, "no chat was created")
        harness.await_utterances(chat_id, 1)
        stop_scenario(harness.event_bus, scenario)
        harness.await_no_scenario()

        # The chat ends with its scenario and is no longer served, but the status
        # line is part of it like any utterance, not cleared like the timeline.
        self.assertEqual(1, len(list(harness.chats.get_utterances(chat_id))))

    def test_a_persistent_status_of_another_scenario_is_dropped(self):
        harness = self.start()
        scenario = start_scenario(harness.event_bus)
        harness.await_scenario()
        chat_id = harness.chat_id()

        publish_status(harness.event_bus, "another", "nope", persistent=True)
        self.persistent(harness, scenario, "yes")

        utterances = harness.await_utterances(chat_id, 1)
        self.assertEqual(1, len(utterances))
        self.assertIn("yes", utterances[0]["text"])

    def test_a_persistent_status_does_not_reset_the_inactivity_timeout(self):
        harness = self.start(timeout=1)
        scenario = start_scenario(harness.event_bus)
        harness.await_scenario()
        chat_id = harness.chat_id()
        before = harness.chats.current_chat(False)[2]

        self.persistent(harness, scenario)
        harness.await_utterances(chat_id, 1)

        self.assertEqual(before, harness.chats.current_chat(False)[2])

    def test_polling_does_not_reset_the_inactivity_timeout(self):
        harness = self.start(timeout=1)
        harness.chat_id()
        before = harness.chats.current_chat(False)[2]

        harness.client.get("/chat/status")

        self.assertEqual(before, harness.chats.current_chat(False)[2])


if __name__ == "__main__":
    unittest.main()
