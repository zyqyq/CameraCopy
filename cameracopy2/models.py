from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Literal

CONFIG_VERSION = 2

DEFAULT_INCLUDE_PATTERNS = [
    "*.NEF",
    "*.NRW",
    "*.CR3",
    "*.CR2",
    "*.CRW",
    "*.ARW",
    "*.SR2",
    "*.SRF",
    "*.DNG",
    "*.RWL",
    "*.RAF",
    "*.JPG",
    "*.JPEG",
    "*.MP4",
    "*.MOV",
]

CopyAction = Literal["copied", "skipped", "removed", "failed", "verified_existing"]
FormatRiskKind = Literal[
    "rating_excluded",
    "clone_kept_first_source",
    "clone_used_second_source",
    "volume_mismatch_skipped",
    "volume_mismatch_kept_existing",
    "batch_verification_failed",
    "replica_failed",
]

CopyMode = Literal[
    "copied",
    "overwrote",
    "renamed_copy",
    "verified_existing",
    "clone_verified",
    "clone_mismatch_kept",
    "clone_mismatch_replaced",
    "clone_mismatch_skipped",
    "volume_mismatch_copied",
    "volume_mismatch_kept_both",
    "volume_mismatch_replaced",
    "volume_mismatch_kept_existing",
    "volume_mismatch_verified_existing",
    "volume_mismatch_skipped",
]
CollisionPolicy = Literal["skip", "overwrite", "rename", "ask"]
RedundantWriteMode = Literal["parallel", "sequential"]
ReportFormat = Literal["csv", "html", "pdf"]

# Default column set for exported copy reports (see report_export.REPORT_FIELDS).
DEFAULT_REPORT_FIELDS = [
    "source",
    "destination",
    "status",
    "size",
    "bytes_written",
    "verification",
    "rating",
    "timestamp",
    "failure_reason",
]

# Every report column key a user may pick ("backups" is off by default).
REPORT_FIELD_KEYS = frozenset([*DEFAULT_REPORT_FIELDS, "backups"])
ThemeMode = Literal["system", "light", "dark"]
LanguageMode = Literal["zh_CN", "en"]
HashMethod = Literal["sha256", "xxhash64"]
VerificationMode = Literal["per_file", "batch"]
VolumeMatchMethod = Literal[
    "device_serial",
    "fs_uuid",
    "label",
    "size",
    "device_path",
    "mount_point",
]
#: Where the date used to rename a copied file comes from. ``same_as_folder``
#: reuses the folder-naming chain so both names always agree.
RenameDateSource = Literal[
    "same_as_folder",
    "exif_datetime_original",
    "exif_create_date",
    "quicktime_create_date",
    "xmp_create_date",
    "file_mtime",
]
CollisionDecision = Literal["skip", "overwrite", "rename", "cancel"]


#: How the destination directory tree is built. ``capture_date`` keeps the
#: original single capture-date folder; the two "today" modes add the current
#: date (captured once per copy task) as the outermost layer.
FolderTreeMode = Literal[
    "capture_date",
    "today_nested",
    "today_only",
]
CloneMismatchDecision = Literal["keep_both", "replace", "skip", "cancel"]
VolumeMismatchDecision = Literal[
    "copy", "keep_both", "keep_existing", "replace", "skip", "cancel"
]

_WRITTEN_COPY_MODES = {
    "copied",
    "overwrote",
    "renamed_copy",
    "clone_mismatch_kept",
    "clone_mismatch_replaced",
    "volume_mismatch_copied",
    "volume_mismatch_kept_both",
    "volume_mismatch_replaced",
}

_HASH_FAILURE_LABELS = {"sha256": "SHA256", "xxhash64": "xxHash64"}
_HASH_FAILURE_TOKENS = {"sha256": "SHA256", "xxhash64": "XXHASH64"}


@dataclass(frozen=True, slots=True)
class FormatRisk:
    kind: FormatRiskKind
    source: Path


@dataclass(slots=True)
class CloneMismatchResponse:
    decision: CloneMismatchDecision
    remove_source: bool = False


@dataclass(slots=True)
class VolumeMatch:
    method: VolumeMatchMethod = "device_serial"
    value: str | int = ""


