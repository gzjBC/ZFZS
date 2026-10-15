from __future__ import annotations

import ctypes
import os
import queue
import sys
import threading
import webbrowser
from datetime import date
from pathlib import Path
from tkinter import BooleanVar, IntVar, StringVar, Tk, Toplevel, TclError, messagebox
from tkinter import ttk
from typing import Any, Callable
from pydantic import ValidationError


PROJECT_ROOT = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


from backend.app.core.desktop_runtime import prepare_desktop_storage

DESKTOP_DATA_DIR = prepare_desktop_storage(PROJECT_ROOT)

from backend.app.crawlers.bangumi import BangumiClient
from backend.app.crawlers.xifan_playwright import XifanPlaywrightCrawler
from backend.app.db import base  # noqa: F401 - register SQLAlchemy models
from backend.app.db.migrate import run_lightweight_migrations
from backend.app.db.session import Base, SessionLocal, engine
from backend.app.schema.anime import AnimeCreate, AnimeUpdate
from backend.app.service import anime_service, reminder_service


APP_TITLE = "ZFZS 追番助手"
STATUS_LABELS = {"watching": "正在追", "paused": "暂停", "finished": "已看完"}
DAY_LABELS = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"]
SEASON_MONTHS = {"1 月（冬季）": 1, "4 月（春季）": 4, "7 月（夏季）": 7, "10 月（秋季）": 10}
DISCOVERY_LIMIT = 50
MUTEX_NAME = "Local\\ZFZS_Anime_Assistant_Desktop"
_MUTEX_HANDLE = None


def _anime_to_dict(item) -> dict[str, Any]:
    return {
        "id": item.id,
        "title": item.title,
        "status": item.status,
        "watched_episodes": item.watched_episodes,
        "total_episodes": item.total_episodes,
        "score": item.score,
        "source_status": item.source_status,
        "year": item.year,
        "broadcast_day": item.broadcast_day,
        "broadcast_time": item.broadcast_time,
        "reminder_enabled": item.reminder_enabled,
        "reminder_minutes": item.reminder_minutes,
        "play_url": item.play_url,
        "source_url": item.source_url,
        "summary": item.summary,
    }


def _progress_text(item: dict[str, Any]) -> str:
    watched = item["watched_episodes"] or 0
    total = item["total_episodes"]
    return f"{watched} / {total}" if total is not None else f"{watched} 集"


def _reminder_text(item: dict[str, Any]) -> str:
    if not item["reminder_enabled"] or item["broadcast_day"] is None:
        return "未设置"
    lead = item["reminder_minutes"] or 0
    suffix = "准点" if lead == 0 else f"提前 {lead} 分钟"
    return f"{DAY_LABELS[item['broadcast_day']]} {item['broadcast_time']} · {suffix}"


def _bring_existing_window_forward() -> None:
    if os.name != "nt":
        return

    user32 = ctypes.windll.user32

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def callback(hwnd, _):
        length = user32.GetWindowTextLengthW(hwnd)
        if not length:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        if buffer.value == APP_TITLE:
            user32.ShowWindow(hwnd, 9)
            user32.SetForegroundWindow(hwnd)
            return False
        return True

    user32.EnumWindows(callback, 0)


def _claim_single_instance() -> bool:
    global _MUTEX_HANDLE
    if os.name != "nt":
        return True
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    _MUTEX_HANDLE = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if kernel32.GetLastError() == 183:
        _bring_existing_window_forward()
        return False
    return True


