"""Headless cover-controller checks: real PNGs, no user storage/network/Tk."""
from io import BytesIO
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image
from scripts import cover_view as view


def png(size):
    buffer = BytesIO()
    Image.new("RGB", size, "#40654c").save(buffer, format="PNG")
    return buffer.getvalue()


DATA = SimpleNamespace(thumbnail_png=png((54, 76)), poster_png=png((180, 254)))


class Photo:
    def __init__(self, **kwargs):
        if threading.get_ident() != self.owner:
            raise AssertionError("Tk image created outside the UI thread")
        self.arguments = kwargs

    def put(self, *_args, **_kwargs):
        pass


class Tree:
    def __init__(self):
        self.entries = {}
        self.selected = ()

    def item(self, iid, **values):
        self.entries.setdefault(iid, {}).update(values)

    def exists(self, iid):
        return iid in self.entries

    def selection(self):
        return self.selected

    def selection_set(self, iid):
        self.selected = (iid,)


class CoverViewTests(unittest.TestCase):
    def setUp(self):
        Photo.owner = threading.get_ident()
        patcher = patch.object(view, "PhotoImage", Photo)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.root = Mock()
        self.loader = Mock(return_value=DATA)
        self.presenter = view.CoverPresenter(self.root, Path("unused-test-cache"), loader=self.loader, workers=0)
        self.addCleanup(self.presenter.close)
        self.tree = Tree()
        self.preview = SimpleNamespace(host=Mock(), label=Mock(), title=Mock(), status=Mock())
        self.preview.host.winfo_width.return_value = 190
        self.preview.host.winfo_height.return_value = 270
        self.presenter.previews[self.tree] = self.preview

    def complete(self, url, data=DATA):
        self.presenter.completed.put((url, data))
        self.presenter.poll()

    def test_rows_display_placeholders_then_real_images_with_strong_references(self):
        self.presenter.set_items(self.tree, [("a", "番剧 A", "https://public.test/a")])
        self.assertIs(self.tree.entries["a"]["image"], self.presenter.placeholder)
        self.complete("https://public.test/a")
        self.assertIsNot(self.tree.entries["a"]["image"], self.presenter.placeholder)
        self.assertIs(self.presenter.references[self.tree]["a"], self.tree.entries["a"]["image"])
        self.assertIn(self.tree, self.presenter.preview_photos)
        self.assertIn("封面已加载", self.preview.status.set.call_args.args[0])

    def test_duplicate_urls_across_rows_and_views_share_one_download(self):
        other = Tree()
        self.presenter.set_items(self.tree, [("a", "A", "https://public.test/a"), ("b", "B", "https://public.test/a")])
        self.presenter.set_items(other, [("c", "C", "https://public.test/a")])
        self.assertEqual(self.presenter.jobs.qsize(), 1)
        self.complete("https://public.test/a")
        self.assertIs(self.tree.entries["a"]["image"], other.entries["c"]["image"])

    def test_stale_row_generation_does_not_overwrite_a_new_result(self):
        self.presenter.set_items(self.tree, [("a", "旧结果", "https://public.test/old")])
        self.presenter.set_items(self.tree, [("a", "新结果", "https://public.test/new")])
        self.complete("https://public.test/old")
        self.assertIs(self.tree.entries["a"]["image"], self.presenter.placeholder)
        self.complete("https://public.test/new")
        self.assertIs(self.tree.entries["a"]["image"], self.presenter.images["https://public.test/new"][0])
        self.preview.title.set.assert_called_with("新结果")

    def test_missing_cover_has_explicit_non_loading_status(self):
        self.presenter.set_items(self.tree, [("a", "手动添加", None)])
        self.assertEqual(self.presenter.jobs.qsize(), 0)
        self.preview.status.set.assert_called_with("该条目未提供封面")

    def test_error_can_be_retried_without_an_application_task_or_modal(self):
        self.presenter.set_items(self.tree, [("a", "A", "https://public.test/a")])
        self.presenter.jobs.get_nowait()
        self.complete("https://public.test/a", None)
        self.assertIn("失败", self.preview.status.set.call_args.args[0])
        self.presenter.retry(self.tree)
        self.assertEqual(self.presenter.jobs.get_nowait(), "https://public.test/a")
        self.complete("https://public.test/a")
        self.assertIn(self.tree, self.presenter.preview_photos)

    def test_cached_image_does_not_enqueue_a_second_download(self):
        self.presenter.set_items(self.tree, [("a", "A", "https://public.test/a")])
        self.presenter.jobs.get_nowait()
        self.complete("https://public.test/a")
        self.presenter.set_items(self.tree, [("b", "B", "https://public.test/a")])
        self.assertEqual(self.presenter.jobs.qsize(), 0)

    def test_retry_updates_all_current_rows_and_views_sharing_the_failed_cover(self):
        url = "https://public.test/shared"
        other = Tree()
        other_preview = SimpleNamespace(host=Mock(), label=Mock(), title=Mock(), status=Mock())
        other_preview.host.winfo_width.return_value = 190
        other_preview.host.winfo_height.return_value = 270
        self.presenter.previews[other] = other_preview
        self.presenter.set_items(self.tree, [("a", "A", url), ("b", "B", url)])
        self.presenter.set_items(other, [("c", "C", url)])
        self.presenter.jobs.get_nowait()
        self.complete(url, None)
        self.presenter.retry(self.tree)
        self.assertEqual(self.presenter.jobs.get_nowait(), url)
        self.complete(url)
        for tree, iid in ((self.tree, "a"), (self.tree, "b"), (other, "c")):
            self.assertIs(tree.entries[iid]["image"], self.presenter.images[url][0])
        self.assertIn(other, self.presenter.preview_photos)
        self.assertIn("封面已加载", other_preview.status.set.call_args.args[0])
        self.assertEqual(self.presenter.jobs.qsize(), 0)

    def test_selection_is_preserved_when_watchlist_refreshes(self):
        self.presenter.set_items(self.tree, [("a", "A", None), ("b", "B", None)], selected="b")
        self.assertEqual(self.tree.selection(), ("b",))
        self.preview.title.set.assert_called_with("B")

    def test_empty_list_clears_previous_poster_and_title(self):
        self.presenter.set_items(self.tree, [("a", "A", "https://public.test/a")])
        self.complete("https://public.test/a")
        self.tree.selected = ()
        self.presenter.set_items(self.tree, [])
        self.assertNotIn(self.tree, self.presenter.preview_photos)
        self.preview.title.set.assert_called_with("选择番剧查看封面")

    def test_preview_scales_to_a_small_window_without_cropping(self):
        self.preview.host.winfo_width.return_value = 120
        self.preview.host.winfo_height.return_value = 100
        self.presenter.set_items(self.tree, [("a", "A", "https://public.test/a")])
        self.complete("https://public.test/a")
        with Image.open(BytesIO(self.presenter.preview_photos[self.tree].arguments["data"])) as image:
            self.assertLessEqual(image.width, 112)
            self.assertLessEqual(image.height, 92)

    def test_download_runs_outside_ui_thread_and_tk_runs_only_in_poll(self):
        calls = []
        self.presenter.loader = lambda url, cache: calls.append(threading.get_ident()) or DATA
        worker = threading.Thread(target=self.presenter._worker, daemon=True)
        worker.start()
        self.presenter.set_items(self.tree, [("a", "A", "https://public.test/a")])
        url, data = self.presenter.completed.get(timeout=3)
        self.presenter.completed.put((url, data))
        self.presenter.poll()
        self.assertNotEqual(calls[0], threading.get_ident())
        self.assertIn(self.tree, self.presenter.preview_photos)
        self.presenter.close()
        worker.join(timeout=2)
        self.assertFalse(worker.is_alive())

    def test_close_cancels_timer_and_does_not_reschedule(self):
        self.presenter.close()
        self.root.after.reset_mock()
        self.presenter.poll()
        self.root.after.assert_not_called()
        self.root.after_cancel.assert_called()

    def test_cross_thread_widget_access_is_refused(self):
        errors = []
        def wrong_thread():
            try:
                self.presenter.set_items(self.tree, [])
            except RuntimeError as error:
                errors.append(error)
        worker = threading.Thread(target=wrong_thread)
        worker.start()
        worker.join(timeout=2)
        self.assertEqual(len(errors), 1)
