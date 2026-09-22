"""Redundant backups: one source file written to several destination roots."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import pytest

from cameracopy2 import i18n
from cameracopy2.config import UnsupportedConfigError, config_from_dict
from cameracopy2.core.copy_engine import CopyEngine
from cameracopy2.core.copy_messages import result_message
from cameracopy2.core.format_warnings import format_risk_warning_paragraphs
from cameracopy2.models import (
    CameraCopyConfig,
    CopyJob,
    VolumeInfo,
)


def make_volume(path: Path) -> VolumeInfo:
    return VolumeInfo(id=str(path), display_name="Test card", mount_path=path, platform="test")


def build_job(
    tmp_path: Path,
    mirrors: list[Path],
    *,
    autoremove: bool = False,
    write_mode: str = "parallel",
    collision_policy: str = "ask",
    datetimestring: str = "",
    copysidecars: bool = False,
    minrating: int = 0,
    checkhash: bool = True,
) -> tuple[CopyJob, Path, Path]:
    card = tmp_path / "card"
    dest = tmp_path / "pictures"
    card.mkdir(exist_ok=True)
    dest.mkdir(exist_ok=True)
    config = CameraCopyConfig(
        source="",
        destination=str(dest),
        includedfiles=["*.JPG", "*.xmp"],
        datetimestring=datetimestring,
        redundantbackup=True,
        additionaldestinations=[str(mirror) for mirror in mirrors],
        redundantwritemode=write_mode,  # type: ignore[arg-type]
        collisionpolicy=collision_policy,  # type: ignore[arg-type]
        copysidecars=copysidecars,
        minrating=minrating,
        checkhash=checkhash,
    )
    job = CopyJob(
        primary=make_volume(card), secondary=None, config=config, autoremove=autoremove
    )
    return job, card, dest


# -- configuration ----------------------------------------------------------


def test_redundant_backup_defaults_are_off() -> None:
    config = CameraCopyConfig()
    assert config.redundantbackup is False
    assert config.additionaldestinations == []
    assert config.redundantwritemode == "parallel"


def test_config_round_trip_keeps_redundant_fields(tmp_path: Path) -> None:
    first = str(tmp_path / "backup-a")
    second = str(tmp_path / "backup-b")
    config = CameraCopyConfig(
        redundantbackup=True,
        additionaldestinations=[first, first, "", second],
        redundantwritemode="sequential",
    )
    parsed = config_from_dict(asdict(config))
    assert parsed.redundantbackup is True
    assert parsed.additionaldestinations == [first, second]
    assert parsed.redundantwritemode == "sequential"


def test_config_rejects_unknown_write_mode() -> None:
    payload = asdict(CameraCopyConfig(redundantbackup=True))
    payload["redundantwritemode"] = "broadcast"
    with pytest.raises(UnsupportedConfigError):
        config_from_dict(payload)


def test_config_without_redundant_fields_still_loads() -> None:
    payload = asdict(CameraCopyConfig())
    for key in ("redundantbackup", "additionaldestinations", "redundantwritemode"):
        payload.pop(key)
    parsed = config_from_dict(payload)
    assert parsed.redundantbackup is False
    assert parsed.additionaldestinations == []
    assert parsed.redundantwritemode == "parallel"


# -- mirroring --------------------------------------------------------------


@pytest.mark.parametrize("write_mode", ["parallel", "sequential"])
def test_every_mirror_receives_the_file(tmp_path: Path, write_mode: str) -> None:
    first = tmp_path / "backup-a"
    second = tmp_path / "backup-b"
    first.mkdir()
    second.mkdir()
    job, card, dest = build_job(tmp_path, [first, second], write_mode=write_mode)
    (card / "DSC0001.JPG").write_bytes(b"image")

    report = CopyEngine().run(job)

    assert not report.has_failures
    assert (dest / "DSC0001.JPG").read_bytes() == b"image"
    assert (first / "DSC0001.JPG").read_bytes() == b"image"
    assert (second / "DSC0001.JPG").read_bytes() == b"image"
    assert report.replica_failed_count == 0
    assert len(report.replica_results) == 2
    assert report.results[0].replicas_verified
    assert report.replica_bytes_copied == 2 * len(b"image")


def test_dated_folder_structure_is_mirrored(tmp_path: Path) -> None:
    mirror = tmp_path / "backup-a"
    mirror.mkdir()
    job, card, dest = build_job(
        tmp_path, [mirror], datetimestring="yyyy-MM-dd", collision_policy="overwrite"
    )
    (card / "DSC0001.JPG").write_bytes(b"image")

    report = CopyEngine().run(job)

    assert not report.has_failures
    primary_files = [path for path in dest.rglob("DSC0001.JPG") if path.is_file()]
    mirror_files = [path for path in mirror.rglob("DSC0001.JPG") if path.is_file()]
    assert len(primary_files) == 1
    assert len(mirror_files) == 1
    assert mirror_files[0].relative_to(mirror) == primary_files[0].relative_to(dest)


def test_sidecars_are_mirrored_with_their_media(tmp_path: Path) -> None:
    mirror = tmp_path / "backup-a"
    mirror.mkdir()
    job, card, dest = build_job(
        tmp_path, [mirror], collision_policy="overwrite", copysidecars=True
    )
    (card / "DSC0001.JPG").write_bytes(b"image")
    (card / "DSC0001.xmp").write_text('<rdf:Description xmp:Rating="4" />')

    report = CopyEngine().run(job)

    assert not report.has_failures
    assert (mirror / "DSC0001.JPG").read_bytes() == b"image"
    assert (mirror / "DSC0001.xmp").exists()
    assert (dest / "DSC0001.xmp").exists()


def test_matching_existing_mirror_is_verified_instead_of_rewritten(tmp_path: Path) -> None:
    mirror = tmp_path / "backup-a"
    mirror.mkdir()
    (mirror / "DSC0001.JPG").write_bytes(b"image")
    job, card, _dest = build_job(tmp_path, [mirror])
    (card / "DSC0001.JPG").write_bytes(b"image")

    report = CopyEngine().run(job)

    assert not report.has_failures
    replicas = report.replica_results
    assert len(replicas) == 1
    assert replicas[0].copy_mode == "verified_existing"
    assert replicas[0].bytes_copied == 0
    assert report.replica_bytes_copied == 0


def test_existing_mirror_with_different_content_is_reported(tmp_path: Path) -> None:
    mirror = tmp_path / "backup-a"
    mirror.mkdir()
    existing = mirror / "DSC0001.JPG"
    existing.write_bytes(b"stale")
    job, card, _dest = build_job(tmp_path, [mirror])
    (card / "DSC0001.JPG").write_bytes(b"image")

    report = CopyEngine().run(job)

    assert report.has_failures
    assert existing.read_bytes() == b"stale"
    replica = report.replica_results[0]
    assert replica.failed
    assert replica.reason == "redundant destination already holds a different file"
    assert report.replica_failed_count == 1


def test_overwrite_policy_replaces_a_different_mirror(tmp_path: Path) -> None:
    mirror = tmp_path / "backup-a"
    mirror.mkdir()
    existing = mirror / "DSC0001.JPG"
    existing.write_bytes(b"stale")
    job, card, _dest = build_job(tmp_path, [mirror], collision_policy="overwrite")
    (card / "DSC0001.JPG").write_bytes(b"image")

    report = CopyEngine().run(job)

    assert not report.has_failures
    assert existing.read_bytes() == b"image"
    assert report.replica_results[0].copy_mode == "overwrote"


def test_rename_policy_keeps_the_existing_mirror(tmp_path: Path) -> None:
    mirror = tmp_path / "backup-a"
    mirror.mkdir()
    existing = mirror / "DSC0001.JPG"
    existing.write_bytes(b"stale")
    job, card, _dest = build_job(tmp_path, [mirror], collision_policy="rename")
    (card / "DSC0001.JPG").write_bytes(b"image")

    report = CopyEngine().run(job)

    assert not report.has_failures
    assert existing.read_bytes() == b"stale"
    assert report.replica_results[0].copy_mode == "renamed_copy"
    assert (mirror / "DSC0001_001.JPG").read_bytes() == b"image"


# -- safety properties ------------------------------------------------------


def test_unavailable_mirror_stops_the_copy_before_anything_is_written(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "not-mounted"
    job, card, dest = build_job(tmp_path, [missing])
    (card / "DSC0001.JPG").write_bytes(b"image")

    report = CopyEngine().run(job)

    assert report.has_failures
    assert report.total_count == 1
    blocked = report.results[0]
    assert blocked.action == "failed"
    assert blocked.reason == "redundant backup destination unavailable"
    assert "not an available folder" in (blocked.error or "")
    assert not list(dest.glob("*.JPG"))
    assert (card / "DSC0001.JPG").exists()


def test_missing_mirror_configuration_stops_the_copy(tmp_path: Path) -> None:
    job, card, dest = build_job(tmp_path, [])
    (card / "DSC0001.JPG").write_bytes(b"image")

    report = CopyEngine().run(job)

    assert report.has_failures
    assert "no redundant backup folder is configured" in (report.results[0].error or "")
    assert not list(dest.glob("*.JPG"))


def test_mirror_equal_to_the_destination_is_not_a_second_copy(tmp_path: Path) -> None:
    job, card, dest = build_job(tmp_path, [])
    # Point the only backup folder at the destination itself.
    job.config.additionaldestinations = [str(dest)]
    (card / "DSC0001.JPG").write_bytes(b"image")

    report = CopyEngine().run(job)

    assert report.has_failures
    assert report.results[0].reason == "redundant backup destination unavailable"


def test_failed_mirror_blocks_source_removal(tmp_path: Path) -> None:
    mirror = tmp_path / "backup-a"
    mirror.mkdir()
    (mirror / "DSC0001.JPG").write_bytes(b"stale")
    job, card, _dest = build_job(tmp_path, [mirror], autoremove=True)
    source = card / "DSC0001.JPG"
    source.write_bytes(b"image")

    report = CopyEngine().run(job)

    assert report.has_failures
    assert source.exists(), "the source must survive until every mirror holds the file"
    result = report.results[0]
    assert result.action == "copied"
    assert result.reason == "redundant backup incomplete; source kept"
    assert report.removed_count == 0


def test_failed_mirror_blocks_deferred_batch_removal(tmp_path: Path) -> None:
    mirror = tmp_path / "backup-a"
    mirror.mkdir()
    (mirror / "DSC0001.JPG").write_bytes(b"stale")
    job, card, _dest = build_job(tmp_path, [mirror], autoremove=True)
    job.config.verificationmode = "batch"
    source = card / "DSC0001.JPG"
    source.write_bytes(b"image")

    report = CopyEngine().run(job)

    assert report.has_failures
    assert source.exists(), "batch mode must not remove a source whose mirror failed"
    assert report.removed_count == 0


def test_unwritable_mirror_file_is_reported_without_losing_the_source(
    tmp_path: Path,
) -> None:
    mirror = tmp_path / "backup-a"
    mirror.mkdir()
    # A directory sitting where the mirrored file belongs makes the write fail.
    (mirror / "DSC0001.JPG").mkdir()
    job, card, _dest = build_job(
        tmp_path, [mirror], autoremove=True, collision_policy="overwrite"
    )
    source = card / "DSC0001.JPG"
    source.write_bytes(b"image")

    report = CopyEngine().run(job)

    assert report.has_failures
    assert source.exists()
    replica = report.replica_results[0]
    assert replica.failed
    assert replica.error


def test_failed_mirror_records_a_format_risk(tmp_path: Path) -> None:
    mirror = tmp_path / "backup-a"
    mirror.mkdir()
    (mirror / "DSC0001.JPG").write_bytes(b"stale")
    job, card, _dest = build_job(tmp_path, [mirror])
    source = card / "DSC0001.JPG"
    source.write_bytes(b"image")

    report = CopyEngine().run(job)

    volume = job.primary
    counts = report.format_risk_counts_for(volume)
    assert counts.get("replica_failed") == 1
    assert format_risk_warning_paragraphs(counts)


def test_complete_mirrors_still_allow_source_removal(tmp_path: Path) -> None:
    mirror = tmp_path / "backup-a"
    mirror.mkdir()
    job, card, dest = build_job(tmp_path, [mirror], autoremove=True)
    source = card / "DSC0001.JPG"
    source.write_bytes(b"image")

    report = CopyEngine().run(job)

    assert not report.has_failures
    assert not source.exists()
    assert (dest / "DSC0001.JPG").read_bytes() == b"image"
    assert (mirror / "DSC0001.JPG").read_bytes() == b"image"
    assert report.removed_count == 1
    assert report.replicas_verified_count == 1


def test_redundant_backup_off_writes_nothing_extra(tmp_path: Path) -> None:
    mirror = tmp_path / "backup-a"
    mirror.mkdir()
    job, card, dest = build_job(tmp_path, [mirror])
    job.config.redundantbackup = False
    (card / "DSC0001.JPG").write_bytes(b"image")

    report = CopyEngine().run(job)

    assert not report.has_failures
    assert (dest / "DSC0001.JPG").exists()
    assert not (mirror / "DSC0001.JPG").exists()
    assert report.replica_results == []


# -- reporting --------------------------------------------------------------


def test_report_lists_each_backup_folder(tmp_path: Path) -> None:
    first = tmp_path / "backup-a"
    second = tmp_path / "backup-b"
    first.mkdir()
    second.mkdir()
    job, card, _dest = build_job(tmp_path, [first, second], collision_policy="overwrite")
    (card / "DSC0001.JPG").write_bytes(b"image")

    report = CopyEngine().run(job)
    lines = report.summary_lines()
    summary = "\n".join(lines)

    assert "Redundant bytes written" in summary
    assert "Redundant backups:" in summary
    assert str(first) in summary
    assert str(second) in summary
    assert summary.count("1 written") == 2


def test_incomplete_mirror_is_named_in_the_result_message(tmp_path: Path) -> None:
    mirror = tmp_path / "backup-a"
    mirror.mkdir()
    (mirror / "DSC0001.JPG").write_bytes(b"stale")
    job, card, _dest = build_job(tmp_path, [mirror])
    (card / "DSC0001.JPG").write_bytes(b"image")

    report = CopyEngine().run(job)
    message = result_message(report.results[0])

    assert "redundant backup incomplete" in message
    assert str(mirror) in message

    i18n.set_language("zh_CN")
    try:
        translated = i18n.translate_log(message)
        assert "冗余备份未完成" in translated
    finally:
        i18n.set_language("en")


def test_redundant_log_line_is_translated(tmp_path: Path) -> None:
    mirror = tmp_path / "backup-a"
    mirror.mkdir()
    job, card, _dest = build_job(tmp_path, [mirror])
    (card / "DSC0001.JPG").write_bytes(b"image")

    report = CopyEngine().run(job)
    start_lines = [
        line for line in report.logs if line.startswith("Redundant backups (")
    ]
    assert start_lines

    i18n.set_language("zh_CN")
    try:
        assert "冗余备份（并行写入）" in i18n.translate_log(start_lines[0])
    finally:
        i18n.set_language("en")


# ---------------------------------------------------------------------------
# Localisation of the redundant-backup user interface
# ---------------------------------------------------------------------------

REDUNDANT_UI_STRINGS = (
    # settings dialog
    "Redundant backup:",
    "Also write every copied file to the backup folders below",
    "Backup folders:",
    "Backup writing:",
    "Write all backup folders at the same time",
    "Write the backup folders one after another",
    "Choose a redundant backup folder",
    "Write a second copy of every file to one or more extra folders.",
    "Use this to keep a redundant copy on a second disk.",
    "Extra folders that receive the same files as the destination.",
    "Only available folders are used; a missing folder stops the copy.",
    "Choose whether the backup folders are written at the same time.",
    "Writing in parallel is faster; writing one after another is gentler on "
    "slow disks.",
    "Each copied file is also written to every backup folder, so a card ends "
    "up on more than one disk. A backup folder that is missing or not "
    "writable stops the copy before anything is written, and source files "
    "are only removed once every folder holds the file.",
    "Add at least one redundant backup folder.",
    # main window
    "Backup copies",
    "Not enabled",
    "No folder configured",
    # dialogs
    "Backup folders unavailable",
    "The redundant backup cannot start because no backup folder is configured. "
    "Add one in Settings or turn the redundant backup off.",
    "The redundant backup cannot start because at least one backup folder is "
    "unusable. Reconnect the disk, choose another folder, or turn the "
    "redundant backup off in Settings.",
    "same folder as the destination",
    "folder is not available",
    "folder is not writable",
    # values composed at runtime
    "/Volumes/A, /Volumes/B (at the same time)",
    "/Volumes/A (one after another)",
    "A redundant backup folder must differ from the destination: /Volumes/A",
)


@pytest.mark.parametrize("english", REDUNDANT_UI_STRINGS)
def test_redundant_ui_strings_are_translated(english: str) -> None:
    previous = i18n.get_language()
    i18n.set_language("zh_CN")
    try:
        translated = i18n.translate_text(english)
    finally:
        i18n.set_language(previous)

    assert translated != english
    assert _contains_cjk(translated)


def _contains_cjk(text: str) -> bool:
    return any("\u4e00" <= character <= "\u9fff" for character in text)


def _gui_app():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_settings_dialog_shows_the_redundant_backup_in_chinese(tmp_path: Path) -> None:
    """The feature's own controls must be localised, not only its log lines."""
    app = _gui_app()
    from PySide6.QtWidgets import QLabel

    previous = i18n.get_language()
    i18n.set_language("zh_CN")
    i18n.install(app)
    try:
        from cameracopy2.ui.settings_dialog import SettingsDialog

        mirror = tmp_path / "backup-a"
        mirror.mkdir()
        config = CameraCopyConfig(
            destination=str(tmp_path / "pictures"),
            redundantbackup=True,
            additionaldestinations=[str(mirror)],
            redundantwritemode="sequential",
        )
        dialog = SettingsDialog(config, [])
        app.processEvents()

        assert _contains_cjk(dialog.redundant_backup_checkbox.text())
        modes = [
            dialog.redundant_write_mode_combo.itemText(index)
            for index in range(dialog.redundant_write_mode_combo.count())
        ]
        assert modes and all(_contains_cjk(mode) for mode in modes)
        assert _contains_cjk(dialog.redundant_backup_checkbox.toolTip())
        assert _contains_cjk(dialog.redundant_folders_editor.toolTip())
        assert _contains_cjk(dialog.redundant_write_mode_combo.toolTip())

        labels = {label.text() for label in dialog.findChildren(QLabel)}
        for english in (
            "Redundant backup:",
            "Backup folders:",
            "Backup writing:",
            "Each copied file is also written to every backup folder, so a card ends "
            "up on more than one disk. A backup folder that is missing or not "
            "writable stops the copy before anything is written, and source files "
            "are only removed once every folder holds the file.",
        ):
            assert i18n.translate_text(english) in labels
            assert english not in labels

        dialog.close()
    finally:
        i18n.set_language(previous)


