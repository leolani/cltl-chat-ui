import abc
import uuid
from dataclasses import dataclass
from typing import Iterable, Optional, Tuple, Union

#: Content type of a plain utterance, and of an utterance that carries HTML the
#: UI is expected to render rather than escape. The HTML variant is produced by
#: the chat UI itself (the image echo), never by a remote speaker.
TEXT_CONTENT_TYPE = "text/plain"
HTML_CONTENT_TYPE = "text/html"

#: Annotation type for a region a person marked by hand. Mirrors the `type`
#: field of `cltl.object_recognition.api.Object`, which carries the detected
#: object class there; here there is no classifier, only a human.
REGION_TYPE = "region"


@dataclass
class Utterance:
    chat_id: str
    sequence: int
    id: str
    timestamp: int
    speaker: str
    text: str
    content_type: str = TEXT_CONTENT_TYPE

    @classmethod
    def for_chat(cls, chat_id: str, speaker: str, timestamp: int, text: str, id: str = None,
                 content_type: str = TEXT_CONTENT_TYPE):
        return cls(chat_id, None, id if id else str(uuid.uuid4()), timestamp, speaker, text, content_type)


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


@dataclass
class ImageAnnotation:
    """
    The value of an EMISSOR `Annotation` on a region of an image.

    Field-for-field the same shape as `cltl.object_recognition.api.Object`, so
    that anything already reading `annotation.value.label` off a machine
    annotation reads a hand-drawn one unchanged. The class is redeclared here
    rather than imported: cltl-chat-ui must not depend on cltl-object-recognition.
    """
    type: str
    label: str
    confidence: Optional[float] = None

    @classmethod
    def for_label(cls, label: str) -> "ImageAnnotation":
        """A region a person drew and named, hence a confidence of 1."""
        return cls(REGION_TYPE, label, 1.0)


@dataclass(frozen=True)
class Region:
    """
    A rectangle over an image, in source-image pixels, with a free-text label.

    Coordinates arrive from the browser as floats in whatever order the person
    dragged, so nothing downstream may use them before `normalized`.
    """
    x0: float
    y0: float
    x1: float
    y1: float
    label: str = ""

    @classmethod
    def from_json(cls, data) -> "Region":
        """Parse one region of an annotation request body.

        Raises `TypeError`/`ValueError`/`KeyError` on anything malformed; the
        service turns those into a 400.
        """
        if not isinstance(data, dict):
            raise TypeError(f"Expected a region object, was {type(data).__name__}")

        return cls(float(data["x0"]), float(data["y0"]), float(data["x1"]), float(data["y1"]),
                   str(data["label"]) if data.get("label") else "")

    @property
    def bounds(self) -> Tuple[float, float, float, float]:
        return self.x0, self.y0, self.x1, self.y1

    def normalized(self, width: int, height: int) -> Optional["Region"]:
        """
        Orient, round and clamp this region to an image of *width* x *height*.

        `MultiIndex.get_area_bounding_box` raises rather than clipping when a
        segment leaves its parent, so clamping has to happen before the EMISSOR
        types are involved. Returns None for a region with no area left after
        clamping — a stray click, or a box dragged entirely off the image. The
        caller drops it and keeps the rest of the submission.
        """
        if width <= 0 or height <= 0:
            return None

        left, right = sorted((int(round(self.x0)), int(round(self.x1))))
        top, bottom = sorted((int(round(self.y0)), int(round(self.y1))))

        left, right = _clamp(left, width), _clamp(right, width)
        top, bottom = _clamp(top, height), _clamp(bottom, height)

        if right <= left or bottom <= top:
            return None

        return Region(left, top, right, bottom, self.label)


def _clamp(value: int, maximum: int) -> int:
    return min(max(value, 0), maximum)


@dataclass(frozen=True)
class StoredImage:
    """Raw bytes of an uploaded image, exactly as the browser sent them.

    `width` and `height` are the browser's `naturalWidth`/`naturalHeight`, not
    something decoded here: they are the frame every region is expressed in, and
    the chat UI must be able to serve the echo without an image library.
    """
    id: str
    data: bytes
    content_type: str
    width: int
    height: int

    @property
    def bounds(self) -> Tuple[int, int, int, int]:
        return 0, 0, self.width, self.height


class ImageStore(abc.ABC):
    """Images held for the lifetime of a conversation, to render the transcript.

    A UI cache, not a system of record: the record is the `ImageSignal` on the
    event bus and the pixels in the backend's image storage.
    """

    def store(self, image: StoredImage) -> None:
        raise NotImplementedError("")

    def get(self, image_id: str) -> Optional[StoredImage]:
        raise NotImplementedError("")

    def remove(self, image_id: str) -> bool:
        raise NotImplementedError("")

    def clear(self) -> None:
        raise NotImplementedError("")
