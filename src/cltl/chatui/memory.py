import logging
import uuid
from collections import OrderedDict
from threading import Lock
from typing import Iterable, Union, Optional

from cltl.combot.infra.time_util import timestamp_now

from cltl.chatui.api import Chats, ImageStore, StoredImage, Utterance

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



class MemoryImageStore(ImageStore):
    """Uploaded images, in memory, bounded and insertion-ordered.

    Deliberately not a directory on disk: in Docker Compose the chat-ui service
    mounts the same host storage directory as every other service, so a file
    store here would collide with cltl-backend's by construction. These bytes
    only ever serve the `<img>` in the transcript; the durable copy is the one
    the annotation submit PUTs to the backend's image storage.

    Eviction is FIFO rather than LRU, because a transcript is chronological: the
    image that has not been touched for longest is the one that scrolled off the
    top of the chat window.
    """

    def __init__(self, capacity: int = 4, max_size: int = 10 * 1024 * 1024):
        self._capacity = max(int(capacity), 1)
        self._max_size = int(max_size)
        self._images = OrderedDict()
        self._lock = Lock()

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def max_size(self) -> int:
        return self._max_size

    def store(self, image: StoredImage) -> None:
        if 0 < self._max_size < len(image.data):
            raise ValueError(f"Image {image.id} is {len(image.data)} bytes, "
                             f"the limit is {self._max_size}")

        with self._lock:
            self._images[image.id] = image
            while len(self._images) > self._capacity:
                evicted, _ = self._images.popitem(last=False)
                logger.debug("Evicted image %s from the chat UI image store", evicted)

    def get(self, image_id: str) -> Optional[StoredImage]:
        with self._lock:
            return self._images.get(image_id)

    def remove(self, image_id: str) -> bool:
        with self._lock:
            return self._images.pop(image_id, None) is not None

    def clear(self) -> None:
        with self._lock:
            self._images.clear()