def test_main_window_redundant_summary_is_chinese(tmp_path: Path) -> None:
    app = _gui_app()
    from PySide6.QtWidgets import QLabel

    previous = i18n.get_language()
    i18n.set_language("zh_CN")
    i18n.install(app)
    try:
        from cameracopy2.ui.main_window import MainWindow

        window = MainWindow(config_path=tmp_path / "cameracopy.json")
        try:
            window.config = CameraCopyConfig(
                destination=str(tmp_path / "pictures"),
                redundantbackup=True,
                additionaldestinations=["/Volumes/Backup"],
                redundantwritemode="sequential",
            )
            window._update_summaries()
            window.show()
            app.processEvents()

            assert "备份副本：" in {label.text() for label in window.findChildren(QLabel)}
            summary = "/Volumes/Backup (one after another)"
            # the tooltip keeps the full value, so it is never elided
            assert window.redundant_summary_label.toolTip() == i18n.translate_text(summary)
            assert window.redundant_summary_label.text() == i18n.translate_text(summary)

            window.config = CameraCopyConfig(destination=str(tmp_path / "pictures"))
            window._update_summaries()
            assert window.redundant_summary_label.text() == i18n.translate_text("Not enabled")

            window.config = CameraCopyConfig(
                destination=str(tmp_path / "pictures"), redundantbackup=True
            )
            window._update_summaries()
            assert window.redundant_summary_label.text() == i18n.translate_text(
                "No folder configured"
            )
        finally:
            window.close()
    finally:
        i18n.set_language(previous)


def test_elided_label_translates_before_eliding() -> None:
    """Narrow labels must not fall back to English just because they elide."""
    app = _gui_app()
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFontMetrics

    from cameracopy2.ui.main_widgets import ElidedLabel

    english = "/Volumes/BackupDiskAlpha/Photos (one after another)"
    previous = i18n.get_language()
    i18n.install(app)
    try:
        label = ElidedLabel(english)
        metrics = QFontMetrics(label.font())

        i18n.set_language("zh_CN")
        translated = i18n.translate_text(english)
        label.resize(120, 20)
        label._apply_elide()
        # the widget elides the localised text, keeps the English source
        assert label.text() == metrics.elidedText(
            translated, Qt.TextElideMode.ElideRight, 120
        )
        assert label.property("_i18n_text") == english

        # wide enough for the localised value: it really is Chinese on screen
        label.resize(metrics.horizontalAdvance(translated) + 4, 20)
        label._apply_elide()
        assert label.text() == translated
        assert _contains_cjk(label.text())

        i18n.set_language("en")
        i18n.retranslate_all()
        assert label.text() == english
    finally:
        i18n.set_language(previous)
