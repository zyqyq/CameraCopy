from __future__ import annotations

import csv
import os
from datetime import datetime
from pathlib import Path

import pytest

from cameracopy2 import i18n
from cameracopy2.config import UnsupportedConfigError, config_from_dict
from cameracopy2.core.report_export import (
    REPORT_FIELDS,
    ReportExportOptions,
    build_export_path,
    export_copy_report,
    report_rows,
)
from cameracopy2.models import (
    DEFAULT_REPORT_FIELDS,
    CameraCopyConfig,
    CopyJob,
    CopyReport,
    FileCopyResult,
    ReplicaResult,
    VolumeInfo,
)

_ALL_FIELD_KEYS = [key for key, _header in REPORT_FIELDS]


@pytest.fixture(autouse=True)
def _restore_language():
    language = i18n.get_language()
    yield
    i18n.set_language(language)


def _make_report() -> CopyReport:
    report = CopyReport(
        started_at=datetime(2026, 9, 22, 13, 45, 0),
        finished_at=datetime(2026, 9, 22, 13, 45, 12),
        hash_method="xxhash64",
        verification_mode="batch",
    )
    report.add_result(
        FileCopyResult(
            source=Path("/card/DCIM/DSC00001.NEF"),
            destination=Path("/pictures/2026-09-22/DSC00001.NEF"),
            action="copied",
            copy_mode="copied",
            hash_ok=True,
            rating=4,
            timestamp=datetime(2026, 9, 20, 10, 30, 0),
            size_bytes=12_345,
            bytes_copied=12_345,
            replicas=[
                ReplicaResult(
                    root=Path("/backup"),
                    action="copied",
                    copy_mode="copied",
                    bytes_copied=12_345,
                )
            ],
        )
    )
    report.add_result(
        FileCopyResult(
            source=Path("/card/DCIM/broken, \"first\".NEF"),
            destination=None,
            action="failed",
            hash_ok=False,
            size_bytes=1_000,
            bytes_copied=0,
            error="destination is not writable",
        )
    )
    report.add_result(
        FileCopyResult(
            source=Path("/card/DCIM/DSC00003.JPG"),
            destination=Path("/pictures/2026-09-22/DSC00003.JPG"),
            action="skipped",
            reason="copy cancelled",
            size_bytes=500,
        )
    )
    return report


# ---------------------------------------------------------------------------
# ReportExportOptions
# ---------------------------------------------------------------------------


def test_options_reject_unknown_format() -> None:
    with pytest.raises(ValueError, match="Unsupported report format"):
        ReportExportOptions(file_format="xlsx")


def test_options_reject_unknown_fields() -> None:
    with pytest.raises(ValueError, match="Unknown report field"):
        ReportExportOptions(fields=["source", "not_a_field"])


def test_options_orders_fields_canonically_and_dedups() -> None:
    options = ReportExportOptions(fields=["rating", "source", "rating"])
    assert options.fields == ["source", "rating"]


def test_options_empty_fields_fall_back_to_defaults() -> None:
    options = ReportExportOptions(fields=[])
    assert options.fields == list(DEFAULT_REPORT_FIELDS)


def test_options_format_is_lowercased() -> None:
    assert ReportExportOptions(file_format="PDF").file_format == "pdf"


# ---------------------------------------------------------------------------
# Table rows
# ---------------------------------------------------------------------------


def test_rows_use_english_headers_when_language_is_english() -> None:
    i18n.set_language("en")
    rows = report_rows(_make_report(), list(DEFAULT_REPORT_FIELDS))
    headers = rows[0]
    assert "Source path" in headers
    assert "Destination path" in headers
    assert "Verification result" in headers
    assert len(rows) == 4  # header + three files


def test_rows_use_chinese_headers_when_language_is_chinese() -> None:
    i18n.set_language("zh_CN")
    rows = report_rows(_make_report(), list(DEFAULT_REPORT_FIELDS))
    assert rows[0][0] == "源路径"
    assert "校验结果" in rows[0]
    assert rows[1][0] == "/card/DCIM/DSC00001.NEF"


def test_rows_status_and_verification_labels_follow_language() -> None:
    i18n.set_language("zh_CN")
    rows = report_rows(_make_report(), ["status", "verification", "backups"])
    assert rows[1] == ["已复制", "已通过", "备份正常（1/1）"]
    assert rows[2] == ["失败", "哈希不一致", ""]
    assert rows[3] == ["已跳过", "未校验", ""]


def test_rows_timestamp_and_rating_columns() -> None:
    i18n.set_language("en")
    rows = report_rows(_make_report(), ["timestamp", "rating"])
    # canonical column order puts Rating before Captured timestamp
    assert rows[0] == ["Rating", "Captured timestamp"]
    assert rows[1] == ["4", "2026-09-20 10:30:00"]
    assert rows[2] == ["", ""]


