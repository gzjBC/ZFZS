"""Opt-in, login-session reminders; no OS service, startup item or PID killing.

Importing this module never starts a process or opens a database. Worker DB
connections always target the supplied directory's existing ``zfzs.db``.
"""

from __future__ import annotations

import ctypes
import errno
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import BinaryIO


_LOG = logging.getLogger(__name__)
_WORKER_LOCK = ".reminder-worker.lock"
_CONTROL_LOCK = ".reminder-control.lock"
_DISPATCH_LOCK = ".reminder-dispatch.lock"
_STATE = ".reminder-worker.json"
_STOP = ".reminder-stop.json"
_LAUNCH = ".reminder-launch.json"
_TOKEN_ENV = "ZFZS_REMINDER_TOKEN"
_START_TIMEOUT = 8.0
_MAC_SCRIPT = (
    'display notification (system attribute "ZFZS_NOTIFICATION_MESSAGE") '
    'with title (system attribute "ZFZS_NOTIFICATION_TITLE")'
)


class _FileLock:
    """OS-released lock; lock files are deliberately never unlinked/replaced."""

    def __init__(self, path: Path, *, create: bool = True):
        self.path = path
        self.create = create
        self.file: BinaryIO | None = None

    def acquire(self) -> bool:
        stream = self.path.open("a+b" if self.create else "r+b")
        try:
            if self.create and self.path.stat().st_size == 0:
                stream.write(b"\0")
                stream.flush()
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            stream.close()
            if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                return False
            raise
        self.file = stream
        return True

    def release(self) -> None:
        if self.file is None:
            return
        stream, self.file = self.file, None
        try:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            stream.close()


def _read_token(path: Path) -> str | None:
    try:
        # State/control files contain only a random generation, never user data.
        with path.open(encoding="utf-8") as stream:
            value = json.loads(stream.read(1024)).get("token")
        if isinstance(value, str) and len(value) == 32:
            int(value, 16)
            return value
    except (OSError, ValueError, AttributeError):
        pass
    return None


def _write_token(path: Path, token: str) -> None:
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump({"token": token}, stream)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _remove_own_token(path: Path, token: str) -> None:
    if _read_token(path) == token:
        path.unlink(missing_ok=True)


def background_status(data_dir: Path) -> bool:
    """Probe a live OS lock. No process, directory or file is created."""
    lock = _FileLock(Path(data_dir).expanduser().resolve() / _WORKER_LOCK, create=False)
    try:
        if not lock.acquire():
            return True
        return False
    except FileNotFoundError:
        return False
    except OSError as exc:
        _LOG.warning("Cannot inspect reminder worker (%s).", type(exc).__name__)
        return False
    finally:
        lock.release()


def _compatible_ui_database(data_dir: Path) -> bool:
    # Inspect the actual UI engine, not just an environment variable that may
    # have changed after SQLAlchemy/settings were imported.
    from backend.app.db.session import engine

    url = engine.url
    return bool(
        url.drivername.startswith("sqlite")
        and url.database
        and url.database != ":memory:"
        and not url.query
        and Path(url.database).expanduser().resolve() == data_dir / "zfzs.db"
    )


def _acquire_control(lock: _FileLock) -> bool:
    deadline = time.monotonic() + 2.0
    while not lock.acquire():
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)
    return True


