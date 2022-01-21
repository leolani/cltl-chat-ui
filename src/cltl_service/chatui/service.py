import uuid

import flask
from emissor.representation.scenario import TextSignal
from cltl.combot.infra.config import ConfigurationManager
from cltl.combot.infra.event import Event, EventBus
from cltl.combot.infra.resource import ResourceManager
from cltl.combot.infra.time_util import timestamp_now
from cltl.combot.infra.topic_worker import TopicWorker
from cltl_service.backend.schema import TextSignalEvent
from flask import Response
from flask import jsonify

from cltl.chatui.api import Chats, Utterance


class ChatUiService:
    @classmethod
    def from_config(cls, chats: Chats,
                    event_bus: EventBus, resource_manager: ResourceManager, config_manager: ConfigurationManager):
        config = config_manager.get_config("cltl.chat-ui")
        name = config.get("name")
        agent_id = config.get("agent_id")

        config = config_manager.get_config("cltl.chat-ui.events")
        utterance_topic = config.get("topic_utterance")
        response_topic = config.get("topic_response")

        return cls(name, agent_id, utterance_topic, response_topic, chats, event_bus, resource_manager)

    def __init__(self, name: str, agent: str, utterance_topic: str, response_topic: str,
                 chats: Chats, event_bus: EventBus, resource_manager: ResourceManager):
        self._name = name
        self._agent = agent

        self._response_topic = response_topic
        self._utterance_topic = utterance_topic
        self._chats = chats

        self._event_bus = event_bus
        self._resource_manager = resource_manager

        self._app = None
        self._topic_worker = None

    def start(self, timeout=30):
        self._topic_worker = TopicWorker([self._response_topic], self._event_bus,
                                         resource_manager=self._resource_manager, processor=self._process)
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

        @self._app.route('/chat/<chat_id>', methods=['GET', 'POST'])
        def utterances(chat_id: str):
            if flask.request.method == 'GET':
                all_utterances = flask.request.args.get('all', default=False, type=bool)
                speaker = flask.request.args.get('speaker', default=self._agent, type=str)
                try:
                    chat = self._chats.get_utterances(chat_id, unread_only=not all_utterances)
                    responses = [utterance for utterance in chat if not speaker or utterance.speaker == speaker]

                    return jsonify(responses)
                except ValueError:
                    return Response(status=404)
            if flask.request.method == 'POST':
                speaker = flask.request.args.get('speaker', default="UNKNOWN", type=str)
                text = flask.request.get_data(as_text=True)
                utterance = Utterance(chat_id, speaker, timestamp_now(), text)
                self._chats.append(utterance)
                payload = self._create_payload(utterance)
                self._event_bus.publish(self._utterance_topic, Event.for_payload(payload))

                return Response(status=200)

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
        signal = TextSignal.for_scenario(None, utterance.timestamp, utterance.timestamp, None, utterance.text)

        return TextSignalEvent.create(signal)

    def _process(self, event: Event[TextSignalEvent]) -> None:
        response = Utterance(self._chats.current_chat, self._agent, event.metadata.timestamp, event.payload.signal.text)
        self._chats.append(response)