def test_rows_backup_status_incomplete() -> None:
    i18n.set_language("en")
    report = _make_report()
    first = report.results[0]
    first.replicas.append(
        ReplicaResult(root=Path("/backup2"), action="failed", error="read-only")
    )
    rows = report_rows(report, ["backups"])
    assert rows[1] == ["Backup incomplete (1/2)"]


def test_rows_failure_reason_prefers_error_over_reason() -> None:
    report = _make_report()
    report.results[1].reason = "ignored reason"
    rows = report_rows(report, ["failure_reason"])
    assert rows[2][0] == "destination is not writable"


# ---------------------------------------------------------------------------
# Exporters
# ---------------------------------------------------------------------------


def test_csv_writes_bom_headers_and_escapes_commas(tmp_path: Path) -> None:
    i18n.set_language("en")
    target = tmp_path / "report.csv"
    export_copy_report(
        _make_report(),
        ReportExportOptions(file_format="csv", include_summary=True),
        target,
    )
    raw = target.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")

    with target.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows[0][0] == "Source path"
    assert rows[1][0] == "/card/DCIM/DSC00001.NEF"
    # the comma/quote inside the failing file name survives the round trip
    assert rows[2][0] == '/card/DCIM/broken, "first".NEF'
    assert len(rows) == 4


def test_csv_field_subset_produces_matching_columns(tmp_path: Path) -> None:
    i18n.set_language("en")
    target = tmp_path / "subset.csv"
    export_copy_report(
        _make_report(),
        ReportExportOptions(file_format="csv", fields=["source", "bytes_written"]),
        target,
    )
    with target.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows[0] == ["Source path", "Bytes written"]
    assert rows[1] == ["/card/DCIM/DSC00001.NEF", "12345"]


def test_html_contains_task_info_files_and_escapes_html(tmp_path: Path) -> None:
    i18n.set_language("en")
    target = tmp_path / "report.html"
    export_copy_report(
        _make_report(), ReportExportOptions(file_format="html"), target
    )
    html = target.read_text(encoding="utf-8")
    assert html.startswith("<!DOCTYPE html>")
    assert "CameraCopy report" in html
    assert "Task information" in html
    assert "Files" in html
    assert "Summary" in html
    # the <script> attempt in the failure path is escaped, not injected
    report = _make_report()
    report.results[1].error = "<script>alert(1)</script>"
    export_copy_report(
        report, ReportExportOptions(file_format="html"), target
    )
    html = target.read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_html_includes_log_only_when_requested(tmp_path: Path) -> None:
    i18n.set_language("en")
    report = _make_report()
    report.add_log("Copied 1 of 3")
    without_log = tmp_path / "no-log.html"
    export_copy_report(
        report,
        ReportExportOptions(file_format="html", include_log=False),
        without_log,
    )
    assert "Copy log" not in without_log.read_text(encoding="utf-8")
    with_log = tmp_path / "with-log.html"
    export_copy_report(
        report,
        ReportExportOptions(file_format="html", include_log=True),
        with_log,
    )
    assert "Copy log" in with_log.read_text(encoding="utf-8")
    assert "Copied 1 of 3" in with_log.read_text(encoding="utf-8")


def test_pdf_writes_a_valid_document(qapp, tmp_path: Path) -> None:  # noqa: ARG001
    i18n.set_language("en")
    target = tmp_path / "report.pdf"
    export_copy_report(
        _make_report(), ReportExportOptions(file_format="pdf"), target
    )
    data = target.read_bytes()
    assert data.startswith(b"%PDF")
    assert len(data) > 1_000


# ---------------------------------------------------------------------------
# File naming
# ---------------------------------------------------------------------------


def test_build_export_path_uses_start_time(tmp_path: Path) -> None:
    report = _make_report()
    path = build_export_path(tmp_path, report, "csv")
    assert path == tmp_path / "CameraCopy report 2026-09-22 13-45-00.csv"


def test_build_export_path_avoids_existing_files(tmp_path: Path) -> None:
    report = _make_report()
    first = build_export_path(tmp_path, report, "csv")
    first.write_text("x", encoding="utf-8")
    second = build_export_path(tmp_path, report, "csv")
    assert second.name == "CameraCopy report 2026-09-22 13-45-00 (1).csv"
    second.write_text("x", encoding="utf-8")
    third = build_export_path(tmp_path, report, "csv")
    assert third.name == "CameraCopy report 2026-09-22 13-45-00 (2).csv"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def test_config_roundtrip_report_fields(tmp_path: Path) -> None:
    from cameracopy2.config import load_config, save_config

    config = CameraCopyConfig(
        reportexport=True,
        reportformat="html",
        reportdirectory=str(tmp_path / "reports"),
        reportfields=["source", "status", "backups"],
        reportincludesummary=False,
        reportincludelog=True,
    )
    path = tmp_path / "cameracopy.json"
    save_config(config, path)
    loaded = load_config(path)
    assert loaded.reportexport is True
    assert loaded.reportformat == "html"
    assert loaded.reportdirectory == str(tmp_path / "reports")
    # canonical order is restored on load
    assert loaded.reportfields == ["source", "status", "backups"]
    assert loaded.reportincludesummary is False
    assert loaded.reportincludelog is True


