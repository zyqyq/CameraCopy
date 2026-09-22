from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from cameracopy2.config import (
    translate_datetime_format,
    validate_file_stem,
    validate_folder_component,
)
from cameracopy2.models import CameraCopyConfig, FolderTreeMode


#: Fallback pattern for the outer "today" folder when the user cleared the
#: date format: an empty name would collapse the layer into the destination
#: root, so a plain ISO date is used instead.
DEFAULT_TODAY_FORMAT = "%Y-%m-%d"


FOLDER_TREE_MODE_LABELS: dict[str, str] = {
    "capture_date": "Capture date only",
    "today_nested": "Today folder / capture date",
    "today_only": "Today folder only",
}


#: Display order of the folder tree modes in the settings dialog.
FOLDER_TREE_MODE_ORDER: tuple[FolderTreeMode, ...] = (
    "capture_date",
    "today_nested",
    "today_only",
)


def folder_tree_mode(config: CameraCopyConfig) -> str:
    """Normalized folder tree mode, tolerating configs written by older versions."""
    value = str(getattr(config, "foldertreemode", "") or "")
    return value if value in FOLDER_TREE_MODE_LABELS else "capture_date"


def folder_tree_mode_label(mode: str) -> str:
    return FOLDER_TREE_MODE_LABELS.get(str(mode or ""), str(mode or ""))


def _validated_directory(parent: Path, name: str, *, layer: str) -> Path:
    if not name:
        return parent
    validation_error = validate_folder_component(name)
    if validation_error:
        raise ValueError(f"Invalid destination folder name {name!r}: {validation_error}")
    return parent / name


def build_destination_directory(
    config: CameraCopyConfig,
    timestamp: datetime,
    task_time: datetime | None = None,
) -> Path:
    """Destination directory for one media file.

    ``timestamp`` is the per-file capture date from the timestamp priority
    chain. ``task_time`` is the copy task's start time, captured once per run
    so every file of the same task shares one "today" folder; it defaults to
    now for previews and direct callers.

    Depending on the folder tree mode the result is one of:

    - ``capture_date``: ``root/<prefix+capture date+postfix>/`` (original)
    - ``today_nested``: ``root/<today>/<prefix+capture date+postfix>/``
    - ``today_only``: ``root/<prefix+today+postfix>/`` — one folder per task
    """
    destination_root = Path(config.destination).expanduser()
    date_format = translate_datetime_format(config.datetimestring)
    mode = folder_tree_mode(config)
    task_time = task_time if task_time is not None else datetime.now()

    def folder_name(prefix: str, moment: datetime, postfix: str) -> str:
        date_part = moment.strftime(date_format) if date_format else ""
        return f"{prefix}{date_part}{postfix}"

    if mode == "today_only":
        return _validated_directory(
            destination_root,
            folder_name(config.folderprefix, task_time, config.folderpostfix),
            layer="today",
        )

    directory = _validated_directory(
        destination_root,
        folder_name(config.folderprefix, timestamp, config.folderpostfix),
        layer="capture",
    )
    if mode != "today_nested":
        return directory
    # The today layer is the outermost one: today / capture date / file.
    today_directory = _validated_directory(
        destination_root,
        task_time.strftime(date_format or DEFAULT_TODAY_FORMAT),
        layer="today",
    )
    return _validated_directory(
        today_directory,
        folder_name(config.folderprefix, timestamp, config.folderpostfix),
        layer="capture",
    )


def rename_date_format(config: CameraCopyConfig) -> str:
    """Return the strftime pattern used for the date part of renamed files."""
    return translate_datetime_format(config.renamefiledatestring)


#: Labels for every selectable "which date" source, shared by the settings
#: dialog, the operation log and the diagnostics report.
RENAME_DATE_SOURCE_LABELS: dict[str, str] = {
    "same_as_folder": "Same as folder date",
    "exif_datetime_original": "EXIF DateTimeOriginal",
    "exif_create_date": "EXIF CreateDate",
    "quicktime_create_date": "QuickTime CreateDate",
    "xmp_create_date": "XMP CreateDate",
    "file_mtime": "File modified time",
}


def rename_date_source_label(source: str) -> str:
    return RENAME_DATE_SOURCE_LABELS.get(str(source or ""), str(source or ""))


#: Display order of the date sources in the settings dialog.
RENAME_DATE_SOURCE_ORDER: tuple[str, ...] = (
    "same_as_folder",
    "exif_datetime_original",
    "exif_create_date",
    "quicktime_create_date",
    "xmp_create_date",
    "file_mtime",
)


