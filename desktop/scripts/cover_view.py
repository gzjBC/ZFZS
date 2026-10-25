"""Asynchronous native cover rendering; all Tk operations stay on the UI thread."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import queue
import threading
from tkinter import PhotoImage, StringVar, TclError, ttk

from PIL import Image


@dataclass
class _Preview:
    host: object
    label: object
    title: object
    status: object


class CoverPresenter:
    def __init__(self, root, cache_dir: Path, *, loader=None, workers: int = 3):
        self.root = root
        self.cache_dir = cache_dir
        self.loader = loader
        self.owner = threading.get_ident()
        self.closed = threading.Event()
        self.jobs = queue.Queue(maxsize=300)
        self.completed = queue.Queue()
        self.rows = {}
        self.generations = {}
        self.references = {}
        self.previews = {}
        self.preview_photos = {}
        self.inflight = {}
        self.errors = set()
        self.images = OrderedDict()
        self.placeholder = PhotoImage(master=root, width=54, height=76)
        self.placeholder.put("#e2e9e1", to=(0, 0, 54, 76))
        self.placeholder.put("#c8d6c9", to=(9, 29, 45, 52))
        self.placeholder.put("#a9beae", to=(15, 37, 39, 46))
        for _ in range(workers):
            threading.Thread(target=self._worker, daemon=True, name="ZFZS-cover").start()
        self.after_id = root.after(60, self.poll)
        root.bind("<Destroy>", self._destroyed, add="+")

    def _assert_ui(self):
        if threading.get_ident() != self.owner:
            raise RuntimeError("Cover widgets must be accessed on the UI thread.")

    def register(self, tree, parent):
        self._assert_ui()
        panel = ttk.Frame(parent, style="Card.TFrame", padding=(10, 10), width=210)
        panel.grid(row=0, column=2, rowspan=2, sticky="ns", padx=(10, 0))
        panel.grid_propagate(False)
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(0, weight=1)
        host = ttk.Frame(panel, style="Card.TFrame", width=188, height=254)
        host.grid(row=0, column=0, sticky="nsew")
        host.pack_propagate(False)
        label = ttk.Label(host, anchor="center", background="#fffdf8")
        label.pack(fill="both", expand=True)
        title = StringVar(master=self.root, value="选择番剧查看封面")
        status = StringVar(master=self.root, value="图片会在后台加载")
        ttk.Label(panel, textvariable=title, background="#fffdf8", foreground="#17201b",
                  font=("Microsoft YaHei UI", 10, "bold"), wraplength=182, justify="center").grid(row=1, column=0, sticky="ew", pady=(8, 4))
        ttk.Label(panel, textvariable=status, background="#fffdf8", foreground="#647069",
                  wraplength=182, justify="center").grid(row=2, column=0, sticky="ew", pady=(0, 4))
        ttk.Button(panel, text="重试封面", command=lambda: self.retry(tree)).grid(row=3, column=0)
        self.previews[tree] = _Preview(host, label, title, status)
        tree.bind("<<TreeviewSelect>>", lambda _event: self.select(tree), add="+")
        host.bind("<Configure>", lambda _event: self.select(tree), add="+")

    def set_items(self, tree, records, *, selected=None):
        self._assert_ui()
        if self.closed.is_set():
            return
        generation = self.generations.get(tree, 0) + 1
        self.generations[tree] = generation
        self.rows[tree] = {str(iid): (title, url or "") for iid, title, url in records}
        self.references[tree] = {}
        for iid, (_title, url) in self.rows[tree].items():
            tree.item(iid, image=self.placeholder)
            self.references[tree][iid] = self.placeholder
            if not url:
                continue
            if url in self.images:
                self._apply(tree, generation, iid, url)
            else:
                self._request(url, (tree, generation, iid))
        if selected and str(selected) in self.rows[tree]:
            tree.selection_set(str(selected))
        elif self.rows[tree]:
            tree.selection_set(next(iter(self.rows[tree])))
        self.select(tree)

    def _request(self, url, subscriber):
        if url in self.errors:
            return
        if url in self.inflight:
            self.inflight[url].append(subscriber)
            return
        try:
            self.jobs.put_nowait(url)
        except queue.Full:
            self.errors.add(url)
        else:
            self.inflight[url] = [subscriber]

    def _worker(self):
        while not self.closed.is_set():
            try:
                url = self.jobs.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                if self.loader is None:
                    from backend.app.service.cover_service import load_cover
                    data = load_cover(url, self.cache_dir)
                else:
                    data = self.loader(url, self.cache_dir)
            except Exception:
                self.completed.put((url, None))
            else:
                self.completed.put((url, data))
            finally:
                self.jobs.task_done()

    def poll(self):
        self._assert_ui()
        if self.closed.is_set():
            return
        for _ in range(12):
            try:
                url, data = self.completed.get_nowait()
            except queue.Empty:
                break
            subscribers = self.inflight.pop(url, [])
            affected = {subscriber[0] for subscriber in subscribers}
            if data is None:
                self.errors.add(url)
            else:
                try:
                    thumbnail = PhotoImage(master=self.root, data=data.thumbnail_png, format="png")
                except TclError:
                    self.errors.add(url)
                else:
                    self.images[url] = (thumbnail, data.poster_png)
                    self.images.move_to_end(url)
                    while len(self.images) > 96:
                        self.images.popitem(last=False)
                    self.errors.discard(url)
                    # A retry may originate in only one view, while other views
                    # still show placeholders from the same failed request.
                    for tree, records in self.rows.items():
                        for iid, (_title, current_url) in records.items():
                            if current_url == url:
                                self._apply(tree, self.generations[tree], iid, url)
                                affected.add(tree)
            for tree in affected:
                self.select(tree)
        self.after_id = self.root.after(60, self.poll)

    def _apply(self, tree, generation, iid, url):
        if self.generations.get(tree) != generation or self.rows.get(tree, {}).get(iid, (None, None))[1] != url:
            return
        if url not in self.images:
            return
        try:
            if tree.exists(iid):
                thumbnail = self.images[url][0]
                tree.item(iid, image=thumbnail)
                self.references[tree][iid] = thumbnail
        except TclError:
            pass

    def select(self, tree):
        self._assert_ui()
        if self.closed.is_set() or tree not in self.previews:
            return
        preview = self.previews[tree]
        try:
            selection = tree.selection()
            record = self.rows.get(tree, {}).get(selection[0]) if selection else None
            self.preview_photos.pop(tree, None)
            preview.label.configure(image="", text="封面预览")
            if not record:
                preview.title.set("选择番剧查看封面")
                preview.status.set("图片会在后台加载")
                return
            title, url = record
            preview.title.set(title[:32] + ("…" if len(title) > 32 else ""))
            if not url:
                preview.status.set("该条目未提供封面")
            elif url in self.images:
                width = min(180, max(20, preview.host.winfo_width() - 8))
                height = min(254, max(20, preview.host.winfo_height() - 8))
                with Image.open(BytesIO(self.images[url][1])) as source:
                    poster = source.convert("RGB")
                poster.thumbnail((width, height), Image.Resampling.LANCZOS)
                buffer = BytesIO()
                poster.save(buffer, format="PNG")
                photo = PhotoImage(master=self.root, data=buffer.getvalue(), format="png")
                self.preview_photos[tree] = photo
                preview.label.configure(image=photo, text="")
                preview.status.set("封面已加载 · 本机缓存")
                self.images.move_to_end(url)
            elif url in self.errors:
                preview.status.set("加载失败，可点重试封面")
            else:
                preview.status.set("正在加载封面…")
                if url not in self.inflight:
                    self._request(url, (tree, self.generations[tree], selection[0]))
        except (OSError, ValueError):
            self.images.pop(url, None)
            self.errors.add(url)
            preview.label.configure(image="", text="封面预览")
            preview.status.set("图片解码失败，可点重试")
        except TclError:
            pass

    def retry(self, tree):
        self._assert_ui()
        selection = tree.selection()
        record = self.rows.get(tree, {}).get(selection[0]) if selection else None
        if record and record[1]:
            url = record[1]
            self.errors.discard(url)
            if url not in self.images:
                self._request(url, (tree, self.generations[tree], selection[0]))
        self.select(tree)

    def _destroyed(self, event):
        if event.widget is self.root:
            self.close()

    def close(self):
        self.closed.set()
        try:
            self.root.after_cancel(self.after_id)
        except TclError:
            pass
