import logging
from threading import Lock
from typing import Iterable, Union

from cltl.chatui.api import Chats, Utterance

logger = logging.getLogger(__name__)


class MemoryChats(Chats):
    def __init__(self):
        self._utterances = set()
        self._chats = dict()
        self._chat_id = None
        self._lock = Lock()

    def append(self, utterances: Union[Utterance, Iterable[Utterance]]):
        if isinstance(utterances, Utterance):
            utterances = [utterances]

        with self._lock:
            for utterance in filter(lambda u: u.id not in self._utterances, utterances):
                if utterance.chat_id not in self._chats:
                    self._chats[utterance.chat_id] = []

                utterance.sequence = len(self._chats[utterance.chat_id])
                self._chats[utterance.chat_id].append(utterance)
                self._utterances.add(utterance.id)
                self._chat_id = utterance.chat_id
                logger.debug("Added utterance %s [%s] to chat %s [%s]", utterance.id, utterance.text, utterance.chat_id, utterance.sequence)

    def get_utterances(self, chat_id: str, from_sequence: int = 0) -> Iterable[Utterance]:
        with self._lock:
            if chat_id not in self._chats:
                raise ValueError("No chat with id " + chat_id)

            return self._chats[chat_id][from_sequence:]

    @property
    def current_chat(self) -> str:
        with self._lock:
            return self._chat_id
