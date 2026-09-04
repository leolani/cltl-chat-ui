"""The EMISSOR shape of an annotated upload.

Everything here is about the record that outlives the conversation: what
cltl-emissor-data writes to disk, and what a downstream consumer of image
annotations reads back. Three of these are regressions waiting to happen,
because the failure is silent in every case:

* a segment outside its parent raises inside `MultiIndex`;
* a falsy `signal.time.end` makes `add_signal` skip the pixels;
* a `files` entry that is not `cltl-storage:` writes a host and port into the
  persisted record instead of a relative path.
"""
import unittest

from emissor.representation.scenario import ImageSignal, class_type
from emissor.representation.util import marshal, unmarshal

from cltl.chatui.api import ImageAnnotation, Region
from cltl_service.chatui.schema import (STORAGE_SCHEME, create_image_signal, image_url,
                                        to_mention, to_mentions)

SCENARIO = "scenario-1"
IMAGE = "image-1"
WIDTH, HEIGHT = 640, 480


def signal(width=WIDTH, height=HEIGHT, regions=()):
    return create_image_signal(SCENARIO, IMAGE, width, height, regions)


class ImageSignalTest(unittest.TestCase):
    def test_bounds_come_from_the_upload(self):
        self.assertEqual((0, 0, WIDTH, HEIGHT), tuple(signal().ruler.bounds))

    def test_signal_id_is_the_image_id(self):
        self.assertEqual(IMAGE, signal().id)

    def test_file_reference_uses_the_storage_scheme(self):
        """Anything else and `_destination_path` writes a URL into the record."""
        self.assertEqual([f"{STORAGE_SCHEME}:image/{IMAGE}"], signal().files)
        self.assertEqual(f"{STORAGE_SCHEME}:image/{IMAGE}", image_url(IMAGE))

    def test_both_time_ends_are_set(self):
        """A falsy `end` makes EmissorDataStorage.add_signal skip the download."""
        time = signal().time

        self.assertTrue(time.start)
        self.assertTrue(time.end)
        self.assertEqual(SCENARIO, time.container_id)

    def test_signal_survives_a_marshal_round_trip(self):
        """Literally the first thing `EmissorDataStorage.add_signal` does."""
        original = signal(regions=[Region(10, 20, 30, 40, "a chair")])

        restored = unmarshal(marshal(original, cls=ImageSignal), cls=ImageSignal)

        self.assertEqual(original.id, restored.id)
        self.assertEqual(list(original.ruler.bounds), list(restored.ruler.bounds))
        self.assertEqual(original.files, restored.files)
        self.assertEqual(1, len(restored.mentions))


class MentionTest(unittest.TestCase):
    def test_segment_hangs_off_the_signal(self):
        annotated = signal(regions=[Region(10, 20, 30, 40, "a chair")])

        mention = annotated.mentions[0]
        segment = mention.segment[0]

        self.assertEqual(annotated.id, segment.container_id)
        self.assertEqual((10, 20, 30, 40), tuple(segment.bounds))

    def test_annotation_carries_the_label(self):
        annotated = signal(regions=[Region(10, 20, 30, 40, "a chair")])

        annotation = annotated.mentions[0].annotations[0]

        self.assertEqual(class_type(ImageAnnotation), annotation.type)
        self.assertEqual("a chair", annotation.value.label)
        self.assertEqual("region", annotation.value.type)
        self.assertTrue(annotation.source.startswith("python-source:"))
        self.assertTrue(annotation.timestamp)

    def test_one_mention_per_region(self):
        annotated = signal(regions=[Region(0, 0, 10, 10, "one"),
                                    Region(20, 20, 30, 30, "two")])

        labels = [mention.annotations[0].value.label for mention in annotated.mentions]

        self.assertEqual(["one", "two"], labels)

    def test_a_region_may_be_unlabelled(self):
        annotated = signal(regions=[Region(0, 0, 10, 10)])

        self.assertEqual("", annotated.mentions[0].annotations[0].value.label)


class RegionNormalizationTest(unittest.TestCase):
    """`get_area_bounding_box` raises outside its parent, it does not clip."""

    def test_a_right_to_left_drag_is_oriented(self):
        normalized = Region(30, 40, 10, 20).normalized(WIDTH, HEIGHT)

        self.assertEqual((10, 20, 30, 40), normalized.bounds)

    def test_floats_are_rounded(self):
        normalized = Region(10.4, 20.6, 30.5, 40.49).normalized(WIDTH, HEIGHT)

        self.assertEqual((10, 21, 30, 40), normalized.bounds)

    def test_an_overhanging_box_is_clamped(self):
        annotated = signal(regions=[Region(-50, -50, WIDTH + 100, HEIGHT + 100, "everything")])

        self.assertEqual(1, len(annotated.mentions))
        self.assertEqual((0, 0, WIDTH, HEIGHT), tuple(annotated.mentions[0].segment[0].bounds))

    def test_a_box_entirely_outside_is_dropped(self):
        self.assertIsNone(Region(WIDTH + 10, 10, WIDTH + 90, 90).normalized(WIDTH, HEIGHT))

    def test_a_zero_area_box_is_dropped(self):
        self.assertIsNone(Region(10, 10, 10, 90).normalized(WIDTH, HEIGHT))
        self.assertIsNone(Region(10, 10, 90, 10).normalized(WIDTH, HEIGHT))

    def test_a_bad_box_does_not_cost_the_good_ones(self):
        annotated = signal(regions=[Region(10, 10, 10, 10, "degenerate"),
                                    Region(0, 0, 10, 10, "kept"),
                                    Region(-90, 10, -10, 90, "off the left edge")])

        labels = [mention.annotations[0].value.label for mention in annotated.mentions]

        self.assertEqual(["kept"], labels)

    def test_label_survives_normalization(self):
        self.assertEqual("a chair", Region(30, 40, 10, 20, "a chair").normalized(WIDTH, HEIGHT).label)

    def test_to_mention_returns_none_for_an_empty_region(self):
        self.assertIsNone(to_mention(signal(), Region(10, 10, 10, 10)))

    def test_to_mentions_drops_the_empty_ones(self):
        self.assertEqual([], to_mentions(signal(), [Region(10, 10, 10, 10)]))


class RegionParsingTest(unittest.TestCase):
    def test_parses_the_request_shape(self):
        region = Region.from_json({"x0": 1.5, "y0": 2, "x1": 3, "y1": 4, "label": "hat"})

        self.assertEqual((1.5, 2.0, 3.0, 4.0), region.bounds)
        self.assertEqual("hat", region.label)

    def test_label_is_optional(self):
        self.assertEqual("", Region.from_json({"x0": 1, "y0": 2, "x1": 3, "y1": 4}).label)
        self.assertEqual("", Region.from_json({"x0": 1, "y0": 2, "x1": 3, "y1": 4, "label": None}).label)

    def test_a_missing_coordinate_is_an_error(self):
        with self.assertRaises(KeyError):
            Region.from_json({"x0": 1, "y0": 2, "x1": 3})

    def test_a_non_numeric_coordinate_is_an_error(self):
        with self.assertRaises(ValueError):
            Region.from_json({"x0": "left", "y0": 2, "x1": 3, "y1": 4})

    def test_a_non_object_is_an_error(self):
        with self.assertRaises(TypeError):
            Region.from_json([1, 2, 3, 4])


if __name__ == '__main__':
    unittest.main()
