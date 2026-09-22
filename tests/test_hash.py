"""Regression tests for the selectable verification method (SHA-256 / xxHash64)
and the two destination-verification timings (per-file / batch)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cameracopy2.config import (
    UnsupportedConfigError,
    config_from_dict,
    load_config,
    save_config,
)
from cameracopy2.core import xxhash64
from cameracopy2.core.copy_engine import CopyEngine
from cameracopy2.core.hash import (
    DEFAULT_HASH_METHOD,
    HASH_METHODS,
    compare_files_cancellable,
    hash_failure_label,
    hash_file,
    hash_method_available,
    hash_method_label,
    new_digest,
)
from cameracopy2.models import CameraCopyConfig, CopyJob, VolumeInfo

# Canonical XXH64 test vectors for seed 0.
XXH64_VECTORS = {
    b"": "ef46db3751d8e999",
    b"a": "d24ec4f1a98c6e5b",
    b"abc": "44bc2cf5ad770999",
    b"message digest": "066ed728fceeb3be",
    b"xxhash": "32dd38952c4bc720",
}


def _volume(path: Path) -> VolumeInfo:
    return VolumeInfo(id=str(path), display_name=path.name, mount_path=path, platform="test")


def _card(tmp_path: Path) -> tuple[Path, Path]:
    card = tmp_path / "card"
    destination = tmp_path / "pictures"
    (card / "DCIM").mkdir(parents=True)
    destination.mkdir(parents=True)
    (card / "DCIM" / "DSC0001.ARW").write_bytes(b"alpha " * 5000)
    (card / "DCIM" / "DSC0002.ARW").write_bytes(b"beta " * 8000)
    return card, destination


def _config(destination: Path, **overrides) -> CameraCopyConfig:
    return CameraCopyConfig(
        source="DCIM",
        destination=str(destination),
        includedfiles=["*.ARW"],
        datetimestring="",
        checkhash=True,
        durablewrites=False,
        **overrides,
    )


def _run(card: Path, config: CameraCopyConfig, *, autoremove: bool = False):
    return CopyEngine().run(CopyJob(_volume(card), None, config, autoremove=autoremove))


# -- digest primitives -----------------------------------------------------


@pytest.mark.parametrize("payload, expected", sorted(XXH64_VECTORS.items()))
def test_xxhash64_matches_canonical_vectors(payload: bytes, expected: str) -> None:
    assert new_digest("xxhash64").update(payload).hexdigest() == expected


def test_xxhash64_streaming_is_chunk_size_independent() -> None:
    payload = bytes(range(256)) * 40
    expected = xxhash64.new().update(payload).hexdigest()
    for size in (1, 3, 31, 32, 33, 64, 127, 1024, len(payload) + 5):
        digest = xxhash64.new()
        for offset in range(0, len(payload), size):
            digest.update(payload[offset : offset + size])
        assert digest.hexdigest() == expected, f"chunk size {size}"


def test_xxhash64_digest_copy_is_independent() -> None:
    digest = xxhash64.new()
    digest.update(b"alpha")
    clone = digest.copy()
    clone.update(b"-beta")
    assert digest.hexdigest() == xxhash64.new().update(b"alpha").hexdigest()
    assert clone.hexdigest() == xxhash64.new().update(b"alpha-beta").hexdigest()


def test_xxhash64_pure_python_matches_native_when_available() -> None:
    if not xxhash64.native_available():
        pytest.skip("native xxhash module is not installed")
    for payload in (b"", b"x", b"a" * 31, b"a" * 32, b"a" * 33, bytes(range(256)) * 7):
        assert (
            xxhash64.PureXXH64().update(payload).hexdigest()
            == xxhash64.XXH64Digest().update(payload).hexdigest()
        )


def test_hash_helpers_expose_both_methods() -> None:
    assert HASH_METHODS == ("sha256", "xxhash64")
    assert DEFAULT_HASH_METHOD == "sha256"
    assert hash_method_label("sha256") == "SHA-256"
    assert hash_method_label("xxhash64") == "xxHash64"
    assert hash_failure_label("sha256") == "SHA256"
    assert hash_failure_label("xxhash64") == "xxHash64"
    assert hash_method_available("sha256") is True
    with pytest.raises(ValueError):
        new_digest("md5")


def test_hash_file_and_compare_are_method_aware(tmp_path: Path) -> None:
    left = tmp_path / "left.bin"
    right = tmp_path / "right.bin"
    left.write_bytes(b"same bytes" * 1000)
    right.write_bytes(b"same bytes" * 1000)
    right.write_bytes(b"same bytes" * 1000)

    for method in HASH_METHODS:
        assert hash_file(left, method=method) == hash_file(right, method=method)
        result = compare_files_cancellable(left, right, None, method=method)
        assert result.ok and result.error is None

    right.write_bytes(b"different!" * 1000)
    for method in HASH_METHODS:
        result = compare_files_cancellable(left, right, None, method=method)
        assert result.ok is False


# -- engine: per-file verification ----------------------------------------


@pytest.mark.parametrize("method", HASH_METHODS)
def test_engine_per_file_verification_copies_and_verifies(
    tmp_path: Path, method: str
) -> None:
    card, destination = _card(tmp_path)
    report = _run(card, _config(destination, hashmethod=method, verificationmode="per_file"))

    assert report.completed_cleanly
    assert report.copied_count == 2
    assert report.hash_method == method
    assert report.verification_mode == "per_file"
    assert sorted(p.name for p in destination.glob("*.ARW")) == ["DSC0001.ARW", "DSC0002.ARW"]
    assert all(result.hash_ok is True for result in report.results)
    assert report.batch_checked_count == 0
    assert any(hash_failure_label(method) in line for line in report.logs)


def test_engine_defaults_to_sha256_per_file(tmp_path: Path) -> None:
    card, destination = _card(tmp_path)
    report = _run(card, _config(destination))

    assert report.completed_cleanly
    assert report.hash_method == "sha256"
    assert report.verification_mode == "per_file"


# -- engine: batch verification -------------------------------------------


@pytest.mark.parametrize("method", HASH_METHODS)
def test_engine_batch_verification_checks_every_file(tmp_path: Path, method: str) -> None:
    card, destination = _card(tmp_path)
    report = _run(card, _config(destination, hashmethod=method, verificationmode="batch"))

    assert report.completed_cleanly
    assert report.verification_mode == "batch"
    assert report.batch_checked_count == 2
    assert report.batch_failed_count == 0
    assert report.batch_checked_bytes > 0
    assert report.batch_verification_seconds > 0
    assert any("Batch verification" in line for line in report.summary_lines())
    assert all(result.hash_ok is True for result in report.results)


def test_batch_verification_defers_source_removal_until_checks_pass(
    tmp_path: Path,
) -> None:
    card, destination = _card(tmp_path)
    report = _run(
        card,
        _config(destination, hashmethod="xxhash64", verificationmode="batch"),
        autoremove=True,
    )

    assert report.completed_cleanly
    assert report.removed_count == 2
    assert not (card / "DCIM" / "DSC0001.ARW").exists()
    assert not (card / "DCIM" / "DSC0002.ARW").exists()


def test_batch_verification_failure_keeps_source_and_reports_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    card, destination = _card(tmp_path)
    config = _config(destination, hashmethod="xxhash64", verificationmode="batch")
    engine = CopyEngine()
    real_digest = engine._digest_path

    def corrupt_destination(path, hash_method, cancel_event=None, progress=None):
        digest = real_digest(path, hash_method, cancel_event, progress)
        if Path(path).parent == destination:
            return "0" * len(digest)
        return digest

    monkeypatch.setattr(engine, "_digest_path", corrupt_destination)
    report = engine.run(CopyJob(_volume(card), None, config, autoremove=True))

    assert report.has_failures
    assert report.failed_count == 2
    assert report.batch_failed_count == 2
    assert report.removed_count == 0
    assert (card / "DCIM" / "DSC0001.ARW").exists()
    assert any(risk.kind == "batch_verification_failed" for risk in report.format_risks)
    assert any("MISMATCH" in line for line in report.logs)
    assert all(result.hash_ok is False for result in report.results)


def test_per_file_verification_fails_a_corrupted_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    card, destination = _card(tmp_path)
    config = _config(destination, hashmethod="xxhash64", verificationmode="per_file")
    engine = CopyEngine()
    real_digest = engine._digest_path

    def corrupt_destination(path, hash_method, cancel_event=None, progress=None):
        digest = real_digest(path, hash_method, cancel_event, progress)
        if Path(path).parent == destination:
            return "0" * len(digest)
        return digest

    monkeypatch.setattr(engine, "_digest_path", corrupt_destination)
    report = engine.run(CopyJob(_volume(card), None, config))

    assert report.has_failures
    assert report.batch_checked_count == 0
    assert all("XXHASH64 FAILED" in (result.reason or "") for result in report.results)


# -- config ----------------------------------------------------------------


@pytest.mark.parametrize("method", HASH_METHODS)
@pytest.mark.parametrize("mode", ["per_file", "batch"])
def test_config_round_trips_hash_settings(
    tmp_path: Path, method: str, mode: str
) -> None:
    path = tmp_path / "config.json"
    config = _config(tmp_path / "out", hashmethod=method, verificationmode=mode)
    save_config(config, path)

    assert load_config(path).hashmethod == method
    assert load_config(path).verificationmode == mode


def test_config_rejects_unknown_hash_settings() -> None:
    with pytest.raises(UnsupportedConfigError):
        config_from_dict({"version": 2, "hashmethod": "md5"})
    with pytest.raises(UnsupportedConfigError):
        config_from_dict({"version": 2, "verificationmode": "sometimes"})


def test_config_without_hash_settings_uses_defaults(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    config = CameraCopyConfig(source="DCIM", destination=str(tmp_path / "out"))
    save_config(config, path)
    loaded = load_config(path)

    assert loaded.hashmethod == "sha256"
    assert loaded.verificationmode == "per_file"
