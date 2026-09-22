"""Resumable copies and interrupted-job recovery.

Two related safety features live here:

**Partial-file resume (断点续传)**
    An interrupted file copy keeps the data it already wrote in the destination
    folder as ``.<name>.<key>.cameracopy.part`` together with a small JSON
    sidecar describing the source file it belongs to.  A later run continues at
    the existing byte offset instead of transferring the file from the start.

**Interrupted-job recovery (任务恢复)**
    While a copy runs, a session journal records the job description and every
    source file that has already been preserved.  After a crash, an aborted run,
    or a power failure the journal can rebuild the same job and skip the files
    that are already complete.

Design rules
------------
* Nothing here may raise because of a missing, partial, or corrupt journal: a
  broken journal is reported as "no session" and a broken partial as "no
  partial", so a copy always keeps working.
* A partial file is only trusted when its sidecar matches the source file's
  size and modification time.  Whenever it does not, the partial is discarded
  and the transfer restarts.
* The byte offset always comes from the size of the partial file on disk, never
  from the journal, so a crash can never make the copy skip unwritten data.
* Writing the journal never touches the destination: the journal lives in the
  per-user state directory and every update is written atomically.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from cameracopy2.config import CameraCopyConfig, config_from_dict
from cameracopy2.models import (
    CONFIG_VERSION,
    CompletedFileEntry,
    CopyJob,
    VolumeInfo,
)
from cameracopy2.operation_log import operation_log_directory

logger = logging.getLogger(__name__)

PARTIAL_SUFFIX = ".cameracopy.part"
PARTIAL_META_SUFFIX = ".cameracopy.part.json"
PARTIAL_KEY_LENGTH = 12

SESSION_FILE_NAME = "session.json"
SESSION_SCHEMA = 1
SESSION_DIR_NAME = "sessions"
MAX_SESSION_AGE_DAYS = 30

#: Journal flushes are batched so a large card does not rewrite the session
#: file once per copied file.
JOURNAL_FLUSH_RECORDS = 32
JOURNAL_FLUSH_SECONDS = 3.0

SessionState = Literal["running", "interrupted", "finished"]


# ---------------------------------------------------------------------------
# Partial files
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PartialFile:
    """Deterministic partial-file location for one destination path."""

    data: Path
    meta: Path


@dataclass(slots=True)
class PartialCopyState:
    """Sidecar contents describing the source file a partial belongs to."""

    source_size: int
    source_mtime_ns: int
    hash_method: str = "sha256"
    offset: int = 0
    version: int = 1
    updated_at: str = ""

    def matches_source(self, size: int, mtime_ns: int) -> bool:
        return self.source_size == size and self.source_mtime_ns == mtime_ns

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "source_size": self.source_size,
            "source_mtime_ns": self.source_mtime_ns,
            "hash_method": self.hash_method,
            "offset": self.offset,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Any) -> PartialCopyState | None:
        if not isinstance(data, dict):
            return None
        size = data.get("source_size")
        mtime = data.get("source_mtime_ns")
        if not isinstance(size, int) or isinstance(size, bool):
            return None
        if not isinstance(mtime, int) or isinstance(mtime, bool):
            return None
        offset = data.get("offset", 0)
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            offset = 0
        hash_method = data.get("hash_method", "sha256")
        if not isinstance(hash_method, str) or not hash_method:
            hash_method = "sha256"
        updated_at = data.get("updated_at", "")
        if not isinstance(updated_at, str):
            updated_at = ""
        return cls(
            source_size=max(0, size),
            source_mtime_ns=mtime,
            hash_method=hash_method,
            offset=offset,
            updated_at=updated_at,
        )


@dataclass(frozen=True, slots=True)
class PartialPlan:
    """How the next attempt at one destination should start."""

    data: Path
    meta: Path
    offset: int = 0

    @property
    def resumed(self) -> bool:
        return self.offset > 0


def partial_key(destination: Path) -> str:
    """Stable short key so two same-named destinations never share a partial."""
    try:
        marker = os.path.normcase(os.path.abspath(str(destination)))
    except OSError:  # pragma: no cover - path conversion is effectively infallible
        marker = str(destination)
    digest = hashlib.blake2s(marker.encode("utf-8", "surrogatepass"), digest_size=8)
    return digest.hexdigest()[:PARTIAL_KEY_LENGTH]


def partial_paths(destination: Path) -> PartialFile:
    """Return the deterministic partial-file pair for ``destination``."""
    prefix = f".{Path(destination).name}.{partial_key(Path(destination))}"
    return PartialFile(
        data=Path(destination).with_name(prefix + PARTIAL_SUFFIX),
        meta=Path(destination).with_name(prefix + PARTIAL_META_SUFFIX),
    )


def read_partial_state(destination: Path) -> PartialCopyState | None:
    """Read the sidecar for ``destination``; never raises."""
    meta = partial_paths(destination).meta
    try:
        text = meta.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None
    try:
        return PartialCopyState.from_dict(json.loads(text))
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def write_partial_state(destination: Path, state: PartialCopyState) -> None:
    """Atomically write the sidecar for ``destination``."""
    meta = partial_paths(destination).meta
    state.updated_at = datetime.now().isoformat(timespec="seconds")
    meta.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(state.to_dict(), indent=2, ensure_ascii=False)
    fd, temp_name = tempfile.mkstemp(prefix=f".{meta.name}.", suffix=".tmp", dir=meta.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, meta)
    except BaseException:
        _unlink(temp_path)
        raise


def partial_size(destination: Path) -> int:
    """Bytes already written for ``destination``; 0 when there is no partial."""
    try:
        return partial_paths(destination).data.stat().st_size
    except OSError:
        return 0


def discard_partial(destination: Path) -> None:
    """Remove both halves of the partial pair for ``destination``."""
    paths = partial_paths(destination)
    _unlink(paths.data)
    _unlink(paths.meta)


def prepare_partial(
    destination: Path,
    *,
    source_size: int,
    source_mtime_ns: int,
    hash_method: str,
) -> PartialPlan:
    """Claim the partial pair for ``destination`` and report where to continue.

    The returned offset is the size of the partial file that survives the
    validation below, so it can never point past data that is really on disk.
    """
    paths = partial_paths(destination)
    existing = read_partial_state(destination)
    offset = 0

    if existing is not None and existing.matches_source(source_size, source_mtime_ns):
        on_disk = partial_size(destination)
        if 0 < on_disk < source_size:
            offset = on_disk
        else:
            _unlink(paths.data)
    else:
        # No sidecar, unreadable sidecar, or a different source file: the
        # partial belongs to something else and must not be trusted.
        _unlink(paths.data)

    write_partial_state(
        destination,
        PartialCopyState(
            source_size=source_size,
            source_mtime_ns=source_mtime_ns,
            hash_method=hash_method,
            offset=offset,
        ),
    )
    return PartialPlan(data=paths.data, meta=paths.meta, offset=offset)


def finish_partial(destination: Path, *, offset: int, keep: bool) -> None:
    """Keep an interrupted partial (updating its sidecar) or remove it."""
    if keep:
        state = read_partial_state(destination)
        if state is None:
            return
        state.offset = max(0, offset)
        try:
            write_partial_state(destination, state)
        except OSError as exc:  # pragma: no cover - best effort only
            logger.warning("Could not update partial-copy information: %s", exc)
        return
    discard_partial(destination)


def iter_partial_files(root: Path) -> list[Path]:
    """Non-recursive list of CameraCopy partial files below ``root``."""
    try:
        entries = list(Path(root).iterdir())
    except OSError:
        return []
    return sorted(
        path
        for path in entries
        if path.is_file()
        and (path.name.endswith(PARTIAL_SUFFIX) or path.name.endswith(PARTIAL_META_SUFFIX))
    )


def _partial_siblings(path: Path) -> tuple[Path, Path]:
    """Return the data/meta pair that a recorded partial path belongs to."""
    if path.name.endswith(PARTIAL_META_SUFFIX):
        return path, Path(str(path)[: -len(".json")])
    if path.name.endswith(PARTIAL_SUFFIX):
        return path, Path(str(path) + ".json")
    return path, path


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError as exc:
        logger.warning("Could not remove CameraCopy partial file %s: %s", path, exc)


# ---------------------------------------------------------------------------
# Volume identity
# ---------------------------------------------------------------------------


def volume_key(volume: VolumeInfo) -> str:
    """Stable in-journal key for one source volume."""
    return "|".join(
        (
            volume.device_serial or "",
            volume.uuid or "",
            volume.device_path or "",
            str(volume.mount_path),
        )
    )


_VOLUME_FIELDS = (
    "id",
    "display_name",
    "mount_path",
    "device_path",
    "label",
    "model",
    "size_bytes",
    "filesystem",
    "removable",
    "uuid",
    "transport",
    "device_serial",
    "partition_uuid",
    "hardware_path",
    "platform",
)


def volume_identity(volume: VolumeInfo) -> dict[str, Any]:
    """Serialize the parts of a volume identity needed to find it again."""
    data: dict[str, Any] = {name: getattr(volume, name) for name in _VOLUME_FIELDS}
    data["mount_path"] = str(volume.mount_path)
    return data


def volume_from_identity(data: Any) -> VolumeInfo | None:
    """Rebuild a volume from a journal entry; ``None`` when it is unusable."""
    if not isinstance(data, dict):
        return None
    mount = data.get("mount_path")
    if not isinstance(mount, str) or not mount:
        return None

    def text(name: str) -> str | None:
        value = data.get(name)
        return value if isinstance(value, str) and value else None

    size = data.get("size_bytes")
    if not isinstance(size, int) or isinstance(size, bool):
        size = None
    removable = data.get("removable")
    if not isinstance(removable, bool):
        removable = None
    volume_id = data.get("id")
    return VolumeInfo(
        id=volume_id if isinstance(volume_id, str) and volume_id else mount,
        display_name=text("display_name") or Path(mount).name,
        mount_path=Path(mount),
        device_path=text("device_path"),
        label=text("label"),
        model=text("model"),
        size_bytes=size,
        filesystem=text("filesystem"),
        removable=removable,
        uuid=text("uuid"),
        transport=text("transport"),
        device_serial=text("device_serial"),
        partition_uuid=text("partition_uuid"),
        hardware_path=text("hardware_path"),
        platform=text("platform") or "unknown",
    )


def match_session_volumes(
    session: CopySession, volumes: list[VolumeInfo]
) -> tuple[VolumeInfo | None, VolumeInfo | None]:
    """Re-resolve the session's source volumes among the mounted volumes."""
    from cameracopy2.services.volume_service import VolumeService

    primary = volume_from_identity(session.primary)
    secondary = volume_from_identity(session.secondary) if session.secondary else None
    return (
        VolumeService.find_matching_copy_source(primary, volumes) if primary else None,
        VolumeService.find_matching_copy_source(secondary, volumes) if secondary else None,
    )


