"""Versioned, settings-free library portability with fail-closed imports."""

from __future__ import annotations

import ipaddress
import json
import math
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, SessionTransactionOrigin, attributes

from backend.app.model.anime import Anime


FORMAT = "zfzs-library"
VERSION = 1
MAX_IMPORT_BYTES = 20 * 1024 * 1024
MAX_IMPORT_ITEMS = 10_000
MAX_EPISODES = 1_000_000

# Explicit allowlist: neither ORM row IDs nor settings can enter an export.
EXPORT_FIELDS = (
    "title", "title_cn", "cover_url", "summary", "status",
    "broadcast_day", "broadcast_time", "reminder_enabled", "reminder_minutes",
    "watched_episodes", "total_episodes", "play_url", "source", "source_id",
    "source_url", "source_status", "year", "score", "user_rating", "tags",
    "last_reminded_at", "completed_at", "created_at", "updated_at",
)
_DATE_FIELDS = ("last_reminded_at", "completed_at", "created_at", "updated_at")
_URL_FIELDS = ("cover_url", "play_url", "source_url")
_TEXT_LIMITS = {
    "title": 255, "title_cn": 255, "summary": 100_000, "source": 64,
    "source_id": 128, "source_status": 64, "tags": 10_000,
    "cover_url": 4096, "play_url": 4096, "source_url": 4096,
}
_ISO_DATETIME = re.compile(
    r"\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d"
    r"(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)?"
)


class TransferError(ValueError):
    """Invalid/ambiguous data or an unsafe import/export request."""


@dataclass(frozen=True)
class ImportSummary:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    backup_path: Path | None = None


def _clean_session(db: Session) -> None:
    if not db.is_active or db.new or db.dirty or db.deleted:
        raise TransferError("Use a clean Session without pending changes for data transfer.")


def _text(value: object, field: str, limit: int, *, required: bool = False) -> None:
    if value is None and not required:
        return
    if not isinstance(value, str) or len(value) > limit:
        raise TransferError(f"Invalid string for {field} (maximum {limit} characters).")
    if required and not value.strip():
        raise TransferError(f"{field} must not be blank.")
    allowed_controls = "\r\n\t" if field in {"summary", "tags"} else ""
    if any((ord(c) < 32 and c not in allowed_controls)
           or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in value):
        raise TransferError(f"Invalid control character for {field}.")