def start_background_worker(data_dir: Path) -> bool:
    """Explicit user action only. True means an existing/new worker is ready.

    Custom UI database URLs are refused unless they resolve to exactly this
    directory's SQLite file. This function must not be called on UI startup.
    """
    data_dir = Path(data_dir).expanduser().resolve()
    guard = _FileLock(data_dir / _CONTROL_LOCK)
    launch_token: str | None = None
    try:
        if not _compatible_ui_database(data_dir):
            _LOG.warning("Background reminders require data_dir/zfzs.db; custom DATABASE_URL is unsupported.")
            return False
        if not (data_dir / "zfzs.db").is_file():
            _LOG.warning("Initialize the desktop database before enabling background reminders.")
            return False
        if not _acquire_control(guard):
            _LOG.warning("Another reminder start/stop operation is in progress; retry shortly.")
            return False
        if background_status(data_dir):
            token = _read_token(data_dir / _STATE)
            return token is not None and _read_token(data_dir / _STOP) != token
        token = uuid.uuid4().hex
        launch_token = token
        _write_token(data_dir / _LAUNCH, token)
        if getattr(sys, "frozen", False):
            command = [sys.executable, "--reminder-worker", "--data-dir", str(data_dir)]
        else:
            script = Path(__file__).resolve().parents[3] / "scripts" / "reminder_worker.py"
            command = [sys.executable, str(script), "--data-dir", str(data_dir)]
        env = {key: value for key, value in os.environ.items() if not key.upper().endswith("API_KEY")}
        env.update({
            "DATABASE_URL": f"sqlite:///{(data_dir / 'zfzs.db').as_posix()}",
            "ZFZS_DATA_DIR": str(data_dir),
            _TOKEN_ENV: token,
        })
        options = {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
        child = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, cwd=str(data_dir), env=env, **options,
        )
        deadline = time.monotonic() + _START_TIMEOUT
        while time.monotonic() < deadline:
            if background_status(data_dir) and _read_token(data_dir / _STATE) == token:
                return True
            if child.poll() is not None:
                _remove_own_token(data_dir / _LAUNCH, token)
                _LOG.warning("Reminder worker exited before readiness; see reminder-worker.log.")
                return False
            time.sleep(0.05)
        # A slow import must not result in a worker starting after a False UI
        # result. The generation is passed before launch, so cancellation also
        # works before the worker has written its readiness file.
        _write_token(data_dir / _STOP, token)
        _remove_own_token(data_dir / _LAUNCH, token)
        _LOG.warning("Reminder worker readiness timed out; cooperative cancellation requested.")
        return False
    except Exception as exc:
        if launch_token is not None:
            try:
                _remove_own_token(data_dir / _LAUNCH, launch_token)
            except OSError:
                pass
        # Exception text can contain database URLs or command payloads.
        _LOG.warning("Cannot start reminder worker (%s).", type(exc).__name__)
        return False
    finally:
        guard.release()


def stop_background_worker(data_dir: Path) -> bool:
    """Request cooperative stop; True also covers an already stopped worker.

    No signal is sent to a PID. An in-flight platform notification can take up
    to 15 seconds to return; use background_status to observe final shutdown.
    """
    data_dir = Path(data_dir).expanduser().resolve()
    if not data_dir.is_dir():
        return True
    guard = _FileLock(data_dir / _CONTROL_LOCK)
    try:
        if not _acquire_control(guard):
            return False
        if not background_status(data_dir):
            return True
        token = _read_token(data_dir / _STATE)
        if token is None:
            _LOG.warning("Reminder worker is starting; retry the stop request shortly.")
            return False
        _write_token(data_dir / _STOP, token)
        return True
    except OSError as exc:
        _LOG.warning("Cannot request reminder shutdown (%s).", type(exc).__name__)
        return False
    finally:
        guard.release()


