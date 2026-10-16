from __future__ import annotations

import json
from dataclasses import asdict, fields
from datetime import datetime
from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox

from cameracopy2 import i18n
from cameracopy2.config_bundle import (
    BUNDLE_SCHEMA,
    BUNDLE_SCHEMA_VERSION,
    SettingsBundleError,
    build_settings_bundle,
    export_settings_file,
    load_settings_file,
    parse_settings_bundle,
)
from cameracopy2.models import CONFIG_VERSION, CameraCopyConfig


def _rich_config(tmp_path: Path) -> CameraCopyConfig:
    return CameraCopyConfig(
        source="DCIM",
        destination=str(tmp_path / "pictures"),
        redundantbackup=True,
        additionaldestinations=[str(tmp_path / "backup")],
        redundantwritemode="sequential",
        folderprefix="Trip",
        datetimestring="yyyy-MM-dd",
        folderpostfix="raw",
        foldertreemode="today_nested",
        renamefiles=True,
        minrating=3,
        collisionpolicy="overwrite",
        hashmethod="xxhash64",
        verificationmode="batch",
        reportexport=True,
        reportformats=["csv", "html"],
        theme="dark",
        language="zh_CN",
    )


# ---------------------------------------------------------------------------
# bundle structure
# ---------------------------------------------------------------------------
def test_bundle_envelope_describes_itself(tmp_path: Path) -> None:
    bundle = build_settings_bundle(_rich_config(tmp_path))
    assert bundle["schema"] == BUNDLE_SCHEMA
    assert bundle["schema_version"] == BUNDLE_SCHEMA_VERSION
    assert bundle["app"]["config_version"] == CONFIG_VERSION
    assert bundle["app"]["name"] == "CameraCopy"
    assert bundle["exported_at"]
    assert bundle["preserved"] == {"settings": {}, "extra": {}}
    # every config field is present, not just the non-default ones
    assert set(bundle["settings"]) == {f.name for f in fields(CameraCopyConfig)}


def test_round_trip_keeps_every_setting(tmp_path: Path) -> None:
    config = _rich_config(tmp_path)
    written = export_settings_file(config, tmp_path / "settings.json")
    assert written.name == "settings.json"
    loaded = load_settings_file(written)
    assert asdict(loaded.config) == asdict(config)


def test_filename_gets_the_json_suffix(tmp_path: Path) -> None:
    written = export_settings_file(CameraCopyConfig(), tmp_path / "no-suffix")
    assert written == tmp_path / "no-suffix.json"
    assert written.exists()


def test_legacy_reportformat_key_is_migrated_on_import() -> None:
    bundle = build_settings_bundle(CameraCopyConfig())
    bundle["settings"].pop("reportformats")
    bundle["settings"]["reportformat"] = "pdf"
    parsed = parse_settings_bundle(bundle)
    assert parsed.config.reportformats == ["pdf"]


def test_missing_version_defaults_to_current() -> None:
    bundle = build_settings_bundle(CameraCopyConfig())
    bundle["settings"].pop("version")
    assert parse_settings_bundle(bundle).config.version == CONFIG_VERSION


# ---------------------------------------------------------------------------
# forward compatibility: unknown data is preserved, never dropped
# ---------------------------------------------------------------------------
def test_future_settings_keys_survive_a_round_trip(tmp_path: Path) -> None:
    bundle = build_settings_bundle(CameraCopyConfig(destination="/tmp/p"))
    bundle["settings"]["futureflag"] = True
    bundle["settings"]["futurelist"] = ["a", "b"]
    source = tmp_path / "future.json"
    source.write_text(json.dumps(bundle), encoding="utf-8")

    parsed = load_settings_file(source)
    assert parsed.preserved["settings"] == {
        "futureflag": True,
        "futurelist": ["a", "b"],
    }
    assert "2 future setting(s) preserved" in parsed.describe()

    again = tmp_path / "again.json"
    export_settings_file(parsed.config, again, preserved=parsed.preserved)
    payload = json.loads(again.read_text(encoding="utf-8"))
    assert payload["settings"]["destination"] == "/tmp/p"
    assert payload["preserved"]["settings"]["futureflag"] is True
    assert payload["preserved"]["settings"]["futurelist"] == ["a", "b"]


def test_future_envelope_keys_are_preserved() -> None:
    bundle = build_settings_bundle(CameraCopyConfig())
    bundle["workspace"] = {"layout": "compact"}
    parsed = parse_settings_bundle(bundle)
    assert parsed.preserved["extra"] == {"workspace": {"layout": "compact"}}
    rebuilt = build_settings_bundle(parsed.config, preserved=parsed.preserved)
    assert "workspace" not in rebuilt  # kept in the preserved section, not re-raised
    assert rebuilt["preserved"]["extra"] == {"workspace": {"layout": "compact"}}


def test_invalid_settings_values_are_reported(tmp_path: Path) -> None:
    bundle = build_settings_bundle(CameraCopyConfig())
    bundle["settings"]["minrating"] = 9
    with pytest.raises(SettingsBundleError, match="minrating"):
        parse_settings_bundle(bundle)


