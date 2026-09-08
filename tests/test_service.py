"""The text half of the chat UI's REST API.

Pins down the behaviour the image routes have to fit into: the chat id is minted
by the service and enforced on every request, an utterance posted over HTTP
becomes an event on the utterance topic, and an agent's reply arriving on the
response topic becomes an utterance attributed to the agent.
"""
import unittest

from cltl.chatui.memory import MemoryImageStore
from cltl.combot.infra.event import Event

from tests.support import (RESPONSE_TOPIC, UTTERANCE_TOPIC, Listener, ServiceHarness,
                           agent_response, start_scenario)


class ChatUITest(unittest.TestCase):
    def setUp(self):
        self.harness = None

    def tearDown(self):
        if self.harness:
            self.harness.stop()

    def start(self, **kwargs) -> ServiceHarness:
        self.harness = ServiceHarness(**kwargs)

        return self.harness

    def test_current_chat_mints_an_id(self):
        harness = self.start()

        payload = harness.current()

        self.assertTrue(payload["id"])
        self.assertEqual("Leolani", payload["agent"])
        self.assertIsNone(payload["scenario_id"])

    def test_scenario_event_reaches_the_service(self):
        harness = self.start()

        scenario = start_scenario(harness.event_bus)

        self.assertEqual(scenario.id, harness.await_scenario())

    def test_posted_utterance_is_published(self):
        harness = self.start()
        start_scenario(harness.event_bus)
        harness.await_scenario()
        listener = Listener(harness.event_bus, UTTERANCE_TOPIC)
        chat_id = harness.chat_id()

        response = harness.client.post(f"/chat/{chat_id}", data="bla bla bla")

        self.assertEqual(200, response.status_code)
        event = listener.await_event()
        self.assertEqual("TextSignalEvent", event.payload.type)
        self.assertEqual("bla bla bla", event.payload.signal.text)

    def test_posted_utterance_is_in_the_transcript(self):
        harness = self.start()
        start_scenario(harness.event_bus)
        harness.await_scenario()
        chat_id = harness.chat_id()

        harness.client.post(f"/chat/{chat_id}", data="bla bla bla")

        utterances = harness.await_utterances(chat_id, 1)
        self.assertEqual(["bla bla bla"], [utterance["text"] for utterance in utterances])
        self.assertEqual("text/plain", utterances[0]["content_type"])

    def test_agent_response_is_attributed_to_the_agent(self):
        harness = self.start()
        scenario = start_scenario(harness.event_bus)
        harness.await_scenario()
        chat_id = harness.chat_id()

        harness.event_bus.publish(
            RESPONSE_TOPIC, Event.for_payload(agent_response(scenario.id, "response text")))

        utterances = harness.await_utterances(chat_id, 1)
        self.assertEqual([("Leolani", "response text")],
                         [(utterance["speaker"], utterance["text"]) for utterance in utterances])

    def test_utterances_are_filtered_by_speaker(self):
        harness = self.start()
        scenario = start_scenario(harness.event_bus)
        harness.await_scenario()
        chat_id = harness.chat_id()
        harness.client.post(f"/chat/{chat_id}", data="bla bla bla")
        harness.event_bus.publish(
            RESPONSE_TOPIC, Event.for_payload(agent_response(scenario.id, "response text")))

        everything = harness.await_utterances(chat_id, 2)
        agent_only = harness.client.get(f"/chat/{chat_id}?speaker=Leolani").get_json()

        self.assertEqual(2, len(everything))
        self.assertEqual(["response text"], [utterance["text"] for utterance in agent_only])

    def test_a_wrong_chat_id_is_rejected(self):
        harness = self.start()
        start_scenario(harness.event_bus)
        harness.await_scenario()
        harness.chat_id()

        self.assertEqual(404, harness.client.post("/chat/not-a-chat-id", data="hello").status_code)

    def test_posting_without_a_scenario_fails(self):
        """The known rough edge in the text path: a bare ValueError, hence a 500."""
        harness = self.start()
        chat_id = harness.chat_id()

        self.assertEqual(500, harness.client.post(f"/chat/{chat_id}", data="hello").status_code)

    def test_terminate_is_a_no_op_without_a_timeout(self):
        harness = self.start()

        self.assertEqual(404, harness.client.delete("/chat/terminate").status_code)

    def test_serves_its_static_files(self):
        """Every asset chat.html references, including the vendored ones.

        These are the files `setup.py`'s `package_data` ladder has to reach; a
        missing one is invisible until somebody opens the page.
        """
        harness = self.start()

        for path in ("static/chat.html", "static/chat.js", "static/chat.css",
                     "static/annotate.js", "static/annotate.css",
                     "static/panels.js", "static/panels.css",
                     "static/annotorious/annotorious.js", "static/annotorious/annotorious.css",
                     "static/chat-bubble/component/Bubbles.js",
                     "static/chat-bubble/component/styles/setup.css"):
            with self.subTest(path=path):
                self.assertEqual(200, harness.client.get(path).status_code)

    def test_the_page_references_only_local_assets(self):
        """No CDN: the page has to work on a machine with no outbound network."""
        harness = self.start()

        page = harness.client.get("static/chat.html").get_data(as_text=True)

        self.assertNotIn("http://", page)
        self.assertNotIn("https://", page)



class ConfigTest(unittest.TestCase):
    """What the page is told about the deployment it is running in."""

    def start(self, **kwargs):
        harness = ServiceHarness(**kwargs)
        self.addCleanup(harness.stop)

        return harness

    def test_it_reports_the_monitoring_url(self):
        harness = self.start(monitoring_url="/monitoring")

        self.assertEqual("/monitoring", harness.client.get("/config").get_json()["monitoring_url"])

    def test_no_monitoring_url_is_reported_as_null(self):
        """The page leaves the tab out entirely rather than framing nothing."""
        harness = self.start(monitoring_url="")

        self.assertIsNone(harness.client.get("/config").get_json()["monitoring_url"])

    def test_it_reports_whether_upload_is_enabled(self):
        self.assertTrue(self.start(image_store=MemoryImageStore())
                        .client.get("/config").get_json()["image_upload"])
        self.assertFalse(self.start().client.get("/config").get_json()["image_upload"])


class CurrentScenarioTest(unittest.TestCase):
    def start(self, **kwargs):
        harness = ServiceHarness(**kwargs)
        self.addCleanup(harness.stop)

        return harness

    def test_it_reports_no_scenario_before_one_starts(self):
        harness = self.start()

        self.assertIsNone(harness.client.get("/chat/scenario").get_json()["scenario_id"])

    def test_it_reports_the_running_scenario(self):
        harness = self.start()
        scenario = start_scenario(harness.event_bus)
        harness.await_scenario()

        self.assertEqual(scenario.id,
                         harness.client.get("/chat/scenario").get_json()["scenario_id"])

    def test_it_does_not_reset_the_inactivity_timeout(self):
        """A poller on this route must not keep a chat alive indefinitely.

        `/chat/current` bumps the chat's last-modified timestamp on every call,
        which is why the page cannot poll that one: the timeout would never fire
        while a browser had the page open.
        """
        harness = self.start(timeout=1)
        harness.chat_id()
        before = harness.chats.current_chat(False)[2]

        harness.client.get("/chat/scenario")

        self.assertEqual(before, harness.chats.current_chat(False)[2])


if __name__ == '__main__':
    unittest.main()