class DesktopApp:
    def __init__(self, root: Tk):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1120x760")
        self.root.minsize(900, 700)
        self.root.configure(bg="#f2f0eb")

        self.items: dict[int, dict[str, Any]] = {}
        self.reminder_items: dict[int, dict[str, Any]] = {}
        self.search_results: dict[str, Any] = {}
        self.discovery_results: dict[str, Any] = {}
        self.busy = False
        self.task_results: queue.Queue = queue.Queue()

        self.keyword = StringVar()
        self.search_source = StringVar(value="Bangumi（推荐）")
        today = date.today()
        self.calendar_date = StringVar(value=today.isoformat())
        self.season_year = StringVar(value=str(today.year))
        quarter_month = ((today.month - 1) // 3) * 3 + 1
        self.season_month = StringVar(value=next(label for label, month in SEASON_MONTHS.items() if month == quarter_month))
        self.discovery_status = StringVar(value="选择日期或季度后加载 · 来源：Bangumi · 每次最多 50 条")
        self.discovery_result_context = "尚未加载"
        self.filter_status = StringVar(value="全部")
        self.status_text = StringVar(value="正在载入本地数据…")
        self.watching_count = StringVar(value="0")
        self.finished_count = StringVar(value="0")
        self.reminder_count = StringVar(value="0")

        self._configure_style()
        self._build_ui()
        self.root.after(50, self._poll_tasks)
        self.refresh_data()

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background="#f2f0eb")
        style.configure("Card.TFrame", background="#fffdf8", relief="solid", borderwidth=1)
        style.configure("Header.TLabel", background="#f2f0eb", foreground="#17201b", font=("Microsoft YaHei UI", 24, "bold"))
        style.configure("Sub.TLabel", background="#f2f0eb", foreground="#647069", font=("Microsoft YaHei UI", 10))
        style.configure("Stat.TLabel", background="#fffdf8", foreground="#17201b", font=("Microsoft YaHei UI", 20, "bold"))
        style.configure("StatName.TLabel", background="#fffdf8", foreground="#647069", font=("Microsoft YaHei UI", 9))
        style.configure("Accent.TButton", background="#e4572e", foreground="white", borderwidth=0, padding=(18, 9), font=("Microsoft YaHei UI", 10, "bold"))
        style.map("Accent.TButton", background=[("active", "#bd3d1c"), ("disabled", "#d8aaa0")])
        style.configure("Dark.TButton", background="#17201b", foreground="white", borderwidth=0, padding=(14, 8))
        style.map("Dark.TButton", background=[("active", "#2c3931")])
        style.configure("TButton", padding=(11, 7), font=("Microsoft YaHei UI", 9))
        style.configure("Treeview", rowheight=34, background="#fffdf8", fieldbackground="#fffdf8", foreground="#17201b", font=("Microsoft YaHei UI", 9), borderwidth=0)
        style.configure("Treeview.Heading", background="#e8eee8", foreground="#275d45", font=("Microsoft YaHei UI", 9, "bold"), padding=(8, 8))
        style.map("Treeview", background=[("selected", "#dce9e0")], foreground=[("selected", "#17201b")])
        style.configure("TNotebook", background="#f2f0eb", borderwidth=0)
        style.configure("TNotebook.Tab", padding=(18, 10), font=("Microsoft YaHei UI", 10, "bold"))
        style.map("TNotebook.Tab", background=[("selected", "#275d45")], foreground=[("selected", "white")])

    def _build_ui(self) -> None:
        shell = ttk.Frame(self.root, padding=(26, 22, 26, 18))
        shell.pack(fill="both", expand=True)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(3, weight=1)

        header = ttk.Frame(shell)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text=APP_TITLE, style="Header.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(header, text="本地原生应用 · 数据保存在本机 SQLite", style="Sub.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Button(header, text="手动添加", command=self.open_manual_dialog).grid(row=0, column=1, rowspan=2, padx=(8, 0))
        ttk.Button(header, text="刷新", style="Dark.TButton", command=self.refresh_data).grid(row=0, column=2, rowspan=2, padx=(8, 0))

        search = ttk.Frame(shell, style="Card.TFrame", padding=(18, 16))
        search.grid(row=1, column=0, sticky="ew", pady=(20, 14))
        search.columnconfigure(1, weight=1)
        ttk.Label(search, text="搜索番剧", background="#fffdf8", foreground="#275d45", font=("Microsoft YaHei UI", 11, "bold")).grid(row=0, column=0, padx=(0, 14))
        entry = ttk.Entry(search, textvariable=self.keyword, font=("Microsoft YaHei UI", 11))
        entry.grid(row=0, column=1, sticky="ew", ipady=7)
        entry.bind("<Return>", lambda _: self.search_xifan())
        ttk.Combobox(
            search,
            textvariable=self.search_source,
            state="readonly",
            width=16,
            values=("Bangumi（推荐）", "稀饭动漫"),
        ).grid(row=0, column=2, padx=(12, 0))
        ttk.Button(search, text="搜索", style="Accent.TButton", command=self.search_xifan).grid(row=0, column=3, padx=(8, 0))

        stats = ttk.Frame(shell)
        stats.grid(row=2, column=0, sticky="ew", pady=(0, 14))
        for index, (value, label) in enumerate(((self.watching_count, "正在追"), (self.finished_count, "已看完"), (self.reminder_count, "今日提醒"))):
            card = ttk.Frame(stats, style="Card.TFrame", padding=(20, 12))
            card.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 6, 0))
            stats.columnconfigure(index, weight=1)
            ttk.Label(card, textvariable=value, style="Stat.TLabel").pack(anchor="w")
            ttk.Label(card, text=label, style="StatName.TLabel").pack(anchor="w")

        self.notebook = ttk.Notebook(shell)
        self.notebook.grid(row=3, column=0, sticky="nsew")
        self.watch_tab = ttk.Frame(self.notebook, padding=(0, 12, 0, 0))
        self.reminder_tab = ttk.Frame(self.notebook, padding=(0, 12, 0, 0))
        self.search_tab = ttk.Frame(self.notebook, padding=(0, 12, 0, 0))
        self.discovery_tab = ttk.Frame(self.notebook, padding=(0, 12, 0, 0))
        self.notebook.add(self.watch_tab, text="我的追番")
        self.notebook.add(self.reminder_tab, text="今日提醒")
        self.notebook.add(self.search_tab, text="搜索结果")
        self.notebook.add(self.discovery_tab, text="发现番剧")

        self._build_watch_tab()
        self._build_reminder_tab()
        self._build_search_tab()
        self._build_discovery_tab()

        status = ttk.Label(shell, textvariable=self.status_text, style="Sub.TLabel", anchor="w")
        status.grid(row=4, column=0, sticky="ew", pady=(12, 0))

    def _tree(self, parent, columns: tuple[str, ...], headings: tuple[str, ...], widths: tuple[int, ...]):
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse")
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        for column, heading, width in zip(columns, headings, widths):
            tree.heading(column, text=heading)
            tree.column(column, width=width, minwidth=70, anchor="w", stretch=column == columns[0])
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        tree.bind("<Double-1>", lambda _: self.open_selected_link(tree))
        return tree

    def _build_watch_tab(self) -> None:
        toolbar = ttk.Frame(self.watch_tab)
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Label(toolbar, text="筛选：", style="Sub.TLabel").pack(side="left")
        filter_box = ttk.Combobox(toolbar, textvariable=self.filter_status, state="readonly", width=10, values=("全部", "正在追", "暂停", "已看完"))
        filter_box.pack(side="left")
        filter_box.bind("<<ComboboxSelected>>", lambda _: self.render_watchlist())

        self.watch_tree = self._tree(
            self.watch_tab,
            ("title", "progress", "status", "source", "reminder", "score"),
            ("番剧", "进度", "状态", "来源更新", "提醒", "评分"),
            (310, 90, 85, 145, 210, 65),
        )
        actions = ttk.Frame(self.watch_tab)
        actions.pack(fill="x", pady=(10, 0))
        for text, command in (
            ("−1 集", lambda: self.change_progress(-1)),
            ("+1 集", lambda: self.change_progress(1)),
            ("暂停 / 继续", self.toggle_pause),
            ("标记看完", self.mark_finished),
            ("提醒设置", self.open_reminder_dialog),
            ("打开播放页", lambda: self.open_selected_link(self.watch_tree)),
            ("移除", self.delete_selected),
        ):
            ttk.Button(actions, text=text, command=command).pack(side="left", padx=(0, 7))

    def _build_reminder_tab(self) -> None:
        self.reminder_tree = self._tree(
            self.reminder_tab,
            ("title", "time", "progress", "status"),
            ("番剧", "提醒时间", "进度", "状态"),
            (390, 240, 120, 100),
        )
        actions = ttk.Frame(self.reminder_tab)
        actions.pack(fill="x", pady=(10, 0))
        ttk.Button(actions, text="今天已提醒", style="Accent.TButton", command=self.mark_selected_reminded).pack(side="left")
        ttk.Button(actions, text="打开播放页", command=lambda: self.open_selected_link(self.reminder_tree)).pack(side="left", padx=(8, 0))

    def _build_search_tab(self) -> None:
        actions = ttk.Frame(self.search_tab)
        actions.pack(side="bottom", fill="x", pady=(10, 0))
        self.search_tree = self._result_tree(self.search_tab)
        ttk.Button(actions, text="加入追番", style="Accent.TButton", command=self.import_selected).pack(side="left")
        ttk.Button(actions, text="打开详情页", command=lambda: self.open_selected_link(self.search_tree)).pack(side="left", padx=(8, 0))

    def _result_tree(self, parent):
        return self._tree(
            parent,
            ("title", "year", "episodes", "status", "score"),
            ("番剧", "年份", "集数", "更新状态", "评分"),
            (430, 80, 90, 190, 70),
        )

    def _build_discovery_tab(self) -> None:
        calendar = ttk.Frame(self.discovery_tab)
        calendar.pack(fill="x", pady=(0, 6))
        ttk.Label(calendar, text="放送日历", style="Sub.TLabel").pack(side="left", padx=(0, 12))
        ttk.Entry(calendar, textvariable=self.calendar_date, width=13).pack(side="left")
        ttk.Label(calendar, text="YYYY-MM-DD", style="Sub.TLabel").pack(side="left", padx=8)
        ttk.Button(calendar, text="加载该日", command=self.load_calendar).pack(side="left")
        ttk.Button(calendar, text="整周", command=lambda: self.load_calendar(whole_week=True)).pack(side="left", padx=6)
        ttk.Label(calendar, text="按星期查询当前放送表，非历史排期", style="Sub.TLabel").pack(side="left")

        season = ttk.Frame(self.discovery_tab)
        season.pack(fill="x", pady=(0, 6))
        ttk.Label(season, text="季度新番", style="Sub.TLabel").pack(side="left", padx=(0, 12))
        ttk.Spinbox(season, textvariable=self.season_year, from_=1900, to=9999, width=6).pack(side="left")
        ttk.Label(season, text="年", style="Sub.TLabel").pack(side="left", padx=6)
        ttk.Combobox(season, textvariable=self.season_month, state="readonly", values=tuple(SEASON_MONTHS), width=14).pack(side="left")
        ttk.Button(season, text="加载季度", command=self.load_season).pack(side="left", padx=8)
        ttk.Label(self.discovery_tab, textvariable=self.discovery_status, style="Sub.TLabel", wraplength=800).pack(fill="x", pady=(0, 8))

        actions = ttk.Frame(self.discovery_tab)
        actions.pack(side="bottom", fill="x", pady=(10, 0))
        self.discovery_tree = self._result_tree(self.discovery_tab)
        ttk.Button(actions, text="加入我的追番", style="Accent.TButton", command=lambda: self.import_selected(self.discovery_tree)).pack(side="left")
        ttk.Button(actions, text="打开详情页", command=lambda: self.open_selected_link(self.discovery_tree)).pack(side="left", padx=(8, 0))

    def set_status(self, text: str) -> None:
        self.status_text.set(text)

    def _run_task(
        self,
        label: str,
        work: Callable[[], Any],
        done: Callable[[Any], None] | None = None,
        failed: Callable[[Exception], None] | None = None,
    ) -> bool:
        if self.busy:
            self.set_status("已有任务正在执行，请稍候。")
            return False
        self.busy = True
        self.set_status(label)

        def runner():
            try:
                result = work()
            except Exception as exc:
                self.task_results.put((False, exc, failed))
            else:
                self.task_results.put((True, result, done))

        threading.Thread(target=runner, daemon=True).start()
        return True

    def _poll_tasks(self) -> None:
        try:
            succeeded, result, done = self.task_results.get_nowait()
        except queue.Empty:
            pass
        else:
            if succeeded:
                self._task_done(result, done)
            else:
                if done:
                    done(result)
                self._task_failed(result)
        self.root.after(50, self._poll_tasks)

    def _task_done(self, result: Any, done: Callable[[Any], None] | None) -> None:
        self.busy = False
        if done:
            done(result)

    def _task_failed(self, error: Exception) -> None:
        self.busy = False
        self.set_status(f"操作失败：{error}")
        messagebox.showerror("操作失败", str(error), parent=self.root)

    def refresh_data(self, success_message: str = "数据已刷新。") -> None:
        def work():
            with SessionLocal() as db:
                anime = [_anime_to_dict(item) for item in anime_service.list_anime(db)]
                reminders = [_anime_to_dict(item) for item in reminder_service.list_today_due_anime(db)]
            return anime, reminders

        def done(result):
            anime, reminders = result
            self.items = {item["id"]: item for item in anime}
            self.reminder_items = {item["id"]: item for item in reminders}
            self.render_watchlist()
            self.render_reminders()
            self.watching_count.set(str(sum(item["status"] == "watching" for item in anime)))
            self.finished_count.set(str(sum(item["status"] == "finished" for item in anime)))
            self.reminder_count.set(str(len(reminders)))
            self.set_status(success_message)

        self._run_task("正在读取本地数据…", work, done)

    def render_watchlist(self) -> None:
        self.watch_tree.delete(*self.watch_tree.get_children())
        wanted = {"正在追": "watching", "暂停": "paused", "已看完": "finished"}.get(self.filter_status.get())
        for item in self.items.values():
            if wanted and item["status"] != wanted:
                continue
            self.watch_tree.insert("", "end", iid=str(item["id"]), values=(
                item["title"], _progress_text(item), STATUS_LABELS.get(item["status"], item["status"]),
                item["source_status"] or "—", _reminder_text(item), item["score"] if item["score"] is not None else "—",
            ))

    def render_reminders(self) -> None:
        self.reminder_tree.delete(*self.reminder_tree.get_children())
        for item in self.reminder_items.values():
            self.reminder_tree.insert("", "end", iid=str(item["id"]), values=(
                item["title"], _reminder_text(item), _progress_text(item), STATUS_LABELS.get(item["status"], item["status"]),
            ))

    def search_xifan(self) -> None:
        keyword = self.keyword.get().strip()
        if not keyword:
            messagebox.showinfo("请输入关键词", "请先输入番剧名称。", parent=self.root)
            return

        def done(results):
            self._render_results(self.search_tree, self.search_results, results)
            self.notebook.select(self.search_tab)
            self.set_status(f"搜索完成：找到 {len(results)} 条结果。")

        source = self.search_source.get()
        if source.startswith("Bangumi"):
            label = "正在通过 Bangumi 搜索…"
            work = lambda: BangumiClient().search(keyword, limit=12)
        else:
            label = "正在通过稀饭动漫搜索并读取详情…"
            work = lambda: XifanPlaywrightCrawler().search(keyword, limit=8)
        self._run_task(label, work, done)

    def _render_results(self, tree, target: dict[str, Any], results) -> None:
        target.clear()
        tree.delete(*tree.get_children())
        for index, item in enumerate(results):
            iid = f"result-{index}"
            target[iid] = item
            tree.insert("", "end", iid=iid, values=(
                item.title, item.year or "—", item.total_episodes or "—", item.status_text or "—",
                item.score if item.score is not None else "—",
            ))

    def load_calendar(self, whole_week: bool = False) -> None:
        if whole_week:
            weekday = None
            context = "放送日历 · 整周"
        else:
            try:
                selected_date = date.fromisoformat(self.calendar_date.get().strip())
            except ValueError:
                messagebox.showinfo("日期有误", "请输入有效日期，格式为 YYYY-MM-DD，例如 2026-10-15。", parent=self.root)
                return
            weekday = (selected_date.weekday() + 1) % 7
            context = f"放送日历 · {selected_date.isoformat()}（{DAY_LABELS[weekday]}）"

        def work():
            from backend.app.crawlers.bangumi_discovery import BangumiDiscoveryClient

            return BangumiDiscoveryClient().calendar(weekday=weekday, limit=DISCOVERY_LIMIT)

        self._load_discovery(context, work)

    def load_season(self) -> None:
        try:
            year = int(self.season_year.get().strip())
            month = SEASON_MONTHS[self.season_month.get()]
            if not 1900 <= year <= 9999:
                raise ValueError
        except (ValueError, KeyError):
            messagebox.showinfo("季度有误", "请输入 1900–9999 之间的年份，并选择 1、4、7 或 10 月季度。", parent=self.root)
            return
        context = f"季度新番 · {year} 年 {month} 月"

        def work():
            from backend.app.crawlers.bangumi_discovery import BangumiDiscoveryClient

            return BangumiDiscoveryClient().season(year=year, month=month, limit=DISCOVERY_LIMIT)

        self._load_discovery(context, work)

    def _load_discovery(self, context: str, work: Callable[[], Any]) -> None:
        def done(result):
            self._render_results(self.discovery_tree, self.discovery_results, result)
            self.discovery_result_context = context
            detail = f"{len(result)} 条结果（最多 {DISCOVERY_LIMIT} 条）" if result else "暂无条目，请尝试其他日期或季度。"
            self.discovery_status.set(f"{context} · {detail}")
            self.set_status(f"{context} 加载完成 · {detail}")

        def failed(_):
            self.discovery_status.set(f"{context} 加载失败，可重试。此前列表：{self.discovery_result_context}（{len(self.discovery_results)} 条）")

        if self._run_task(f"正在加载 {context}…", work, done, failed):
            self.discovery_status.set(f"正在加载 {context}…（完成前保留此前结果）")
            self.notebook.select(self.discovery_tab)

    def _selected_item(self, tree=None) -> dict[str, Any] | None:
        tree = tree or self.watch_tree
        selection = tree.selection()
        if not selection:
            messagebox.showinfo("请选择番剧", "请先在列表中选择一部番剧。", parent=self.root)
            return None
        item_id = int(selection[0])
        return self.reminder_items.get(item_id) if tree is self.reminder_tree else self.items.get(item_id)

    def import_selected(self, tree=None) -> None:
        tree = tree if tree is not None else self.search_tree
        results = self.discovery_results if tree is self.discovery_tree else self.search_results
        selection = tree.selection()
        if not selection:
            messagebox.showinfo("请选择结果", "请先选择一条番剧结果。", parent=self.root)
            return
        result = results[selection[0]]

        def work():
            with SessionLocal() as db:
                anime_service.import_search_result(db, result)
            return result.title

        def done(title):
            self.filter_status.set("全部")
            self.notebook.select(self.watch_tab)
            self.refresh_data(f"已加入追番：{title}（已有条目保留观看进度）")

        self._run_task(f"正在加入：{result.title}", work, done)

    def _mutate_selected(self, label: str, mutate: Callable[[Any, Any], None]) -> None:
        item = self._selected_item()
        if not item:
            return

        def work():
            with SessionLocal() as db:
                anime = anime_service.get_anime(db, item["id"])
                if anime is None:
                    raise RuntimeError("番剧不存在，可能已被删除。")
                mutate(db, anime)

        self._run_task(label, work, lambda _: self.refresh_data("操作已完成。"))

    def change_progress(self, delta: int) -> None:
        item = self._selected_item()
        if not item:
            return
        next_value = max(0, (item["watched_episodes"] or 0) + delta)
        if item["total_episodes"] is not None:
            next_value = min(next_value, item["total_episodes"])

        def mutate(db, anime):
            anime_service.update_progress(db, anime, next_value)

        self._mutate_selected(f"正在更新进度：{item['title']}", mutate)

    def toggle_pause(self) -> None:
        item = self._selected_item()
        if not item:
            return
        next_status = "watching" if item["status"] == "paused" else "paused"
        self._mutate_selected("正在更新状态…", lambda db, anime: anime_service.update_anime(db, anime, AnimeUpdate(status=next_status)))

    def mark_finished(self) -> None:
        self._mutate_selected("正在标记为已看完…", lambda db, anime: anime_service.update_anime(db, anime, AnimeUpdate(status="finished")))

    def delete_selected(self) -> None:
        item = self._selected_item()
        if not item or not messagebox.askyesno("确认移除", f"确定从追番列表移除“{item['title']}”吗？", parent=self.root):
            return
        self._mutate_selected("正在移除…", lambda db, anime: anime_service.delete_anime(db, anime))

    def mark_selected_reminded(self) -> None:
        item = self._selected_item(self.reminder_tree)
        if not item:
            return

        def work():
            with SessionLocal() as db:
                anime = anime_service.get_anime(db, item["id"])
                reminder_service.mark_reminded(db, anime)

        self._run_task("正在确认提醒…", work, lambda _: self.refresh_data("今日提醒已确认。"))

    def open_selected_link(self, tree) -> None:
        if tree is self.search_tree or tree is self.discovery_tree:
            selection = tree.selection()
            if not selection:
                messagebox.showinfo("请选择结果", "请先选择一条番剧结果。", parent=self.root)
                return
            results = self.discovery_results if tree is self.discovery_tree else self.search_results
            item = results[selection[0]]
            url = item.play_url or item.source_url
        else:
            item = self._selected_item(tree)
            if not item:
                return
            url = item["play_url"] or item["source_url"]
        if not url:
            messagebox.showinfo("没有链接", "这部番剧没有可用链接。", parent=self.root)
            return
        webbrowser.open(url)

    def open_manual_dialog(self) -> None:
        dialog = Toplevel(self.root)
        dialog.title("手动添加番剧")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)
        frame = ttk.Frame(dialog, padding=22)
        frame.pack(fill="both", expand=True)
        title = StringVar()
        total = StringVar()
        watched = IntVar(value=0)
        url = StringVar()
        fields = (("番剧名称", title), ("总集数（可留空）", total), ("当前进度", watched), ("播放地址（可留空）", url))
        for row, (label, variable) in enumerate(fields):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=7)
            ttk.Entry(frame, textvariable=variable, width=42).grid(row=row, column=1, sticky="ew", padx=(14, 0), pady=7)

        def save():
            name = title.get().strip()
            if not name:
                messagebox.showinfo("缺少名称", "请输入番剧名称。", parent=dialog)
                return
            try:
                total_value = int(total.get()) if total.get().strip() else None
                watched_value = watched.get()
                if total_value is not None and watched_value > total_value:
                    raise ValueError("当前进度不能超过总集数。")
                payload = AnimeCreate(title=name, total_episodes=total_value, watched_episodes=watched_value, play_url=url.get().strip() or None, reminder_enabled=False)
            except (ValueError, TclError, ValidationError):
                messagebox.showinfo("输入有误", "名称不超过 255 字；集数和进度须为非负整数，且进度不能超过总集数。", parent=dialog)
                return

            def work():
                with SessionLocal() as db:
                    anime_service.create_anime(db, payload)

            dialog.destroy()
            self._run_task("正在添加番剧…", work, lambda _: self.refresh_data("番剧已添加。"))

        buttons = ttk.Frame(frame)
        buttons.grid(row=len(fields), column=0, columnspan=2, sticky="e", pady=(16, 0))
        ttk.Button(buttons, text="取消", command=dialog.destroy).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="添加", style="Accent.TButton", command=save).pack(side="left")
        dialog.bind("<Escape>", lambda _: dialog.destroy())
        dialog.wait_visibility()
        dialog.geometry(f"+{self.root.winfo_rootx() + 220}+{self.root.winfo_rooty() + 150}")

    def open_reminder_dialog(self) -> None:
        item = self._selected_item()
        if not item:
            return
        dialog = Toplevel(self.root)
        dialog.title("提醒设置")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)
        frame = ttk.Frame(dialog, padding=22)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=item["title"], font=("Microsoft YaHei UI", 12, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))
        enabled = BooleanVar(value=item["reminder_enabled"])
        day = StringVar(value="" if item["broadcast_day"] is None else str(item["broadcast_day"]))
        time_value = StringVar(value=item["broadcast_time"] or "20:00")
        minutes = StringVar(value=str(item["reminder_minutes"] or 0))
        ttk.Checkbutton(frame, text="启用更新提醒", variable=enabled).grid(row=1, column=0, columnspan=2, sticky="w", pady=6)
        ttk.Label(frame, text="每周更新日").grid(row=2, column=0, sticky="w", pady=7)
        ttk.Combobox(frame, textvariable=day, state="readonly", values=("", "1", "2", "3", "4", "5", "6", "0"), width=18).grid(row=2, column=1, padx=(14, 0), pady=7)
        ttk.Label(frame, text="时间（HH:MM）").grid(row=3, column=0, sticky="w", pady=7)
        ttk.Entry(frame, textvariable=time_value, width=20).grid(row=3, column=1, padx=(14, 0), pady=7)
        ttk.Label(frame, text="提前分钟").grid(row=4, column=0, sticky="w", pady=7)
        ttk.Combobox(frame, textvariable=minutes, state="readonly", values=("0", "15", "30", "60"), width=18).grid(row=4, column=1, padx=(14, 0), pady=7)

        def save():
            if enabled.get() and not day.get():
                messagebox.showinfo("缺少更新日", "启用提醒前请选择每周更新日。", parent=dialog)
                return
            try:
                payload = AnimeUpdate(
                    reminder_enabled=enabled.get(),
                    broadcast_day=int(day.get()) if day.get() else None,
                    broadcast_time=time_value.get(),
                    reminder_minutes=int(minutes.get()),
                )
            except (ValueError, ValidationError):
                messagebox.showinfo("时间有误", "请输入有效的 24 小时时间，例如 20:00。", parent=dialog)
                return

            def work():
                with SessionLocal() as db:
                    anime = anime_service.get_anime(db, item["id"])
                    anime_service.update_anime(db, anime, payload)

            dialog.destroy()
            self._run_task("正在保存提醒设置…", work, lambda _: self.refresh_data("提醒设置已保存。"))

        buttons = ttk.Frame(frame)
        buttons.grid(row=5, column=0, columnspan=2, sticky="e", pady=(16, 0))
        ttk.Button(buttons, text="取消", command=dialog.destroy).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="保存", style="Accent.TButton", command=save).pack(side="left")
        dialog.bind("<Escape>", lambda _: dialog.destroy())
        dialog.wait_visibility()
        dialog.geometry(f"+{self.root.winfo_rootx() + 250}+{self.root.winfo_rooty() + 160}")


def main() -> None:
    if not _claim_single_instance():
        return
    try:
        if os.name == "nt":
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                pass
        Base.metadata.create_all(bind=engine)
        run_lightweight_migrations()
        root = Tk()
        DesktopApp(root)
        root.mainloop()
    except Exception as exc:
        try:
            error_root = Tk()
            error_root.withdraw()
            messagebox.showerror("ZFZS 启动失败", str(exc), parent=error_root)
            error_root.destroy()
        except Exception:
            raise


if __name__ == "__main__":
    main()
