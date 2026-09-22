"""Tests for renaming copied files from metadata."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import pytest

from cameracopy2.config import config_from_dict, validate_file_stem
from cameracopy2.core.copy_engine import CopyEngine
from cameracopy2.core.naming import (
    RENAME_DATE_SOURCE_LABELS,
    RENAME_DATE_SOURCE_ORDER,
    build_destination_file,
    build_renamed_file_name,
    effective_rename_pattern,
    expand_rename_pattern,
    rename_date_source_label,
)
from cameracopy2.models import CameraCopyConfig, CopyJob, VolumeInfo

RENAME_DATE = datetime(2026, 1, 1, 20, 0, 0)


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
        "datetimestring": "",
    }
    values.update(overrides)
    return CameraCopyConfig(**values)  # type: ignore[arg-type]


def card_with(source: Path, names: tuple[str, ...] = ("DJI0001.MP4", "DJI0002.MP4")) -> Path:
    source.mkdir(parents=True, exist_ok=True)
    for index, name in enumerate(names):
        (source / name).write_bytes(f"video-{index}".encode())
        # 2026-01-02 03:04:05 local time, so folder and mtime dates are predictable.
        stamp = datetime(2026, 1, 2, 3, 4, 5).timestamp()
        os.utime(source / name, ns=(int(stamp * 1e9), int(stamp * 1e9)))
    return source


# ---------------------------------------------------------------------------
# Pattern expansion
# ---------------------------------------------------------------------------


def test_pattern_with_name_token_keeps_the_camera_name() -> None:
    config = make_config(
        Path("/tmp/pics"),
        renamefiles=True,
        renamefiledatestring="yyyyMMddHHmm",
        renamefilepattern="{date}-{name}",
    )
    name = build_renamed_file_name(config, Path("/card/DJI0001.MP4"), RENAME_DATE)
    assert name == "202601012000-DJI0001.MP4"


def test_star_is_an_alias_for_the_original_stem() -> None:
    config = make_config(
        Path("/tmp/pics"),
        renamefiles=True,
        renamefiledatestring="yyyyMMddHHmm",
        renamefilepattern="{date}-*",
    )
    starred = build_renamed_file_name(config, Path("/card/DJI0001.MP4"), RENAME_DATE)
    tokenised = build_renamed_file_name(
        config,
        Path("/card/DJI0001.MP4"),
        RENAME_DATE,
    ) if False else expand_rename_pattern("{date}-{name}", config, Path("/card/DJI0001.MP4"), RENAME_DATE)
    assert starred == f"{tokenised}.MP4"


def test_namefull_keeps_the_extension_and_is_not_doubled() -> None:
    config = make_config(
        Path("/tmp/pics"), renamefiles=True, renamefilepattern="backup-{namefull}"
    )
    assert (
        build_renamed_file_name(config, Path("/card/DJI0001.MP4"), RENAME_DATE)
        == "backup-DJI0001.MP4"
    )
    config = make_config(
        Path("/tmp/pics"), renamefiles=True, renamefilepattern="{namefull}"
    )
    assert (
        build_renamed_file_name(config, Path("/card/DJI0001.MP4"), RENAME_DATE)
        == "DJI0001.MP4"
    )


def test_simple_date_tokens_expand_without_a_date_format() -> None:
    config = make_config(
        Path("/tmp/pics"),
        renamefiles=True,
        renamefiledatestring="",
        renamefilepattern="{yyyy}{MM}{dd}_{HH}{mm}{ss}-{name}",
    )
    assert (
        build_renamed_file_name(config, Path("/card/DJI0001.MP4"), RENAME_DATE)
        == "20260101_200000-DJI0001.MP4"
    )


def test_empty_pattern_expansion_falls_back_to_the_camera_name() -> None:
    config = make_config(
        Path("/tmp/pics"),
        renamefiles=True,
        renamefileprefix="",
        renamefilepostfix="",
        renamefiledatestring="",
        renamefilepattern="{prefix}{date}{postfix}",
    )
    assert (
        build_renamed_file_name(config, Path("/card/DJI0001.MP4"), RENAME_DATE)
        == "DJI0001.MP4"
    )


def test_unknown_token_raises_instead_of_landing_in_the_name() -> None:
    config = make_config(Path("/tmp/pics"), renamefiles=True, renamefilepattern="{dtae}")
    with pytest.raises(ValueError, match="Unknown rename token \\{dtae\\}"):
        build_renamed_file_name(config, Path("/card/DJI0001.MP4"), RENAME_DATE)


def test_invalid_characters_in_the_stem_are_rejected() -> None:
    config = make_config(Path("/tmp/pics"), renamefiles=True, renamefilepattern="a<b")
    with pytest.raises(ValueError, match="Invalid destination file name"):
        build_renamed_file_name(config, Path("/card/DJI0001.MP4"), RENAME_DATE)


def test_validate_file_stem_mirrors_windows_rules() -> None:
    assert validate_file_stem("IMG_0001") is None
    assert validate_file_stem("IMG 0001") is None
    assert validate_file_stem("IMG:0001") is not None
    assert validate_file_stem("IMG_0001.") is not None
    assert validate_file_stem("CON") is not None


def test_effective_pattern_defaults_to_prefix_date_postfix() -> None:
    config = make_config(Path("/tmp/pics"), renamefileprefix="A", renamefilepostfix="B")
    assert effective_rename_pattern(config) == "{prefix}{date}{postfix}"
    config = make_config(Path("/tmp/pics"), renamefilepattern="  {date}-{name}  ")
    assert effective_rename_pattern(config) == "{date}-{name}"


def test_rename_date_source_labels_cover_every_source() -> None:
    assert set(RENAME_DATE_SOURCE_ORDER) == set(RENAME_DATE_SOURCE_LABELS)
    assert rename_date_source_label("same_as_folder") == "Same as folder date"
    assert rename_date_source_label("") == ""


# ---------------------------------------------------------------------------
# Destination path composition
# ---------------------------------------------------------------------------


def test_destination_file_combines_folder_date_and_rename_date(tmp_path: Path) -> None:
    config = make_config(
        tmp_path,
        datetimestring="yyyy-MM-dd",
        renamefiles=True,
        renamefiledatestring="yyyyMMdd_HHmmss",
        renamefilepattern="{date}-{name}",
    )
    destination = build_destination_file(
        config,
        Path("/card/DJI0001.MP4"),
        datetime(2026, 1, 2, 3, 4, 5),
        RENAME_DATE,
    )
    assert destination == tmp_path / "2026-01-02" / "20260101_200000-DJI0001.MP4"


def test_destination_file_keeps_the_camera_name_without_a_rename_date(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path, datetimestring="yyyy-MM-dd", renamefiles=True)
    destination = build_destination_file(
        config, Path("/card/DJI0001.MP4"), datetime(2026, 1, 2, 3, 4, 5), None
    )
    assert destination == tmp_path / "2026-01-02" / "DJI0001.MP4"


# ---------------------------------------------------------------------------
# Config persistence
# ---------------------------------------------------------------------------


def test_rename_settings_round_trip() -> None:
    config = make_config(
        Path("/tmp/pics"),
        renamefiles=True,
        renamefileprefix="IMG_",
        renamefiledatestring="yyyyMMdd",
        renamefilepostfix="_edit",
        renamefilepattern="{date}_{name}",
        renamefiledatesource="exif_create_date",
    )
    restored = config_from_dict(config_to_plain_dict(config))
    assert restored.renamefiles is True
    assert restored.renamefileprefix == "IMG_"
    assert restored.renamefiledatestring == "yyyyMMdd"
    assert restored.renamefilepostfix == "_edit"
    assert restored.renamefilepattern == "{date}_{name}"
    assert restored.renamefiledatesource == "exif_create_date"


def test_unknown_rename_date_source_is_rejected() -> None:
    config = make_config(Path("/tmp/pics"))
    data = config_to_plain_dict(config)
    data["renamefiledatesource"] = "bogus_source"
    with pytest.raises(Exception):  # noqa: B017, PT011
        config_from_dict(data)


def config_to_plain_dict(config: CameraCopyConfig) -> dict:
    """Plain-dict snapshot of the config for round-trip tests."""
    from dataclasses import asdict

    return asdict(config)


# ---------------------------------------------------------------------------
# Engine integration
# ---------------------------------------------------------------------------


def test_engine_renames_files_from_the_file_mtime(tmp_path: Path) -> None:
    card = card_with(tmp_path / "card")
    dest = tmp_path / "pictures"
    config = make_config(
        dest,
        renamefiles=True,
        renamefiledatesource="file_mtime",
        renamefiledatestring="yyyyMMdd_HHmmss",
        renamefilepattern="{date}-{name}",
    )
    report = CopyEngine().run(
        CopyJob(primary=make_volume(card), secondary=None, config=config)
    )

    assert not report.has_failures
    copied = sorted(path.name for path in dest.iterdir())
    assert copied == [
        "20260102_030405-DJI0001.MP4",
        "20260102_030405-DJI0002.MP4",
    ]


def test_engine_keeps_names_while_renaming_is_off(tmp_path: Path) -> None:
    card = card_with(tmp_path / "card")
    dest = tmp_path / "pictures"
    config = make_config(dest, renamefiles=False)
    CopyEngine().run(CopyJob(primary=make_volume(card), secondary=None, config=config))

    assert sorted(path.name for path in dest.iterdir()) == [
        "DJI0001.MP4",
        "DJI0002.MP4",
    ]


def test_engine_renames_into_the_dated_folder(tmp_path: Path) -> None:
    card = card_with(tmp_path / "card")
    dest = tmp_path / "pictures"
    config = make_config(
        dest,
        datetimestring="yyyy-MM-dd",
        renamefiles=True,
        renamefiledatesource="same_as_folder",
        renamefiledatestring="yyyyMMdd",
        renamefilepattern="{date}_{name}",
    )
    report = CopyEngine().run(
        CopyJob(primary=make_volume(card), secondary=None, config=config)
    )

    assert not report.has_failures
    folder = dest / "2026-01-02"
    assert sorted(path.name for path in folder.iterdir()) == [
        "20260102_DJI0001.MP4",
        "20260102_DJI0002.MP4",
    ]


def test_engine_reports_an_invalid_pattern_as_a_failure(tmp_path: Path) -> None:
    card = card_with(tmp_path / "card")
    dest = tmp_path / "pictures"
    config = make_config(
        dest,
        renamefiles=True,
        renamefiledatesource="file_mtime",
        renamefilepattern="{dtae}-{name}",
    )
    report = CopyEngine().run(
        CopyJob(primary=make_volume(card), secondary=None, config=config)
    )

    assert report.has_failures
    written = list(dest.iterdir()) if dest.exists() else []
    assert not written
    assert any("Unknown rename token" in failure.error for failure in report.failures)


def test_engine_falls_back_to_the_camera_name_for_an_empty_result(
    tmp_path: Path,
) -> None:
    card = card_with(tmp_path / "card")
    dest = tmp_path / "pictures"
    config = make_config(
        dest,
        renamefiles=True,
        renamefiledatesource="file_mtime",
        renamefilepattern="{prefix}",
        renamefileprefix="",
    )
    report = CopyEngine().run(
        CopyJob(primary=make_volume(card), secondary=None, config=config)
    )

    assert not report.has_failures
    assert sorted(path.name for path in dest.iterdir()) == [
        "DJI0001.MP4",
        "DJI0002.MP4",
    ]


# ---------------------------------------------------------------------------
# Chinese rendering of the new strings
# ---------------------------------------------------------------------------


def test_rename_strings_are_translated(monkeypatch: pytest.MonkeyPatch) -> None:
    from cameracopy2 import i18n

    monkeypatch.setattr(i18n, "_current_language", "zh_CN")
    assert i18n.translate("Rename files from metadata") == "根据元数据重命名文件"
    assert i18n.translate("File name pattern:") == "文件名通配模式："
    assert i18n.translate("Same as folder date") == "与文件夹日期相同"
    assert i18n.translate("File modified time") == "文件修改时间"
    assert i18n.translate(
        "Working with the pattern replaces prefix and postfix. Example: "
        "{date}-{name} turns DJI0001.MP4 into 20260101-DJI0001.MP4."
    ).startswith("填写通配模式后")
    assert (
        i18n.translate_log(
            "Rename files: {date}-{name} (date from Same as folder date)"
        )
        == "重命名文件：{date}-{name}（日期来自 与文件夹日期相同）"
    )
    assert i18n.translate_log(
        "Unknown rename token {dtae}. Supported tokens: "
        + ", ".join(f"{{{name}}}" for name in (
            "prefix", "date", "name", "postfix", "ext", "namefull",
            "yyyy", "yy", "MM", "dd", "HH", "mm", "ss",
        ))
        + " and *."
    ).startswith("未知的重命名占位符")


# ---------------------------------------------------------------------------
# GUI wiring
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


def test_settings_dialog_collects_the_rename_settings(
    tmp_path: Path, gui_app, english_ui
) -> None:
    from cameracopy2.ui.settings_dialog import SettingsDialog

    config = make_config(
        tmp_path,
        renamefileprefix="IMG_",
        renamefiledatestring="yyyyMMdd",
        renamefilepostfix="_edit",
        renamefilepattern="{date}_{name}",
        renamefiledatesource="exif_create_date",
    )
    dialog = SettingsDialog(config, volumes=[])
    try:
        tab_titles = [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())]
        assert "Naming and metadata" in tab_titles
        assert "Folder naming" not in tab_titles
        assert "Metadata" not in tab_titles

        assert dialog.rename_prefix_edit.text() == "IMG_"
        assert dialog.rename_pattern_edit.text() == "{date}_{name}"
        assert dialog.rename_date_source_combo.currentData() == "exif_create_date"

        dialog.rename_prefix_edit.setText("VID_")
        dialog.rename_pattern_edit.setText("{date}-*")
        dialog.rename_date_source_combo.setCurrentIndex(
            RENAME_DATE_SOURCE_ORDER.index("file_mtime")
        )
        updated = dialog._config_from_controls()  # noqa: SLF001
        assert updated.renamefileprefix == "VID_"
        assert updated.renamefilepattern == "{date}-*"
        assert updated.renamefiledatesource == "file_mtime"
    finally:
        dialog.close()
        gui_app.processEvents()


def test_settings_preview_mentions_the_rename_example(
    tmp_path: Path, gui_app, english_ui
) -> None:
    from cameracopy2.ui.settings_dialog import SettingsDialog

    config = make_config(
        tmp_path,
        renamefiles=False,
        renamefiledatestring="yyyyMMdd",
        renamefilepattern="{date}-{name}",
    )
    dialog = SettingsDialog(config, volumes=[])
    try:
        preview = dialog.preview_label.text()
        assert "Rename example (when enabled):" in preview
        assert "-DSC0001.ARW" in preview
    finally:
        dialog.close()
        gui_app.processEvents()


def test_settings_preview_reports_an_invalid_pattern(
    tmp_path: Path, gui_app, english_ui
) -> None:
    from cameracopy2.ui.settings_dialog import SettingsDialog

    config = make_config(tmp_path, renamefilepattern="{dtae}")
    dialog = SettingsDialog(config, volumes=[])
    try:
        assert "unavailable" in dialog.preview_label.text()
    finally:
        dialog.close()
        gui_app.processEvents()


def test_main_window_checkbox_follows_and_drives_the_config(
    tmp_path: Path, gui_app, english_ui
) -> None:
    from cameracopy2.ui.main_window import MainWindow

    config = make_config(tmp_path, renamefiles=False)
    window = MainWindow(
        config_path=tmp_path / "cameracopy.json",
        config=config,
    )
    try:
        assert not window.rename_checkbox.isChecked()

        window.rename_checkbox.setChecked(True)
        window._set_copy_setup_enabled(False)  # noqa: SLF001
        assert not window.rename_checkbox.isEnabled()
        window._set_copy_setup_enabled(True)  # noqa: SLF001
        assert window.rename_checkbox.isEnabled()
    finally:
        window.close()
        gui_app.processEvents()
