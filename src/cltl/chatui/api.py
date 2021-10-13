import abc
from dataclasses import dataclass
from typing import Iterable, Union


@dataclass
class Utterance:
    chat_id: str
    speaker: str
    timestamp: float
    text: str


class Chats(abc.ABC):
    def append(self, utterances: Union[Utterance, Iterable[Utterance]]):
        raise NotImplementedError("")

    def get_utterances(self, chat_id: str, unread_only: bool = False):
        raise NotImplementedError("")

    @property
    def current_chat(self) -> str:
        """Return the latest used chat id"""
        raise NotImplementedError("")