# ---------------------------------------------------------------------------
# Session journal
# ---------------------------------------------------------------------------


def session_directory(config_path: Path | None = None) -> Path:
    """Per-user directory holding interrupted-copy journals."""
    return operation_log_directory(config_path).parent / SESSION_DIR_NAME


@dataclass(slots=True)
class CopySession:
    """A copy job that can still be resumed."""

    session_id: str
    directory: Path
    created_at: str
    updated_at: str
    state: SessionState
    destination: str
    source_subfolder: str
    config: dict[str, Any]
    primary: dict[str, Any]
    secondary: dict[str, Any] | None = None
    clone_mode: bool = False
    autoremove: bool = False
    format_after_copy: str | None = None
    completed: dict[str, CompletedFileEntry] = field(default_factory=dict)
    partials: list[str] = field(default_factory=list)
    volume_keys: list[str] = field(default_factory=list)
    completed_bytes: int = 0
    failures: int = 0
    total_files: int = 0

    @property
    def path(self) -> Path:
        return self.directory / SESSION_FILE_NAME

    @property
    def completed_count(self) -> int:
        return len(self.completed)

    def restored_config(self) -> CameraCopyConfig | None:
        """Rebuild the configuration the interrupted run was using."""
        try:
            return config_from_dict(self.config)
        except (TypeError, ValueError):
            return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SESSION_SCHEMA,
            "session_id": self.session_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "state": self.state,
            "destination": self.destination,
            "source_subfolder": self.source_subfolder,
            "config": self.config,
            "primary": self.primary,
            "secondary": self.secondary,
            "clone_mode": self.clone_mode,
            "autoremove": self.autoremove,
            "format_after_copy": self.format_after_copy,
            "completed": {
                key: _entry_to_dict(entry) for key, entry in self.completed.items()
            },
            "partials": list(self.partials),
            "volume_keys": list(self.volume_keys),
            "completed_bytes": self.completed_bytes,
            "failures": self.failures,
            "total_files": self.total_files,
        }

    @classmethod
    def from_dict(cls, data: Any, directory: Path) -> CopySession | None:
        if not isinstance(data, dict) or data.get("schema") != SESSION_SCHEMA:
            return None
        session_id = data.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            return None
        config = data.get("config")
        primary = data.get("primary")
        if not isinstance(config, dict) or not isinstance(primary, dict):
            return None
        destination = data.get("destination")
        if not isinstance(destination, str) or not destination:
            return None
        secondary = data.get("secondary")
        if not isinstance(secondary, dict):
            secondary = None
        state = data.get("state")
        if state not in {"running", "interrupted", "finished"}:
            state = "interrupted"

        completed: dict[str, CompletedFileEntry] = {}
        raw_completed = data.get("completed")
        if isinstance(raw_completed, dict):
            for key, value in raw_completed.items():
                entry = _entry_from_dict(value)
                if entry is not None:
                    completed[str(key)] = entry

        return cls(
            session_id=session_id,
            directory=directory,
            created_at=_text(data.get("created_at")),
            updated_at=_text(data.get("updated_at")),
            state=state,
            destination=destination,
            source_subfolder=_text(data.get("source_subfolder")),
            config=config,
            primary=primary,
            secondary=secondary,
            clone_mode=bool(data.get("clone_mode")),
            autoremove=bool(data.get("autoremove")),
            format_after_copy=_optional_text(data.get("format_after_copy")),
            completed=completed,
            partials=[item for item in data.get("partials") or [] if isinstance(item, str)],
            volume_keys=[item for item in data.get("volume_keys") or [] if isinstance(item, str)],
            completed_bytes=_int_or_zero(data.get("completed_bytes")),
            failures=_int_or_zero(data.get("failures")),
            total_files=_int_or_zero(data.get("total_files")),
        )


