import logging

import flask
import math
from cltl.combot.event.bdi import DesireEvent
from cltl.combot.event.emissor import TextSignalEvent, ScenarioStopped
from cltl.combot.infra.config import ConfigurationManager
from cltl.combot.infra.event import Event, EventBus
from cltl.combot.infra.resource import ResourceManager
from cltl.combot.infra.time_util import timestamp_now
from cltl.combot.infra.topic_worker import TopicWorker
from emissor.representation.scenario import TextSignal
from flask import Response
from flask import jsonify, request, make_response

from cltl.chatui.api import Chats, Utterance

logger = logging.getLogger(__name__)

_SPEAKER_COOKIE = "cltl.chatui.chatid"


class ChatUiService:
    @classmethod
    def from_config(cls, chats: Chats, event_bus: EventBus,
                    resource_manager: ResourceManager, config_manager: ConfigurationManager):
        config = config_manager.get_config("cltl.chat-ui")
        name = config.get("name")
        external_input = config.get_boolean("external_input")
        timeout = config.get_int("timeout")

        config = config_manager.get_config("cltl.chat-ui.events")
        utterance_topic = config.get("topic_utterance")
        response_topics = config.get("topic_response", multi=True)
        scenario_topic = config.get("topic_scenario")
        desire_topic = config.get("topic_desire") if "topic_desire" in config else None

        return cls(name, external_input, utterance_topic, response_topics, scenario_topic, desire_topic,
                   timeout, chats, event_bus, resource_manager)

    def __init__(self, name: str, external_input: bool, utterance_topic: str, response_topics: str,
                 scenario_topic: str, desire_topic: str, timeout: int,
                 chats: Chats, event_bus: EventBus, resource_manager: ResourceManager):
        self._name = name
        self._external_input = external_input

        self._response_topics = response_topics
        self._utterance_topic = utterance_topic
        self._desire_topic = desire_topic
        self._scenario_topic = scenario_topic
        self._chats = chats

        self._scenario_id = None
        self._agent = None
        self._speaker = None

        self._event_bus = event_bus
        self._resource_manager = resource_manager

        self._app = None
        self._topic_worker = None

        self._timeout = timeout * 60000 if timeout > 0 else 0
        self._use_cookie = timeout > 0

    def start(self, timeout=30):
        self._topic_worker = TopicWorker([self._utterance_topic, self._scenario_topic] + self._response_topics,
                                         self._event_bus, resource_manager=self._resource_manager,
                                         processor=self._process, buffer_size=256,
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

        @self._app.route('/chat/terminate', methods=['DELETE'])
        def terminate_chat():
            if self._use_cookie and self._desire_topic:
                chat_id, is_new, last_modified = self._chats.current_chat(False, False)
                self._event_bus.publish(self._desire_topic, Event.for_payload(DesireEvent(['quit'])))
                logger.warning("Chat %s (%s) terminated through endpoint /chat/terminate", chat_id, last_modified)
                return Response(status=200)
            else:
                logger.warning("No-op on /chat/terminate")
                return Response(status=404)

        @self._app.route('/chat/current', methods=['GET'])
        def current_chat():
            if self._use_cookie:
                status, chat_id, remain_until_timeout = handle_ccookie(request.cookies.get(_SPEAKER_COOKIE))
            else:
                id_, _, _ = self._chats.current_chat(True, True)
                status, chat_id, remain_until_timeout = 200, id_, self._timeout

            if remain_until_timeout < 0 and self._desire_topic:
                logger.debug("Chat %s timed out in UI", self._chats.current_chat(False)[0])
                self._event_bus.publish(self._desire_topic, Event.for_payload(DesireEvent(['quit'])))

            if status == 200:
                agent_name = self._agent.name if self._agent and self._agent.name else "Leolani"
                payload = {"id": chat_id, "agent": agent_name}
            else:
                payload = math.ceil(remain_until_timeout)

            response = make_response(jsonify(payload), status)
            if chat_id and self._use_cookie:
                response.set_cookie(_SPEAKER_COOKIE, chat_id, samesite='Lax')
            elif self._use_cookie:
                response.delete_cookie(_SPEAKER_COOKIE)

            return response

        def handle_ccookie(expected):
            remain_until_timeout = self._timeout
            status = None

            chat_id, is_new, last_modified = self._chats.current_chat(True, False)
            if is_new:
                # Chat is created by speaker
                logger.debug("Started new chat by speaker: %s", chat_id)
                status = 200
            elif last_modified is None:
                # Chat was created by agent, but no speaker connected yet
                logger.debug("Accepted new cookie: %s", chat_id)
                status = 200
            else:
                remain_until_timeout = (self._timeout - timestamp_now() + last_modified) / 60000
                if expected == chat_id and remain_until_timeout > 0:
                    # speaker reconnected within timeout
                    logger.debug("Accepted cookie %s", expected)
                    status = 200
                else:
                    # other user or speaker reconnected after timeout
                    logger.debug("Rejected cookie %s for chat %s", expected, chat_id)
                    status = 307
                    chat_id = None

            if status == 200:
                # Reset timeout if cookie is accepted
                self._chats.current_chat(False, True)

            return status, chat_id, remain_until_timeout

        @self._app.route('/chat/<chat_id>', methods=['GET', 'POST'])
        def utterances(chat_id: str):
            if not chat_id:
                logger.debug("Request with missing chat id")
                return Response("Missing chat id", status=400)

            current_chat, _, _ = self._chats.current_chat(False)
            if chat_id != current_chat:
                logger.debug("Request with wrong chat id: %s, current: %s", chat_id, current_chat)
                return Response("Chat unavailable", status=404)

            if flask.request.method == 'GET':
                return get_utterances(chat_id)
            if flask.request.method == 'POST':
                return post_utterances(chat_id)

        def get_utterances(chat_id: str):
            from_sequence = flask.request.args.get('from', default=0, type=int)
            agent_name = self._agent.name if self._agent and self._agent.name else "Leolani"
            speaker = flask.request.args.get('speaker', default=None if self._external_input else agent_name, type=str)
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
        if not self._scenario_id:
            raise ValueError("No active scenario in chat UI for utterance %" + utterance.text)

        signal = TextSignal.for_scenario(self._scenario_id, utterance.timestamp, utterance.timestamp,
                                         None, utterance.text, signal_id=utterance.id)

        return TextSignalEvent.for_speaker(signal)

    def _process(self, event: Event) -> None:
        if event.metadata.topic == self._scenario_topic:
            self._process_scenario_event(event)
            return

        chat_id, is_new, last_modified = self._chats.current_chat(True)
        if is_new:
            logger.debug("Started new chat by agent: %s", chat_id)

        if event.metadata.topic in self._response_topics:
            agent_name = self._agent.name if self._agent and self._agent.name else "Leolani"
            response = Utterance.for_chat(chat_id, agent_name, event.payload.signal.time.start,
                                          event.payload.signal.text)
            self._chats.append(response, modify_timestamp=False)
        elif event.metadata.topic == self._utterance_topic:
            speaker_name = self._speaker.name if self._speaker and self._speaker.name else "Stranger"
            utterance = Utterance.for_chat(chat_id, speaker_name, event.payload.signal.time.start,
                                           event.payload.signal.text, id=event.payload.signal.id)
            self._chats.append(utterance)

    def _process_scenario_event(self, event):
        self._scenario_id = event.payload.scenario.id
        if event.payload.scenario.context and event.payload.scenario.context.agent:
            self._agent = event.payload.scenario.context.agent
        if event.payload.scenario.context and event.payload.scenario.context.speaker:
            self._speaker = event.payload.scenario.context.speaker
        if event.payload.type == ScenarioStopped.__name__:
            self._scenario_id = None
            self._agent = None
            self._speaker = None
            self._chats.stop_chat()

        logger.info("Updated Chat UI for scenario %s with agent %s, speaker %s",
                    self._scenario_id, self._agent, self._speaker)
