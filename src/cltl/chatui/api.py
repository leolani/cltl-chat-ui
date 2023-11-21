import abc
import functools

import time
import uuid
from dataclasses import dataclass
from typing import Iterable, Union, Optional


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
    def append(self, utterances: Union[Utterance, Iterable[Utterance]], modify_timestamp: bool = True):
        raise NotImplementedError("")

    def get_utterances(self, chat_id: str, from_sequence: int = 0):
        raise NotImplementedError("")

    def current_chat(self, create: bool, modify_timestamp: bool = False) -> (Optional[str], bool, Optional[int]):
        """
        Parameters
        ----------
        create : bool
            Create new chat id if it is None. If True this updates the modification timestamp.
        modify_timestamp : bool
            Update last_modified timestamp if the chat id already exists

        Returns
        -------
        chat_id : Optional[str]
            chat id, may be None
        is_new : bool
            chat id, may be None
        last_modified : Optional[int]
            last modification timestamp, may be None
        """
        raise NotImplementedError("")

    def stop_chat(self):
        """Stop the current chat id"""
        raise NotImplementedError("")