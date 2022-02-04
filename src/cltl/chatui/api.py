import abc
import functools

import time
import uuid
from dataclasses import dataclass
from typing import Iterable, Union


@dataclass
class Utterance:
    chat_id: str
    sequence: int
    id: str
    timestamp: int
    speaker: str
    text: str

    @classmethod
    def for_chat(cls, chat_id: str, speaker: str, timestamp: int, text: str, id: str = None):
        return cls(chat_id, None, id if id else str(uuid.uuid4()), timestamp, speaker, text)


class Chats(abc.ABC):
    def append(self, utterances: Union[Utterance, Iterable[Utterance]]):
        raise NotImplementedError("")

    def get_utterances(self, chat_id: str, from_sequence: int = 0):
        raise NotImplementedError("")

    @property
    def current_chat(self) -> str:
        """Return the latest used chat id"""
        raise NotImplementedError("")