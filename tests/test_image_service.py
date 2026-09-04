"""Upload, annotate, submit — the HTTP surface and what it puts on the bus.

The property this file exists to protect is a negative one: submitting an
annotated image must publish an `ImageSignalEvent` and *nothing at all* on the
utterance topic. cltl-eliza consumes that topic, so a stray publish here turns
every uploaded picture into a question the agent answers.
"""
import base64
import time
import unittest
from unittest import mock

from cltl.chatui.memory import MemoryImageStore
from tests.support import (IMAGE_TOPIC, UTTERANCE_TOPIC, Listener, ServiceHarness,
                           cv2_available, png_bytes, start_scenario, stop_scenario)

PNG = png_bytes(4, 3, (255, 0, 0))
WIDTH, HEIGHT = 4, 3

REGIONS = {"regions": [{"x0": 0, "y0": 0, "x1": 2, "y1": 2, "label": "a chair"},
                       {"x0": 2, "y0": 1, "x1": 4, "y1": 3, "label": "a lamp"}]}


class ImageServiceTest(unittest.TestCase):
    def setUp(self):
        self.harness = None

    def tearDown(self):
        if self.harness:
            self.harness.stop()

    def start(self, image_store=None, **kwargs) -> ServiceHarness:
        store = image_store if image_store is not None else MemoryImageStore()
        self.harness = ServiceHarness(image_store=store, image_topic=IMAGE_TOPIC, **kwargs)

        return self.harness

    def started(self, **kwargs):
        """A harness with an open scenario and a chat id, ready to upload into."""
        harness = self.start(**kwargs)
        scenario = start_scenario(harness.event_bus)
        harness.await_scenario()

        return harness, scenario, harness.chat_id()

    def upload(self, harness, chat_id, data=PNG, content_type="image/png",
               width=WIDTH, height=HEIGHT):
        return harness.client.post(
            f"/chat/{chat_id}/image?width={width}&height={height}",
            data=data, content_type=content_type)


class UploadTest(ImageServiceTest):
    def test_upload_returns_an_id_and_a_url(self):
        harness, _, chat_id = self.started()

        response = self.upload(harness, chat_id)

        self.assertEqual(201, response.status_code)
        payload = response.get_json()
        self.assertTrue(payload["id"])
        self.assertEqual(f"/chat/{chat_id}/image/{payload['id']}", payload["url"])
        self.assertEqual([WIDTH, HEIGHT], [payload["width"], payload["height"]])
        self.assertEqual("image/png", payload["content_type"])

    def test_upload_publishes_nothing(self):
        """The event goes out on submit, not on upload."""
        harness, _, chat_id = self.started()
        listener = Listener(harness.event_bus, IMAGE_TOPIC, UTTERANCE_TOPIC)

        self.upload(harness, chat_id)

        self.assertEqual(0, listener.count())

    def test_the_bytes_come_back_unchanged(self):
        harness, _, chat_id = self.started()
        image_id = self.upload(harness, chat_id).get_json()["id"]

        response = harness.client.get(f"/chat/{chat_id}/image/{image_id}")

        self.assertEqual(200, response.status_code)
        self.assertEqual(PNG, response.data)
        self.assertEqual("image/png", response.mimetype)

    def test_an_unsupported_type_is_rejected(self):
        harness, _, chat_id = self.started()

        response = self.upload(harness, chat_id, content_type="application/pdf")

        self.assertEqual(415, response.status_code)

    def test_a_content_type_with_parameters_is_accepted(self):
        harness, _, chat_id = self.started()

        self.assertEqual(201, self.upload(harness, chat_id,
                                          content_type="image/png; charset=binary").status_code)

    def test_dimensions_are_required(self):
        harness, _, chat_id = self.started()

        response = harness.client.post(f"/chat/{chat_id}/image",
                                       data=PNG, content_type="image/png")

        self.assertEqual(400, response.status_code)

    def test_dimensions_must_be_positive(self):
        harness, _, chat_id = self.started()

        self.assertEqual(400, self.upload(harness, chat_id, width=0).status_code)
        self.assertEqual(400, self.upload(harness, chat_id, height=-3).status_code)

    def test_an_empty_body_is_rejected(self):
        harness, _, chat_id = self.started()

        self.assertEqual(400, self.upload(harness, chat_id, data=b"").status_code)

    def test_an_oversized_upload_is_rejected(self):
        harness, _, chat_id = self.started(image_store=MemoryImageStore(max_size=16))

        response = self.upload(harness, chat_id, data=PNG)

        self.assertEqual(413, response.status_code)

    def test_a_wrong_chat_id_is_rejected(self):
        harness, _, _ = self.started()

        self.assertEqual(404, self.upload(harness, "not-a-chat-id").status_code)

    def test_an_unknown_image_is_a_404(self):
        harness, _, chat_id = self.started()

        self.assertEqual(404, harness.client.get(f"/chat/{chat_id}/image/nothing").status_code)

    def test_an_image_can_be_deleted(self):
        harness, _, chat_id = self.started()
        image_id = self.upload(harness, chat_id).get_json()["id"]

        self.assertEqual(204, harness.client.delete(f"/chat/{chat_id}/image/{image_id}").status_code)
        self.assertEqual(404, harness.client.delete(f"/chat/{chat_id}/image/{image_id}").status_code)
        self.assertEqual(404, harness.client.get(f"/chat/{chat_id}/image/{image_id}").status_code)


