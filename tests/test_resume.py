"""Tests for resumable partial-file copies and interrupted-job recovery."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from threading import Event

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cameracopy2.config import config_from_dict, load_config, save_config
from cameracopy2.core.copy_engine import CopyEngine
from cameracopy2.core.resume import (
    MAX_SESSION_AGE_DAYS,
    PARTIAL_META_SUFFIX,
    PARTIAL_SUFFIX,
    SESSION_DIR_NAME,
    SESSION_FILE_NAME,
    CopySessionStore,
    PartialCopyState,
    finish_partial,
    match_session_volumes,
    partial_paths,
    partial_size,
    prepare_partial,
    read_partial_state,
    session_directory,
    volume_from_identity,
    volume_identity,
    volume_key,
    write_partial_state,
)
from cameracopy2.models import (
    CameraCopyConfig,
    CompletedFileEntry,
    CopyCallbacks,
    CopyJob,
    ResumedCopyState,
    VolumeInfo,
)
from cameracopy2.operation_log import operation_log_directory


@pytest.fixture()
def english_ui():
    """Keep user-facing strings in English so assertions stay stable."""
    pytest.importorskip("PySide6")
    from cameracopy2 import i18n

    previous = i18n.get_language()
    i18n.set_language("en")
    try:
        yield
    finally:
        i18n.set_language(previous)


def make_volume(path: Path, **overrides: object) -> VolumeInfo:
    values: dict[str, object] = {
        "id": str(path),
        "display_name": "Test card",
        "mount_path": path,
        "platform": "test",
    }
    values.update(overrides)
    return VolumeInfo(**values)  # type: ignore[arg-type]


def make_config(destination: Path, **overrides: object) -> CameraCopyConfig:
    values: dict[str, object] = {
        "source": "",
        "destination": str(destination),
        "includedfiles": ["*.JPG"],
        "datetimestring": "",
    }
    values.update(overrides)
    return CameraCopyConfig(**values)  # type: ignore[arg-type]


def seed_partial(destination: Path, payload: bytes, source: Path) -> Path:
    """Write a partial file for ``destination`` that matches ``source``."""
    paths = partial_paths(destination)
    paths.data.write_bytes(payload)
    stat = source.stat()
    write_partial_state(
        destination,
        PartialCopyState(
            source_size=stat.st_size,
            source_mtime_ns=stat.st_mtime_ns,
            hash_method="sha256",
            offset=len(payload),
        ),
    )
    return paths.data


# ---------------------------------------------------------------------------
# Partial files
# ---------------------------------------------------------------------------


def test_partial_paths_are_hidden_and_destination_specific(tmp_path: Path) -> None:
    first = partial_paths(tmp_path / "IMG_1.JPG")
    second = partial_paths(tmp_path / "IMG_2.JPG")

    assert first.data.parent == tmp_path
    assert first.data.name.startswith(".IMG_1.JPG.")
    assert first.data.name.endswith(PARTIAL_SUFFIX)
    assert first.meta.name.endswith(PARTIAL_META_SUFFIX)
    assert first.data != second.data
    assert first.meta != second.meta
    assert partial_paths(tmp_path / "IMG_1.JPG").data == first.data


def test_prepare_partial_resumes_from_the_bytes_on_disk(tmp_path: Path) -> None:
    destination = tmp_path / "IMG_1.JPG"
    paths = partial_paths(destination)
    paths.data.write_bytes(b"a" * 400)
    write_partial_state(
        destination,
        PartialCopyState(source_size=1000, source_mtime_ns=7, hash_method="sha256"),
    )

    plan = prepare_partial(
        destination, source_size=1000, source_mtime_ns=7, hash_method="sha256"
    )

    assert plan.resumed
    assert plan.offset == 400
    assert plan.data == paths.data
    state = read_partial_state(destination)
    assert state is not None
    assert state.offset == 400
    assert state.source_size == 1000
    assert state.hash_method == "sha256"


def test_prepare_partial_discards_data_when_the_source_changed(tmp_path: Path) -> None:
    destination = tmp_path / "IMG_1.JPG"
    paths = partial_paths(destination)
    paths.data.write_bytes(b"a" * 400)
    write_partial_state(
        destination,
        PartialCopyState(source_size=1000, source_mtime_ns=7, hash_method="sha256"),
    )

    plan = prepare_partial(
        destination, source_size=1200, source_mtime_ns=7, hash_method="sha256"
    )

    assert plan.offset == 0
    assert not paths.data.exists()
    state = read_partial_state(destination)
    assert state is not None
    assert state.source_size == 1200

    # A changed modification time is just as suspicious as a changed size.
    paths.data.write_bytes(b"a" * 400)
    plan = prepare_partial(
        destination, source_size=1200, source_mtime_ns=8, hash_method="sha256"
    )
    assert plan.offset == 0
    assert not paths.data.exists()


def test_prepare_partial_discards_data_without_a_sidecar(tmp_path: Path) -> None:
    destination = tmp_path / "IMG_1.JPG"
    paths = partial_paths(destination)
    paths.data.write_bytes(b"leftover")

    plan = prepare_partial(
        destination, source_size=1000, source_mtime_ns=7, hash_method="sha256"
    )

    assert plan.offset == 0
    assert not paths.data.exists()
    assert read_partial_state(destination) is not None


def test_prepare_partial_discards_an_oversized_partial(tmp_path: Path) -> None:
    destination = tmp_path / "IMG_1.JPG"
    paths = partial_paths(destination)
    paths.data.write_bytes(b"a" * 1000)
    write_partial_state(
        destination,
        PartialCopyState(source_size=1000, source_mtime_ns=7, hash_method="sha256"),
    )

    plan = prepare_partial(
        destination, source_size=1000, source_mtime_ns=7, hash_method="sha256"
    )

    assert plan.offset == 0
    assert not paths.data.exists()


def test_prepare_partial_discards_an_unreadable_sidecar(tmp_path: Path) -> None:
    destination = tmp_path / "IMG_1.JPG"
    paths = partial_paths(destination)
    paths.data.write_bytes(b"a" * 400)
    paths.meta.write_text("{not json", encoding="utf-8")

    assert read_partial_state(destination) is None
    plan = prepare_partial(
        destination, source_size=1000, source_mtime_ns=7, hash_method="sha256"
    )
    assert plan.offset == 0
    assert not paths.data.exists()


def test_partial_size_is_zero_without_a_partial(tmp_path: Path) -> None:
    destination = tmp_path / "IMG_1.JPG"
    assert partial_size(destination) == 0
    partial_paths(destination).data.write_bytes(b"a" * 17)
    assert partial_size(destination) == 17


def test_finish_partial_keeps_the_offset_or_removes_the_pair(tmp_path: Path) -> None:
    destination = tmp_path / "IMG_1.JPG"
    paths = partial_paths(destination)
    paths.data.write_bytes(b"a" * 300)
    write_partial_state(
        destination,
        PartialCopyState(source_size=1000, source_mtime_ns=7, hash_method="sha256"),
    )

    finish_partial(destination, offset=300, keep=True)
    state = read_partial_state(destination)
    assert state is not None
    assert state.offset == 300
    assert paths.data.exists()

    finish_partial(destination, offset=0, keep=False)
    assert not paths.data.exists()
    assert not paths.meta.exists()


def test_partial_state_rejects_invalid_payloads() -> None:
    assert PartialCopyState.from_dict(None) is None
    assert PartialCopyState.from_dict({"source_size": "x"}) is None
    assert PartialCopyState.from_dict({"source_size": 1}) is None
    assert PartialCopyState.from_dict({"source_size": 1, "source_mtime_ns": True}) is None

    state = PartialCopyState.from_dict(
        {"source_size": -5, "source_mtime_ns": 3, "offset": -1, "hash_method": ""}
    )
    assert state is not None
    assert state.source_size == 0
    assert state.offset == 0
    assert state.hash_method == "sha256"
    assert state.matches_source(0, 3)
    assert not state.matches_source(0, 4)


# ---------------------------------------------------------------------------
# Volume identity
# ---------------------------------------------------------------------------


def test_volume_identity_round_trip(tmp_path: Path) -> None:
    volume = make_volume(
        tmp_path,
        device_path="/dev/sdb1",
        uuid="ABCD-1234",
        device_serial="SN1",
        platform="linux",
    )

    data = volume_identity(volume)
    restored = volume_from_identity(data)

    assert restored is not None
    assert restored.mount_path == tmp_path
    assert restored.uuid == "ABCD-1234"
    assert restored.device_serial == "SN1"
    assert restored.platform == "linux"
    assert volume_key(volume) == f"SN1|ABCD-1234|/dev/sdb1|{tmp_path}"

    assert volume_from_identity(None) is None
    assert volume_from_identity({"mount_path": ""}) is None
    minimal = volume_from_identity({"mount_path": str(tmp_path)})
    assert minimal is not None
    assert minimal.id == str(tmp_path)
    assert minimal.platform == "unknown"


def test_session_volumes_match_the_current_mount_points(tmp_path: Path) -> None:
    card = tmp_path / "card"
    card.mkdir()
    volume = make_volume(card)
    session = _bare_session(destination=tmp_path / "pictures", primary=volume)

    matched, secondary = match_session_volumes(session, [volume])
    assert matched is volume
    assert secondary is None

    assert match_session_volumes(session, [make_volume(tmp_path)]) == (None, None)


def _bare_session(
    *, destination: Path, primary: VolumeInfo, secondary: VolumeInfo | None = None
):
    """Minimal session object good enough for volume matching."""
    from cameracopy2.core.resume import CopySession

    return CopySession(
        session_id="test",
        directory=Path("/nonexistent"),
        created_at="",
        updated_at="",
        state="interrupted",
        destination=str(destination),
        source_subfolder="",
        config={},
        primary=volume_identity(primary),
        secondary=volume_identity(secondary) if secondary else None,
    )


# ---------------------------------------------------------------------------
# Session journal
# ---------------------------------------------------------------------------


def test_session_directory_sits_next_to_the_operation_logs(tmp_path: Path) -> None:
    config_path = tmp_path / "cameracopy.json"
    logs = operation_log_directory(config_path)
    assert session_directory(config_path) == logs.parent / SESSION_DIR_NAME


def test_session_store_records_and_reloads_a_job(tmp_path: Path) -> None:
    card = tmp_path / "card"
    dest = tmp_path / "pictures"
    card.mkdir()
    dest.mkdir()
    store = CopySessionStore(tmp_path / "sessions")
    job = CopyJob(
        primary=make_volume(card),
        secondary=None,
        config=make_config(dest),
        autoremove=True,
    )

    session = store.create(job)

    assert session.state == "running"
    assert session.session_id
    assert session.path == session.directory / SESSION_FILE_NAME
    assert session.path.exists()
    assert session.volume_keys == [volume_key(job.primary)]

    store.record(
        session,
        key=f"{session.volume_keys[0]}|IMG_1.JPG",
        relative_path="IMG_1.JPG",
        destination=dest / "IMG_1.JPG",
        size_bytes=10,
        mode="copied",
    )
    store.save(session, force=True)

    loaded = store.load(session.session_id)
    assert loaded is not None
    assert loaded.completed_count == 1
    assert loaded.completed_bytes == 10
    assert loaded.completed[f"{session.volume_keys[0]}|IMG_1.JPG"].relative_path == "IMG_1.JPG"
    assert loaded.destination == str(dest)
    assert loaded.autoremove is True
    assert loaded.state == "running"

    restored = loaded.restored_config()
    assert restored is not None
    assert restored.destination == str(dest)
    assert [item.session_id for item in store.open_sessions()] == [session.session_id]

    store.touch(loaded, total_files=4)
    assert store.load(session.session_id).total_files == 4  # type: ignore[union-attr]


def test_session_store_unrecord_keeps_the_totals_consistent(tmp_path: Path) -> None:
    store = _store_with_session(tmp_path)
    session = store.open_sessions()[0]

    store.record(
        session,
        key="key",
        relative_path="IMG_1.JPG",
        destination=tmp_path / "pictures" / "IMG_1.JPG",
        size_bytes=42,
        mode="copied",
    )
    assert session.completed_bytes == 42

    store.unrecord(session, "key")
    assert session.completed == {}
    assert session.completed_bytes == 0

    store.unrecord(session, "missing")
    assert session.completed_bytes == 0


def test_session_store_records_entries_without_a_destination(tmp_path: Path) -> None:
    store = _store_with_session(tmp_path)
    session = store.open_sessions()[0]
    store.record(
        session,
        key="key",
        relative_path="IMG_1.JPG",
        destination=None,
        size_bytes=-5,
        mode=None,
    )
    store.save(session, force=True)

    loaded = store.load(session.session_id)
    assert loaded is not None
    entry = loaded.completed["key"]
    assert entry.destination is None
    assert entry.size_bytes == 0
    assert entry.mode is None


def test_session_store_finish_clean_removes_the_journal(tmp_path: Path) -> None:
    store = _store_with_session(tmp_path)
    session = store.open_sessions()[0]

    session.state = "finished"
    store.save(session, force=True)
    assert store.load(session.session_id) is not None
    assert store.open_sessions() == []

    store.finish(session, clean=True)
    assert not session.directory.exists()
    assert store.load(session.session_id) is None


def test_session_store_finish_with_failures_keeps_the_journal(tmp_path: Path) -> None:
    store = _store_with_session(tmp_path)
    session = store.open_sessions()[0]

    store.finish(session, clean=False, failures=2)
    assert session.state == "interrupted"
    assert session.failures == 2
    kept = store.load(session.session_id)
    assert kept is not None
    assert kept.failures == 2
    assert [item.session_id for item in store.open_sessions()] == [session.session_id]


def test_session_store_discard_removes_partials_and_keeps_copied_files(
    tmp_path: Path,
) -> None:
    dest = tmp_path / "pictures"
    dest.mkdir()
    store = CopySessionStore(tmp_path / "sessions")
    session = store.create(
        CopyJob(primary=make_volume(tmp_path), secondary=None, config=make_config(dest))
    )
    preserved = dest / "IMG_0.JPG"
    preserved.write_bytes(b"done")
    destination = dest / "IMG_1.JPG"
    paths = partial_paths(destination)
    paths.data.write_bytes(b"a" * 500)
    write_partial_state(
        destination,
        PartialCopyState(source_size=1000, source_mtime_ns=7, hash_method="sha256"),
    )
    store.add_partial(session, paths.data)
    store.add_partial(session, paths.data)  # never recorded twice

    store.discard(session)

    assert session.partials == []
    assert not paths.data.exists()
    assert not paths.meta.exists()
    assert preserved.read_bytes() == b"done"
    assert not session.directory.exists()
    assert store.open_sessions() == []


def test_session_store_discard_keeps_partials_other_sessions_still_need(
    tmp_path: Path,
) -> None:
    first_dest = tmp_path / "first"
    second_dest = tmp_path / "second"
    first_dest.mkdir()
    second_dest.mkdir()
    store = CopySessionStore(tmp_path / "sessions")
    first = store.create(
        CopyJob(primary=make_volume(tmp_path), secondary=None, config=make_config(first_dest))
    )
    second = store.create(
        CopyJob(primary=make_volume(tmp_path), secondary=None, config=make_config(second_dest))
    )
    destination = first_dest / "IMG_1.JPG"
    paths = partial_paths(destination)
    paths.data.write_bytes(b"a" * 500)
    write_partial_state(
        destination,
        PartialCopyState(source_size=1000, source_mtime_ns=7, hash_method="sha256"),
    )
    store.add_partial(first, paths.data)
    store.add_partial(second, paths.data)
    store.save(first, force=True)
    store.save(second, force=True)

    store.discard(first)

    assert paths.data.exists()
    assert paths.meta.exists()
    assert [item.session_id for item in store.open_sessions()] == [second.session_id]

    store.discard(second)
    assert not paths.data.exists()
    assert not paths.meta.exists()


def test_session_store_discard_removes_orphan_partials_near_the_destination(
    tmp_path: Path,
) -> None:
    dest = tmp_path / "pictures"
    dest.mkdir()
    store = CopySessionStore(tmp_path / "sessions")
    session = store.create(
        CopyJob(primary=make_volume(tmp_path), secondary=None, config=make_config(dest))
    )
    orphan = partial_paths(dest / "UNLISTED.JPG")
    orphan.data.write_bytes(b"a" * 10)
    sibling = partial_paths(tmp_path / "OUTSIDE.JPG")
    sibling.data.write_bytes(b"a" * 10)

    store.discard(session)

    assert not orphan.data.exists()
    assert not orphan.meta.exists()
    assert not sibling.data.exists()


def test_session_store_prune_drops_old_sessions(tmp_path: Path) -> None:
    store = _store_with_session(tmp_path)
    session = store.open_sessions()[0]
    old = time.time() - (MAX_SESSION_AGE_DAYS + 1) * 86400
    os.utime(session.directory, (old, old))

    store.prune()

    assert store.open_sessions() == []
    assert not session.directory.exists()


def test_session_store_prune_keeps_recent_sessions_and_ignores_bad_age(
    tmp_path: Path,
) -> None:
    store = _store_with_session(tmp_path)
    session = store.open_sessions()[0]

    store.prune(max_age_days=0)
    assert store.load(session.session_id) is not None

    store.prune()
    assert store.load(session.session_id) is not None


def test_session_store_prune_removes_unreadable_session_directories(
    tmp_path: Path,
) -> None:
    store = CopySessionStore(tmp_path / "sessions")
    broken = store.directory / "20200101-000000"
    broken.mkdir(parents=True)
    (broken / SESSION_FILE_NAME).write_text("{not json", encoding="utf-8")
    old = time.time() - (MAX_SESSION_AGE_DAYS + 1) * 86400
    os.utime(broken, (old, old))

    store.prune()

    assert not broken.exists()


def test_session_store_ignores_unreadable_journals(tmp_path: Path) -> None:
    store = CopySessionStore(tmp_path / "sessions")
    store.directory.mkdir(parents=True)
    broken = store.directory / "broken"
    broken.mkdir()
    (broken / SESSION_FILE_NAME).write_text("{not json", encoding="utf-8")
    empty = store.directory / "empty"
    empty.mkdir()
    wrong_schema = store.directory / "wrong-schema"
    wrong_schema.mkdir()
    (wrong_schema / SESSION_FILE_NAME).write_text(
        json.dumps({"schema": 99, "session_id": "x"}), encoding="utf-8"
    )

    assert store.open_sessions() == []
    assert store.load("broken") is None
    assert store.load("missing") is None


def test_session_store_without_a_directory_has_no_sessions(tmp_path: Path) -> None:
    store = CopySessionStore(tmp_path / "absent")
    assert store.open_sessions() == []


def test_session_load_rejects_unusable_payloads(tmp_path: Path) -> None:
    from cameracopy2.core.resume import CopySession

    directory = tmp_path / "sessions" / "x"
    assert CopySession.from_dict(None, directory) is None
    assert CopySession.from_dict({"schema": 1}, directory) is None
    assert CopySession.from_dict({"schema": 1, "session_id": "x"}, directory) is None
    assert (
        CopySession.from_dict(
            {"schema": 1, "session_id": "x", "config": {}, "primary": {}, "destination": ""},
            directory,
        )
        is None
    )

    session = CopySession.from_dict(
        {
            "schema": 1,
            "session_id": "x",
            "config": {},
            "primary": {"mount_path": str(tmp_path)},
            "destination": str(tmp_path),
            "completed": {"gone": 5, "entry": {"relative_path": "a.JPG", "size_bytes": "no"}},
            "partials": ["a", 7],
            "state": "unexpected",
            "completed_bytes": "3",
        },
        directory,
    )
    assert session is not None
    assert session.state == "interrupted"
    assert session.completed_count == 1
    assert session.completed["entry"].size_bytes == 0
    assert session.partials == ["a"]
    assert session.completed_bytes == 0


def test_session_restored_config_reports_unusable_settings(tmp_path: Path) -> None:
    from cameracopy2.core.resume import CopySession

    session = CopySession(
        session_id="x",
        directory=tmp_path,
        created_at="",
        updated_at="",
        state="interrupted",
        destination=str(tmp_path),
        source_subfolder="",
        config={"version": 0},
        primary={"mount_path": str(tmp_path)},
    )
    assert session.restored_config() is None


def _store_with_session(tmp_path: Path) -> CopySessionStore:
    card = tmp_path / "card"
    dest = tmp_path / "pictures"
    card.mkdir(exist_ok=True)
    dest.mkdir(exist_ok=True)
    store = CopySessionStore(tmp_path / "sessions")
    store.create(CopyJob(primary=make_volume(card), secondary=None, config=make_config(dest)))
    return store


# ---------------------------------------------------------------------------
# Copy engine
# ---------------------------------------------------------------------------


def test_engine_continues_an_interrupted_partial_file(tmp_path: Path) -> None:
    card = tmp_path / "card"
    dest = tmp_path / "pictures"
    card.mkdir()
    dest.mkdir()
    payload = bytes(range(256)) * 400
    source = card / "IMG_1.JPG"
    source.write_bytes(payload)
    destination = dest / "IMG_1.JPG"
    half = len(payload) // 2
    seed_partial(destination, payload[:half], source)

    report = CopyEngine().run(
        CopyJob(primary=make_volume(card), secondary=None, config=make_config(dest))
    )

    assert not report.has_failures
    assert report.partial_resume_count == 1
    assert report.resumed_partial_bytes == half
    assert report.bytes_copied == len(payload)
    assert destination.read_bytes() == payload
    assert not partial_paths(destination).data.exists()
    assert not partial_paths(destination).meta.exists()


def test_engine_restarts_when_the_partial_belongs_to_another_source(
    tmp_path: Path,
) -> None:
    card = tmp_path / "card"
    dest = tmp_path / "pictures"
    card.mkdir()
    dest.mkdir()
    payload = b"payload" * 128
    source = card / "IMG_1.JPG"
    source.write_bytes(payload)
    destination = dest / "IMG_1.JPG"
    paths = partial_paths(destination)
    paths.data.write_bytes(b"stale data from a different file")
    write_partial_state(
        destination,
        PartialCopyState(source_size=9_999_999, source_mtime_ns=1, hash_method="sha256"),
    )

    report = CopyEngine().run(
        CopyJob(primary=make_volume(card), secondary=None, config=make_config(dest))
    )

    assert not report.has_failures
    assert report.partial_resume_count == 0
    assert report.resumed_partial_bytes == 0
    assert destination.read_bytes() == payload
    assert not paths.data.exists()
    assert not paths.meta.exists()


def test_engine_ignores_partial_files_when_resume_is_disabled(tmp_path: Path) -> None:
    card = tmp_path / "card"
    dest = tmp_path / "pictures"
    card.mkdir()
    dest.mkdir()
    payload = b"payload" * 256
    source = card / "IMG_1.JPG"
    source.write_bytes(payload)
    destination = dest / "IMG_1.JPG"
    seed_partial(destination, payload[:100], source)

    report = CopyEngine().run(
        CopyJob(
            primary=make_volume(card),
            secondary=None,
            config=make_config(dest, resumepartialfiles=False),
        )
    )

    assert not report.has_failures
    assert report.partial_resume_count == 0
    assert destination.read_bytes() == payload
    assert not list(dest.glob("*.cameracopy.tmp"))


def test_engine_discards_the_partial_when_the_source_changes_mid_copy(
    tmp_path: Path,
) -> None:
    card = tmp_path / "card"
    dest = tmp_path / "pictures"
    card.mkdir()
    dest.mkdir()
    source = card / "IMG_1.JPG"
    source.write_bytes(b"x" * (2 * 1024 * 1024))
    destination = dest / "IMG_1.JPG"

    def mutate_source(done: int, _total: int, _index: int) -> None:
        if done >= 1024 * 1024:
            source.write_bytes(b"y" * (3 * 1024 * 1024))

    report = CopyEngine().run(
        CopyJob(primary=make_volume(card), secondary=None, config=make_config(dest)),
        CopyCallbacks(byte_progress=mutate_source),
    )

    assert report.has_failures
    assert not destination.exists()
    assert not partial_paths(destination).data.exists()
    assert not partial_paths(destination).meta.exists()


def test_engine_keeps_a_partial_when_the_copy_is_cancelled(tmp_path: Path) -> None:
    card = tmp_path / "card"
    dest = tmp_path / "pictures"
    card.mkdir()
    dest.mkdir()
    source = card / "IMG_1.JPG"
    source.write_bytes(b"x" * (4 * 1024 * 1024))
    destination = dest / "IMG_1.JPG"
    cancel_event = Event()

    def cancel_later(done: int, _total: int, _index: int) -> None:
        if done >= 2 * 1024 * 1024:
            cancel_event.set()

    report = CopyEngine().run(
        CopyJob(primary=make_volume(card), secondary=None, config=make_config(dest)),
        CopyCallbacks(byte_progress=cancel_later),
        cancel_event,
    )

    assert report.cancelled
    assert not destination.exists()
    paths = partial_paths(destination)
    assert paths.data.exists()
    assert 0 < paths.data.stat().st_size < source.stat().st_size
    state = read_partial_state(destination)
    assert state is not None
    assert state.offset == paths.data.stat().st_size


def test_engine_records_an_interrupted_session_and_resumes_it(tmp_path: Path) -> None:
    card = tmp_path / "card"
    dest = tmp_path / "pictures"
    card.mkdir()
    dest.mkdir()
    small = card / "IMG_A.JPG"
    small.write_bytes(b"a" * 128)
    big = card / "IMG_B.JPG"
    big.write_bytes(b"b" * (4 * 1024 * 1024))
    store = CopySessionStore(tmp_path / "sessions")
    cancel_event = Event()

    def cancel_later(done: int, _total: int, _index: int) -> None:
        if done >= 2 * 1024 * 1024:
            cancel_event.set()

    report = CopyEngine(session_store=store).run(
        CopyJob(
            primary=make_volume(card),
            secondary=None,
            config=make_config(dest, checkhash=False),
        ),
        CopyCallbacks(byte_progress=cancel_later),
        cancel_event,
    )

    assert report.cancelled
    assert report.session_saved
    assert report.session_id
    assert (dest / "IMG_A.JPG").read_bytes() == b"a" * 128
    assert not (dest / "IMG_B.JPG").exists()
    partial = partial_paths(dest / "IMG_B.JPG")
    assert partial.data.exists()

    sessions = store.open_sessions()
    assert len(sessions) == 1
    session = sessions[0]
    assert session.session_id == report.session_id
    assert session.state == "interrupted"
    assert session.completed_count == 1
    assert session.completed_bytes == 128
    assert session.volume_keys == [volume_key(make_volume(card))]
    assert session.partials == [str(partial.data)]
    assert session.destination == str(dest)
    assert session.restored_config() is not None

    resumed = CopyEngine(session_store=store).run(
        CopyJob(
            primary=make_volume(card),
            secondary=None,
            config=make_config(dest, checkhash=False),
            resume=ResumedCopyState(
                session_id=session.session_id,
                volume_keys=tuple(session.volume_keys),
                completed=dict(session.completed),
                completed_bytes=session.completed_bytes,
                total_files=session.total_files,
            ),
        )
    )

    assert not resumed.has_failures
    assert not resumed.cancelled
    assert not resumed.session_saved
    assert resumed.resumed_files == 1
    assert resumed.resumed_bytes == 128
    assert resumed.partial_resume_count == 1
    assert resumed.resumed_partial_bytes > 0
    assert (dest / "IMG_A.JPG").read_bytes() == b"a" * 128
    assert (dest / "IMG_B.JPG").read_bytes() == big.read_bytes()
    assert not partial.data.exists()
    assert store.open_sessions() == []


def test_engine_skips_files_an_earlier_run_already_copied(tmp_path: Path) -> None:
    card = tmp_path / "card"
    dest = tmp_path / "pictures"
    card.mkdir()
    dest.mkdir()
    (card / "IMG_A.JPG").write_bytes(b"a" * 64)
    (card / "IMG_B.JPG").write_bytes(b"b" * 64)
    volume = make_volume(card)
    preserved = dest / "IMG_A.JPG"
    preserved.write_bytes(b"a" * 64)
    resume = ResumedCopyState(
        session_id="earlier",
        volume_keys=(volume_key(volume),),
        completed={
            f"{volume_key(volume)}|IMG_A.JPG": CompletedFileEntry(
                relative_path="IMG_A.JPG",
                destination=str(preserved),
                size_bytes=64,
                mode="copied",
            )
        },
        completed_bytes=64,
        total_files=2,
    )

    report = CopyEngine().run(
        CopyJob(
            primary=volume,
            secondary=None,
            config=make_config(dest),
            resume=resume,
        )
    )

    assert not report.has_failures
    assert report.resumed_files == 1
    assert report.resumed_bytes == 64
    assert (dest / "IMG_B.JPG").read_bytes() == b"b" * 64
    assert any("were already copied and were skipped" in line for line in report.logs)


def test_engine_recopies_a_file_whose_destination_disappeared(tmp_path: Path) -> None:
    card = tmp_path / "card"
    dest = tmp_path / "pictures"
    card.mkdir()
    dest.mkdir()
    source = card / "IMG_A.JPG"
    source.write_bytes(b"a" * 64)
    volume = make_volume(card)
    resume = ResumedCopyState(
        session_id="earlier",
        volume_keys=(volume_key(volume),),
        completed={
            f"{volume_key(volume)}|IMG_A.JPG": CompletedFileEntry(
                relative_path="IMG_A.JPG",
                destination=str(dest / "IMG_A.JPG"),
                size_bytes=64,
                mode="copied",
            )
        },
    )

    report = CopyEngine().run(
        CopyJob(
            primary=volume,
            secondary=None,
            config=make_config(dest, collisionpolicy="overwrite"),
            resume=resume,
        )
    )

    assert not report.has_failures
    assert report.resumed_files == 0
    assert (dest / "IMG_A.JPG").read_bytes() == b"a" * 64


def test_engine_recopies_a_file_whose_destination_shrank(tmp_path: Path) -> None:
    card = tmp_path / "card"
    dest = tmp_path / "pictures"
    card.mkdir()
    dest.mkdir()
    (card / "IMG_A.JPG").write_bytes(b"a" * 64)
    volume = make_volume(card)
    (dest / "IMG_A.JPG").write_bytes(b"truncated")
    resume = ResumedCopyState(
        session_id="earlier",
        volume_keys=(volume_key(volume),),
        completed={
            f"{volume_key(volume)}|IMG_A.JPG": CompletedFileEntry(
                relative_path="IMG_A.JPG",
                destination=str(dest / "IMG_A.JPG"),
                size_bytes=64,
                mode="copied",
            )
        },
    )

    report = CopyEngine().run(
        CopyJob(
            primary=volume,
            secondary=None,
            config=make_config(dest, collisionpolicy="overwrite"),
            resume=resume,
        )
    )

    assert not report.has_failures
    assert report.resumed_files == 0
    assert (dest / "IMG_A.JPG").read_bytes() == b"a" * 64


def test_engine_uses_the_recorded_volume_key_of_the_resumed_job(tmp_path: Path) -> None:
    """A card that now reports different metadata still resolves its earlier work."""
    card = tmp_path / "card"
    dest = tmp_path / "pictures"
    card.mkdir()
    dest.mkdir()
    (card / "IMG_A.JPG").write_bytes(b"a" * 32)
    (dest / "IMG_A.JPG").write_bytes(b"a" * 32)
    volume = make_volume(card)
    previous_key = volume_key(make_volume(card, device_serial="SN1"))
    assert previous_key != volume_key(volume)
    resume = ResumedCopyState(
        session_id="earlier",
        volume_keys=(previous_key,),
        completed={
            f"{previous_key}|IMG_A.JPG": CompletedFileEntry(
                relative_path="IMG_A.JPG",
                destination=str(dest / "IMG_A.JPG"),
                size_bytes=32,
                mode="copied",
            )
        },
        completed_bytes=32,
    )

    report = CopyEngine().run(
        CopyJob(primary=volume, secondary=None, config=make_config(dest), resume=resume)
    )

    assert not report.has_failures
    assert report.resumed_files == 1
    assert report.resumed_bytes == 32


def test_engine_removes_the_session_after_a_clean_copy(tmp_path: Path) -> None:
    card = tmp_path / "card"
    dest = tmp_path / "pictures"
    card.mkdir()
    dest.mkdir()
    (card / "IMG_1.JPG").write_bytes(b"image")
    store = CopySessionStore(tmp_path / "sessions")

    report = CopyEngine(session_store=store).run(
        CopyJob(primary=make_volume(card), secondary=None, config=make_config(dest))
    )

    assert not report.has_failures
    assert report.session_id
    assert not report.session_saved
    assert store.open_sessions() == []
    assert any("nothing is left to resume" in line for line in report.logs)


def test_engine_keeps_the_session_after_a_failure(tmp_path: Path) -> None:
    card = tmp_path / "card"
    dest = tmp_path / "pictures"
    card.mkdir()
    dest.mkdir()
    (card / "IMG_1.JPG").write_bytes(b"image")
    (dest / "IMG_1.JPG").mkdir()
    store = CopySessionStore(tmp_path / "sessions")

    report = CopyEngine(session_store=store).run(
        CopyJob(
            primary=make_volume(card),
            secondary=None,
            config=make_config(dest, collisionpolicy="overwrite"),
        )
    )

    assert report.has_failures
    assert report.session_saved
    sessions = store.open_sessions()
    assert len(sessions) == 1
    assert sessions[0].session_id == report.session_id
    assert sessions[0].state == "interrupted"
    assert sessions[0].partials == []
    assert not partial_paths(dest / "IMG_1.JPG").data.exists()
    assert any("can be resumed later" in line for line in report.logs)


def test_engine_runs_without_recovery_settings(tmp_path: Path) -> None:
    card = tmp_path / "card"
    dest = tmp_path / "pictures"
    card.mkdir()
    dest.mkdir()
    (card / "IMG_1.JPG").write_bytes(b"image")
    store = CopySessionStore(tmp_path / "sessions")

    report = CopyEngine(session_store=store).run(
        CopyJob(
            primary=make_volume(card),
            secondary=None,
            config=make_config(dest, resumepartialfiles=False),
        )
    )

    assert not report.has_failures
    assert report.session_id
    assert store.open_sessions() == []


def test_engine_continues_a_partial_with_batch_verification(tmp_path: Path) -> None:
    card = tmp_path / "card"
    dest = tmp_path / "pictures"
    card.mkdir()
    dest.mkdir()
    payload = bytes(range(256)) * 300
    source = card / "IMG_1.JPG"
    source.write_bytes(payload)
    destination = dest / "IMG_1.JPG"
    seed_partial(destination, payload[: len(payload) // 3], source)

    report = CopyEngine().run(
        CopyJob(
            primary=make_volume(card),
            secondary=None,
            config=make_config(dest, checkhash=True, verificationmode="batch"),
        )
    )

    assert not report.has_failures
    assert report.partial_resume_count == 1
    assert report.resumed_partial_bytes == len(payload) // 3
    assert report.batch_failed_count == 0
    assert destination.read_bytes() == payload
    assert not partial_paths(destination).data.exists()


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def test_resume_settings_default_to_enabled() -> None:
    default = config_from_dict({"version": 2})
    assert default.resumepartialfiles is True
    assert default.recoverinterruptedjobs is True


def test_resume_settings_round_trip_through_the_config_file(tmp_path: Path) -> None:
    configured = config_from_dict(
        {"version": 2, "resumepartialfiles": False, "recoverinterruptedjobs": False}
    )
    assert configured.resumepartialfiles is False
    assert configured.recoverinterruptedjobs is False

    path = tmp_path / "cameracopy.json"
    save_config(configured, path)
    assert load_config(path).resumepartialfiles is False
    assert load_config(path).recoverinterruptedjobs is False


# ---------------------------------------------------------------------------
# Translations
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "english",
    [
        "Resume interrupted copy",
        "Discard session",
        "Resume interrupted file copies",
        "Recover interrupted copy jobs",
        "Interrupted files:",
        "Interrupted copies:",
        "Copy session",
        "Resumed session",
        "Interrupted copy stopped; it can be resumed later.",
        "Copy session finished; nothing is left to resume.",
        "The interrupted copy is saved and can be resumed later.",
        "Continue the copy that was interrupted on 2026-09-22T12:00:00.",
    ],
)
def test_recovery_strings_are_translated(english: str) -> None:
    from cameracopy2 import i18n

    previous = i18n.get_language()
    i18n.set_language("zh_CN")
    try:
        translated = i18n.translate_text(english)
    finally:
        i18n.set_language(previous)

    assert translated != english
    assert any("\u4e00" <= character <= "\u9fff" for character in translated)


# ---------------------------------------------------------------------------
# User interface
# ---------------------------------------------------------------------------


def _gui_app():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_settings_dialog_exposes_the_recovery_options(
    tmp_path: Path, english_ui: None
) -> None:
    app = _gui_app()
    from cameracopy2.ui.settings_dialog import SettingsDialog

    config = make_config(
        tmp_path / "pictures", resumepartialfiles=False, recoverinterruptedjobs=False
    )
    dialog = SettingsDialog(config, volumes=[])

    assert not dialog.resume_partial_checkbox.isChecked()
    assert not dialog.recover_jobs_checkbox.isChecked()
    assert dialog.resume_partial_checkbox.toolTip()
    assert dialog.recover_jobs_checkbox.toolTip()
    assert "partial" in dialog.resume_partial_checkbox.toolTip().lower()

    dialog.resume_partial_checkbox.setChecked(True)
    dialog.recover_jobs_checkbox.setChecked(True)
    updated = dialog._config_from_controls()  # noqa: SLF001

    assert updated.resumepartialfiles is True
    assert updated.recoverinterruptedjobs is True

    dialog.close()
    app.processEvents()


def test_main_window_offers_recovery_for_a_matching_volume(
    tmp_path: Path, english_ui: None
) -> None:
    app = _gui_app()
    from cameracopy2.ui.main_window import MainWindow

    card = tmp_path / "card"
    dest = tmp_path / "pictures"
    card.mkdir()
    dest.mkdir()
    volume = make_volume(card)
    config = make_config(dest)
    store = CopySessionStore(tmp_path / "sessions")
    session = store.create(
        CopyJob(primary=volume, secondary=None, config=config, autoremove=True)
    )
    store.touch(session, total_files=12)
    store.record(
        session,
        key=f"{volume_key(volume)}|IMG_1.JPG",
        relative_path="IMG_1.JPG",
        destination=dest / "IMG_1.JPG",
        size_bytes=1024,
        mode="copied",
    )
    store.save(session, force=True)

    window = MainWindow(
        config_path=tmp_path / "cameracopy.json", config=config, session_store=store
    )
    try:
        assert window.resume_button.isHidden()
        assert window.discard_session_button.isHidden()

        window._apply_volume_list([volume])  # noqa: SLF001

        assert not window.resume_button.isHidden()
        assert not window.discard_session_button.isHidden()
        tooltip = window.resume_button.toolTip()
        assert "Continue the copy that was interrupted on" in tooltip
        assert str(dest) in tooltip
        assert "1 of 12" in tooltip

        window._apply_volume_list([])  # noqa: SLF001
        assert window.resume_button.isHidden()
    finally:
        window.close()
        app.processEvents()


def test_main_window_builds_the_resumed_job_from_the_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, english_ui: None
) -> None:
    app = _gui_app()
    from cameracopy2.ui import main_window as main_window_module
    from cameracopy2.ui.main_window import MainWindow

    card = tmp_path / "card"
    dest = tmp_path / "pictures"
    card.mkdir()
    dest.mkdir()
    volume = make_volume(card)
    config = make_config(dest)
    store = CopySessionStore(tmp_path / "sessions")
    session = store.create(
        CopyJob(
            primary=volume,
            secondary=None,
            config=config,
            autoremove=True,
            format_after_copy=None,
        )
    )
    (dest / "IMG_1.JPG").write_bytes(b"a" * 16)
    store.record(
        session,
        key=f"{volume_key(volume)}|IMG_1.JPG",
        relative_path="IMG_1.JPG",
        destination=dest / "IMG_1.JPG",
        size_bytes=16,
        mode="copied",
    )
    store.save(session, force=True)

    captured: dict[str, object] = {}

    class _StubSignal:
        def connect(self, _slot: object) -> None:
            return None

    class _StubDialog:
        def __init__(
            self,
            job: CopyJob,
            parent: object = None,
            *,
            operation_log: object = None,
            session_store: object = None,
        ) -> None:
            captured["job"] = job
            captured["store"] = session_store
            captured["operation_log"] = operation_log
            self.volumes_changed = _StubSignal()
            self.finished = _StubSignal()

        def show(self) -> None:
            return None

        def start(self, job: CopyJob | None = None) -> None:
            captured["started"] = job

    monkeypatch.setattr(main_window_module, "CopyProgressDialog", _StubDialog)

    window = MainWindow(
        config_path=tmp_path / "cameracopy.json", config=config, session_store=store
    )
    try:
        window._apply_volume_list([volume])  # noqa: SLF001
        window.start_resumed_copy()

        job = captured["job"]
        assert isinstance(job, CopyJob)
        assert job.resume is not None
        assert job.resume.session_id == session.session_id
        assert job.resume.volume_keys == tuple(session.volume_keys)
        assert set(job.resume.completed) == set(session.completed)
        assert job.resume.completed_bytes == 16
        assert job.primary.mount_path == card
        assert job.autoremove is True
        assert job.config.destination == str(dest)
        assert job.config.source == ""
        assert captured["store"] is store
        assert captured["started"] is job
    finally:
        window.close()
        app.processEvents()


def test_main_window_ignores_sessions_of_unrelated_volumes(tmp_path: Path) -> None:
    app = _gui_app()
    from cameracopy2.ui.main_window import MainWindow

    card = tmp_path / "card"
    other_card = tmp_path / "other-card"
    dest = tmp_path / "pictures"
    card.mkdir()
    other_card.mkdir()
    dest.mkdir()
    config = make_config(dest)
    store = CopySessionStore(tmp_path / "sessions")
    store.create(CopyJob(primary=make_volume(card), secondary=None, config=config))

    window = MainWindow(
        config_path=tmp_path / "cameracopy.json", config=config, session_store=store
    )
    try:
        window._apply_volume_list([make_volume(other_card)])  # noqa: SLF001
        assert window.resume_button.isHidden()
    finally:
        window.close()
        app.processEvents()


def test_main_window_shows_no_recovery_when_the_setting_is_disabled(
    tmp_path: Path,
) -> None:
    app = _gui_app()
    from cameracopy2.ui.main_window import MainWindow

    card = tmp_path / "card"
    dest = tmp_path / "pictures"
    card.mkdir()
    dest.mkdir()
    volume = make_volume(card)
    config = make_config(dest, recoverinterruptedjobs=False)
    store = CopySessionStore(tmp_path / "sessions")
    store.create(CopyJob(primary=volume, secondary=None, config=config))

    window = MainWindow(
        config_path=tmp_path / "cameracopy.json", config=config, session_store=store
    )
    try:
        window._apply_volume_list([volume])  # noqa: SLF001
        assert window.resume_button.isHidden()
    finally:
        window.close()
        app.processEvents()


def test_main_window_discards_a_session_after_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, english_ui: None
) -> None:
    app = _gui_app()
    from PySide6.QtWidgets import QMessageBox

    from cameracopy2.ui.main_window import MainWindow

    card = tmp_path / "card"
    dest = tmp_path / "pictures"
    card.mkdir()
    dest.mkdir()
    volume = make_volume(card)
    config = make_config(dest)
    store = CopySessionStore(tmp_path / "sessions")
    session = store.create(CopyJob(primary=volume, secondary=None, config=config))
    destination = dest / "IMG_1.JPG"
    partial = partial_paths(destination)
    partial.data.write_bytes(b"a" * 100)
    write_partial_state(
        destination,
        PartialCopyState(source_size=500, source_mtime_ns=9, hash_method="sha256"),
    )
    store.add_partial(session, partial.data)
    store.save(session, force=True)

    window = MainWindow(
        config_path=tmp_path / "cameracopy.json", config=config, session_store=store
    )
    try:
        window._apply_volume_list([volume])  # noqa: SLF001
        assert not window.resume_button.isHidden()

        prompts: list[str] = []

        def confirm(*args: object, **_kwargs: object) -> QMessageBox.StandardButton:
            prompts.append(str(args[2]))
            return QMessageBox.StandardButton.Yes

        monkeypatch.setattr(QMessageBox, "warning", confirm)
        window.discard_resumable_session()

        assert prompts
        assert str(dest) in prompts[0]
        assert not partial.data.exists()
        assert not partial.meta.exists()
        assert store.open_sessions() == []
        assert window.resume_button.isHidden()
    finally:
        window.close()
        app.processEvents()


def test_main_window_keeps_a_session_when_discard_is_declined(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _gui_app()
    from PySide6.QtWidgets import QMessageBox

    from cameracopy2.ui.main_window import MainWindow

    card = tmp_path / "card"
    dest = tmp_path / "pictures"
    card.mkdir()
    dest.mkdir()
    volume = make_volume(card)
    config = make_config(dest)
    store = CopySessionStore(tmp_path / "sessions")
    session = store.create(CopyJob(primary=volume, secondary=None, config=config))

    window = MainWindow(
        config_path=tmp_path / "cameracopy.json", config=config, session_store=store
    )
    try:
        window._apply_volume_list([volume])  # noqa: SLF001
        monkeypatch.setattr(
            QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.No
        )

        window.discard_resumable_session()

        assert [item.session_id for item in store.open_sessions()] == [session.session_id]
        assert not window.resume_button.isHidden()
    finally:
        window.close()
        app.processEvents()


def test_main_window_reports_an_unavailable_destination_on_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, english_ui: None
) -> None:
    app = _gui_app()
    from cameracopy2.ui.main_window import MainWindow

    card = tmp_path / "card"
    dest = tmp_path / "pictures"
    card.mkdir()
    dest.mkdir()
    volume = make_volume(card)
    config = make_config(dest)
    store = CopySessionStore(tmp_path / "sessions")
    store.create(CopyJob(primary=volume, secondary=None, config=config))

    window = MainWindow(
        config_path=tmp_path / "cameracopy.json", config=config, session_store=store
    )
    try:
        window._apply_volume_list([volume])  # noqa: SLF001
        assert not window.resume_button.isHidden()

        captured: list[str] = []
        monkeypatch.setattr(
            "cameracopy2.ui.main_window.QMessageBox.critical",
            lambda *args, **kwargs: captured.append(str(args[2])),
        )
        monkeypatch.setattr(
            MainWindow, "_destination_looks_usable", lambda self, destination: False
        )

        window.start_resumed_copy()

        assert captured
        assert "Reconnect it and try again" in captured[0]
        assert not window.resume_button.isHidden()
    finally:
        window.close()
        app.processEvents()


def test_progress_dialog_reports_a_resumed_job(
    tmp_path: Path, english_ui: None
) -> None:
    app = _gui_app()
    from cameracopy2.ui.copy_progress_dialog import CopyProgressDialog

    card = tmp_path / "card"
    dest = tmp_path / "pictures"
    card.mkdir()
    dest.mkdir()
    store = CopySessionStore(tmp_path / "sessions")
    job = CopyJob(
        primary=make_volume(card),
        secondary=None,
        config=make_config(dest),
        resume=ResumedCopyState(session_id="earlier"),
    )
    dialog = CopyProgressDialog(job, session_store=store)
    try:
        assert dialog.session_store is store
        assert dialog.initial_status_text() == "Resuming interrupted copy…"
    finally:
        dialog.cancel_event.set()
        dialog.close()
        app.processEvents()


def test_progress_dialog_reports_a_new_job(tmp_path: Path, english_ui: None) -> None:
    app = _gui_app()
    from cameracopy2.ui.copy_progress_dialog import CopyProgressDialog

    card = tmp_path / "card"
    dest = tmp_path / "pictures"
    card.mkdir()
    dest.mkdir()
    job = CopyJob(primary=make_volume(card), secondary=None, config=make_config(dest))
    dialog = CopyProgressDialog(job, session_store=CopySessionStore(tmp_path / "sessions"))
    try:
        assert dialog.session_store is not None
        assert dialog.initial_status_text() == "Starting copy…"
    finally:
        dialog.cancel_event.set()
        dialog.close()
        app.processEvents()


def test_copy_worker_receives_the_session_store(tmp_path: Path) -> None:
    app = _gui_app()
    from cameracopy2.ui.copy_workers import CopyWorker

    card = tmp_path / "card"
    dest = tmp_path / "pictures"
    card.mkdir()
    dest.mkdir()
    store = CopySessionStore(tmp_path / "sessions")
    job = CopyJob(primary=make_volume(card), secondary=None, config=make_config(dest))

    worker = CopyWorker(job, Event(), store)

    assert worker.job is job
    assert worker.session_store is store
    app.processEvents()