@dataclass(slots=True)
class CameraCopyConfig:
    version: int = CONFIG_VERSION
    source: str = "DCIM"
    destination: str = field(default_factory=lambda: str(Path.home() / "Pictures"))
    redundantbackup: bool = False
    additionaldestinations: list[str] = field(default_factory=list)
    redundantwritemode: RedundantWriteMode = "parallel"
    includedfiles: list[str] = field(default_factory=lambda: list(DEFAULT_INCLUDE_PATTERNS))
    excludedfiles: list[str] = field(default_factory=list)
    includeddevices: list[str] = field(default_factory=list)
    folderprefix: str = ""
    datetimestring: str = "yyyy-MM-dd"
    folderpostfix: str = ""
    foldertreemode: FolderTreeMode = "capture_date"
    renamefiles: bool = False
    renamefileprefix: str = ""
    renamefiledatestring: str = "yyyyMMdd_HHmmss"
    renamefilepostfix: str = ""
    renamefilepattern: str = ""
    renamefiledatesource: RenameDateSource = "same_as_folder"
    defaultprimaryvolumeid: str = ""
    defaultsecondaryvolumeid: str = ""
    defaultprimaryvolumematch: VolumeMatch = field(default_factory=VolumeMatch)
    defaultsecondaryvolumematch: VolumeMatch = field(default_factory=VolumeMatch)
    minrating: int = 0
    useembeddedmetadata: bool = False
    copysidecars: bool = False
    clonemode: bool = False
    autoformat: str | None = None
    autoremove: bool = False
    formatprompt: bool = True
    checkhash: bool = True
    hashmethod: HashMethod = "sha256"
    verificationmode: VerificationMode = "per_file"
    durablewrites: bool = True
    resumepartialfiles: bool = True
    recoverinterruptedjobs: bool = True
    fixsonytimestamps: bool = True
    collisionpolicy: CollisionPolicy = "ask"
    applicationname: str = ""
    applicationpath: str = ""
    applicationarguments: str = ""
    applicationenvironment: str = ""
    theme: ThemeMode = "system"
    language: LanguageMode = "zh_CN"
    copyloginformationcolor: str | None = None
    copylogcopiedcolor: str | None = None
    copylogconfirmedcolor: str | None = None
    copylogwarningcolor: str | None = None
    copylogerrorcolor: str | None = None
    copylogbackgroundcolor: str | None = None
    reportexport: bool = False
    reportformat: ReportFormat = "csv"
    reportdirectory: str = ""
    reportfields: list[str] = field(default_factory=lambda: list(DEFAULT_REPORT_FIELDS))
    reportincludesummary: bool = True
    reportincludelog: bool = False


@dataclass(slots=True)
class VolumeInfo:
    id: str
    display_name: str
    mount_path: Path
    device_path: str | None = None
    label: str | None = None
    model: str | None = None
    size_bytes: int | None = None
    filesystem: str | None = None
    removable: bool | None = None
    uuid: str | None = None
    transport: str | None = None
    device_serial: str | None = None
    partition_uuid: str | None = None
    hardware_path: str | None = None
    platform: str = "unknown"

    @property
    def is_available(self) -> bool:
        return self.mount_path.exists()

    @property
    def is_likely_removable(self) -> bool:
        if self.removable is True:
            return True
        mount = str(self.mount_path)
        return mount.startswith(("/media", "/run/media", "/mnt"))

    def matches_keywords(self, keywords: list[str]) -> bool:
        normalized_keywords = [
            keyword.strip().lower() for keyword in keywords if keyword.strip()
        ]
        if not normalized_keywords:
            return True
        haystack = " ".join(
            str(part or "")
            for part in (
                self.display_name,
                self.mount_path,
                self.device_path,
                self.label,
                self.model,
                self.filesystem,
                self.uuid,
                self.transport,
                self.device_serial,
                self.partition_uuid,
                self.hardware_path,
            )
        ).lower()
        return any(keyword in haystack for keyword in normalized_keywords)


@dataclass(slots=True)
class CompletedFileEntry:
    """One source file an earlier, interrupted run already preserved."""

    relative_path: str = ""
    destination: str | None = None
    size_bytes: int = 0
    mode: str | None = None


