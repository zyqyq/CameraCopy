"""Tests for the destination folder tree modes (capture date / today layers)."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import pytest

from cameracopy2.config import CONFIG_VERSION, UnsupportedConfigError, config_from_dict
from cameracopy2.core.copy_engine import CopyEngine
from cameracopy2.core.naming import (
    FOLDER_TREE_MODE_LABELS,
    FOLDER_TREE_MODE_ORDER,
    build_destination_directory,
    build_destination_file,
    folder_tree_mode,
    folder_tree_mode_label,
    preview_destination,
)
from cameracopy2.models import CameraCopyConfig, CopyJob, VolumeInfo

CAPTURE_DATE = datetime(2026, 1, 2, 3, 4, 5)
TASK_DATE = datetime(2026, 9, 22, 14, 0, 0)


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
        "includedfiles": ["*.MP4"],
        "datetimestring": "yyyy-MM-dd",
    }
    values.update(overrides)
    return CameraCopyConfig(**values)  # type: ignore[arg-type]


def card_with(source: Path, names: tuple[str, ...] = ("DJI0001.MP4", "DJI0002.MP4")) -> Path:
    source.mkdir(parents=True, exist_ok=True)
    for index, name in enumerate(names):
        (source / name).write_bytes(f"video-{index}".encode())
        # 2026-01-02 03:04:05 local time, so capture-date folders are predictable.
        stamp = CAPTURE_DATE.timestamp()
        os.utime(source / name, ns=(int(stamp * 1e9), int(stamp * 1e9)))
    return source


# ---------------------------------------------------------------------------
# Folder tree mode plumbing
# ---------------------------------------------------------------------------


def test_every_mode_has_a_label_and_order_matches_labels() -> None:
    assert set(FOLDER_TREE_MODE_LABELS) == set(FOLDER_TREE_MODE_ORDER)
    assert folder_tree_mode_label("today_nested") == "Today folder / capture date"
    assert folder_tree_mode_label("nonsense") == "nonsense"


def test_unknown_configured_mode_falls_back_to_capture_date(tmp_path: Path) -> None:
    config = make_config(tmp_path, foldertreemode="somehow-corrupted")
    assert folder_tree_mode(config) == "capture_date"


def test_config_round_trip_accepts_every_mode(tmp_path: Path) -> None:
    for mode in FOLDER_TREE_MODE_ORDER:
        config = config_from_dict(
            {
                "version": CONFIG_VERSION,
                "destination": str(tmp_path),
                "datetimestring": "yyyy-MM-dd",
                "foldertreemode": mode,
            }
        )
        assert config.foldertreemode == mode


def test_config_rejects_an_unknown_mode(tmp_path: Path) -> None:
    with pytest.raises(UnsupportedConfigError):
        config_from_dict(
            {
                "version": CONFIG_VERSION,
                "destination": str(tmp_path),
                "foldertreemode": "flat",
            }
        )


# ---------------------------------------------------------------------------
# build_destination_directory
# ---------------------------------------------------------------------------


def test_capture_date_mode_keeps_the_original_single_folder(tmp_path: Path) -> None:
    config = make_config(tmp_path, folderprefix="IMG_", folderpostfix="_raw")
    directory = build_destination_directory(config, CAPTURE_DATE, TASK_DATE)
    assert directory == tmp_path / "IMG_2026-01-02_raw"


def test_today_nested_mode_wraps_the_capture_date_folder(tmp_path: Path) -> None:
    config = make_config(
        tmp_path, folderprefix="IMG_", folderpostfix="_raw", foldertreemode="today_nested"
    )
    directory = build_destination_directory(config, CAPTURE_DATE, TASK_DATE)
    assert directory == tmp_path / "2026-09-22" / "IMG_2026-01-02_raw"


def test_today_nested_mode_ignores_prefix_and_postfix_for_the_today_layer(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path, folderprefix="IMG_", foldertreemode="today_nested")
    directory = build_destination_directory(config, CAPTURE_DATE, TASK_DATE)
    assert directory == tmp_path / "2026-09-22" / "IMG_2026-01-02"


def test_today_nested_mode_falls_back_to_iso_date_without_a_date_format(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path, datetimestring="", foldertreemode="today_nested")
    directory = build_destination_directory(config, CAPTURE_DATE, TASK_DATE)
    assert directory == tmp_path / "2026-09-22"


def test_today_only_mode_builds_one_task_folder(tmp_path: Path) -> None:
    config = make_config(
        tmp_path, folderprefix="IMG_", folderpostfix="_day", foldertreemode="today_only"
    )
    directory = build_destination_directory(config, CAPTURE_DATE, TASK_DATE)
    assert directory == tmp_path / "IMG_2026-09-22_day"


def test_today_only_mode_ignores_the_capture_date(tmp_path: Path) -> None:
    config = make_config(tmp_path, foldertreemode="today_only")
    morning = build_destination_directory(
        config, datetime(2026, 1, 1, 8, 0, 0), TASK_DATE
    )
    evening = build_destination_directory(
        config, datetime(2026, 1, 2, 23, 0, 0), TASK_DATE
    )
    assert morning == evening == tmp_path / "2026-09-22"


def test_today_only_mode_without_a_date_format_keeps_prefix_and_postfix(
    tmp_path: Path,
) -> None:
    config = make_config(
        tmp_path, datetimestring="", folderpostfix="_import", foldertreemode="today_only"
    )
    directory = build_destination_directory(config, CAPTURE_DATE, TASK_DATE)
    assert directory == tmp_path / "_import"


def test_empty_inner_folder_still_keeps_the_today_layer(tmp_path: Path) -> None:
    config = make_config(tmp_path, datetimestring="", foldertreemode="today_nested")
    directory = build_destination_directory(config, CAPTURE_DATE, TASK_DATE)
    assert directory == tmp_path / "2026-09-22"


def test_invalid_folder_component_still_raises(tmp_path: Path) -> None:
    config = make_config(tmp_path, folderprefix="bad/name", foldertreemode="today_nested")
    with pytest.raises(ValueError, match="Invalid destination folder name"):
        build_destination_directory(config, CAPTURE_DATE, TASK_DATE)


def test_build_destination_file_passes_the_task_time_through(tmp_path: Path) -> None:
    config = make_config(tmp_path, foldertreemode="today_nested")
    destination = build_destination_file(
        config, Path("/card/DJI0001.MP4"), CAPTURE_DATE, None, TASK_DATE
    )
    assert destination == tmp_path / "2026-09-22" / "2026-01-02" / "DJI0001.MP4"


def test_preview_destination_reflects_the_folder_tree_mode(tmp_path: Path) -> None:
    config = make_config(tmp_path, foldertreemode="today_only")
    preview = preview_destination(
        config, timestamp=CAPTURE_DATE, task_time=TASK_DATE
    )
    assert preview == str(tmp_path / "2026-09-22" / "DSC0001.ARW")


# ---------------------------------------------------------------------------
# Engine end to end
# ---------------------------------------------------------------------------


def test_engine_today_only_puts_every_file_in_one_folder(tmp_path: Path) -> None:
    card = card_with(tmp_path / "card")
    dest = tmp_path / "pictures"
    config = make_config(dest, foldertreemode="today_only")
    before = datetime.now().strftime("%Y-%m-%d")
    report = CopyEngine().run(
        CopyJob(primary=make_volume(card), secondary=None, config=config)
    )
    after = datetime.now().strftime("%Y-%m-%d")

    assert not report.has_failures
    folders = [path for path in dest.iterdir() if path.is_dir()]
    assert len(folders) == 1
    assert folders[0].name in {before, after}
    assert sorted(path.name for path in folders[0].iterdir()) == [
        "DJI0001.MP4",
        "DJI0002.MP4",
    ]
    assert "Folder tree: Today folder only" in report.logs


def test_engine_today_nested_wraps_capture_date_folders(tmp_path: Path) -> None:
    card = card_with(tmp_path / "card")
    dest = tmp_path / "pictures"
    config = make_config(dest, foldertreemode="today_nested")
    report = CopyEngine().run(
        CopyJob(primary=make_volume(card), secondary=None, config=config)
    )

    assert not report.has_failures
    folders = [path for path in dest.iterdir() if path.is_dir()]
    assert len(folders) == 1
    capture_folder = folders[0] / "2026-01-02"
    assert sorted(path.name for path in capture_folder.iterdir()) == [
        "DJI0001.MP4",
        "DJI0002.MP4",
    ]
    assert "Folder tree: Today folder / capture date" in report.logs


def test_engine_capture_date_mode_logs_no_folder_tree_line(tmp_path: Path) -> None:
    card = card_with(tmp_path / "card")
    dest = tmp_path / "pictures"
    config = make_config(dest)
    report = CopyEngine().run(
        CopyJob(primary=make_volume(card), secondary=None, config=config)
    )

    assert not report.has_failures
    assert not any(line.startswith("Folder tree:") for line in report.logs)
    assert (dest / "2026-01-02" / "DJI0001.MP4").exists()


def test_engine_today_only_rename_date_follows_the_task_date(tmp_path: Path) -> None:
    card = card_with(tmp_path / "card")
    dest = tmp_path / "pictures"
    config = make_config(
        dest,
        foldertreemode="today_only",
        renamefiles=True,
        renamefiledatesource="same_as_folder",
        renamefiledatestring="yyyyMMdd",
        renamefilepattern="{date}-{name}",
    )
    before = datetime.now().strftime("%Y%m%d")
    report = CopyEngine().run(
        CopyJob(primary=make_volume(card), secondary=None, config=config)
    )
    after = datetime.now().strftime("%Y%m%d")

    assert not report.has_failures
    folders = [path for path in dest.iterdir() if path.is_dir()]
    assert len(folders) == 1
    folder_date = datetime.strptime(folders[0].name, "%Y-%m-%d").strftime("%Y%m%d")
    assert folder_date in {before, after}
    assert sorted(path.name for path in folders[0].iterdir()) == [
        f"{folder_date}-DJI0001.MP4",
        f"{folder_date}-DJI0002.MP4",
    ]


# ---------------------------------------------------------------------------
# Settings dialog
# ---------------------------------------------------------------------------


@pytest.fixture()
def gui_app():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def english_ui():
    from cameracopy2 import i18n

    previous = i18n.get_language()
    i18n.set_language("en")
    try:
        yield
    finally:
        i18n.set_language(previous)


def test_settings_dialog_collects_the_folder_tree_mode(
    tmp_path: Path, gui_app, english_ui
) -> None:
    from cameracopy2.ui.settings_dialog import SettingsDialog

    config = make_config(tmp_path, foldertreemode="today_nested")
    dialog = SettingsDialog(config, volumes=[])
    try:
        assert dialog.folder_tree_combo.currentData() == "today_nested"

        dialog.folder_tree_combo.setCurrentIndex(
            FOLDER_TREE_MODE_ORDER.index("today_only")
        )
        updated = dialog._config_from_controls()  # noqa: SLF001
        assert updated.foldertreemode == "today_only"
    finally:
        dialog.close()
        gui_app.processEvents()


def test_settings_preview_shows_the_today_layer(
    tmp_path: Path, gui_app, english_ui
) -> None:
    from cameracopy2.ui.settings_dialog import SettingsDialog

    config = make_config(tmp_path, foldertreemode="today_nested")
    dialog = SettingsDialog(config, volumes=[])
    try:
        preview = dialog.preview_label.text()
        destination_line = next(
            line for line in preview.splitlines() if "Destination example:" in line
        )
        # today layer / capture-date layer / file
        assert destination_line.count("/") >= 3
        assert "/2026" in destination_line
    finally:
        dialog.close()
        gui_app.processEvents()


def test_chinese_ui_translates_the_folder_tree_strings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cameracopy2 import i18n

    monkeypatch.setattr(i18n, "_current_language", "zh_CN")
    assert i18n.translate("Folder tree:") == "文件夹层级："
    assert i18n.translate("Capture date only") == "仅拍摄日期"
    assert i18n.translate("Today folder / capture date") == "当前日期/拍摄日期"
    assert i18n.translate("Today folder only") == "仅当前日期"
    assert (
        i18n.translate_log("Folder tree: Today folder / capture date")
        == "文件夹层级：当前日期/拍摄日期"
    )
    assert (
        i18n.translate_log("Folder tree: Today folder only") == "文件夹层级：仅当前日期"
    )