def test_config_rejects_bad_report_format() -> None:
    with pytest.raises(UnsupportedConfigError, match="reportformat"):
        config_from_dict({"version": 2, "reportformat": "xlsx"})


def test_config_drops_unknown_report_field_keys() -> None:
    config = config_from_dict(
        {"version": 2, "reportfields": ["source", "bogus", "status"]}
    )
    assert config.reportfields == ["source", "status"]


def test_config_empty_report_fields_fall_back_to_defaults() -> None:
    config = config_from_dict({"version": 2, "reportfields": []})
    assert config.reportfields == list(DEFAULT_REPORT_FIELDS)


def test_config_report_fields_restores_canonical_order() -> None:
    config = config_from_dict(
        {"version": 2, "reportfields": ["status", "backups", "source"]}
    )
    assert config.reportfields == ["source", "status", "backups"]


# ---------------------------------------------------------------------------
# GUI: settings tab and progress dialog integration
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = __import__("PySide6.QtWidgets", fromlist=["QApplication"]).QApplication
    instance = app.instance() or app([])
    yield instance


def test_settings_report_tab_roundtrip(qapp, tmp_path: Path) -> None:  # noqa: ARG001
    from PySide6.QtCore import Qt

    from cameracopy2.ui.settings_dialog import SettingsDialog

    config = CameraCopyConfig(
        reportexport=True,
        reportformat="pdf",
        reportdirectory=str(tmp_path),
        reportfields=["source", "backups"],
        reportincludesummary=False,
        reportincludelog=True,
    )
    dialog = SettingsDialog(config)
    tab_texts = [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())]
    assert "Report" in tab_texts

    assert dialog.report_export_checkbox.isChecked()
    assert str(dialog.report_format_combo.currentData()) == "pdf"
    assert dialog.report_directory_edit.text() == str(tmp_path)
    assert dialog.report_include_summary_checkbox.isChecked() is False
    assert dialog.report_include_log_checkbox.isChecked() is True

    # change controls and read them back through _config_from_controls
    dialog.report_export_checkbox.setChecked(False)
    dialog.report_format_combo.setCurrentIndex(0)  # csv
    dialog.report_directory_edit.setText(str(tmp_path / "elsewhere"))
    for index in range(dialog.report_fields_list.count()):
        item = dialog.report_fields_list.item(index)
        wanted = str(item.data(Qt.ItemDataRole.UserRole)) in {"status", "rating"}
        item.setCheckState(
            Qt.CheckState.Checked if wanted else Qt.CheckState.Unchecked
        )
    dialog.report_include_summary_checkbox.setChecked(True)
    dialog.report_include_log_checkbox.setChecked(False)

    updated = dialog._config_from_controls()  # noqa: SLF001
    assert updated.reportexport is False
    assert updated.reportformat == "csv"
    assert updated.reportdirectory == str(tmp_path / "elsewhere")
    assert updated.reportfields == ["status", "rating"]
    assert updated.reportincludesummary is True
    assert updated.reportincludelog is False
    dialog.close()


def test_settings_report_fields_default_all_checked(qapp) -> None:  # noqa: ARG001
    from cameracopy2.ui.settings_dialog import SettingsDialog

    dialog = SettingsDialog(CameraCopyConfig())
    checked = dialog._selected_report_fields()  # noqa: SLF001
    assert checked == list(DEFAULT_REPORT_FIELDS)
    assert len(checked) < len(_ALL_FIELD_KEYS)  # backups stays opt-in
    dialog.close()