@dataclass(slots=True)
class ResumedCopyState:
    """Everything a restarted job needs to continue an interrupted run.

    ``completed`` is keyed by the volume-scoped source key used in the copy
    journal, so two volumes holding the same relative path never collide.
    """

    session_id: str
    volume_keys: tuple[str, ...] = ()
    completed: dict[str, CompletedFileEntry] = field(default_factory=dict)
    completed_bytes: int = 0
    total_files: int = 0

    def volume_key_for(self, source_index: int) -> str | None:
        if 0 < source_index <= len(self.volume_keys):
            return self.volume_keys[source_index - 1]
        return None


@dataclass(slots=True)
class CopyJob:
    primary: VolumeInfo
    secondary: VolumeInfo | None
    config: CameraCopyConfig
    clone_mode: bool = False
    autoremove: bool = False
    format_after_copy: str | None = None
    resume: ResumedCopyState | None = None

    def selected_volumes(self) -> list[VolumeInfo]:
        volumes = [self.primary]
        if self.secondary is not None:
            volumes.append(self.secondary)
        return volumes


@dataclass(slots=True)
class HashResult:
    source_hash: str | None
    destination_hash: str | None
    ok: bool
    error: str | None = None


@dataclass(slots=True)
class ReplicaResult:
    """Outcome of writing one source file to one redundant backup destination."""

    root: Path
    destination: Path | None = None
    action: CopyAction = "copied"
    copy_mode: CopyMode | None = None
    hash_ok: bool | None = None
    bytes_copied: int = 0
    reason: str | None = None
    error: str | None = None

    @property
    def failed(self) -> bool:
        return self.action == "failed" or self.error is not None or self.hash_ok is False

    @property
    def skipped(self) -> bool:
        return self.action == "skipped"

    @property
    def verified_existing(self) -> bool:
        return self.copy_mode == "verified_existing"

    @property
    def written(self) -> bool:
        return self.copy_mode in {"copied", "overwrote", "renamed_copy"}


@dataclass(slots=True)
class FileCopyResult:
    source: Path
    destination: Path | None
    action: CopyAction
    hash_ok: bool | None = None
    rating: int | None = None
    timestamp: datetime | None = None
    reason: str | None = None
    error: str | None = None
    size_bytes: int = 0
    bytes_copied: int = 0
    timestamp_source: str | None = None
    rating_source: str | None = None
    copy_mode: CopyMode | None = None
    volume_mismatch: bool = False
    first_source_destination: Path | None = None
    first_source_size_bytes: int | None = None
    replicas: list[ReplicaResult] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return (
            self.action == "failed"
            or self.error is not None
            or self.hash_ok is False
            or self.has_replica_failure
        )

    @property
    def replica_failures(self) -> list[ReplicaResult]:
        return [replica for replica in self.replicas if replica.failed]

    @property
    def has_replica_failure(self) -> bool:
        return any(replica.failed for replica in self.replicas)

    @property
    def replica_bytes_copied(self) -> int:
        return sum(replica.bytes_copied for replica in self.replicas)

    @property
    def replicas_verified(self) -> bool:
        """True when every redundant destination holds a fresh or verified copy."""
        return bool(self.replicas) and not self.replicas_incomplete

    @property
    def replicas_incomplete(self) -> bool:
        """True when a configured mirror is missing, failed or was left behind."""
        return any(replica.failed or replica.skipped for replica in self.replicas)

    @property
    def cancelled(self) -> bool:
        return self.action == "skipped" and (self.reason or "").startswith("copy cancelled")


