import dataclasses
import uuid

import flask
from cltl_service.emissordata.client import EmissorDataClient
from emissor.representation.scenario import TextSignal
from cltl.combot.infra.config import ConfigurationManager
from cltl.combot.infra.event import Event, EventBus
from cltl.combot.infra.resource import ResourceManager
from cltl.combot.infra.time_util import timestamp_now
from cltl.combot.infra.topic_worker import TopicWorker
from cltl.combot.event.emissor import TextSignalEvent
from flask import Response
from flask import jsonify

from cltl.chatui.api import Chats, Utterance


class ChatUiService:
    @classmethod
    def from_config(cls, chats: Chats, emissor_data: EmissorDataClient,
                    event_bus: EventBus, resource_manager: ResourceManager, config_manager: ConfigurationManager):
        config = config_manager.get_config("cltl.chat-ui")
        name = config.get("name")
        agent_id = config.get("agent_id")
        external_input = config.get_boolean("external_input")

        config = config_manager.get_config("cltl.chat-ui.events")
        utterance_topic = config.get("topic_utterance")
        response_topic = config.get("topic_response")

        return cls(name, agent_id, external_input, utterance_topic, response_topic, chats, emissor_data, event_bus, resource_manager)

    def __init__(self, name: str, agent: str, external_input: bool, utterance_topic: str, response_topic: str,
                 chats: Chats, emissor_data: EmissorDataClient, event_bus: EventBus, resource_manager: ResourceManager):
        self._name = name
        self._agent = agent
        self._external_input = external_input

        self._response_topic = response_topic
        self._utterance_topic = utterance_topic
        self._chats = chats

        self._emissor_data = emissor_data
        self._event_bus = event_bus
        self._resource_manager = resource_manager

        self._app = None
        self._topic_worker = None

    def start(self, timeout=30):
        self._topic_worker = TopicWorker([self._utterance_topic, self._response_topic], self._event_bus,
                                         resource_manager=self._resource_manager, processor=self._process,
                                         name=self.__class__.__name__)
        self._topic_worker.start().wait()

    def stop(self):
        if not self._topic_worker:
            return

        self._topic_worker.stop()
        self._topic_worker.await_stop()
        self._topic_worker = None

    @property
    def app(self):
        if self._app:
            return self._app

        self._app = flask.Flask(__name__)

        @self._app.route('/chat/current', methods=['GET'])
        def current_chat():
            current_chat = self._chats.current_chat if self._chats.current_chat else str(uuid.uuid4())
            return {"id": current_chat, "agent": self._agent}

        @self._app.route('/chat/<chat_id>', methods=['GET', 'POST'])
        def utterances(chat_id: str):
            if not chat_id:
                return Response("Missing chat id", status=400)

            if flask.request.method == 'GET':
                return get_utterances(chat_id)
            if flask.request.method == 'POST':
                return post_utterances(chat_id)

        def get_utterances(chat_id: str):
            from_sequence = flask.request.args.get('from', default=0, type=int)
            speaker = flask.request.args.get('speaker', default=None if self._external_input else self._agent , type=str)
            try:
                utterances = self._chats.get_utterances(chat_id, from_sequence=from_sequence)
                responses = [utterance for utterance in utterances if not speaker or utterance.speaker == speaker]

                return jsonify(responses)
            except ValueError:
                return Response(status=404)

        def post_utterances(chat_id: str):
            speaker = flask.request.args.get('speaker', default=None, type=str)
            text = flask.request.get_data(as_text=True)
            utterance = Utterance.for_chat(chat_id, speaker, timestamp_now(), text)
            self._chats.append(utterance)
            payload = self._create_payload(utterance)
            self._event_bus.publish(self._utterance_topic, Event.for_payload(payload))

            return Response(utterance.id, status=200)

        @self._app.route('/urlmap')
        def url_map():
            return str(self._app.url_map)

        @self._app.after_request
        def set_cache_control(response):
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'

            return response

        return self._app

    def _create_payload(self, utterance: Utterance) -> TextSignalEvent:
        scenario_id = self._emissor_data.get_current_scenario_id()
        signal = TextSignal.for_scenario(scenario_id, utterance.timestamp, utterance.timestamp, None, utterance.text,
                                         signal_id=utterance.id)

        return TextSignalEvent.for_speaker(signal)

    def _process(self, event: Event[TextSignalEvent]) -> None:
        chat_id = self._chats.current_chat
        chat_id = chat_id if chat_id else str(uuid.uuid4())

        if event.metadata.topic == self._response_topic:
            response = Utterance.for_chat(chat_id, self._agent, event.payload.signal.time.start,
                                          event.payload.signal.text)
            self._chats.append(response)
        elif event.metadata.topic == self._utterance_topic:
            # TODO resolve speaker
            utterance = Utterance.for_chat(chat_id, "UNKNOWN", event.payload.signal.time.start,
                                           event.payload.signal.text, id=event.payload.signal.id)
            self._chats.append(utterance)