class CopySessionStore:
    """Reads and writes interrupted-copy journals below one directory."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self._pending_records = 0
        self._last_flush: float | None = None

    # -- creation and lookup ------------------------------------------------
    def create(self, job: CopyJob) -> CopySession:
        """Start a journal for ``job``."""
        now = datetime.now().isoformat(timespec="seconds")
        session_id = self._new_session_id()
        session_directory_path = self.directory / session_id
        session_directory_path.mkdir(parents=True, exist_ok=True)
        session = CopySession(
            session_id=session_id,
            directory=session_directory_path,
            created_at=now,
            updated_at=now,
            state="running",
            destination=job.config.destination,
            source_subfolder=job.config.source,
            config=_config_snapshot(job),
            primary=volume_identity(job.primary),
            secondary=volume_identity(job.secondary) if job.secondary else None,
            clone_mode=job.clone_mode,
            autoremove=job.autoremove,
            format_after_copy=job.format_after_copy,
            volume_keys=[
                volume_key(volume) for volume in job.selected_volumes()
            ],
        )
        self.save(session)
        return session

    def open_sessions(self) -> list[CopySession]:
        """Every resumable session, most recently updated first."""
        sessions: list[CopySession] = []
        try:
            children = sorted(self.directory.iterdir())
        except (FileNotFoundError, NotADirectoryError, OSError):
            return []
        for child in children:
            session = self.load_path(child / SESSION_FILE_NAME, child)
            if session is not None and session.state != "finished":
                sessions.append(session)
        sessions.sort(key=lambda item: item.updated_at, reverse=True)
        return sessions

    def load(self, session_id: str) -> CopySession | None:
        directory = self.directory / session_id
        return self.load_path(directory / SESSION_FILE_NAME, directory)

    def load_path(self, path: Path, directory: Path) -> CopySession | None:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, ValueError):
            return None
        try:
            return CopySession.from_dict(json.loads(text), directory)
        except (json.JSONDecodeError, TypeError, ValueError):
            logger.warning("Ignoring unreadable copy session %s", path)
            return None

    # -- updates -----------------------------------------------------------
    def save(self, session: CopySession, *, force: bool = False) -> None:
        """Write the journal atomically, batching frequent updates."""
        if not force and not self._flush_due():
            return
        session.updated_at = datetime.now().isoformat(timespec="seconds")
        self._write(session)
        self._pending_records = 0
        self._last_flush = time.monotonic()

    def record(
        self,
        session: CopySession,
        *,
        key: str,
        relative_path: str,
        destination: Path | None,
        size_bytes: int,
        mode: str | None,
    ) -> None:
        """Remember one preserved source file."""
        session.completed[key] = CompletedFileEntry(
            relative_path=relative_path,
            destination=str(destination) if destination is not None else None,
            size_bytes=max(0, size_bytes),
            mode=mode,
        )
        session.completed_bytes += max(0, size_bytes)
        self._pending_records += 1
        self.save(session)

    def unrecord(self, session: CopySession, key: str) -> None:
        """Forget a file whose verification later failed."""
        entry = session.completed.pop(key, None)
        if entry is None:
            return
        session.completed_bytes = max(0, session.completed_bytes - entry.size_bytes)
        self.save(session, force=True)

    def add_partial(self, session: CopySession, path: Path) -> None:
        text = str(path)
        if text not in session.partials:
            session.partials.append(text)

    def remove_partial(self, session: CopySession, path: Path) -> None:
        text = str(path)
        if text in session.partials:
            session.partials.remove(text)

    def finish(self, session: CopySession, *, clean: bool, failures: int = 0) -> None:
        """Close the journal, deleting it when nothing is left to resume."""
        session.failures = max(0, failures)
        session.state = "finished" if clean else "interrupted"
        self.save(session, force=True)
        if clean:
            self.discard(session)

    def touch(self, session: CopySession, *, total_files: int) -> None:
        """Record the size of the job once the scan is known."""
        session.total_files = max(0, total_files)
        self.save(session, force=True)

    # -- removal -----------------------------------------------------------
    def discard(self, session: CopySession) -> None:
        """Delete the journal and the partial files it knows about."""
        protected = self._partials_of_other_sessions(session)
        for text in list(session.partials):
            for path in _partial_siblings(Path(text)):
                if path.name not in protected:
                    _unlink(path)
        session.partials.clear()
        destination = Path(session.destination).expanduser()
        for root in (destination, destination.parent):
            for path in iter_partial_files(root):
                if path.name not in protected:
                    _unlink(path)
        shutil.rmtree(session.directory, ignore_errors=True)

    def _partials_of_other_sessions(self, session: CopySession) -> set[str]:
        """Names of partial files that other open sessions still expect.

        Both halves of a partial pair are protected together: keeping the data
        without its sidecar would make the surviving session restart the file
        from the beginning, which is worse than leaving the pair alone.
        """
        names: set[str] = set()
        for other in self.open_sessions():
            if other.session_id == session.session_id:
                continue
            for item in other.partials:
                for path in _partial_siblings(Path(item)):
                    names.add(path.name)
        return names

    def prune(self, max_age_days: int = MAX_SESSION_AGE_DAYS) -> None:
        """Drop journals that are too old to be useful."""
        if max_age_days <= 0:
            return
        cutoff = time.time() - max_age_days * 86400
        try:
            children = list(self.directory.iterdir())
        except OSError:
            return
        for child in children:
            try:
                if child.stat().st_mtime >= cutoff:
                    continue
            except OSError:
                continue
            session = self.load_path(child / SESSION_FILE_NAME, child)
            if session is not None:
                self.discard(session)
            else:
                shutil.rmtree(child, ignore_errors=True)

    # -- internals ---------------------------------------------------------
    def _flush_due(self) -> bool:
        if self._pending_records >= JOURNAL_FLUSH_RECORDS:
            return True
        if self._last_flush is None:
            return True
        return time.monotonic() - self._last_flush >= JOURNAL_FLUSH_SECONDS

    def _write(self, session: CopySession) -> None:
        directory = session.directory
        try:
            directory.mkdir(parents=True, exist_ok=True)
            text = json.dumps(session.to_dict(), indent=2, ensure_ascii=False)
            fd, temp_name = tempfile.mkstemp(
                prefix=f".{SESSION_FILE_NAME}.", suffix=".tmp", dir=directory
            )
            temp_path = Path(temp_name)
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                    handle.write(text)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp_path, session.path)
            except BaseException:
                _unlink(temp_path)
                raise
        except OSError as exc:
            # A journal that cannot be written must never stop a copy.
            logger.warning("Could not write copy session %s: %s", session.session_id, exc)

    def _new_session_id(self) -> str:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        for attempt in range(1000):
            suffix = os.urandom(3).hex()
            candidate = f"{stamp}-{suffix}" if attempt else stamp
            if not (self.directory / candidate).exists():
                return candidate
        return f"{stamp}-{os.urandom(8).hex()}"  # pragma: no cover - pathological


def _config_snapshot(job: CopyJob) -> dict[str, Any]:
    snapshot = asdict(job.config)
    snapshot["version"] = CONFIG_VERSION
    return snapshot


def _entry_to_dict(entry: CompletedFileEntry) -> dict[str, Any]:
    return {
        "relative_path": entry.relative_path,
        "destination": entry.destination,
        "size_bytes": entry.size_bytes,
        "mode": entry.mode,
    }


def _entry_from_dict(data: Any) -> CompletedFileEntry | None:
    if isinstance(data, dict):
        destination = _optional_text(data.get("destination"))
        return CompletedFileEntry(
            relative_path=_text(data.get("relative_path")),
            destination=destination,
            size_bytes=_int_or_zero(data.get("size_bytes")),
            mode=_optional_text(data.get("mode")),
        )
    if isinstance(data, str):
        # Tolerate a future/older journal that stored only the source path.
        return CompletedFileEntry(relative_path=data)
    return None


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _optional_text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _int_or_zero(value: Any) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return 0
