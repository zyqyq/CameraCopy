"""Source deletions always wait behind a confirmation prompt in the GUI."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from cameracopy2 import i18n
from cameracopy2.core.copy_engine import CopyEngine
from cameracopy2.models import CameraCopyConfig, CopyJob, CopyReport, VolumeInfo


def make_volume(path: Path) -> VolumeInfo:
    return VolumeInfo(id="card", display_name="Card", mount_path=path)


def make_job(card: Path, dest: Path, **config_extra) -> CopyJob:
    config = CameraCopyConfig(
        source="",
        destination=str(dest),
        includedfiles=["*.JPG"],
        datetimestring="",
        **config_extra,
    )
    return CopyJob(
        primary=make_volume(card), secondary=None, config=config, autoremove=True
    )


def test_engine_defers_source_removal_until_confirmation(tmp_path: Path) -> None:
    card = tmp_path / "card"
    dest = tmp_path / "pictures"
    card.mkdir()
    dest.mkdir()
    source = card / "DSC0001.JPG"
    source.write_bytes(b"image")

    report = CopyEngine(defer_source_removal=True).run(make_job(card, dest))

    assert not report.has_failures
    assert source.exists(), "the engine must not delete before confirmation"
    assert (dest / "DSC0001.JPG").read_bytes() == b"image"
    assert report.pending_source_removals == [(source, source.stat().st_size)]
    assert report.results[0].action == "copied"
    assert any("Source cleanup deferred: 1 file(s)" in line for line in report.logs)


def test_engine_without_deferral_removes_source(tmp_path: Path) -> None:
    card = tmp_path / "card"
    dest = tmp_path / "pictures"
    card.mkdir()
    dest.mkdir()
    source = card / "DSC0001.JPG"
    source.write_bytes(b"image")

    report = CopyEngine().run(make_job(card, dest))

    assert not report.has_failures
    assert not source.exists()
    assert report.results[0].action == "removed"
    assert report.pending_source_removals == []


def test_batch_verification_defers_removal(tmp_path: Path) -> None:
    card = tmp_path / "card"
    dest = tmp_path / "pictures"
    card.mkdir()
    dest.mkdir()
    source = card / "DSC0001.JPG"
    source.write_bytes(b"image")

    report = CopyEngine(defer_source_removal=True).run(
        make_job(card, dest, checkhash=True, verificationmode="batch")
    )

    assert not report.has_failures
    assert source.exists()
    assert report.pending_source_removals == [(source, source.stat().st_size)]


def test_summary_reports_kept_and_confirmed_removals() -> None:
    source = Path("/card/DSC0001.JPG")
    kept = CopyReport(started_at=__import__("datetime").datetime.now())
    kept.pending_source_removals = [(source, 10)]
    kept.removal_confirmed = False
    assert any(
        "Source files kept (deletion cancelled): 1" in line
        for line in kept.summary_lines()
    )

    confirmed = CopyReport(started_at=__import__("datetime").datetime.now())
    confirmed.pending_source_removals = [(source, 10)]
    confirmed.removal_confirmed = True
    confirmed.confirmed_removals = 1
    assert any(
        "Source files removed after confirmation: 1" in line
        for line in confirmed.summary_lines()
    )


class FakeMessageBox:
    """Stands in for QMessageBox; records calls, never blocks."""

    last: "FakeMessageBox | None" = None
    chosen_text: str = "Delete source files"
    Icon = SimpleNamespace(Warning="warning")
    ButtonRole = SimpleNamespace(AcceptRole="accept", RejectRole="reject")

    def __init__(self, parent=None) -> None:  # noqa: ARG002
        self.buttons: list[SimpleNamespace] = []
        self.texts: list[str] = []
        self.infos: list[str] = []
        self.clicked: SimpleNamespace | None = None
        FakeMessageBox.last = self

    def setIcon(self, *args) -> None:  # noqa: ARG002
        pass

    def setWindowTitle(self, *args) -> None:  # noqa: ARG002
        pass

    def setTextFormat(self, *args) -> None:  # noqa: ARG002
        pass

    def setText(self, text: str) -> None:
        self.texts.append(text)

    def setInformativeText(self, text: str) -> None:
        self.infos.append(text)

    def addButton(self, text: str, role) -> SimpleNamespace:
        button = SimpleNamespace(
            text=text, role=role, setStyleSheet=lambda *a, **k: None
        )
        self.buttons.append(button)
        return button

    def setDefaultButton(self, button) -> None:  # noqa: ARG002
        pass

    def exec(self) -> None:
        chosen = next(
            (b for b in self.buttons if b.text == FakeMessageBox.chosen_text), None
        )
        self.clicked = chosen

    def clickedButton(self) -> SimpleNamespace | None:
        return self.clicked


@pytest.fixture()
def fake_message_box(monkeypatch) -> type[FakeMessageBox]:
    FakeMessageBox.last = None
    FakeMessageBox.chosen_text = "Delete source files"
    monkeypatch.setattr(
        "cameracopy2.ui.copy_progress_dialog.QMessageBox", FakeMessageBox
    )
    return FakeMessageBox


def _dialog_with_pending(qapp, tmp_path: Path, source: Path):  # noqa: ARG001
    from cameracopy2.models import CopyJob
    from cameracopy2.ui.copy_progress_dialog import CopyProgressDialog

    config = CameraCopyConfig(
        source="", destination=str(tmp_path / "pictures")
    )
    job = CopyJob(
        primary=make_volume(tmp_path / "card"), secondary=None, config=config
    )
    dialog = CopyProgressDialog(job)
    report = CopyReport(started_at=__import__("datetime").datetime.now())
    report.pending_source_removals = [(source, source.stat().st_size)]
    dialog.report = report
    return dialog


def test_dialog_deletes_only_after_confirmation(
    qapp, tmp_path: Path, fake_message_box
) -> None:
    i18n.set_language("en")
    try:
        source = tmp_path / "DSC0001.JPG"
        source.write_bytes(b"image")
        dialog = _dialog_with_pending(qapp, tmp_path, source)

        dialog._finish_all_operations()  # noqa: SLF001
        dialog.close()
        qapp.processEvents()

        box = fake_message_box.last
        assert box is not None, "a confirmation prompt must be shown"
        assert "1 source file(s)" in box.texts[0]
        # red, prominent warning + structured scope/reassurance lines
        assert "#e53935" in box.infos[0]
        assert "cannot be recovered" in box.infos[0]
        assert "Only files that were copied and verified" in box.infos[0]
        assert "The copies on the destination stay" in box.infos[0]
        assert not source.exists(), "confirming must delete the source file"
        assert dialog.report.removal_confirmed is True
        assert dialog.report.confirmed_removals == 1
        log_text = dialog.log_view.toPlainText()
        assert "Deleted 1 source file(s) after confirmation" in log_text
    finally:
        i18n.set_language(i18n.DEFAULT_LANGUAGE)


def test_dialog_keep_keeps_files(
    qapp, tmp_path: Path, fake_message_box
) -> None:
    fake_message_box.chosen_text = "Keep source files"
    i18n.set_language("en")
    try:
        source = tmp_path / "DSC0001.JPG"
        source.write_bytes(b"image")
        dialog = _dialog_with_pending(qapp, tmp_path, source)

        dialog._finish_all_operations()  # noqa: SLF001
        dialog.close()
        qapp.processEvents()

        assert source.exists(), "declining must keep the source file"
        assert dialog.report.removal_confirmed is False
        log_text = dialog.log_view.toPlainText()
        assert "Kept 1 source file(s); deletion cancelled." in log_text
    finally:
        i18n.set_language(i18n.DEFAULT_LANGUAGE)


def test_dialog_skips_prompt_without_pending(
    qapp, tmp_path: Path, fake_message_box
) -> None:  # noqa: ARG001
    from cameracopy2.models import CopyJob
    from cameracopy2.ui.copy_progress_dialog import CopyProgressDialog

    config = CameraCopyConfig(
        source="", destination=str(tmp_path / "pictures")
    )
    job = CopyJob(
        primary=make_volume(tmp_path / "card"), secondary=None, config=config
    )
    dialog = CopyProgressDialog(job)
    dialog.report = CopyReport(started_at=__import__("datetime").datetime.now())

    dialog._finish_all_operations()  # noqa: SLF001
    dialog.close()
    qapp.processEvents()

    assert fake_message_box.last is None, "no prompt without pending deletions"


def test_deletion_messages_follow_language() -> None:
    i18n.set_language("zh_CN")
    try:
        assert i18n.translate_text("Confirm source deletion") == "确认删除源文件"
        assert (
            i18n.translate_text(
                "The copy finished successfully. Delete 3 source file(s) "
                "(1.5 MB) from the card?"
            )
            == "复制已成功完成。要从存储卡删除 3 个源文件（共 1.5 MB）吗？"
        )
        assert (
            i18n.translate_text("Deleted files cannot be recovered.")
            == "删除后无法恢复。"
        )
        assert (
            i18n.translate_text(
                "Only files that were copied and verified are affected."
            )
            == "仅影响已复制并校验通过的文件。"
        )
        assert (
            i18n.translate_text("The copies on the destination stay.")
            == "目标位置的副本不受影响。"
        )
        assert (
            i18n.translate_log("Kept 2 source file(s); deletion cancelled.")
            == "已保留 2 个源文件；已取消删除。"
        )
        assert (
            i18n.translate_log(
                "Deleted 2 source file(s) after confirmation (1.5 MB)."
            )
            == "已确认删除 2 个源文件（共 1.5 MB）。"
        )
        assert (
            i18n.translate_log("Source cleanup deferred: 4 file(s) awaiting confirmation.")
            == "源文件删除已暂缓：4 个文件等待确认。"
        )
    finally:
        i18n.set_language("en")
