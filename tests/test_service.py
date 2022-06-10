import threading
import time
import unittest
from queue import Queue

from cltl.combot.infra.event import Event
from cltl.combot.infra.event.memory import SynchronousEventBus
from cltl.combot.event.emissor import TextSignalEvent

from cltl.chatui.memory import MemoryChats
from cltl_service.chatui.service import ChatUiService


class ChatUITest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = None

    def tearDown(self) -> None:
        if self.service:
            self.service.stop()

    def test_service_all_utterances(self):
        event_bus = SynchronousEventBus()
        chats = MemoryChats()
        # TODO
        self.service = ChatUiService("testUI", "testAgent", "utteranceTopic", "responseTopic",
                                     chats, None, event_bus, None)
        self.service.start()

        event_received = threading.Event()
        events = Queue()

        def handler(ev):
            events.put(ev)
            event_received.set()

        event_bus.subscribe("utteranceTopic", handler)

        with self.service.app.test_client() as client:
            response = client.post('chat/1', data="bla bla bla")
            self.assertEqual(200, response.status_code)

        event_received.wait()
        event_received.clear()

        event = events.get()
        self.assertEqual("1", chats.current_chat)
        self.assertEqual("TextSignalEvent", event.payload.type)
        self.assertEqual("bla bla bla", event.payload.text)

        response_payload = TextSignalEvent.for_agent("signal_id", 1, "response text")
        event_bus.publish("responseTopic", Event.for_payload(response_payload))

        for _ in range(100):
            with self.service.app.test_client() as client:
                response = client.get('chat/1?all=True&speaker=')
                self.assertEqual(200, response.status_code)
                if len(response.json) > 1:
                    break

        self.assertEqual(2, len(list(response.json)))
        self.assertEqual("bla bla bla", response.json[0]['text'])
        self.assertEqual("UNKNOWN", response.json[0]['speaker'])
        self.assertEqual("response text", response.json[1]['text'])
        self.assertEqual("testAgent", response.json[1]['speaker'])

    def test_service_responses_only(self):
        event_bus = SynchronousEventBus()
        chats = MemoryChats()
        # TODO
        self.service = ChatUiService("testUI", "testAgent", "utteranceTopic", "responseTopic",
                                     chats, event_bus, None)
        self.service.start()

        event_received = threading.Event()
        events = Queue()

        def handler(ev):
            events.put(ev)
            event_received.set()

        event_bus.subscribe("utteranceTopic", handler)

        with self.service.app.test_client() as client:
            response = client.post('chat/1', data="bla bla bla")
            self.assertEqual(200, response.status_code)

        event_received.wait()
        event_received.clear()

        event = events.get()
        self.assertEqual("1", chats.current_chat)
        self.assertEqual("TextSignalEvent", event.payload.type)
        self.assertEqual("bla bla bla", event.payload.text)

        response_payload = TextSignalEvent.for_agent("signal_id", 1, "response text")
        event_bus.publish("responseTopic", Event.for_payload(response_payload))

        for _ in range(100):
            with self.service.app.test_client() as client:
                response = client.get('chat/1')
                self.assertEqual(200, response.status_code)
                if len(response.json) > 0:
                    break

        self.assertEqual(1, len(list(response.json)))
        self.assertEqual("response text", response.json[0]['text'])
        self.assertEqual("testAgent", response.json[0]['speaker'])

    def test_service_serves_static_files(self):
        event_bus = SynchronousEventBus()
        chats = MemoryChats()
        # TODO
        self.service = ChatUiService("testUI", "testAgent", "utteranceTopic", "responseTopic",
                                     chats, event_bus, None)
        self.service.start()

        with self.service.app.test_client() as client:
            response = client.get('static/chat.html')
            self.assertEqual(200, response.status_code)

        with self.service.app.test_client() as client:
            response = client.get('static/chat.js')
            self.assertEqual(200, response.status_code)

        with self.service.app.test_client() as client:
            response = client.get('static/chat-bubble/component/Bubbles.js')
            self.assertEqual(200, response.status_code)