@dataclass(slots=True)
class CopyReport:
    started_at: datetime
    finished_at: datetime | None = None
    results: list[FileCopyResult] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)
    cancelled: bool = False
    prompt_wait_seconds: float = 0.0
    format_risks: list[FormatRisk] = field(default_factory=list)
    hash_method: str = "sha256"
    verification_mode: str = "per_file"
    batch_checked_count: int = 0
    batch_failed_count: int = 0
    batch_checked_bytes: int = 0
    batch_verification_seconds: float = 0.0
    session_id: str | None = None
    session_saved: bool = False
    resumed_files: int = 0
    resumed_bytes: int = 0
    partial_resume_count: int = 0
    resumed_partial_bytes: int = 0
    # Source deletions that wait behind a confirmation prompt: (path, size).
    pending_source_removals: list[tuple[Path, int]] = field(default_factory=list)
    removal_confirmed: bool | None = None
    confirmed_removals: int = 0
    confirmed_removal_bytes: int = 0

    def add_log(self, message: str) -> None:
        self.logs.append(message)

    def add_result(self, result: FileCopyResult) -> None:
        self.results.append(result)

    def add_format_risk(self, kind: FormatRiskKind, source: Path) -> None:
        risk = FormatRisk(kind=kind, source=source)
        if risk not in self.format_risks:
            self.format_risks.append(risk)

    @property
    def failures(self) -> list[FileCopyResult]:
        return [result for result in self.results if result.failed]

    @property
    def has_failures(self) -> bool:
        return bool(self.failures)

    @property
    def completed_cleanly(self) -> bool:
        return not self.cancelled and not self.has_failures

    @property
    def copied_count(self) -> int:
        return sum(1 for result in self.results if result.copy_mode in _WRITTEN_COPY_MODES)

    @property
    def new_copy_count(self) -> int:
        return sum(
            1
            for result in self.results
            if result.copy_mode in {"copied", "volume_mismatch_copied"}
        )

    @property
    def kept_both_count(self) -> int:
        return sum(
            1
            for result in self.results
            if result.copy_mode in {
                "renamed_copy",
                "clone_mismatch_kept",
                "volume_mismatch_kept_both",
            }
        )

    @property
    def replaced_count(self) -> int:
        return sum(
            1
            for result in self.results
            if result.copy_mode in {
                "overwrote",
                "clone_mismatch_replaced",
                "volume_mismatch_replaced",
            }
        )

    @property
    def skipped_count(self) -> int:
        return sum(1 for result in self.results if result.action == "skipped")

    @property
    def removed_count(self) -> int:
        return sum(1 for result in self.results if result.action == "removed")

    @property
    def verified_existing_count(self) -> int:
        return sum(
            1
            for result in self.results
            if result.copy_mode in {
                "verified_existing",
                "volume_mismatch_verified_existing",
            }
        )

    @property
    def clone_verified_count(self) -> int:
        return sum(1 for result in self.results if result.copy_mode == "clone_verified")

    def format_risk_counts_for(self, volume: VolumeInfo) -> dict[FormatRiskKind, int]:
        """Return data-loss warning counts for one selected source volume."""
        try:
            mount_root = volume.mount_path.resolve()
        except OSError:
            mount_root = volume.mount_path

        counts: dict[FormatRiskKind, int] = {}
        for risk in self.format_risks:
            try:
                risk.source.resolve().relative_to(mount_root)
            except (OSError, ValueError):
                continue
            counts[risk.kind] = counts.get(risk.kind, 0) + 1
        return counts

    @property
    def failed_count(self) -> int:
        return len(self.failures)

    @property
    def hash_failure_count(self) -> int:
        token = _HASH_FAILURE_TOKENS.get(str(self.hash_method).lower(), "SHA256")
        return sum(
            1
            for result in self.results
            if result.hash_ok is False
            or token in (result.reason or "").upper()
            or token in (result.error or "").upper()
        )

    @property
    def sha256_failure_count(self) -> int:
        return self.hash_failure_count

    @property
    def hash_failure_label(self) -> str:
        return _HASH_FAILURE_LABELS.get(str(self.hash_method).lower(), "SHA256")

    @property
    def total_count(self) -> int:
        return len(self.results)

    @property
    def bytes_copied(self) -> int:
        return sum(result.bytes_copied for result in self.results)

    @property
    def rating_source_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for result in self.results:
            if result.rating_source:
                source_type = result.rating_source.partition(":")[0]
                counts[source_type] = counts.get(source_type, 0) + 1
        return counts

    @property
    def copy_seconds(self) -> float | None:
        if self.finished_at is None:
            return None
        elapsed = (self.finished_at - self.started_at).total_seconds()
        return max(0.0, elapsed - self.prompt_wait_seconds)

    def summary_lines(self) -> list[str]:
        if self.cancelled:
            status = "cancelled"
        elif self.has_failures:
            status = "finished with failures"
        else:
            status = "finished successfully"
        lines = [f"Status: {status}"]
        lines.append("Files:")
        lines.append(f"  {self.total_count} total")
        self._append_count_line(lines, self.copied_count, "copied")
        self._append_count_line(lines, self.new_copy_count, "new")
        self._append_count_line(lines, self.kept_both_count, "kept both")
        self._append_count_line(lines, self.replaced_count, "replaced")
        self._append_count_line(lines, self.verified_existing_count, "verified existing")
        self._append_count_line(lines, self.clone_verified_count, "verified clones")
        self._append_count_line(lines, self.skipped_count, "skipped")
        lines.append(f"  {self.failed_count} failed")
        if self.hash_failure_count:
            lines.append(f"{self.hash_failure_label} failures: {self.hash_failure_count}")
        if self.verification_mode == "batch":
            lines.append(
                f"Batch verification ({self.hash_failure_label}): "
                f"{self.batch_checked_count} checked, {self.batch_failed_count} mismatched"
            )
            if self.batch_verification_seconds > 0:
                lines.append(
                    f"Batch verification time: "
                    f"{_format_elapsed_seconds(self.batch_verification_seconds)}"
                )
        self._append_count_line(lines, self.removed_count, "source files removed")
        if self.removal_confirmed is False and self.pending_source_removals:
            lines.append(
                f"Source files kept (deletion cancelled): "
                f"{len(self.pending_source_removals)}"
            )
        elif self.removal_confirmed and self.confirmed_removals:
            lines.append(
                f"Source files removed after confirmation: {self.confirmed_removals}"
            )
        self._append_count_line(lines, self.resumed_files, "already copied by an earlier run")
        self._append_count_line(lines, self.partial_resume_count, "continued from partial files")
        if self.rating_source_counts:
            lines.append("Ratings:")
            lines.extend(_format_rating_source_counts(self.rating_source_counts))
        lines.append(f"Bytes written: {self.bytes_copied:,}")
        if self.resumed_partial_bytes:
            lines.append(
                f"Bytes continued from partial files: {self.resumed_partial_bytes:,}"
            )
        if self.replica_results:
            lines.append(f"Redundant bytes written: {self.replica_bytes_copied:,}")
            lines.extend(self.redundant_backup_lines())
        if self.copy_seconds is not None:
            if self.bytes_copied > 0 and self.copy_seconds > 0:
                average_speed = _format_byte_speed(self.bytes_copied / self.copy_seconds)
                lines.append(f"Average write speed: {average_speed}")
            lines.append(f"Copy time: {_format_elapsed_seconds(self.copy_seconds)}")
        return lines

    @property
    def replica_results(self) -> list[ReplicaResult]:
        """Flatten every redundant-backup outcome recorded on this report."""
        return [replica for result in self.results for replica in result.replicas]

    @property
    def replica_bytes_copied(self) -> int:
        return sum(replica.bytes_copied for replica in self.replica_results)

    @property
    def replica_failed_count(self) -> int:
        return sum(1 for replica in self.replica_results if replica.failed)

    @property
    def replicas_verified_count(self) -> int:
        """Files whose every redundant destination holds a fresh or verified copy."""
        return sum(1 for result in self.results if result.replicas_verified)

    def redundant_backup_lines(self) -> list[str]:
        """Summarise one redundant-backup destination per line."""
        stats: dict[str, dict[str, int]] = {}
        for replica in self.replica_results:
            entry = stats.setdefault(
                str(replica.root), {"written": 0, "verified": 0, "skipped": 0, "failed": 0}
            )
            if replica.failed:
                entry["failed"] += 1
            elif replica.skipped:
                entry["skipped"] += 1
            elif replica.verified_existing:
                entry["verified"] += 1
            else:
                entry["written"] += 1
        if not stats:
            return []

        lines = ["Redundant backups:"]
        for root, counts in stats.items():
            parts: list[str] = []
            for key, label in (
                ("written", "written"),
                ("verified", "verified existing"),
                ("skipped", "skipped"),
                ("failed", "failed"),
            ):
                if counts[key]:
                    parts.append(f"{counts[key]} {label}")
            lines.append(f"  {root}: {', '.join(parts)}")
        return lines

    @staticmethod
    def _append_count_line(lines: list[str], count: int, label: str) -> None:
        if count:
            lines.append(f"  {count} {label}")


