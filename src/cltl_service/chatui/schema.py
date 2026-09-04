"""EMISSOR payloads for images a person uploaded and annotated in the chat UI.

The shape follows `cltl_service.object_recognition.schema` — a `Mention` per
region, its `segment` a narrower `MultiIndex` of the signal's own ruler, its
`annotation` an `ImageAnnotation` value — so a hand-drawn annotation is
indistinguishable downstream from a detected one.

One thing is deliberately different. cltl-object-recognition publishes an
`AnnotationEvent` on its own topic, because it annotates a signal that some
other process already published. Here the chat UI owns both halves, so the
mentions travel *inside* the `ImageSignal`: `KombuEventBus.subscribe` runs one
consumer thread per topic, and `EmissorDataFileStorage._add_mention` drops a
mention whose signal it has not seen yet with nothing but a log warning. Two
topics would be a race that only fails in a multi-process deployment, and only
sometimes.
"""
import uuid
from dataclasses import dataclass
from typing import Iterable, List, Optional

from cltl.combot.event.emissor import AnnotationEvent
from cltl.combot.infra.time_util import timestamp_now
from emissor.representation.scenario import (Annotation, ImageSignal, Mention, class_type,
                                             module_source)

from cltl.chatui.api import ImageAnnotation, Region

#: The URL scheme cltl-backend's storage resolves, and the only one
#: `EmissorDataFileStorage._destination_path` turns into a sane relative path:
#: it strips exactly this prefix and joins the rest onto the scenario folder, so
#: an `http://` URL would write a host and port into the persisted record.
#:
#: Duplicated from `cltl.backend.api.storage.STORAGE_SCHEME` rather than
#: imported. It is a wire contract between two services, not an API, and
#: importing it would make the chat UI depend on cltl-backend.
STORAGE_SCHEME = "cltl-storage"

IMAGE_MODALITY = "image"


def image_url(image_id: str) -> str:
    """The `signal.files` entry that lets cltl-emissor-data fetch the pixels."""
    return f"{STORAGE_SCHEME}:{IMAGE_MODALITY}/{image_id}"


def to_mention(image_signal: ImageSignal, region: Region) -> Optional[Mention]:
    """One labelled region as an EMISSOR `Mention`, or None if it has no area.

    Returns None rather than raising so that one bad box — a stray click, or a
    rectangle dragged off the edge — costs its own annotation and not the whole
    submission.
    """
    _, _, width, height = image_signal.ruler.bounds
    normalized = region.normalized(width, height)
    if normalized is None:
        return None

    segment = image_signal.ruler.get_area_bounding_box(
        normalized.x0, normalized.y0, normalized.x1, normalized.y1)
    annotation = Annotation(class_type(ImageAnnotation),
                            ImageAnnotation.for_label(normalized.label),
                            module_source(__name__),
                            timestamp_now())

    return Mention(str(uuid.uuid4()), [segment], [annotation])


def to_mentions(image_signal: ImageSignal, regions: Iterable[Region]) -> List[Mention]:
    mentions = (to_mention(image_signal, region) for region in regions)

    return [mention for mention in mentions if mention is not None]


def create_image_signal(scenario_id: str, image_id: str, width: int, height: int,
                        regions: Iterable[Region] = (),
                        start: int = None, end: int = None) -> ImageSignal:
    """An `ImageSignal` for an uploaded image, with its regions already mentioned.

    `bounds` is `(0, 0, width, height)` taken from the browser, never from
    `cltl.backend.api.camera.Image.bounds`: that goes through `CameraResolution`
    and falls back to `(-1, -1)` for any size not in the enum, which is
    essentially every upload.

    Both ends of the temporal ruler must be truthy. `EmissorDataStorage.add_signal`
    skips the file download entirely when `signal.time.end` is falsy, and submit
    time is the only moment at which both ends are honestly known.
    """
    now = timestamp_now()
    signal = ImageSignal.for_scenario(scenario_id,
                                      start if start else now,
                                      end if end else now,
                                      image_url(image_id),
                                      (0, 0, width, height),
                                      signal_id=image_id)
    signal.mentions.extend(to_mentions(signal, regions))

    return signal


@dataclass
class ImageAnnotationEvent(AnnotationEvent[Annotation[ImageAnnotation]]):
    """Regions as a standalone annotation event.

    Not what the chat UI publishes — see the module docstring — but the payload
    a consumer would receive from any other annotator, and the thing to reach
    for if the mentions ever do need to travel separately.
    """

    @classmethod
    def for_regions(cls, image_signal: ImageSignal, regions: Iterable[Region]):
        return cls(cls.__name__, to_mentions(image_signal, regions))