def test_progress_dialog_exports_manually_and_automatically(
    qapp, tmp_path: Path, monkeypatch
) -> None:  # noqa: ARG001
    i18n.set_language("en")
    from cameracopy2.ui.copy_progress_dialog import CopyProgressDialog

    messages: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "cameracopy2.ui.copy_progress_dialog.QMessageBox.information",
        lambda *a, **k: messages.append(("info", str(a))),
    )
    monkeypatch.setattr(
        "cameracopy2.ui.copy_progress_dialog.QMessageBox.warning",
        lambda *a, **k: messages.append(("warning", str(a))),
    )

    config = CameraCopyConfig(
        source="",
        destination=str(tmp_path / "pictures"),
        reportexport=True,
        reportformat="csv",
        reportdirectory=str(tmp_path / "reports"),
    )
    job_copy = {
        "primary": VolumeInfo(
            id="card", display_name="Card", mount_path=tmp_path / "card"
        )
    }
    from cameracopy2.models import CopyJob

    job = CopyJob(
        primary=job_copy["primary"], secondary=None, config=config
    )
    dialog = CopyProgressDialog(job)

    # before any copy finished, the export button is disabled
    assert not dialog.export_report_button.isEnabled()

    dialog.report = _make_report()
    dialog._finish_all_operations()  # noqa: SLF001

    assert dialog.export_report_button.isEnabled()
    auto_path = tmp_path / "reports" / "CameraCopy report 2026-09-22 13-45-00.csv"
    assert auto_path.exists(), "automatic export should have written the report"
    text = auto_path.read_text(encoding="utf-8-sig")
    assert "Source path" in text
    # export progress is written to the on-screen log view, not report.logs
    log_text = dialog.log_view.toPlainText()
    assert "Automatic report export" in log_text
    assert "Report exported:" in log_text

    # manual export lands next to the automatic one with a non-clashing name
    manual_target = tmp_path / "manual-report.html"
    dialog._export_report(manual_target)  # noqa: SLF001
    assert manual_target.exists()
    assert messages and messages[0][0] == "info"
    dialog.close()
    qapp.processEvents()


def test_progress_dialog_reports_export_errors(
    qapp, tmp_path: Path, monkeypatch
) -> None:  # noqa: ARG001
    from cameracopy2.ui.copy_progress_dialog import CopyProgressDialog
    from cameracopy2.models import CopyJob

    warnings: list[str] = []
    monkeypatch.setattr(
        "cameracopy2.ui.copy_progress_dialog.QMessageBox.warning",
        lambda *a, **k: warnings.append(str(a[2])),
    )

    config = CameraCopyConfig(
        source="",
        destination=str(tmp_path / "pictures"),
        reportformat="csv",
        reportfields=["not_a_field"],  # type: ignore[list-item]
    )
    job = CopyJob(
        primary=VolumeInfo(
            id="card", display_name="Card", mount_path=tmp_path / "card"
        ),
        secondary=None,
        config=config,
    )
    dialog = CopyProgressDialog(job)
    dialog.report = _make_report()

    # A raw bogus field reaches ReportExportOptions through the dialog only if
    # config validation is bypassed; the options layer must reject it loudly.
    from cameracopy2.core.report_export import ReportExportOptions as Opts

    with pytest.raises(ValueError):
        Opts(file_format="csv", fields=list(config.reportfields))

    dialog.close()
    qapp.processEvents()


# ---------------------------------------------------------------------------
# resolve_report_directory: default = destination top level
# ---------------------------------------------------------------------------


def test_resolve_report_directory_prefers_explicit_setting(tmp_path: Path) -> None:
    from cameracopy2.core.report_export import resolve_report_directory

    custom = tmp_path / "custom"
    config = CameraCopyConfig(
        source="",
        destination=str(tmp_path / "pictures"),
        reportdirectory=str(custom),
    )
    assert resolve_report_directory(config) == custom


def test_resolve_report_directory_defaults_to_destination_top_level(
    tmp_path: Path,
) -> None:
    from cameracopy2.core.report_export import resolve_report_directory

    config = CameraCopyConfig(
        source="",
        destination=str(tmp_path / "pictures"),
        reportdirectory="  ",
    )
    assert resolve_report_directory(config) == tmp_path / "pictures"


def test_resolve_report_directory_without_destination_falls_back(
    tmp_path: Path,
) -> None:
    from cameracopy2.core.report_export import (
        default_report_directory,
        resolve_report_directory,
    )

    config = CameraCopyConfig(source="", destination="")
    assert resolve_report_directory(config) == default_report_directory()


def test_auto_export_writes_to_destination_top_level(qapp, tmp_path: Path) -> None:  # noqa: ARG001
    dest = tmp_path / "pictures"
    config = CameraCopyConfig(
        source="",
        destination=str(dest),
        reportexport=True,
        reportformat="csv",
        reportdirectory="",
    )
    job = CopyJob(
        primary=VolumeInfo(
            id="card", display_name="Card", mount_path=tmp_path / "card"
        ),
        secondary=None,
        config=config,
    )
    from cameracopy2.ui.copy_progress_dialog import CopyProgressDialog

    dialog = CopyProgressDialog(job)
    dialog.report = _make_report()
    dialog._finish_all_operations()  # noqa: SLF001
    dialog.close()
    qapp.processEvents()

    reports = list(dest.glob("CameraCopy report *.csv"))
    assert reports, "the report must land in the destination top level"
    # 不落进任何按日期/层级组织的子文件夹
    assert all(report.parent == dest for report in reports)
