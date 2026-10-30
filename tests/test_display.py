"""The Display tab's server half: which pages may be shown, and the history of them."""
import unittest
from types import SimpleNamespace

from cltl.chatui.display import DisplayLog

from tests.support import (DISPLAY_TOPIC, ServiceHarness, publish_display, start_scenario,
                           stop_scenario)


class DisplayLogTest(unittest.TestCase):
    def setUp(self):
        self.log = DisplayLog(3, ["Example.org", " trusted.test "])

    def urls(self):
        return [entry.url for entry in self.log.entries]

    def test_local_hosts_are_always_allowed(self):
        for url in ("http://localhost:8000/x", "https://127.0.0.1/", "http://[::1]:9000/"):
            with self.subTest(url=url):
                self.assertTrue(DisplayLog().is_allowed(url))

    def test_listed_hosts_are_allowed_regardless_of_case(self):
        self.assertTrue(self.log.is_allowed("https://EXAMPLE.org/page"))
        self.assertTrue(self.log.is_allowed("http://trusted.test:81/"))

    def test_other_hosts_are_not(self):
        self.assertFalse(self.log.is_allowed("https://evil.example/"))
        self.assertFalse(self.log.is_allowed("https://sub.example.org/"))

    def test_only_http_and_https_are_shown(self):
        for url in ("javascript:alert(1)", "data:text/html,<b>x</b>", "file:///etc/passwd",
                    "ftp://localhost/", "//localhost/", "localhost", ""):
            with self.subTest(url=url):
                self.assertFalse(self.log.is_allowed(url))

    def test_credentials_cannot_pose_as_a_host(self):
        self.assertFalse(self.log.is_allowed("http://localhost@evil.example/"))
        self.assertFalse(self.log.is_allowed("http://localhost:pw@example.org/"))

    def test_a_bad_port_is_rejected_rather_than_raised(self):
        self.assertFalse(self.log.is_allowed("http://localhost:notaport/"))

    def test_a_rejected_url_is_not_added_and_uses_no_sequence(self):
        self.assertIsNone(self.log.add("javascript:alert(1)", "bad"))

        self.assertEqual([], self.log.entries)
        self.assertEqual(-1, self.log.last_sequence)

    def test_the_newest_page_is_last(self):
        self.log.add("http://localhost/a", "A")
        self.log.add("http://localhost/b", "B")

        self.assertEqual("B", self.log.latest().name)
        self.assertEqual(["http://localhost/a", "http://localhost/b"], self.urls())

    def test_showing_a_url_again_moves_it_to_the_end(self):
        self.log.add("http://localhost/a", "A")
        self.log.add("http://localhost/b", "B")
        self.log.add("http://localhost/a", "A again")

        self.assertEqual(["http://localhost/b", "http://localhost/a"], self.urls())
        self.assertEqual("A again", self.log.latest().name)
        self.assertEqual(2, self.log.last_sequence)

    def test_the_oldest_page_goes_when_full(self):
        for name in "abcd":
            self.log.add("http://localhost/" + name, name)

        self.assertEqual(["http://localhost/" + name for name in "bcd"], self.urls())

    def test_clear_forgets_the_pages_but_sequences_keep_counting(self):
        self.log.add("http://localhost/a", "A")
        self.log.clear()

        self.assertIsNone(self.log.latest())
        self.assertEqual(0, self.log.last_sequence)
        self.assertEqual(1, self.log.add("http://localhost/a", "A").sequence)

    def test_since_returns_only_newer_entries(self):
        self.log.add("http://localhost/a", "A")
        self.log.add("http://localhost/b", "B")

        self.assertEqual(["B"], [entry.name for entry in self.log.since(1)])