def _format_byte_speed(bytes_per_second: float) -> str:
    return f"{_format_byte_count(int(bytes_per_second))}/s"


def _format_byte_count(size_bytes: int) -> str:
    size = float(max(0, size_bytes))
    units = ["bytes", "KB", "MB", "GB", "TB"]
    unit_index = 0
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    if unit_index == 0:
        return f"{int(size)} bytes"
    if size >= 100:
        return f"{size:.0f} {units[unit_index]}"
    if size >= 10:
        return f"{size:.1f} {units[unit_index]}"
    return f"{size:.2f} {units[unit_index]}"


def _format_elapsed_seconds(seconds: float) -> str:
    if seconds < 1:
        return f"{seconds:.3f} seconds"
    if seconds < 10:
        return f"{seconds:.2f} seconds"
    return f"{seconds:.1f} seconds"


def _format_rating_source_counts(counts: dict[str, int]) -> list[str]:
    labels = {
        "xmp_sidecar": "XMP sidecar",
        "rrdata_sidecar": "RapidRaw sidecar",
        "embedded_xmp": "Embedded metadata",
        "missing": "No rating found (treated as 0)",
    }
    preferred_order = ("xmp_sidecar", "rrdata_sidecar", "embedded_xmp", "missing")
    keys = [key for key in preferred_order if key in counts]
    keys.extend(sorted(set(counts) - set(preferred_order)))
    lines = []
    for key in keys:
        count = counts[key]
        noun = "file" if count == 1 else "files"
        label = labels.get(key, key.replace("_", " ").capitalize())
        lines.append(f"  {label}: {count} {noun}")
    return lines


