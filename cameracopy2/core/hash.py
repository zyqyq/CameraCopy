from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from threading import Event

from cameracopy2.core import xxhash64
from cameracopy2.models import HashMethod, HashResult


HashProgressCallback = Callable[[int, int], None]

HASH_METHODS: tuple[HashMethod, ...] = ("sha256", "xxhash64")

HASH_METHOD_LABELS: dict[HashMethod, str] = {
    "sha256": "SHA-256",
    "xxhash64": "xxHash64",
}

DEFAULT_HASH_METHOD: HashMethod = "sha256"

_HASH_FAILURE_LABELS: dict[str, str] = {"sha256": "SHA256", "xxhash64": "xxHash64"}


def hash_method_label(method: str) -> str:
    """Human-readable name for a configured hash method."""
    return HASH_METHOD_LABELS.get(method, str(method).upper())


def hash_failure_label(method: str) -> str:
    """Label used for verification failures and log lines."""
    return _HASH_FAILURE_LABELS.get(str(method).lower(), str(method).upper())


def hash_method_available(method: str) -> bool:
    """True when the method can run at full speed on this machine."""
    if method == "xxhash64":
        return xxhash64.native_available()
    return True


def new_digest(method: str = DEFAULT_HASH_METHOD):
    """Return a fresh incremental digest object for ``method``."""
    if method == "xxhash64":
        return xxhash64.new()
    if method == "sha256":
        return hashlib.sha256()
    raise ValueError(f"Unsupported hash method: {method}")


def hash_file(
    path: Path,
    method: str = DEFAULT_HASH_METHOD,
    block_size: int = 1024 * 1024,
    cancel_event: Event | None = None,
    progress: HashProgressCallback | None = None,
) -> str:
    digest = new_digest(method)
    total_bytes = Path(path).stat().st_size
    bytes_done = 0
    if progress:
        progress(0, total_bytes)
    with Path(path).open("rb") as handle:
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise InterruptedError("cancelled")
            chunk = handle.read(block_size)
            if not chunk:
                break
            digest.update(chunk)
            bytes_done += len(chunk)
            if progress:
                progress(bytes_done, total_bytes)
    return digest.hexdigest()


def compare_files_cancellable(
    source: Path,
    destination: Path,
    cancel_event: Event | None,
    method: str = DEFAULT_HASH_METHOD,
    source_progress: HashProgressCallback | None = None,
) -> HashResult:
    try:
        source_hash = hash_file(
            source,
            method=method,
            cancel_event=cancel_event,
            progress=source_progress,
        )
        destination_hash = hash_file(destination, method=method, cancel_event=cancel_event)
        return HashResult(source_hash, destination_hash, source_hash == destination_hash)
    except InterruptedError:
        return HashResult(None, None, False, "cancelled")
    except Exception as exc:  # noqa: BLE001 - callers need structured failure, not traceback.
        return HashResult(None, None, False, str(exc))


def sha256_file(
    path: Path,
    block_size: int = 1024 * 1024,
    cancel_event: Event | None = None,
    progress: HashProgressCallback | None = None,
) -> str:
    return hash_file(
        path,
        method="sha256",
        block_size=block_size,
        cancel_event=cancel_event,
        progress=progress,
    )


def compare_sha256_cancellable(
    source: Path,
    destination: Path,
    cancel_event: Event | None,
    source_progress: HashProgressCallback | None = None,
) -> HashResult:
    return compare_files_cancellable(
        source,
        destination,
        cancel_event,
        method="sha256",
        source_progress=source_progress,
    )
