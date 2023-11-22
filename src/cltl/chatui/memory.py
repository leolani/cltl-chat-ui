import logging
import uuid
from threading import Lock
from typing import Iterable, Union, Optional

from cltl.combot.infra.time_util import timestamp_now

from cltl.chatui.api import Chats, Utterance

logger = logging.getLogger(__name__)


class MemoryChats(Chats):
    def __init__(self):
        self._utterances = set()
        self._chats = dict()
        self._chat_id = None
        self._lock = Lock()

        self._last_modified = None

    def append(self, utterances: Union[Utterance, Iterable[Utterance]], modify_timestamp: bool = True):
        if isinstance(utterances, Utterance):
            utterances = [utterances]

        with self._lock:
            for utterance in filter(lambda u: u.id not in self._utterances, utterances):
                if not self._chat_id == utterance.chat_id:
                    raise ValueError("Chat IDs don't match: " + str(self._chat_id) + " - " + str(utterance.chat_id))

                utterance.sequence = len(self._chats[utterance.chat_id])
                self._chats[utterance.chat_id].append(utterance)
                self._utterances.add(utterance.id)
                if modify_timestamp:
                    self._last_modified = max(self._last_modified if self._last_modified else 0, utterance.timestamp if utterance.timestamp else 0)
                logger.debug("Added utterance %s [%s] to chat %s [%s]", utterance.id, utterance.text, utterance.chat_id, utterance.sequence)

    def get_utterances(self, chat_id: str, from_sequence: int = 0) -> Iterable[Utterance]:
        with self._lock:
            if chat_id not in self._chats:
                raise ValueError("No chat with id " + chat_id)

            return self._chats[chat_id][from_sequence:]

    def stop_chat(self):
        with self._lock:
            self._chat_id = None
            self._last_modified = None

    def current_chat(self, create: bool, modify_timestamp: bool = False) -> (Optional[str], bool, Optional[int]):
        with self._lock:
            last_modified = self._last_modified

            is_new = not self._chat_id and create
            if is_new:
                self._chat_id = str(uuid.uuid4())
                self._chats[self._chat_id] = []

            if self._chat_id and modify_timestamp:
                self._last_modified = max(self._last_modified if self._last_modified else 0, timestamp_now())

            return self._chat_id, is_new, last_modified

