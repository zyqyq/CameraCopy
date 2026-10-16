"""Portable settings bundles: export every setting to a file, import it back.

The bundle is a self-describing envelope around the config schema so a file
written by a newer CameraCopy can still be imported by an older one:

    {
      "schema": "cameracopy.settings",     # envelope identity
      "schema_version": 1,                 # envelope layout version
      "exported_at": "2026-10-17T00:12:33+08:00",
      "app": {"name": "CameraCopy", "version": "2.1.0", "config_version": 2},
      "settings": { ...config fields... }, # same shape as cameracopy.json
      "preserved": {
        "settings": { ...future config keys... },
        "extra":    { ...future envelope keys... }
      }
    }

Forward compatibility rules:

* Config keys this version does not know are moved into ``preserved.settings``
  instead of being rejected, and are written back out on the next export, so
  importing a newer bundle and exporting again never silently drops data.
* Envelope keys this version does not know go into ``preserved.extra``.
* The legacy single-value ``reportformat`` key is migrated by the config
  reader just like it is for ``cameracopy.json``.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path
from typing import Any

from cameracopy2 import __version__
from cameracopy2.config import UnsupportedConfigError, config_from_dict
from cameracopy2.models import CONFIG_VERSION, CameraCopyConfig

BUNDLE_SCHEMA = "cameracopy.settings"
BUNDLE_SCHEMA_VERSION = 1
BUNDLE_SUFFIX = ".json"
BUNDLE_FILE_FILTER = "CameraCopy settings (*.json);;JSON (*.json);;All files (*)"

#: Envelope keys written by this version; anything else is preserved, not lost.
_BUNDLE_KEYS = {"schema", "schema_version", "exported_at", "app", "settings", "preserved"}

#: Config keys accepted on import (current fields plus migrated legacy keys).
_KNOWN_SETTING_KEYS = {f.name for f in fields(CameraCopyConfig)} | {"reportformat"}

_PRESERVED_SECTIONS = ("settings", "extra")


class SettingsBundleError(ValueError):
    """Raised when a settings bundle cannot be read or written."""


@dataclass
class SettingsBundle:
    """An imported bundle: the config plus data this version cannot interpret."""

    config: CameraCopyConfig
    preserved: dict[str, dict[str, Any]] = field(
        default_factory=lambda: {"settings": {}, "extra": {}}
    )
    exported_at: str = ""
    app_version: str = ""

    def describe(self) -> str:
        """One-line human summary used by the import confirmation dialog."""
        parts = [f"schema v{BUNDLE_SCHEMA_VERSION}"]
        if self.app_version:
            parts.append(f"CameraCopy {self.app_version}")
        if self.exported_at:
            parts.append(self.exported_at.replace("T", " ")[:19])
        unknown = len(self.preserved.get("settings", {}))
        if unknown:
            parts.append(f"{unknown} future setting(s) preserved")
        return " · ".join(parts)


def _clean_preserved(
    preserved: Any = None,
    *,
    extra_settings: dict[str, Any] | None = None,
    extra_top: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {section: {} for section in _PRESERVED_SECTIONS}
    if isinstance(preserved, dict):
        for section in _PRESERVED_SECTIONS:
            value = preserved.get(section)
            if isinstance(value, dict):
                result[section].update(value)
    if extra_settings:
        result["settings"].update(extra_settings)
    if extra_top:
        result["extra"].update(extra_top)
    return result


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def build_settings_bundle(
    config: CameraCopyConfig,
    *,
    preserved: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return the envelope dict for ``config``."""
    return {
        "schema": BUNDLE_SCHEMA,
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "exported_at": _now_iso(),
        "app": {
            "name": "CameraCopy",
            "version": __version__,
            "config_version": CONFIG_VERSION,
        },
        "settings": asdict(config),
        "preserved": _clean_preserved(preserved),
    }


def parse_settings_bundle(data: Any) -> SettingsBundle:
    """Read an envelope dict into a :class:`SettingsBundle`.

    Raises :class:`SettingsBundleError` for anything that is not a usable
    CameraCopy settings bundle, including an invalid ``settings`` section.
    """
    if not isinstance(data, dict):
        raise SettingsBundleError("Settings file must contain a JSON object.")
    schema = data.get("schema")
    if schema != BUNDLE_SCHEMA:
        raise SettingsBundleError(
            f"Not a CameraCopy settings file (schema: {schema!r})."
        )
    schema_version = data.get("schema_version")
    if not isinstance(schema_version, int) or not 1 <= schema_version <= BUNDLE_SCHEMA_VERSION:
        raise SettingsBundleError(
            f"Unsupported settings schema version: {schema_version!r}"
        )
    raw_settings = data.get("settings")
    if not isinstance(raw_settings, dict):
        raise SettingsBundleError("Settings file is missing its settings section.")

    settings = dict(raw_settings)
    settings.setdefault("version", CONFIG_VERSION)
    future_settings = {
        key: settings.pop(key)
        for key in list(settings)
        if key not in _KNOWN_SETTING_KEYS
    }
    try:
        config = config_from_dict(settings)
    except UnsupportedConfigError as exc:
        raise SettingsBundleError(str(exc)) from exc
    except (TypeError, ValueError) as exc:  # defensive: bad types from a stray file
        raise SettingsBundleError(f"Invalid settings values: {exc}") from exc

    future_top = {
        key: value for key, value in data.items() if key not in _BUNDLE_KEYS
    }
    app_info = data.get("app")
    return SettingsBundle(
        config=config,
        preserved=_clean_preserved(
            data.get("preserved"),
            extra_settings=future_settings,
            extra_top=future_top,
        ),
        exported_at=str(data.get("exported_at") or ""),
        app_version=str(app_info.get("version", "") if isinstance(app_info, dict) else ""),
    )


def export_settings_file(
    config: CameraCopyConfig,
    path: str | Path,
    *,
    preserved: dict[str, dict[str, Any]] | None = None,
) -> Path:
    """Write ``config`` to ``path`` atomically and return the final path."""
    target = Path(path)
    if target.suffix.lower() != BUNDLE_SUFFIX:
        target = target.with_suffix(BUNDLE_SUFFIX)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(
        build_settings_bundle(config, preserved=preserved),
        indent=2,
        ensure_ascii=False,
    )
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, target)
    except BaseException:
        try:
            temp_path.unlink()
        except OSError:
            pass
        raise
    return target


def load_settings_file(path: str | Path) -> SettingsBundle:
    """Read a settings bundle from disk."""
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise SettingsBundleError(f"Cannot read {source.name}: {exc.strerror}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SettingsBundleError(f"{source.name} is not valid JSON (line {exc.lineno}).") from exc
    return parse_settings_bundle(data)