class DisplayServiceTest(unittest.TestCase):
    def start(self, **kwargs):
        kwargs.setdefault("display_topic", DISPLAY_TOPIC)
        harness = ServiceHarness(**kwargs)
        self.addCleanup(harness.stop)

        return harness

    def test_it_is_off_without_a_topic(self):
        harness = self.start(display_topic=None)

        self.assertFalse(harness.client.get("/config").get_json()["display_enabled"])
        self.assertEqual(404, harness.client.get("/chat/display").status_code)

    def test_it_reports_when_on(self):
        self.assertTrue(self.start().client.get("/config").get_json()["display_enabled"])

    def test_a_page_of_the_active_scenario_is_kept(self):
        harness = self.start()
        scenario = start_scenario(harness.event_bus)
        harness.await_scenario()

        publish_display(harness.event_bus, scenario.id, "http://localhost:8000/x", "Chart")
        display = harness.await_display(1)

        self.assertEqual([{"sequence": 0, "url": "http://localhost:8000/x", "name": "Chart"}],
                         display["entries"])
        self.assertEqual(scenario.id, display["scenario_id"])

    def test_pages_are_listed_oldest_first_and_a_repeat_moves(self):
        harness = self.start()
        scenario = start_scenario(harness.event_bus)
        harness.await_scenario()

        publish_display(harness.event_bus, scenario.id, "http://localhost/a", "A")
        publish_display(harness.event_bus, scenario.id, "http://localhost/b", "B")
        publish_display(harness.event_bus, scenario.id, "http://localhost/a", "A")
        display = harness.await_display(2)

        self.assertEqual(["B", "A"], [entry["name"] for entry in display["entries"]])
        self.assertEqual(2, display["last_sequence"])

    def test_other_scenarios_unscoped_and_early_events_are_dropped(self):
        harness = self.start()
        publish_display(harness.event_bus, "whatever", "http://localhost/early", "early")
        scenario = start_scenario(harness.event_bus)
        harness.await_scenario()

        publish_display(harness.event_bus, "another-scenario", "http://localhost/other", "other")
        publish_display(harness.event_bus, None, "http://localhost/unscoped", "unscoped")
        publish_display(harness.event_bus, scenario.id, "http://localhost/right", "right")

        display = harness.await_display(1)
        self.assertEqual(["right"], [entry["name"] for entry in display["entries"]])

    def test_a_url_that_may_not_be_shown_never_reaches_the_page(self):
        harness = self.start()
        scenario = start_scenario(harness.event_bus)
        harness.await_scenario()

        publish_display(harness.event_bus, scenario.id, "https://evil.example/", "not allowed")
        publish_display(harness.event_bus, scenario.id, "http://localhost/ok", "ok")

        self.assertEqual(["ok"], [e["name"] for e in harness.await_display(1)["entries"]])

    def test_hosts_from_configuration_are_allowed(self):
        harness = self.start(display_allowed_hosts=["example.org, other.test"])
        scenario = start_scenario(harness.event_bus)
        harness.await_scenario()

        publish_display(harness.event_bus, scenario.id, "https://other.test/p", "listed")

        self.assertEqual(["listed"], [e["name"] for e in harness.await_display(1)["entries"]])

    def test_a_payload_delivered_as_a_namespace_is_read(self):
        """The kombu bus does not rebuild the dataclass."""
        harness = self.start()
        scenario = start_scenario(harness.event_bus)
        harness.await_scenario()

        publish_display(harness.event_bus, scenario.id, None,
                        payload=SimpleNamespace(url="http://localhost/ns", name="namespace"))

        self.assertEqual(["namespace"], [e["name"] for e in harness.await_display(1)["entries"]])

    def test_a_payload_without_a_url_is_dropped(self):
        harness = self.start()
        scenario = start_scenario(harness.event_bus)
        harness.await_scenario()

        publish_display(harness.event_bus, scenario.id, None, payload=SimpleNamespace(name="no url"))
        publish_display(harness.event_bus, scenario.id, "http://localhost/ok", "ok")

        self.assertEqual(["ok"], [e["name"] for e in harness.await_display(1)["entries"]])

    def test_history_is_cleared_when_the_scenario_stops(self):
        harness = self.start()
        scenario = start_scenario(harness.event_bus)
        harness.await_scenario()
        publish_display(harness.event_bus, scenario.id, "http://localhost/a", "A")
        harness.await_display(1)

        stop_scenario(harness.event_bus, scenario)
        harness.await_no_scenario()

        display = harness.display()
        self.assertEqual([], display["entries"])
        self.assertIsNone(display["scenario_id"])


class DisplayEventTest(unittest.TestCase):
    def test_a_display_needs_a_url_and_a_name(self):
        from cltl.combot.event.display import DisplayEvent

        for url, name in (("", "n"), ("  ", "n"), ("http://localhost/", ""), (None, "n")):
            with self.subTest(url=url, name=name):
                with self.assertRaises(ValueError):
                    DisplayEvent(url, name)


if __name__ == "__main__":
    unittest.main()