def test_non_bundle_files_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(SettingsBundleError, match="must contain a JSON object"):
        parse_settings_bundle([])
    with pytest.raises(SettingsBundleError, match="Not a CameraCopy settings file"):
        parse_settings_bundle({"schema": "something.else"})
    with pytest.raises(SettingsBundleError, match="schema version"):
        parse_settings_bundle({"schema": BUNDLE_SCHEMA, "schema_version": 99})
    with pytest.raises(SettingsBundleError, match="missing its settings section"):
        parse_settings_bundle({"schema": BUNDLE_SCHEMA, "schema_version": 1})

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(SettingsBundleError, match="not valid JSON"):
        load_settings_file(broken)
    with pytest.raises(SettingsBundleError, match="Cannot read"):
        load_settings_file(tmp_path / "missing.json")


# ---------------------------------------------------------------------------
# settings dialog: export and import through the buttons
# ---------------------------------------------------------------------------
def test_settings_dialog_exports_and_imports(qapp, tmp_path: Path, monkeypatch) -> None:  # noqa: ARG001
    i18n.set_language("en")
    from cameracopy2.ui.settings_dialog import SettingsDialog

    original = _rich_config(tmp_path)
    dialog = SettingsDialog(original)

    saved = tmp_path / "my-settings"
    monkeypatch.setattr(
        "cameracopy2.ui.settings_dialog.QFileDialog.getSaveFileName",
        lambda *a, **k: (str(saved), ""),
    )
    monkeypatch.setattr(
        "cameracopy2.ui.settings_dialog.QMessageBox.information",
        lambda *a, **k: None,
    )
    dialog._export_settings_file()  # noqa: SLF001
    written = tmp_path / "my-settings.json"
    assert written.exists()

    # the dialog is moved to a different config, then the bundle is imported
    dialog._apply_config(CameraCopyConfig(destination="/tmp/unrelated"))  # noqa: SLF001
    assert dialog.destination_edit.text() == "/tmp/unrelated"
    tabs_before = dialog.tabs

    monkeypatch.setattr(
        "cameracopy2.ui.settings_dialog.QFileDialog.getOpenFileName",
        lambda *a, **k: (str(written), ""),
    )
    monkeypatch.setattr(
        "cameracopy2.ui.settings_dialog.QMessageBox.question",
        lambda *a, **k: QMessageBox.StandardButton.Yes,
    )
    dialog._import_settings_file()  # noqa: SLF001

    assert dialog.tabs is not tabs_before, "tab pages must be rebuilt on import"
    assert dialog.destination_edit.text() == str(tmp_path / "pictures")
    assert dialog.prefix_edit.text() == "Trip"
    assert dialog.config().reportformats == ["csv", "html"]
    assert dialog.config().foldertreemode == "today_nested"
    dialog.close()
    qapp.processEvents()
    i18n.set_language("zh_CN")


def test_settings_dialog_reports_a_broken_import(qapp, tmp_path: Path, monkeypatch) -> None:  # noqa: ARG001
    i18n.set_language("en")
    from cameracopy2.ui.settings_dialog import SettingsDialog

    broken = tmp_path / "broken.json"
    broken.write_text('{"schema": "nope"}', encoding="utf-8")
    errors: list[str] = []
    monkeypatch.setattr(
        "cameracopy2.ui.settings_dialog.QFileDialog.getOpenFileName",
        lambda *a, **k: (str(broken), ""),
    )
    monkeypatch.setattr(
        "cameracopy2.ui.settings_dialog.QMessageBox.critical",
        lambda *a, **k: errors.append(str(a[2])),
    )
    dialog = SettingsDialog(CameraCopyConfig(destination="/tmp/keep"))
    dialog._import_settings_file()  # noqa: SLF001
    assert errors and "Not a CameraCopy settings file" in errors[0]
    assert dialog.destination_edit.text() == "/tmp/keep", "dialog must stay unchanged"
    dialog.close()
    qapp.processEvents()
    i18n.set_language("zh_CN")


# ---------------------------------------------------------------------------
# regression: manual report export must use reportformats, not reportformat
# ---------------------------------------------------------------------------
def test_manual_report_export_uses_configured_formats(qapp, tmp_path: Path, monkeypatch) -> None:  # noqa: ARG001
    i18n.set_language("en")
    from cameracopy2.models import CopyJob, CopyReport, VolumeInfo
    from cameracopy2.ui.copy_progress_dialog import CopyProgressDialog

    suggested: list[str] = []

    def fake_save(*args, **kwargs):  # noqa: ARG001
        suggested.append(args[2])
        return args[2], ""

    monkeypatch.setattr(
        "cameracopy2.ui.copy_progress_dialog.QFileDialog.getSaveFileName", fake_save
    )
    # modal message boxes would block the test
    monkeypatch.setattr(
        "cameracopy2.ui.copy_progress_dialog.QMessageBox.information",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "cameracopy2.ui.copy_progress_dialog.QMessageBox.warning",
        lambda *a, **k: None,
    )
    config = CameraCopyConfig(
        destination=str(tmp_path / "pictures"),
        reportformats=["html", "pdf"],
        reportdirectory=str(tmp_path / "reports"),
    )
    job = CopyJob(
        primary=VolumeInfo(id="card", display_name="Card", mount_path=tmp_path / "card"),
        secondary=None,
        config=config,
    )
    dialog = CopyProgressDialog(job)
    dialog.report = CopyReport(started_at=datetime.now())
    dialog.export_report_dialog()
    assert suggested, "export dialog should have suggested a file name"
    assert suggested[0].endswith(".html")
    assert "Report export failed" not in dialog.log_view.toPlainText()
    dialog.close()
    qapp.processEvents()
    i18n.set_language("zh_CN")