class UploadDisabledTest(ImageServiceTest):
    def test_the_routes_are_404_when_upload_is_off(self):
        """`@singleton` hands back False, not None, for a disabled service."""
        harness = self.start(image_store=False)
        start_scenario(harness.event_bus)
        harness.await_scenario()
        chat_id = harness.chat_id()

        self.assertEqual(404, self.upload(harness, chat_id).status_code)
        self.assertEqual(404, harness.client.get(f"/chat/{chat_id}/image/any").status_code)
        self.assertEqual(404, harness.client.post(f"/chat/{chat_id}/image/any/annotations",
                                                  json=REGIONS).status_code)

    def test_text_still_works_when_upload_is_off(self):
        harness = self.start(image_store=False)
        start_scenario(harness.event_bus)
        harness.await_scenario()
        chat_id = harness.chat_id()

        self.assertEqual(200, harness.client.post(f"/chat/{chat_id}", data="hello").status_code)


class AnnotationTest(ImageServiceTest):
    def annotate(self, harness, chat_id, image_id, body=None):
        return harness.client.post(f"/chat/{chat_id}/image/{image_id}/annotations",
                                   json=body if body is not None else REGIONS)

    def test_submit_publishes_one_image_signal(self):
        harness, scenario, chat_id = self.started()
        image_id = self.upload(harness, chat_id).get_json()["id"]
        listener = Listener(harness.event_bus, IMAGE_TOPIC)

        response = self.annotate(harness, chat_id, image_id)

        self.assertEqual(200, response.status_code)
        event = listener.await_event()
        self.assertEqual("ImageSignalEvent", event.payload.type)
        self.assertEqual(image_id, event.payload.signal.id)
        self.assertEqual(scenario.id, event.payload.signal.time.container_id)
        self.assertEqual(scenario.id, event.metadata.scenario_id)

    def test_submit_publishes_exactly_one_event(self):
        harness, _, chat_id = self.started()
        image_id = self.upload(harness, chat_id).get_json()["id"]
        listener = Listener(harness.event_bus, IMAGE_TOPIC)

        self.annotate(harness, chat_id, image_id)
        listener.await_event()

        self.assertEqual(0, listener.count())

    def test_submit_says_nothing_on_the_utterance_topic(self):
        """The regression that would make Eliza answer every picture."""
        harness, _, chat_id = self.started()
        image_id = self.upload(harness, chat_id).get_json()["id"]
        listener = Listener(harness.event_bus, UTTERANCE_TOPIC)

        self.annotate(harness, chat_id, image_id)

        self.assertEqual(0, listener.count())

    def test_the_signal_carries_the_mentions(self):
        harness, _, chat_id = self.started()
        image_id = self.upload(harness, chat_id).get_json()["id"]
        listener = Listener(harness.event_bus, IMAGE_TOPIC)

        response = self.annotate(harness, chat_id, image_id)

        signal = listener.await_event().payload.signal
        self.assertEqual(2, len(signal.mentions))
        self.assertEqual(2, response.get_json()["mentions"])
        self.assertEqual([(0, 0, 2, 2), (2, 1, 4, 3)],
                         [tuple(mention.segment[0].bounds) for mention in signal.mentions])
        self.assertEqual(["a chair", "a lamp"],
                         [mention.annotations[0].value.label for mention in signal.mentions])

    def test_the_signal_references_the_storage_url(self):
        harness, _, chat_id = self.started()
        image_id = self.upload(harness, chat_id).get_json()["id"]
        listener = Listener(harness.event_bus, IMAGE_TOPIC)

        self.annotate(harness, chat_id, image_id)

        self.assertEqual([f"cltl-storage:image/{image_id}"], listener.await_event().payload.signal.files)

    def test_a_submission_without_regions_is_allowed(self):
        harness, _, chat_id = self.started()
        image_id = self.upload(harness, chat_id).get_json()["id"]
        listener = Listener(harness.event_bus, IMAGE_TOPIC)

        response = self.annotate(harness, chat_id, image_id, {"regions": []})

        self.assertEqual(200, response.status_code)
        self.assertEqual(0, len(listener.await_event().payload.signal.mentions))

    def test_a_malformed_body_is_a_400(self):
        harness, _, chat_id = self.started()
        image_id = self.upload(harness, chat_id).get_json()["id"]

        for body in ({}, {"regions": "everything"},
                     {"regions": [{"x0": 0, "y0": 0, "x1": 1}]},
                     {"regions": [{"x0": "left", "y0": 0, "x1": 1, "y1": 1}]},
                     {"regions": ["not-an-object"]}):
            with self.subTest(body=body):
                self.assertEqual(400, self.annotate(harness, chat_id, image_id, body).status_code)

    def test_an_unknown_image_is_a_404(self):
        harness, _, chat_id = self.started()

        self.assertEqual(404, self.annotate(harness, chat_id, "nothing").status_code)

    def test_no_scenario_is_a_conflict_not_a_server_error(self):
        """`MemoryChats` mints a chat id eagerly, before any scenario exists.

        The text path lets that become an uncaught ValueError and so a 500. The
        image path must not copy it: nothing is wrong with the request.
        """
        harness = self.start()
        chat_id = harness.chat_id()
        image_id = self.upload(harness, chat_id).get_json()["id"]

        response = self.annotate(harness, chat_id, image_id)

        self.assertEqual(409, response.status_code)

    def test_the_chat_is_gone_once_the_scenario_stops(self):
        harness, scenario, chat_id = self.started()
        image_id = self.upload(harness, chat_id).get_json()["id"]

        stop_scenario(harness.event_bus, scenario)
        harness.await_no_scenario()

        self.assertEqual(404, self.annotate(harness, chat_id, image_id).status_code)


