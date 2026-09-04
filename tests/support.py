"""Shared scaffolding for the service tests.

Not named `test_*.py` on purpose: `make test` runs a bare `python -m unittest`,
which would otherwise try to collect this as a test module.
"""
import struct
import threading
import time
import uuid
import zlib
from queue import Empty, Queue
from typing import Optional

from cltl.combot.event.emissor import (Agent, LeolaniContext, ScenarioStarted, ScenarioStopped,
                                       TextSignalEvent)
from cltl.combot.infra.event import Event
from cltl.combot.infra.event.memory import SynchronousEventBus
from cltl.combot.infra.time_util import timestamp_now
from emissor.representation.scenario import Modality, Scenario, TextSignal

from cltl.chatui.memory import MemoryChats
from cltl_service.chatui.service import ChatUiService

UTTERANCE_TOPIC = "test.topic.text_in"
RESPONSE_TOPIC = "test.topic.text_out"
SCENARIO_TOPIC = "test.topic.scenario"
IMAGE_TOPIC = "test.topic.image"

AGENT_NAME = "Leolani"
SPEAKER_NAME = "Human"

SIGNALS = {
    Modality.IMAGE.name.lower(): "./image.json",
    Modality.TEXT.name.lower(): "./text.json",
    Modality.AUDIO.name.lower(): "./audio.json",
}


def new_scenario(scenario_id: Optional[str] = None) -> Scenario:
    context = LeolaniContext(Agent(AGENT_NAME, "http://cltl.nl/leolani/world/leolani"),
                             Agent(SPEAKER_NAME, "http://cltl.nl/leolani/world/human"),
                             str(uuid.uuid4()), "test-location", [], [])

    return Scenario.new_instance(scenario_id or str(uuid.uuid4()), timestamp_now(), None,
                                 context, SIGNALS)


def start_scenario(event_bus, scenario: Scenario = None) -> Scenario:
    scenario = scenario if scenario else new_scenario()
    event_bus.publish(SCENARIO_TOPIC, Event.for_payload(ScenarioStarted.create(scenario)))

    return scenario


def stop_scenario(event_bus, scenario: Scenario) -> None:
    scenario.ruler.end = timestamp_now()
    event_bus.publish(SCENARIO_TOPIC, Event.for_payload(ScenarioStopped.create(scenario)))


def agent_response(scenario_id: str, text: str) -> TextSignalEvent:
    signal = TextSignal.for_scenario(scenario_id, timestamp_now(), timestamp_now(), None, text)

    return TextSignalEvent.for_agent(signal)


def png_bytes(width: int = 4, height: int = 3, color=(255, 0, 0)) -> bytes:
    """A minimal, valid, truecolour PNG.

    Hand-rolled from `zlib` and `struct` rather than encoded with cv2: cv2 is an
    optional dependency of this component (see `ChatUiService._decode_rgb`), and
    the fixture must not be the thing that decides whether a test can run.
    """
    scanlines = b"".join(b"\x00" + bytes(color) * width for _ in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xffffffff)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(scanlines))
            + chunk(b"IEND", b""))


def cv2_available() -> bool:
    try:
        import cv2  # noqa: F401
        import numpy  # noqa: F401
    except ImportError:
        return False

    return True


class Listener:
    """Collect events published on a topic, and wait for them.

    `SynchronousEventBus` calls handlers on the publisher's thread, but the
    service publishes from its own worker, so a plain list would be read before
    it is written.
    """

    def __init__(self, event_bus, *topics):
        self.events = Queue()
        self._received = threading.Event()
        for topic in topics:
            event_bus.subscribe(topic, self._handle)

    def _handle(self, event):
        self.events.put(event)
        self._received.set()

    def await_event(self, timeout: float = 5.0) -> Event:
        try:
            return self.events.get(timeout=timeout)
        except Empty:
            raise AssertionError(f"No event received within {timeout}s")

    def count(self) -> int:
        return self.events.qsize()


class ServiceHarness:
    """A started `ChatUiService` with its event bus, torn down by the test."""

    def __init__(self, **kwargs):
        self.event_bus = SynchronousEventBus()
        self.chats = kwargs.pop("chats", None) or MemoryChats()
        self.service = ChatUiService(
            kwargs.pop("name", "test-chat-ui"),
            kwargs.pop("external_input", True),
            UTTERANCE_TOPIC,
            [RESPONSE_TOPIC],
            SCENARIO_TOPIC,
            kwargs.pop("desire_topic", None),
            kwargs.pop("timeout", 0),
            self.chats,
            self.event_bus,
            None,
            **kwargs)
        self.service.start()
        self.client = self.service.app.test_client()

    def stop(self):
        self.service.stop()

    def current(self) -> dict:
        return self.client.get("/chat/current").get_json()

    def chat_id(self) -> str:
        return self.current()["id"]

    def await_scenario(self, timeout: float = 5.0) -> str:
        """Block until the scenario event has reached the service's worker.

        Events are handled on the `TopicWorker`'s thread, not the publisher's,
        so a test that publishes and immediately asserts races the service.
        """
        return _await(lambda: self.current()["scenario_id"], timeout,
                      "the service saw no scenario")

    def await_no_scenario(self, timeout: float = 5.0) -> None:
        _await(lambda: self.current()["scenario_id"] is None, timeout,
               "the service still has a scenario")

    def await_utterances(self, chat_id: str, count: int, timeout: float = 5.0):
        def enough():
            utterances = self.client.get(f"/chat/{chat_id}").get_json() or []
            return utterances if len(utterances) >= count else None

        return _await(enough, timeout, f"fewer than {count} utterance(s) in chat {chat_id}")


def _await(condition, timeout: float, message: str):
    end = time.monotonic() + timeout
    while True:
        result = condition()
        if result:
            return result
        if time.monotonic() >= end:
            raise AssertionError(f"{message} within {timeout}s")
        time.sleep(0.01)
