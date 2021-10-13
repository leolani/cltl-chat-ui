from queue import Empty, Queue
from threading import Lock
from typing import Iterable, Union

from cltl.chatui.api import Chats, Utterance


class MemoryChats(Chats):
    def __init__(self):
        self._chats = dict()
        self._unread = dict()
        self._chat_id = None
        self._lock = Lock()

    def append(self, utterances: Union[Utterance, Iterable[Utterance]]):
        if isinstance(utterances, Utterance):
            utterances = [utterances]

        try:
            for utterance in utterances:
                self._unread[utterance.chat_id].put(utterance)
                self._chat_id = utterance.chat_id
        except KeyError:
            with self._lock:
                if not utterance.chat_id in self._unread:
                    self._unread[utterance.chat_id] = Queue()
            self.append(utterance)

    def get_utterances(self, chat_id: str, unread_only: bool = False) -> Iterable[Utterance]:
        if chat_id not in self._unread:
            raise ValueError("No chat with id " + chat_id)
        if chat_id not in self._chats:
            self._chats[chat_id] = Queue()

        chat = self._unread[chat_id]
        responses = []
        while True:
            try:
                utterance = chat.get_nowait()
                responses.append(utterance)
                self._chats[chat_id].put(utterance)
            except Empty:
                break

        return responses if unread_only else self._chats[chat_id].queue

    @property
    def current_chat(self) -> str:
        return self._chat_id