def _send_windows_notification(title: str, message: str) -> bool:
    """Call Unicode Shell_NotifyIcon directly, with no shell/script interpolation."""
    from ctypes import wintypes

    class NotifyIconData(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND),
            ("uID", wintypes.UINT), ("uFlags", wintypes.UINT),
            ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
            ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD),
            ("dwStateMask", wintypes.DWORD), ("szInfo", wintypes.WCHAR * 256),
            ("uTimeoutOrVersion", wintypes.UINT), ("szInfoTitle", wintypes.WCHAR * 64),
            ("dwInfoFlags", wintypes.DWORD), ("guidItem", ctypes.c_byte * 16),
            ("hBalloonIcon", wintypes.HICON),
        ]

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.DestroyWindow.restype = wintypes.BOOL
    user32.LoadIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
    user32.LoadIconW.restype = wintypes.HICON
    user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
    user32.PeekMessageW.restype = wintypes.BOOL
    user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.restype = ctypes.c_ssize_t
    shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NotifyIconData)]
    shell32.Shell_NotifyIconW.restype = wintypes.BOOL
    hwnd = user32.CreateWindowExW(0, "STATIC", "ZFZS reminders", 0, 0, 0, 0, 0, None, None, None, None)
    if not hwnd:
        return False
    data = NotifyIconData()
    data.cbSize, data.hWnd, data.uID = ctypes.sizeof(data), hwnd, 1
    data.uFlags, data.uCallbackMessage = 1 | 2 | 4, 0x8001  # MESSAGE | ICON | TIP
    data.hIcon = user32.LoadIconW(None, ctypes.cast(ctypes.c_void_p(32516), wintypes.LPCWSTR))
    data.szTip = "ZFZS"
    added = False
    try:
        added = bool(shell32.Shell_NotifyIconW(0, ctypes.byref(data)))  # NIM_ADD
        if not added:
            return False
        data.uTimeoutOrVersion = 4
        if not shell32.Shell_NotifyIconW(4, ctypes.byref(data)):  # NIM_SETVERSION
            return False
        data.uFlags, data.uTimeoutOrVersion, data.dwInfoFlags = 0x10, 10000, 1 | 0x80
        # Win32 limits count UTF-16 code units, not Python Unicode code points.
        data.szInfoTitle = title.encode("utf-16-le", errors="replace")[:126].decode("utf-16-le", errors="ignore")
        data.szInfo = message.encode("utf-16-le", errors="replace")[:510].decode("utf-16-le", errors="ignore")
        if not shell32.Shell_NotifyIconW(1, ctypes.byref(data)):  # NIM_MODIFY + NIF_INFO
            return False
        # Keep the transient icon/window alive while Windows presents it.
        end = time.monotonic() + 10.0
        event = wintypes.MSG()
        while time.monotonic() < end:
            while user32.PeekMessageW(ctypes.byref(event), None, 0, 0, 1):
                user32.TranslateMessage(ctypes.byref(event))
                user32.DispatchMessageW(ctypes.byref(event))
            time.sleep(0.05)
        return True
    finally:
        if added:
            shell32.Shell_NotifyIconW(2, ctypes.byref(data))  # NIM_DELETE
        user32.DestroyWindow(hwnd)


def send_system_notification(title: str, message: str) -> bool:
    """True means the platform API accepted the request, not that it was read.

    Focus/quiet mode and user notification preferences can suppress visibility.
    Only payload-free error categories are logged; errors never become success.
    """
    if not isinstance(title, str) or not isinstance(message, str) or "\0" in title + message:
        _LOG.warning("Notification requires text without NUL characters.")
        return False
    title, message = title[:512], message[:2048]
    try:
        if sys.platform == "win32":
            success = _send_windows_notification(title, message)
            if not success:
                _LOG.warning("Windows notification API rejected the request; check the interactive desktop session.")
            return success
        if sys.platform == "darwin":
            executable = shutil.which("osascript")
            if not executable:
                _LOG.warning("macOS notifications unavailable: osascript was not found.")
                return False
            env = dict(os.environ, ZFZS_NOTIFICATION_TITLE=title, ZFZS_NOTIFICATION_MESSAGE=message)
            command = [executable, "-e", _MAC_SCRIPT]
        elif sys.platform.startswith("linux"):
            executable = shutil.which("notify-send")
            if not executable:
                _LOG.warning("Linux notifications unsupported: install/provide notify-send and a desktop notification session.")
                return False
            # Disable body markup and terminate option parsing before user text.
            import html

            command = [executable, "--app-name=ZFZS", "--", title, html.escape(message)]
            env = None
        else:
            _LOG.warning("System notifications are unsupported on this platform.")
            return False
        result = subprocess.run(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, env=env, timeout=15, check=False,
        )
        if result.returncode != 0:
            _LOG.warning("%s notification command failed (exit %s); check notification access and the desktop session.", sys.platform, result.returncode)
            return False
        return True
    except Exception as exc:
        _LOG.warning("System notification failed (%s); check platform notification availability.", type(exc).__name__)
        return False


def _open_database(data_dir: Path):
    from sqlalchemy import create_engine

    target = data_dir / "zfzs.db"
    if not target.is_file():
        raise FileNotFoundError("Initialize the desktop database before running reminders.")
    # mode=rw refuses to create a DB, even if it disappears after is_file().
    # The URI escapes spaces, '?' and '#' independently of SQLAlchemy URLs.
    return create_engine(
        "sqlite://", creator=lambda: sqlite3.connect(
            target.as_uri() + "?mode=rw", uri=True, timeout=5,
        ),
    )