class EchoTest(ImageServiceTest):
    def submit(self, harness, chat_id, regions=None):
        image_id = self.upload(harness, chat_id).get_json()["id"]
        harness.client.post(f"/chat/{chat_id}/image/{image_id}/annotations",
                            json=regions if regions is not None else REGIONS)

        return image_id

    def test_the_image_appears_in_the_transcript(self):
        harness, _, chat_id = self.started()

        image_id = self.submit(harness, chat_id)

        utterance = harness.client.get(f"/chat/{chat_id}").get_json()[0]
        self.assertEqual("text/html", utterance["content_type"])
        self.assertIn("<img src=", utterance["text"])
        self.assertIn(f"/chat/{chat_id}/image/{image_id}", utterance["text"])
        self.assertIn("a chair", utterance["text"])
        self.assertIn("a lamp", utterance["text"])

    def test_the_echo_is_attributed_to_the_speaker(self):
        harness, _, chat_id = self.started()

        self.submit(harness, chat_id)

        utterance = harness.client.get(f"/chat/{chat_id}").get_json()[0]
        self.assertEqual("Human", utterance["speaker"])

    def test_labels_are_escaped(self):
        """`Bubbles.js` assigns `innerHTML`; escaping is this end's job."""
        harness, _, chat_id = self.started()

        self.submit(harness, chat_id,
                    {"regions": [{"x0": 0, "y0": 0, "x1": 2, "y1": 2,
                                  "label": '"><script>alert(1)</script>'}]})

        text = harness.client.get(f"/chat/{chat_id}").get_json()[0]["text"]
        self.assertNotIn("<script>", text)
        self.assertIn("&lt;script&gt;", text)

    def test_the_echo_is_the_only_new_utterance(self):
        harness, _, chat_id = self.started()

        self.submit(harness, chat_id)

        self.assertEqual(1, len(harness.client.get(f"/chat/{chat_id}").get_json()))


