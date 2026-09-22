"""Export a finished single-task :class:`CopyReport` as CSV, HTML or PDF.

The report is built from the English strings that are the single source of
truth everywhere else in the app; every label is passed through
``i18n.translate_text`` / ``i18n.translate_log`` right before it is written,
so exported documents follow the current interface language.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from cameracopy2.i18n import translate_log, translate_text
from cameracopy2.models import (
    DEFAULT_REPORT_FIELDS,
    REPORT_FIELD_KEYS,
    CopyReport,
    FileCopyResult,
)

__all__ = [
    "REPORT_FIELDS",
    "ReportExportOptions",
    "build_export_path",
    "export_copy_report",
    "report_rows",
]

#: Every selectable report column, in canonical order, with its English header.
REPORT_FIELDS: tuple[tuple[str, str], ...] = (
    ("source", "Source path"),
    ("destination", "Destination path"),
    ("status", "Status"),
    ("size", "File size (bytes)"),
    ("bytes_written", "Bytes written"),
    ("verification", "Verification result"),
    ("rating", "Rating"),
    ("timestamp", "Captured timestamp"),
    ("backups", "Redundant backups"),
    ("failure_reason", "Failure reason"),
)

_FIELD_ORDER = [*DEFAULT_REPORT_FIELDS, "backups"]
_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"

_STATUS_LABELS = {
    "copied": "Copied",
    "overwrote": "Overwrote",
    "renamed_copy": "Kept both (renamed)",
    "verified_existing": "Verified existing",
    "clone_verified": "Clone verified",
    "clone_mismatch_kept": "Kept both (clone)",
    "clone_mismatch_replaced": "Replaced (clone)",
    "clone_mismatch_skipped": "Skipped (clone)",
    "volume_mismatch_copied": "Copied",
    "volume_mismatch_kept_both": "Kept both",
    "volume_mismatch_replaced": "Replaced",
    "volume_mismatch_kept_existing": "Kept existing",
    "volume_mismatch_verified_existing": "Verified existing",
    "volume_mismatch_skipped": "Skipped",
}

# Columns whose *values* are UI labels and follow the interface language.
_TRANSLATED_VALUE_KEYS = frozenset({"status", "verification", "backups"})


@dataclass(slots=True)
class ReportExportOptions:
    """Which columns and extra sections a report contains."""

    file_format: str = "csv"
    fields: list[str] = field(default_factory=lambda: list(DEFAULT_REPORT_FIELDS))
    include_summary: bool = True
    include_log: bool = False

    def __post_init__(self) -> None:
        self.file_format = str(self.file_format).lower()
        if self.file_format not in {"csv", "html", "pdf"}:
            raise ValueError(f"Unsupported report format: {self.file_format!r}")
        unknown = [key for key in self.fields if key not in REPORT_FIELD_KEYS]
        if unknown:
            raise ValueError(f"Unknown report field(s): {', '.join(unknown)}")
        # Canonical column order, duplicates removed, never empty.
        selected = [key for key in _FIELD_ORDER if key in set(self.fields)]
        self.fields = selected or list(DEFAULT_REPORT_FIELDS)


def header_of(key: str) -> str:
    for candidate_key, header in REPORT_FIELDS:
        if candidate_key == key:
            return header
    raise KeyError(key)


def report_rows(report: CopyReport, fields: list[str]) -> list[list[str]]:
    """Return the report table as strings: header row first, one row per file."""
    keys = [key for key in _FIELD_ORDER if key in set(fields)] or list(DEFAULT_REPORT_FIELDS)
    rows: list[list[str]] = [[translate_text(header_of(key)) for key in keys]]
    for result in report.results:
        row = []
        for key in keys:
            value = _result_value(result, key)
            if key in _TRANSLATED_VALUE_KEYS:
                value = translate_text(value)
            row.append(value)
        rows.append(row)
    return rows


def _result_value(result: FileCopyResult, key: str) -> str:
    if key == "source":
        return str(result.source)
    if key == "destination":
        return str(result.destination) if result.destination else ""
    if key == "status":
        mode = result.copy_mode or result.action
        label = _STATUS_LABELS.get(str(mode))
        if label is None:
            label = str(result.action).replace("_", " ").capitalize()
        return label
    if key == "size":
        return str(result.size_bytes)
    if key == "bytes_written":
        return str(result.bytes_copied)
    if key == "verification":
        if result.hash_ok is True:
            return "Verified"
        if result.hash_ok is False:
            return "Hash mismatch"
        return "Not verified"
    if key == "rating":
        return "" if result.rating is None else str(result.rating)
    if key == "timestamp":
        return result.timestamp.strftime(_TIMESTAMP_FORMAT) if result.timestamp else ""
    if key == "backups":
        return _backup_status(result)
    if key == "failure_reason":
        return (result.error or result.reason or "").strip()
    raise KeyError(key)


def _backup_status(result: FileCopyResult) -> str:
    total = len(result.replicas)
    if not total:
        return ""
    healthy = sum(
        1 for replica in result.replicas if not replica.failed and not replica.skipped
    )
    if healthy == total:
        return f"Backup OK ({healthy}/{total})"
    return f"Backup incomplete ({healthy}/{total})"


def build_export_path(
    directory: str | Path, report: CopyReport, file_format: str
) -> Path:
    """Return a non-clashing export path named after the task start time."""
    directory = Path(directory).expanduser()
    stamp = report.started_at.strftime("%Y-%m-%d %H-%M-%S")
    base = directory / f"CameraCopy report {stamp}.{file_format}"
    if not base.exists():
        return base
    for index in range(1, 1000):
        candidate = directory / f"CameraCopy report {stamp} ({index}).{file_format}"
        if not candidate.exists():
            return candidate
    raise OSError(f"Could not find an available report name in {directory}")


def export_copy_report(
    report: CopyReport,
    options: ReportExportOptions,
    output_path: str | Path,
) -> Path:
    """Write ``report`` to ``output_path`` and return the written path."""
    output_path = Path(output_path)
    if options.file_format == "csv":
        _write_csv(report, options, output_path)
    else:
        html = build_html(report, options)
        if options.file_format == "html":
            output_path.write_text(html, encoding="utf-8")
        else:
            _write_pdf(html, output_path)
    return output_path


def _write_csv(report: CopyReport, options: ReportExportOptions, output_path: Path) -> None:
    # utf-8-sig: the BOM makes Excel auto-detect UTF-8 for non-ASCII paths.
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerows(report_rows(report, options.fields))


def build_html(report: CopyReport, options: ReportExportOptions) -> str:
    title = translate_text("CameraCopy report")
    sections = [
        f"<h1>{_esc(title)}</h1>",
        f"<h2>{_esc(translate_text('Task information'))}</h2>",
        _meta_table(report),
        f"<h2>{_esc(translate_text('Files'))}</h2>",
        _files_table(report, options.fields),
    ]
    if options.include_summary:
        summary = "\n".join(report.summary_lines())
        sections.append(f"<h2>{_esc(translate_text('Summary'))}</h2>")
        sections.append(f"<pre>{_esc(translate_log(summary))}</pre>")
    if options.include_log and report.logs:
        log_text = "\n".join(report.logs)
        sections.append(f"<h2>{_esc(translate_text('Copy log'))}</h2>")
        sections.append(f"<pre>{_esc(translate_log(log_text))}</pre>")
    style = (
        "body{font-family:-apple-system,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;"
        "margin:32px;color:#1d1d1f;}"
        "h1{font-size:22px;}h2{font-size:16px;margin-top:28px;}"
        "table{border-collapse:collapse;width:100%;font-size:13px;}"
        "th,td{border:1px solid #c8c8c8;padding:4px 8px;text-align:left;vertical-align:top;}"
        "th{background:#f0f0f0;}"
        "pre{background:#f6f6f6;border:1px solid #e0e0e0;padding:12px;"
        "font-size:12px;white-space:pre-wrap;word-break:break-word;}"
    )
    return (
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
        f"<title>{_esc(title)}</title><style>{style}</style></head><body>"
        + "".join(sections)
        + "</body></html>"
    )


def _esc(text: str) -> str:
    from html import escape

    return escape(text, quote=False)


def _meta_table(report: CopyReport) -> str:
    if report.cancelled:
        status = "cancelled"
    elif report.has_failures:
        status = "finished with failures"
    else:
        status = "finished successfully"
    copy_seconds = report.copy_seconds
    copy_time = f"{copy_seconds:.1f} s" if copy_seconds is not None else "—"
    entries = [
        ("Started at", report.started_at.strftime(_TIMESTAMP_FORMAT)),
        (
            "Finished at",
            report.finished_at.strftime(_TIMESTAMP_FORMAT)
            if report.finished_at
            else "—",
        ),
        ("Status", status),
        ("Total files", str(report.total_count)),
        ("Failed", str(report.failed_count)),
        ("Bytes written", f"{report.bytes_copied:,}"),
        ("Copy time", copy_time),
        ("Hash method", report.hash_method),
        ("Verification mode", report.verification_mode),
    ]
    cells = "".join(
        f"<tr><th>{_esc(translate_text(label))}</th><td>{_esc(translate_text(value))}</td></tr>"
        for label, value in entries
    )
    return f"<table>{cells}</table>"


def _files_table(report: CopyReport, fields: list[str]) -> str:
    rows = report_rows(report, fields)
    if not rows:
        return "<p>—</p>"
    header_cells = "".join(f"<th>{_esc(cell)}</th>" for cell in rows[0])
    body = "".join(
        "<tr>" + "".join(f"<td>{_esc(cell)}</td>" for cell in row) + "</tr>"
        for row in rows[1:]
    )
    return (
        f"<table><thead><tr>{header_cells}</tr></thead><tbody>{body}</tbody></table>"
    )


def _write_pdf(html: str, output_path: Path) -> None:
    # Imported lazily so the module stays importable in non-GUI unit tests
    # that never exercise the PDF branch.
    from PySide6.QtCore import QMarginsF
    from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter, QTextDocument

    writer = QPdfWriter(str(output_path))
    writer.setPageSize(QPageSize(QPageSize.A4))
    writer.setPageMargins(QMarginsF(15, 15, 15, 15), QPageLayout.Millimeter)
    writer.setResolution(96)
    document = QTextDocument()
    document.setHtml(html)
    document.print_(writer)


def default_report_directory() -> Path:
    from cameracopy2.config import APP_NAME

    return Path.home() / "Documents" / f"{APP_NAME} reports"


def resolve_report_directory(config, report: CopyReport | None = None) -> Path:
    """Return the folder reports should be written to.

    An explicit ``reportdirectory`` wins. Otherwise the report goes to the
    top level of the copy destination — the outermost folder created by the
    folder tree mode: the capture-date folder in ``capture_date`` mode, the
    today folder in ``today_nested`` / ``today_only`` mode. The level is
    derived from the first file the task actually wrote, so prefixes,
    postfixes and mixed capture dates all follow what really happened.
    Files that were copied directly into the destination root keep the root.
    Without a destination configured, fall back to Documents.
    """
    configured = config.reportdirectory.strip()
    if configured:
        return Path(configured).expanduser()
    destination = config.destination.strip()
    if not destination:
        return default_report_directory()
    destination_root = Path(destination).expanduser()
    if report is not None:
        for result in report.results:
            output = result.destination
            if output is None:
                continue
            try:
                relative = output.resolve().relative_to(
                    destination_root.resolve()
                )
            except ValueError:
                continue
            if len(relative.parts) > 1:
                return destination_root / relative.parts[0]
            return destination_root
    return destination_root
