import base64
import html
import logging
import uuid
from typing import Iterable, Optional
from urllib.parse import urljoin

import flask
import math
import requests
from cltl.combot.event.bdi import DesireEvent
from cltl.combot.event.emissor import ImageSignalEvent, TextSignalEvent, ScenarioStopped
from cltl.combot.infra.config import ConfigurationManager
from cltl.combot.infra.event import Event, EventBus
from cltl.combot.infra.resource import ResourceManager
from cltl.combot.infra.time_util import timestamp_now
from cltl.combot.infra.topic_worker import TopicWorker
from emissor.representation.scenario import TextSignal
from flask import Response
from flask import jsonify, request, make_response, url_for

from cltl.chatui.api import (HTML_CONTENT_TYPE, Chats, ImageStore, Region, StoredImage,
                             Utterance)
from cltl_service.chatui.schema import create_image_signal

logger = logging.getLogger(__name__)

_SPEAKER_COOKIE = "cltl.chatui.chatid"

DEFAULT_IMAGE_TYPES = ("image/png", "image/jpeg", "image/gif", "image/webp")
DEFAULT_UPLOAD_TIMEOUT = 30


class ChatUiService:
    @classmethod
    def from_config(cls, chats: Chats, image_store: ImageStore, event_bus: EventBus,
                    resource_manager: ResourceManager, config_manager: ConfigurationManager):
        config = config_manager.get_config("cltl.chat-ui")
        name = config.get("name")
        external_input = config.get_boolean("external_input")
        timeout = config.get_int("timeout")
        image_types = (config.get("image_types", multi=True) if "image_types" in config
                       else DEFAULT_IMAGE_TYPES)
        image_upload_timeout = (config.get_int("image_upload_timeout")
                                if "image_upload_timeout" in config else DEFAULT_UPLOAD_TIMEOUT)
        image_storage_url = cls._image_storage_url(config, config_manager)

        config = config_manager.get_config("cltl.chat-ui.events")
        utterance_topic = config.get("topic_utterance")
        response_topics = config.get("topic_response", multi=True)
        scenario_topic = config.get("topic_scenario")
        desire_topic = config.get("topic_desire") if "topic_desire" in config else None
        image_topic = config.get("topic_image") if "topic_image" in config else None

        return cls(name, external_input, utterance_topic, response_topics, scenario_topic, desire_topic,
                   timeout, chats, event_bus, resource_manager,
                   image_store=image_store, image_topic=image_topic, image_types=image_types,
                   image_storage_url=image_storage_url, image_upload_timeout=image_upload_timeout)

    @staticmethod
    def _image_storage_url(config, config_manager: ConfigurationManager) -> Optional[str]:
        """Where to PUT uploaded pixels so that `cltl-storage:` resolves for everyone.

        Falls back to `[cltl.backend] storage_url`, which is the value
        cltl-emissor-data resolves `cltl-storage:` against — configuring one
        without the other is how a record ends up referencing pixels nothing can
        fetch.

        The two `in` tests are not interchangeable: `Configuration.__contains__`
        delegates to `ConfigParser.has_option`, which raises `NoSectionError`
        when the *section* is absent, so the section is checked on the manager.
        """
        if "image_storage_url" in config and config.get("image_storage_url"):
            return config.get("image_storage_url")

        if "cltl.backend" not in config_manager:
            return None

        backend = config_manager.get_config("cltl.backend")

        return backend.get("storage_url") if "storage_url" in backend else None

    def __init__(self, name: str, external_input: bool, utterance_topic: str, response_topics: str,
                 scenario_topic: str, desire_topic: str, timeout: int,
                 chats: Chats, event_bus: EventBus, resource_manager: ResourceManager,
                 image_store: ImageStore = None, image_topic: str = None,
                 image_types: Iterable[str] = DEFAULT_IMAGE_TYPES,
                 image_storage_url: str = None,
                 image_upload_timeout: int = DEFAULT_UPLOAD_TIMEOUT):
        self._name = name
        self._external_input = external_input

        # `@singleton` cannot hold None, so a disabled image store arrives as
        # False rather than None. Truthiness, never `is not None`.
        self._image_store = image_store if image_store else None
        self._image_topic = image_topic
        self._image_types = {image_type.strip().lower() for image_type in image_types if image_type}
        self._image_storage_url = image_storage_url
        self._image_upload_timeout = image_upload_timeout

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
        if self._image_store:
            # Werkzeug turns an oversized body into a 413 before the view runs,
            # which is the only place a streamed upload can be stopped early.
            self._app.config['MAX_CONTENT_LENGTH'] = self._image_store.max_size

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
                self._event_bus.publish(self._desire_topic, Event.for_scenario_payload(self._scenario_id, DesireEvent(['quit'])))

            if status == 200:
                payload = {"id": chat_id, "agent": self._agent_name,
                           "scenario_id": self._scenario_id}
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

        def reject_chat(chat_id: str):
            """The guard every chat-scoped route shares; None when the id is good."""
            if not chat_id:
                logger.debug("Request with missing chat id")
                return Response("Missing chat id", status=400)

            current_chat, _, _ = self._chats.current_chat(False)
            if chat_id != current_chat:
                logger.debug("Request with wrong chat id: %s, current: %s", chat_id, current_chat)
                return Response("Chat unavailable", status=404)

            return None

        @self._app.route('/chat/<chat_id>', methods=['GET', 'POST'])
        def utterances(chat_id: str):
            rejected = reject_chat(chat_id)
            if rejected:
                return rejected

            if flask.request.method == 'GET':
                return get_utterances(chat_id)
            if flask.request.method == 'POST':
                return post_utterances(chat_id)

        def get_utterances(chat_id: str):
            from_sequence = flask.request.args.get('from', default=0, type=int)
            speaker = flask.request.args.get(
                'speaker', default=None if self._external_input else self._agent_name, type=str)
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
            self._event_bus.publish(self._utterance_topic, Event.for_scenario_payload(self._scenario_id, payload))

            return Response(utterance.id, status=200)

        @self._app.route('/chat/<chat_id>/image', methods=['POST'])
        def upload_image(chat_id: str):
            """Take the bytes and mint an id. Deliberately publishes nothing.

            An upload is not yet a contribution to the conversation: the person
            is still drawing on it. The event goes out on submit, once, with the
            regions embedded — see `cltl_service.chatui.schema`.
            """
            rejected = reject_chat(chat_id) or self._reject_uploads()
            if rejected:
                return rejected

            content_type = _mime_type(request.headers.get("Content-Type"))
            if content_type not in self._image_types:
                return Response(f"Unsupported image type: {content_type or 'none'}", status=415)

            width = request.args.get('width', default=0, type=int)
            height = request.args.get('height', default=0, type=int)
            if width <= 0 or height <= 0:
                # Not guessed from the bytes: these are the frame every region is
                # expressed in, and a wrong size makes every segment silently
                # wrong rather than visibly broken.
                return Response("Query parameters 'width' and 'height' are required "
                                "and must be positive", status=400)

            data = request.get_data()
            if not data:
                return Response("Empty image", status=400)

            image = StoredImage(str(uuid.uuid4()), data, content_type, width, height)
            try:
                self._image_store.store(image)
            except ValueError as e:
                return Response(str(e), status=413)

            logger.debug("Stored upload %s (%s, %s bytes) for chat %s",
                         image.id, content_type, len(data), chat_id)

            return jsonify({"id": image.id,
                            "url": url_for('chat_image', chat_id=chat_id, image_id=image.id),
                            "width": width,
                            "height": height,
                            "content_type": content_type}), 201

        @self._app.route('/chat/<chat_id>/image/<image_id>', methods=['GET', 'DELETE'])
        def chat_image(chat_id: str, image_id: str):
            """Serve the upload back, byte for byte.

            The chat UI cannot render the backend's `/storage/image/<id>`: that
            returns the pixels as JSON. This is the only endpoint an `<img>` tag
            can point at.
            """
            rejected = reject_chat(chat_id) or self._reject_uploads()
            if rejected:
                return rejected

            if flask.request.method == 'DELETE':
                return Response(status=204 if self._image_store.remove(image_id) else 404)

            image = self._image_store.get(image_id)
            if not image:
                return Response("No such image", status=404)

            return Response(image.data, mimetype=image.content_type)

        @self._app.route('/chat/<chat_id>/image/<image_id>/annotations', methods=['POST'])
        def annotate_image(chat_id: str, image_id: str):
            """Submit: record the annotated image, and echo it into the transcript.

            Two things happen and a third deliberately does not. The signal goes
            out on the image topic with its mentions embedded, so
            cltl-emissor-data persists both; the echo is appended straight to
            the transcript. Nothing is published on the utterance topic — that
            is what keeps the agent from answering an image as if it were a
            question.
            """
            rejected = reject_chat(chat_id) or self._reject_uploads()
            if rejected:
                return rejected

            image = self._image_store.get(image_id)
            if not image:
                return Response("No such image", status=404)

            if not self._scenario_id:
                # The text path lets this become a 500; a conflict is what it is.
                return Response("No active scenario", status=409)

            payload = request.get_json(force=True, silent=True)
            if not isinstance(payload, dict) or not isinstance(payload.get("regions"), list):
                return Response("Expected a JSON body with a 'regions' array", status=400)

            try:
                regions = [Region.from_json(region) for region in payload["regions"]]
            except (KeyError, TypeError, ValueError) as e:
                return Response(f"Malformed region: {e}", status=400)

            self._upload_to_storage(image)

            signal = create_image_signal(self._scenario_id, image.id, image.width, image.height,
                                         regions)
            if self._image_topic:
                self._event_bus.publish(
                    self._image_topic,
                    Event.for_scenario_payload(self._scenario_id, ImageSignalEvent.create(signal)))
            else:
                logger.warning("No image topic configured; annotations for %s are not recorded",
                               image.id)

            utterance = self._echo_utterance(chat_id, image, signal)
            self._chats.append(utterance)

            return jsonify({"signal_id": signal.id,
                            "utterance_id": utterance.id,
                            "mentions": len(signal.mentions)}), 200

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

    def _reject_uploads(self):
        """404 when image upload is switched off, so the UI can hide the panel."""
        if self._image_store:
            return None

        return Response("Image upload is not enabled", status=404)

    def _echo_utterance(self, chat_id: str, image: StoredImage, signal) -> Utterance:
        """The submitted image as a turn in the transcript.

        Appended directly, exactly as `post_utterances` does before it publishes
        — minus the publish. Marked `text/html` so the front end renders it
        rather than escaping it, and so it can be routed to chat-bubble's `says`
        path: the `reply` path interpolates its content into an `onClick`
        attribute, which no user-supplied label may reach.

        Every label is escaped here, not in the browser. The transcript is
        served to anything that asks, and this is the only place that knows the
        text is about to become HTML.
        """
        source = url_for('chat_image', chat_id=chat_id, image_id=image.id)
        boxes = "".join(
            f'<li class="cltl-box">{html.escape(_label_of(mention))}'
            f'<span class="cltl-box-bounds">{_bounds_of(mention)}</span></li>'
            for mention in signal.mentions)
        regions = f'<ul class="cltl-boxes">{boxes}</ul>' if boxes else ""
        markup = (f'<span class="cltl-annotated">'
                  f'<img src="{html.escape(source, quote=True)}" alt="annotated image"/>'
                  f'{regions}</span>')

        return Utterance.for_chat(chat_id, self._speaker_name, timestamp_now(), markup,
                                  content_type=HTML_CONTENT_TYPE)

    def _upload_to_storage(self, image: StoredImage) -> bool:
        """Best-effort PUT of the pixels to cltl-backend's image storage.

        An HTTP call against a public endpoint, not a code dependency: the chat
        UI never imports cltl-backend. It exists so that the
        `cltl-storage:image/<id>` reference in the signal resolves, which is the
        only way cltl-emissor-data copies the PNG into the scenario folder.

        Failure is not fatal and is not reported to the caller. The signal and
        its mentions are published either way — `_store_image_files` swallows a
        failed download and still registers the signal — so what is lost is the
        copy of the pixels, not the annotations.
        """
        if not self._image_storage_url:
            logger.debug("No image storage configured; not uploading %s", image.id)
            return False

        rgb = self._decode_rgb(image)
        if rgb is None:
            return False

        url = urljoin(self._image_storage_url, f"image/{image.id}")
        body = {
            "image": {"__type": "np.ndarray",
                      "data": base64.b64encode(rgb.tobytes()).decode('ascii'),
                      "shape": list(rgb.shape),
                      "dtype": str(rgb.dtype)},
            # A dict, not a list. `image_hook` tries `Bounds(**view)` first and
            # falls back to `Bounds(*view)`, whose field order is
            # (x0, x1, y0, y1) rather than the diagonal it looks like.
            "view": {"x0": 0, "x1": image.width, "y0": 0, "y1": image.height},
            # Present and null: `image_hook` indexes it unconditionally.
            "depth": None,
        }

        try:
            response = requests.put(url, json=body, timeout=self._image_upload_timeout)
            if not response.ok:
                logger.warning("Storing image %s at %s failed: %s %s",
                               image.id, url, response.status_code, response.text)
                return False
        except Exception:
            logger.exception("Could not store image %s at %s", image.id, url)
            return False

        logger.debug("Stored image %s at %s", image.id, url)

        return True

    @staticmethod
    def _decode_rgb(image: StoredImage):
        """The upload as an RGB array, or None if this deployment cannot decode.

        `cv2` is imported here and declared by neither `setup.py` nor
        `requirements.txt` on purpose: two differently named distributions
        provide it — `opencv-python` in the application and harness virtual
        environments, `opencv-python-headless` in the `cltl-base-slim` image
        this component's own image is built on — and naming either one breaks
        the other environment's `--no-index` install. Same reasoning, and same
        shape, as `cltl.backend.impl.cached_storage`.
        """
        try:
            import cv2
            import numpy as np
        except ImportError as e:
            logger.warning("cv2 is not available, cannot store image pixels: %s", e)
            return None

        decoded = cv2.imdecode(np.frombuffer(image.data, dtype=np.uint8), cv2.IMREAD_COLOR)
        if decoded is None:
            logger.warning("Could not decode image %s (%s)", image.id, image.content_type)
            return None

        return cv2.cvtColor(decoded, cv2.COLOR_BGR2RGB)

    @property
    def _agent_name(self) -> str:
        return self._agent.name if self._agent and self._agent.name else "Leolani"

    @property
    def _speaker_name(self) -> str:
        return self._speaker.name if self._speaker and self._speaker.name else "Stranger"

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
            response = Utterance.for_chat(chat_id, self._agent_name, event.payload.signal.time.start,
                                          event.payload.signal.text)
            self._chats.append(response, modify_timestamp=False)
        elif event.metadata.topic == self._utterance_topic:
            utterance = Utterance.for_chat(chat_id, self._speaker_name, event.payload.signal.time.start,
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
            if self._image_store:
                # The transcript they belong to is gone, and nothing else in the
                # process is holding these megabytes for a reason.
                self._image_store.clear()

        logger.info("Updated Chat UI for scenario %s with agent %s, speaker %s",
                    self._scenario_id, self._agent, self._speaker)


def _mime_type(content_type: str) -> str:
    """The bare media type of a Content-Type header, lowercased."""
    return (content_type or "").split(";")[0].strip().lower()


def _label_of(mention) -> str:
    value = mention.annotations[0].value

    return getattr(value, "label", "") or ""


def _bounds_of(mention) -> str:
    x0, y0, x1, y1 = mention.segment[0].bounds

    return f"{x0}, {y0} - {x1}, {y1}"