def _integer(value: object, field: str, low: int, high: int, *, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    if type(value) is not int or not low <= value <= high:
        raise TransferError(f"{field} must be an integer between {low} and {high}.")


def _datetime(value: object, field: str, *, nullable: bool = False) -> datetime | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not _ISO_DATETIME.fullmatch(value):
        raise TransferError(f"{field} must be an ISO 8601 datetime with seconds.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        # The current ORM uses timezone-naive DateTime. Preserve naive values;
        # normalize explicit offsets to UTC rather than silently dropping them.
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except (ValueError, OverflowError) as exc:
        raise TransferError(f"Invalid calendar datetime for {field}.") from exc


def _canonical_url(value: str) -> str:
    if any(c.isspace() for c in value) or "\\" in value:
        raise TransferError("URLs must not contain whitespace or backslashes.")
    if re.search(r"%(?![0-9A-Fa-f]{2})|%(?:0[0-9A-Fa-f]|1[0-9A-Fa-f]|7[fF])", value):
        raise TransferError("URLs must not contain invalid escapes or escaped controls.")
    try:
        parts = urlsplit(value)
        if (parts.scheme.lower() not in {"http", "https"} or not parts.hostname
                or parts.username is not None or parts.password is not None
                or parts.netloc.endswith(":")):
            raise ValueError("Only absolute HTTP(S) URLs without credentials are supported.")
        if parts.netloc.startswith("[") and not re.fullmatch(r"\[[^\]]+\](?::[0-9]+)?", parts.netloc):
            raise ValueError("Invalid bracketed authority.")
        host = parts.hostname
        if "%" in host:
            raise ValueError("Invalid host.")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            host = host.encode("idna").decode("ascii").lower()
            labels = host.rstrip(".").split(".")
            if len(host) > 253 or any(
                not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                for label in labels
            ):
                raise ValueError("Invalid host.")
        else:
            host = f"[{address.compressed}]" if address.version == 6 else str(address)
        port = parts.port  # Also validates the port range and syntax.
        if port is not None and port != {"http": 80, "https": 443}[parts.scheme.lower()]:
            host = f"{host}:{port}"
        return urlunsplit((parts.scheme.lower(), host, parts.path or "/", parts.query, ""))
    except (ValueError, UnicodeError) as exc:
        raise TransferError("Invalid HTTP(S) URL.") from exc


def _record(data: object, now: datetime) -> dict:
    if not isinstance(data, dict) or set(data) - set(EXPORT_FIELDS):
        raise TransferError("Each item must be an object containing only supported anime fields.")
    values = dict.fromkeys(EXPORT_FIELDS)
    values.update(status="watching", broadcast_time="20:00", reminder_enabled=True,
                  reminder_minutes=15, watched_episodes=0,
                  created_at=now.isoformat(), updated_at=now.isoformat())
    values.update(data)
    for field, limit in _TEXT_LIMITS.items():
        _text(values[field], field, limit, required=field == "title")
    for field in ("source", "source_id"):
        if values[field] is not None and not values[field].strip():
            raise TransferError(f"{field} must be nonblank or null.")
    if values["source_id"] is not None and values["source"] is None:
        raise TransferError("source_id requires a source.")
    if not isinstance(values["status"], str) or values["status"] not in {"watching", "paused", "finished"}:
        raise TransferError("Invalid watching status.")
    if not isinstance(values["broadcast_time"], str) or not re.fullmatch(
        r"(?:[01]\d|2[0-3]):[0-5]\d", values["broadcast_time"]
    ):
        raise TransferError("broadcast_time must use HH:MM (24-hour time).")
    if type(values["reminder_enabled"]) is not bool:
        raise TransferError("reminder_enabled must be a boolean.")
    _integer(values["broadcast_day"], "broadcast_day", 0, 6, nullable=True)
    _integer(values["reminder_minutes"], "reminder_minutes", 0, 1440)
    _integer(values["watched_episodes"], "watched_episodes", 0, MAX_EPISODES)
    _integer(values["total_episodes"], "total_episodes", 0, MAX_EPISODES, nullable=True)
    _integer(values["year"], "year", 1900, 2200, nullable=True)
    if values["total_episodes"] is not None and values["watched_episodes"] > values["total_episodes"]:
        raise TransferError("watched_episodes cannot exceed total_episodes; use null for unknown totals.")
    for field in ("score", "user_rating"):
        value = values[field]
        if value is not None and (type(value) not in (int, float)
                                  or not 0 <= value <= 10 or not math.isfinite(value)):
            raise TransferError(f"{field} must be a finite number between 0 and 10, or null.")
    for field in _URL_FIELDS:
        if values[field] is not None:
            _canonical_url(values[field])
    for field in _DATE_FIELDS:
        values[field] = _datetime(values[field], field, nullable=field not in {"created_at", "updated_at"})
    return values


def _identity(values: dict) -> tuple[str, ...]:
    if values["source"] is not None and values["source_id"] is not None:
        return ("source", values["source"].strip().casefold(), values["source_id"].strip())
    title = " ".join(unicodedata.normalize("NFKC", values["title"]).split()).casefold()
    link = values["source_url"] or values["play_url"]
    return ("manual", title, _canonical_url(link) if link else "")


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise TransferError("Duplicate JSON object key.")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise TransferError("Non-finite JSON numbers are not supported.")


def _read_import(path: Path) -> list[dict]:
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_IMPORT_BYTES + 1)
    if len(raw) > MAX_IMPORT_BYTES:
        raise TransferError(f"Import exceeds the {MAX_IMPORT_BYTES}-byte limit.")
    try:
        document = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_object,
                              parse_constant=_invalid_constant)
    except TransferError:
        raise
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise TransferError("Invalid UTF-8 JSON export.") from exc
    if not isinstance(document, dict) or set(document) != {"format", "version", "exported_at", "items"}:
        raise TransferError("Invalid export envelope.")
    if document["format"] != FORMAT or type(document["version"]) is not int or document["version"] != VERSION:
        raise TransferError("Unsupported export format or version.")
    exported_at = _datetime(document["exported_at"], "exported_at")
    if not isinstance(document["items"], list) or len(document["items"]) > MAX_IMPORT_ITEMS:
        raise TransferError(f"items must be an array with at most {MAX_IMPORT_ITEMS} entries.")
    # Stable defaults keep even hand-authored minimal files idempotent.
    records = [_record(item, exported_at) for item in document["items"]]
    identities = [_identity(item) for item in records]
    if len(set(identities)) != len(identities):
        raise TransferError("Import contains duplicate item identities; resolve them before importing.")
    return records


def _database_path(db: Session) -> Path | None:
    if db.get_bind(mapper=Anime).dialect.name != "sqlite":
        return None
    # The driver reports the actual file, including URI handling and spaces.
    rows = db.connection(bind_arguments={"mapper": Anime}).exec_driver_sql("PRAGMA database_list")
    filename = next((row[2] for row in rows if row[1] == "main"), "")
    return Path(filename) if filename else None