class StorageUploadTest(ImageServiceTest):
    """The best-effort PUT that makes `cltl-storage:image/<id>` resolvable."""

    def submit(self, harness, chat_id):
        image_id = self.upload(harness, chat_id).get_json()["id"]
        response = harness.client.post(f"/chat/{chat_id}/image/{image_id}/annotations",
                                       json=REGIONS)

        return image_id, response

    @unittest.skipUnless(cv2_available(), "cv2 is not installed in this environment")
    def test_the_pixels_are_put_to_the_backend(self):
        harness, _, chat_id = self.started(
            image_storage_url="http://storage.test/storage/")

        with mock.patch("cltl_service.chatui.service.requests") as http:
            http.put.return_value = mock.Mock(ok=True, status_code=204, text="")
            image_id, response = self.submit(harness, chat_id)

        self.assertEqual(200, response.status_code)
        http.put.assert_called_once()
        url = http.put.call_args[0][0]
        body = http.put.call_args[1]["json"]

        self.assertEqual(f"http://storage.test/storage/image/{image_id}", url)
        # A dict, so `image_hook` takes `Bounds(**view)` rather than the
        # positional fallback, whose field order is (x0, x1, y0, y1).
        self.assertEqual({"x0": 0, "x1": WIDTH, "y0": 0, "y1": HEIGHT}, body["view"])
        # Present and null: `image_hook` indexes it unconditionally.
        self.assertIn("depth", body)
        self.assertIsNone(body["depth"])
        self.assertEqual("np.ndarray", body["image"]["__type"])
        self.assertEqual([HEIGHT, WIDTH, 3], body["image"]["shape"])
        self.assertEqual("uint8", body["image"]["dtype"])
        pixels = base64.b64decode(body["image"]["data"])
        self.assertEqual(HEIGHT * WIDTH * 3, len(pixels))
        self.assertEqual((255, 0, 0), tuple(pixels[:3]))

    def test_nothing_is_put_without_a_storage_url(self):
        harness, _, chat_id = self.started(image_storage_url=None)

        with mock.patch("cltl_service.chatui.service.requests") as http:
            _, response = self.submit(harness, chat_id)

        self.assertEqual(200, response.status_code)
        http.put.assert_not_called()

    @unittest.skipUnless(cv2_available(), "cv2 is not installed in this environment")
    def test_a_failed_put_does_not_lose_the_annotations(self):
        harness, _, chat_id = self.started(image_storage_url="http://storage.test/storage/")
        listener = Listener(harness.event_bus, IMAGE_TOPIC)

        with mock.patch("cltl_service.chatui.service.requests") as http:
            http.put.side_effect = OSError("connection refused")
            _, response = self.submit(harness, chat_id)

        self.assertEqual(200, response.status_code)
        self.assertEqual(2, len(listener.await_event().payload.signal.mentions))


class ScenarioLifecycleTest(ImageServiceTest):
    def test_stopping_the_scenario_empties_the_store(self):
        store = MemoryImageStore()
        harness = self.start(image_store=store)
        scenario = start_scenario(harness.event_bus)
        harness.await_scenario()
        chat_id = harness.chat_id()
        image_id = self.upload(harness, chat_id).get_json()["id"]
        self.assertIsNotNone(store.get(image_id))

        stop_scenario(harness.event_bus, scenario)

        deadline = time.monotonic() + 5
        while store.get(image_id) is not None and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertIsNone(store.get(image_id))


if __name__ == '__main__':
    unittest.main()