#: Placeholders accepted by "File name pattern". ``*`` is an alias for
#: ``{name}`` because that is the convention most bulk renamers use.
RENAME_PATTERN_TOKENS: tuple[str, ...] = (
    "prefix",
    "date",
    "name",
    "postfix",
    "ext",
    "namefull",
    "yyyy",
    "yy",
    "MM",
    "dd",
    "HH",
    "mm",
    "ss",
)

#: What the pattern is when the field is left empty, i.e. the prefix, the
#: formatted date and the postfix alone.
RENAME_PATTERN_DEFAULT = "{prefix}{date}{postfix}"

_RENAME_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z0-9_]*)\}|\*")


def effective_rename_pattern(config: CameraCopyConfig) -> str:
    """Return the pattern in use, filling in the simple fields by default."""
    return str(config.renamefilepattern or "").strip() or RENAME_PATTERN_DEFAULT


def rename_token_values(
    config: CameraCopyConfig, source_file: Path, rename_date: datetime
) -> dict[str, str]:
    """Values behind every ``{token}`` of a rename pattern."""
    date_format = rename_date_format(config)
    return {
        "prefix": config.renamefileprefix,
        "postfix": config.renamefilepostfix,
        "date": rename_date.strftime(date_format) if date_format else "",
        "name": source_file.stem,
        "namefull": source_file.name,
        "ext": source_file.suffix[1:],
        "yyyy": f"{rename_date.year:04d}",
        "yy": f"{rename_date.year % 100:02d}",
        "MM": f"{rename_date.month:02d}",
        "dd": f"{rename_date.day:02d}",
        "HH": f"{rename_date.hour:02d}",
        "mm": f"{rename_date.minute:02d}",
        "ss": f"{rename_date.second:02d}",
    }


def expand_rename_pattern(
    pattern: str, config: CameraCopyConfig, source_file: Path, rename_date: datetime
) -> str:
    """Expand ``{token}`` placeholders and ``*`` in one pass.

    An unknown token raises instead of quietly landing in the file name, so a
    typo surfaces in the settings preview and in the operation log rather than
    on the card.
    """
    values = rename_token_values(config, source_file, rename_date)

    def replace(match: re.Match[str]) -> str:
        if match.group(0) == "*":
            return values["name"]
        token = match.group(1)
        if token not in values:
            supported = ", ".join(f"{{{name}}}" for name in RENAME_PATTERN_TOKENS)
            raise ValueError(
                f"Unknown rename token {{{token}}}. Supported tokens: {supported} and *."
            )
        return values[token]

    return _RENAME_PLACEHOLDER_RE.sub(replace, pattern)


def build_renamed_file_name(
    config: CameraCopyConfig, source_file: Path, rename_date: datetime
) -> str:
    """Return the destination name for one source file.

    The pattern can keep part or all of the camera name (``{name}`` / ``*``),
    drop it entirely, or spell the date out per token. The extension is
    appended unless the pattern already carries it, and a pattern that expands
    to nothing falls back to the camera name.
    """
    expanded = expand_rename_pattern(
        effective_rename_pattern(config), config, source_file, rename_date
    ).strip()
    if not expanded:
        return source_file.name

    suffix = source_file.suffix
    if suffix and expanded.lower().endswith(suffix.lower()):
        final_name = expanded
        stem = expanded[: -len(suffix)]
    else:
        final_name = f"{expanded}{suffix}"
        stem = expanded

    if not stem:
        raise ValueError("The rename pattern produced an empty file name.")
    validation_error = validate_file_stem(stem)
    if validation_error:
        raise ValueError(f"Invalid destination file name {final_name!r}: {validation_error}")
    return final_name


def build_destination_file(
    config: CameraCopyConfig,
    source_file: Path,
    timestamp: datetime,
    rename_date: datetime | None = None,
    task_time: datetime | None = None,
) -> Path:
    """Destination of one media file.

    ``rename_date`` is supplied only while "rename files from metadata" is
    active; without it the camera name is kept. ``task_time`` is shared by
    every file of one copy task (see :func:`build_destination_directory`).
    """
    directory = build_destination_directory(config, timestamp, task_time)
    if rename_date is None:
        return directory / source_file.name
    return directory / build_renamed_file_name(config, source_file, rename_date)


def preview_destination(
    config: CameraCopyConfig,
    sample_name: str = "DSC0001.ARW",
    *,
    timestamp: datetime | None = None,
    task_time: datetime | None = None,
) -> str:
    timestamp = timestamp if timestamp is not None else datetime.now().replace(microsecond=0)
    task_time = task_time if task_time is not None else datetime.now().replace(microsecond=0)
    directory = build_destination_directory(config, timestamp, task_time)
    if not config.renamefiles:
        return str(directory / sample_name)
    return str(directory / build_renamed_file_name(config, Path(sample_name), timestamp))