def _dump(anime: Anime) -> dict:
    values = {field: getattr(anime, field) for field in EXPORT_FIELDS}
    for field in _DATE_FIELDS:
        value = values[field]
        if value is not None:
            if not isinstance(value, datetime):
                raise TransferError(f"Invalid stored datetime for {field}.")
            values[field] = value.isoformat()
    _record(values, datetime.now())  # Never emit an unreadable export silently.
    return values


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent,
                                         prefix=f".{path.name}.", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def save_export(db: Session, path: Path) -> int:
    """Atomically export a clean Session's library; never commit or read settings."""
    _clean_session(db)
    path = Path(path)
    with db.no_autoflush:
        database_path = _database_path(db)
        if database_path is not None:
            target = os.path.normcase(str(path.resolve()))
            protected = {os.path.normcase(str(database_path.resolve()) + suffix)
                         for suffix in ("", "-wal", "-shm", "-journal")}
            if target in protected or (path.exists() and path.samefile(database_path)):
                raise TransferError("An export must not overwrite the database or its journal files.")
        rows = list(db.scalars(select(Anime).order_by(Anime.id).limit(MAX_IMPORT_ITEMS + 1)
                               .execution_options(populate_existing=True)))
        if len(rows) > MAX_IMPORT_ITEMS:
            raise TransferError(f"Export exceeds the {MAX_IMPORT_ITEMS}-item limit.")
        items = [_dump(anime) for anime in rows]
    document = {"format": FORMAT, "version": VERSION,
                "exported_at": datetime.now(timezone.utc).isoformat(), "items": items}
    content = (json.dumps(document, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf-8")
    if len(content) > MAX_IMPORT_BYTES:
        raise TransferError(f"Export exceeds the {MAX_IMPORT_BYTES}-byte limit.")
    _atomic_write(path, content)
    return len(items)


def create_backup(db: Session, backup_dir: Path) -> Path:
    """Create a uniquely named atomic JSON snapshot, without changing the DB."""
    name = f"zfzs-backup-{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}-{uuid4().hex}.json"
    path = Path(backup_dir) / name
    save_export(db, path)
    return path


def load_import(db: Session, path: Path, conflict: str = "keep_local",
                backup_dir: Path | None = None) -> ImportSummary:
    """Validate all records, back up, then merge in one owned transaction.

    A clean read-autobegun Session is accepted; explicit caller transactions are
    rejected so this function cannot unexpectedly commit unrelated work.
    Errors propagate, with every attempted DB change rolled back.
    """
    if not isinstance(conflict, str) or conflict not in {"keep_local", "replace_existing"}:
        raise TransferError("conflict must be 'keep_local' or 'replace_existing'.")
    records = _read_import(path)  # No DB access or autoflush before full validation.
    _clean_session(db)
    transaction = db.get_transaction()
    if db.in_nested_transaction() or (transaction is not None and transaction.origin != SessionTransactionOrigin.AUTOBEGIN):
        raise TransferError("Import requires its own transaction, not an explicit caller transaction.")
    # A flushed caller write is no longer present in Session.new/dirty/deleted.
    # In sqlite3 legacy mode, any physical transaction here is caller-owned;
    # in modern mode only a newly opened Session is unambiguously ours.
    with db.no_autoflush:
        connection = db.connection(bind_arguments={"mapper": Anime})
    driver = None
    if connection.dialect.name == "sqlite":
        driver = connection.connection.driver_connection
        modern_mode = getattr(driver, "autocommit", None) is False
        if driver.in_transaction and (not modern_mode or transaction is not None):
            raise TransferError("Commit or roll back the pre-existing SQLite transaction before importing.")
    try:
        with db.no_autoflush:
            if driver is not None:
                # Python sqlite3 legacy transaction mode does not BEGIN on SELECT.
                # Lock before reading the snapshot, excluding concurrent writers.
                if not driver.in_transaction:
                    connection.exec_driver_sql("BEGIN IMMEDIATE")
            existing = list(db.scalars(select(Anime).order_by(Anime.id)
                                       .execution_options(populate_existing=True)))
            index = {}
            for anime in existing:
                key = _identity(_dump(anime))
                index.setdefault(key, []).append(anime)
            plan = []
            for record in records:
                matches = index.get(_identity(record), [])
                if len(matches) > 1:
                    raise TransferError("Multiple local items match an imported identity; resolve them first.")
                plan.append((matches[0] if matches else None, record))
            backup_path = None
            if existing:
                if backup_dir is None:
                    database_path = _database_path(db)
                    if database_path is None:
                        raise TransferError("An explicit backup_dir is required for an in-memory/non-file database.")
                    backup_dir = database_path.parent / "backups"
                backup_path = create_backup(db, Path(backup_dir))
            created = updated = skipped = 0
            for anime, record in plan:
                if anime is None:
                    db.add(Anime(**record))
                    created += 1
                elif conflict == "keep_local":
                    skipped += 1
                elif all(getattr(anime, field) == value for field, value in record.items()):
                    skipped += 1
                else:
                    for field, value in record.items():
                        setattr(anime, field, value)
                    # A same-valued timestamp is otherwise omitted from UPDATE,
                    # allowing the ORM's onupdate clock to replace imported time.
                    attributes.flag_modified(anime, "updated_at")
                    updated += 1
        db.commit()
        return ImportSummary(created, updated, skipped, backup_path)
    except BaseException:
        db.rollback()
        raise