def run_once(
    data_dir: Path, *, now: datetime | None = None,
    notifier: Callable[[str, str], bool] | None = None,
    stop_requested: Callable[[], bool] | None = None,
) -> int:
    """Dispatch one poll against the explicit DB; return persisted successes.

    A separate dispatch lock serializes concurrent manual polls and workers.
    notifier/now/stop_requested allow tests without real OS notifications.
    """
    from sqlalchemy.orm import Session
    from backend.app.service.reminder_service import _is_due, list_today_due_anime, mark_reminded

    data_dir = Path(data_dir).expanduser().resolve()
    engine = _open_database(data_dir)
    lock = _FileLock(data_dir / _DISPATCH_LOCK)
    sent = 0
    try:
        if not lock.acquire():
            return 0
        now = now or datetime.now()
        notify = notifier if notifier is not None else send_system_notification
        with Session(engine) as db:
            for anime in list_today_due_anime(db, now):
                if stop_requested is not None and stop_requested():
                    break
                # Reimport/status edits may have happened since the list query.
                db.refresh(anime)
                if not _is_due(anime, now):
                    continue
                try:
                    accepted = notify("ZFZS 追番提醒", f"{anime.title_cn or anime.title} · 放送时间 {anime.broadcast_time}")
                except Exception as exc:
                    _LOG.warning("Reminder notifier failed (%s); it will be retried.", type(exc).__name__)
                    accepted = False
                if accepted:
                    mark_reminded(db, anime, now)
                    sent += 1
                else:
                    _LOG.warning("Reminder was not submitted; last_reminded_at was left unchanged.")
        return sent
    finally:
        lock.release()
        engine.dispose()


def run_worker(
    data_dir: Path, poll_seconds: int = 30, *,
    notifier: Callable[[str, str], bool] | None = None,
    clock: Callable[[], datetime] | None = None,
    wait: Callable[[float], None] | None = None,
) -> None:
    """Run until cooperatively stopped, with injectable notification/time/wait.

    The packaged main entry point must dispatch --reminder-worker here before
    constructing Tk or performing normal desktop initialization.
    """
    if not isinstance(poll_seconds, int) or isinstance(poll_seconds, bool) or poll_seconds < 1:
        raise ValueError("poll_seconds must be a positive integer")
    data_dir = Path(data_dir).expanduser().resolve()
    if not data_dir.is_dir():
        raise FileNotFoundError("Reminder data directory does not exist.")
    handler = RotatingFileHandler(data_dir / "reminder-worker.log", maxBytes=131072, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    _LOG.addHandler(handler)
    lock = _FileLock(data_dir / _WORKER_LOCK)
    token = os.environ.get(_TOKEN_ENV, "")
    launched = len(token) == 32 and all(char in "0123456789abcdef" for char in token)
    if not launched:
        token = uuid.uuid4().hex
    acquired = False
    # A launch generation is revocable even before imports/lock acquisition.
    # One stop file alone is insufficient: a later stop could overwrite an old
    # timeout cancellation while that old child is still slowly starting.
    should_stop = lambda: (
        _read_token(data_dir / _STOP) == token
        or (launched and _read_token(data_dir / _LAUNCH) != token)
    )
    now = clock if clock is not None else datetime.now
    pause = wait if wait is not None else time.sleep
    try:
        acquired = lock.acquire()
        if not acquired:
            return
        if should_stop():
            return
        # Verify connectivity/schema before reporting readiness. Never call
        # shared migrations/create_all, which are bound to the UI/global engine.
        engine = _open_database(data_dir)
        try:
            from sqlalchemy import select
            from backend.app.model.anime import Anime

            with engine.connect() as db:
                db.execute(select(Anime).limit(0))
        finally:
            engine.dispose()
        if should_stop():
            return
        _write_token(data_dir / _STATE, token)
        while not should_stop():
            try:
                run_once(data_dir, now=now(), notifier=notifier, stop_requested=should_stop)
            except Exception as exc:
                _LOG.warning("Reminder poll failed (%s); check the database/schema and retry interval.", type(exc).__name__)
            remaining = float(poll_seconds)
            while remaining > 0 and not should_stop():
                interval = min(remaining, 0.25)
                pause(interval)
                remaining -= interval
    except Exception as exc:
        _LOG.warning("Reminder worker failed (%s); no OS configuration was changed.", type(exc).__name__)
    finally:
        try:
            if acquired:
                _remove_own_token(data_dir / _STATE, token)
                _remove_own_token(data_dir / _STOP, token)
                _remove_own_token(data_dir / _LAUNCH, token)
        finally:
            lock.release()
            _LOG.removeHandler(handler)
            handler.close()
