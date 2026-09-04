"""The in-memory image cache behind the chat transcript's `<img>` tags."""
import unittest

from cltl.chatui.api import StoredImage
from cltl.chatui.memory import MemoryImageStore


def image(image_id: str, size: int = 8) -> StoredImage:
    return StoredImage(image_id, b"x" * size, "image/png", 64, 48)


class MemoryImageStoreTest(unittest.TestCase):
    def test_stores_and_returns_the_bytes_unchanged(self):
        store = MemoryImageStore()
        store.store(image("one"))

        stored = store.get("one")

        self.assertEqual(b"x" * 8, stored.data)
        self.assertEqual("image/png", stored.content_type)
        self.assertEqual((0, 0, 64, 48), stored.bounds)

    def test_an_unknown_id_is_none(self):
        self.assertIsNone(MemoryImageStore().get("nothing"))

    def test_evicts_the_oldest_first(self):
        """FIFO, not LRU: a transcript is chronological."""
        store = MemoryImageStore(capacity=2)
        store.store(image("one"))
        store.store(image("two"))
        store.get("one")
        store.store(image("three"))

        self.assertIsNone(store.get("one"))
        self.assertIsNotNone(store.get("two"))
        self.assertIsNotNone(store.get("three"))

    def test_capacity_is_at_least_one(self):
        store = MemoryImageStore(capacity=0)
        store.store(image("one"))

        self.assertIsNotNone(store.get("one"))

    def test_an_oversized_image_is_rejected(self):
        store = MemoryImageStore(max_size=4)

        with self.assertRaises(ValueError):
            store.store(image("one", size=5))

        self.assertIsNone(store.get("one"))

    def test_an_image_at_the_limit_is_accepted(self):
        store = MemoryImageStore(max_size=4)
        store.store(image("one", size=4))

        self.assertIsNotNone(store.get("one"))

    def test_remove_reports_whether_it_removed_anything(self):
        store = MemoryImageStore()
        store.store(image("one"))

        self.assertTrue(store.remove("one"))
        self.assertFalse(store.remove("one"))
        self.assertIsNone(store.get("one"))

    def test_clear_empties_the_store(self):
        store = MemoryImageStore()
        store.store(image("one"))
        store.store(image("two"))

        store.clear()

        self.assertIsNone(store.get("one"))
        self.assertIsNone(store.get("two"))


if __name__ == '__main__':
    unittest.main()