@dataclass(slots=True)
class CopyCallbacks:
    log: Callable[[str], None] | None = None
    typed_log: Callable[[str, str], None] | None = None
    progress: Callable[[int, int], None] | None = None
    source_started: Callable[[int, int, str, int], None] | None = None
    source_progress: Callable[[int, int, bool], None] | None = None
    result: Callable[[FileCopyResult], None] | None = None
    file_started: Callable[[Path, int, int, int], None] | None = None
    byte_progress: Callable[[int, int, int], None] | None = None
    collision_decision: Callable[[Path, Path], CollisionDecision] | None = None
    clone_mismatch_decision: Callable[[Path, Path, bool], CloneMismatchResponse] | None = None
    volume_mismatch_decision: (
        Callable[[Path, Path, int, int, bool], VolumeMismatchDecision] | None
    ) = None

    def emit_log(self, message: str) -> None:
        if self.log:
            self.log(message)

    def emit_typed_log(self, message: str, message_type: str) -> bool:
        if self.typed_log:
            self.typed_log(message, message_type)
            return True
        return False

    def emit_progress(self, current: int, total: int) -> None:
        if self.progress:
            self.progress(current, total)

    def emit_source_started(self, index: int, total: int, action: str, total_bytes: int) -> None:
        if self.source_started:
            self.source_started(index, total, action, total_bytes)

    def emit_source_progress(
        self, bytes_done: int, total_bytes: int, metered: bool = False
    ) -> None:
        if self.source_progress:
            self.source_progress(bytes_done, total_bytes, metered)

    def emit_result(self, result: FileCopyResult) -> None:
        if self.result:
            self.result(result)

    def emit_file_started(self, source: Path, index: int, total: int, size_bytes: int) -> None:
        if self.file_started:
            self.file_started(source, index, total, size_bytes)

    def emit_byte_progress(self, bytes_done: int, total_bytes: int, file_index: int) -> None:
        if self.byte_progress:
            self.byte_progress(bytes_done, total_bytes, file_index)

    def ask_collision_decision(self, source: Path, destination: Path) -> CollisionDecision:
        if self.collision_decision:
            return self.collision_decision(source, destination)
        return "skip"

    def ask_clone_mismatch_decision(
        self,
        source: Path,
        destination: Path,
        allow_remove: bool,
    ) -> CloneMismatchResponse:
        if self.clone_mismatch_decision:
            return self.clone_mismatch_decision(source, destination, allow_remove)
        return CloneMismatchResponse(decision="skip", remove_source=False)

    def ask_volume_mismatch_decision(
        self,
        source: Path,
        destination: Path,
        size_bytes: int,
        companion_count: int,
        destination_exists: bool,
    ) -> VolumeMismatchDecision:
        if self.volume_mismatch_decision:
            return self.volume_mismatch_decision(
                source, destination, size_bytes, companion_count, destination_exists
            )
        return "keep_existing" if destination_exists else "skip"
