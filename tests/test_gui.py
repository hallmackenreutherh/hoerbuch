"""Qt-/Arbeitsprozess-Integration ohne Sprachmodelle oder GPU."""
import os
from pathlib import Path
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtCore import QSettings, Qt, QProcess, QEvent
from PySide6.QtTest import QTest
from PySide6.QtMultimedia import QMediaPlayer, QMediaDevices
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QPushButton, QScrollArea
from hoerbuch.gui import Window, apply_theme


@pytest.fixture(scope="module")
def application():
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    return app


@pytest.fixture
def window(tmp_path, monkeypatch, application):
    app = application
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    widget = Window(QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat))
    widget.dialogs = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: widget.dialogs.append(args[2]))
    for field in (widget.source, widget.prepared, widget.ref, widget.destination, widget.ffmpeg):
        field.clear()
    yield widget, app
    widget.editor.document().setModified(False)
    widget.close()
    widget.deleteLater()
    app.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


def wait_worker(widget, app, timeout=30):
    deadline = time.monotonic() + timeout
    while widget.process is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert widget.process is None, widget.log.toPlainText()


def click(widget, label):
    matches = [b for b in widget.findChildren(QPushButton) if b.text() == label]
    assert len(matches) == 1
    QTest.mouseClick(matches[0], Qt.LeftButton)


def test_prepare_in_real_worker_and_edit(window, tmp_path):
    widget, app = window
    source = tmp_path / "buch.txt"
    source.write_text("Kapitel 1\n\nDas ist ein langer Satz zum Testen der Textvorbereitung.\n", encoding="utf-8")
    widget.source.setText(str(source))
    widget.prepare()
    deadline = time.monotonic() + 30
    while widget.process is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert widget.process is None, widget.log.toPlainText()
    assert widget.result is not None, widget.log.toPlainText()
    prepared = Path(widget.prepared.text())
    assert prepared.is_file()
    assert "Textvorbereitung" in widget.editor.toPlainText()
    widget.editor.insertPlainText("Geändert. ")
    with pytest.raises(ValueError, match="speichern"):
        widget.prepared_file()
    widget.save_text()
    assert "Geändert." in prepared.read_text(encoding="utf-8")


def test_reference_transcript_and_voice_selection(window, tmp_path):
    widget, _ = window
    ref = tmp_path / "stimme_entwurf_1.wav"
    ref.touch()
    ref.with_suffix(".txt").write_text("Guten Morgen.", encoding="utf-8")
    widget.samples.addItem("probe_entwurf_1.wav")
    widget.samples.item(0).setData(256, str(tmp_path / "probe_entwurf_1.wav"))
    widget.samples.setCurrentRow(0)
    widget.select_sample()
    assert widget.artificial_voice.isChecked()
    assert widget.selected_reference() == ref
    assert widget.ref.text() == ""
    widget.own_voice.setChecked(True)
    widget.ref.setText(str(ref))
    assert widget.transcript.toPlainText() == "Guten Morgen."
    widget.transcript.setPlainText("Guten Abend.")
    widget.save_transcript()
    assert ref.with_suffix(".txt").read_text(encoding="utf-8") == "Guten Abend."


def test_empty_selection_shows_error_on_button_click(window):
    widget, _ = window
    click(widget, "Buch einlesen und Text bereinigen")
    assert "vorhandene Datei" in widget.dialogs[-1]
    assert widget.process is None


def test_file_picker_and_cancel(window, monkeypatch, tmp_path):
    widget, _ = window
    button = widget.source.parentWidget().findChild(QPushButton)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(tmp_path / "buch.epub"), ""))
    QTest.mouseClick(button, Qt.LeftButton)
    assert widget.source.text().endswith("buch.epub")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: ("", ""))
    QTest.mouseClick(button, Qt.LeftButton)
    assert widget.source.text().endswith("buch.epub")


def test_epub_worker(window, tmp_path):
    from test_epub import make_epub
    widget, app = window
    source = tmp_path / "mit Leerzeichen.epub"
    make_epub(source)
    widget.source.setText(str(source))
    click(widget, "Buch einlesen und Text bereinigen")
    wait_worker(widget, app)
    assert widget.result is not None, widget.log.toPlainText()
    assert "# Kapitel 1: Der alte Bahnhof" in widget.editor.toPlainText()
    assert "# Die Nachricht" in widget.editor.toPlainText()
    assert not widget.dialogs


def test_worker_failure_recovers_controls(window, tmp_path):
    widget, app = window
    bad = tmp_path / "bad.epub"
    bad.write_text("Kein EPUB", encoding="utf-8")
    widget.source.setText(str(bad))
    widget.prepare()
    wait_worker(widget, app)
    assert widget.result is None
    assert widget.tabs.isEnabled()
    assert not widget.cancel.isEnabled()
    assert widget.dialogs
    assert widget.progress.value() == 0


def test_cancel_and_run_again(window, tmp_path):
    widget, app = window
    source = tmp_path / "buch.txt"
    source.write_text("# Kapitel 1\n\nEin kurzer Testtext.", encoding="utf-8")
    widget.source.setText(str(source))
    widget.prepare()
    assert not widget.tabs.isEnabled()
    click(widget, "Vorgang abbrechen")
    wait_worker(widget, app)
    assert widget.cancelled
    assert "Abgebrochen" in widget.status.text()
    widget.prepare()
    wait_worker(widget, app)
    assert widget.result is not None


def test_invalid_saved_transcript_does_not_crash(window, tmp_path):
    widget, _ = window
    ref = tmp_path / "stimme.wav"
    ref.touch()
    ref.with_suffix(".txt").write_bytes(b'\xff\xfeinvalid')
    settings = QSettings(str(tmp_path / "broken.ini"), QSettings.IniFormat)
    settings.setValue("ref", str(ref))
    second = Window(settings)
    assert second.transcript.toPlainText() == ""
    second.close()


def test_stale_ffmpeg_setting_does_not_block_text_preparation(window, tmp_path):
    widget, app = window
    widget.ffmpeg.setText(str(tmp_path / "missing" / "ffmpeg.exe"))
    source = tmp_path / "buch.txt"
    source.write_text("Ein Text zum Vorlesen.", encoding="utf-8")
    widget.source.setText(str(source))
    widget.prepare()
    wait_worker(widget, app)
    assert widget.result is not None


def test_empty_book_and_changed_path_block_rendering(window, tmp_path):
    widget, _ = window
    source = tmp_path / "leer.txt"
    source.write_text("  ", encoding="utf-8")
    widget.prepared.setText(str(source))
    with pytest.raises(ValueError, match="leer"):
        widget.prepared_file()
    source.write_text("Ein Satz.", encoding="utf-8")
    widget.load_text()
    widget.editor.insertPlainText("Noch einer.")
    other = tmp_path / "anderer.txt"
    other.write_text("Andere Datei", encoding="utf-8")
    widget.prepared.setText(str(other))
    with pytest.raises(ValueError, match="speichern"):
        widget.prepared_file()


def test_custom_whisper_model_forwarded(window, tmp_path):
    widget, _ = window
    ref = tmp_path / "stimme.wav"
    ref.touch()
    widget.ref.setText(str(ref))
    widget.advanced.setChecked(True)
    widget.stt_model.setText("openai/whisper-tiny")
    args = widget.ref_args()
    assert args[args.index("--modell-stt") + 1] == "openai/whisper-tiny"


def test_own_sample_remembers_original_reference(window, tmp_path):
    widget, _ = window
    first = tmp_path / "erste.wav"
    second = tmp_path / "zweite.wav"
    first.touch()
    second.touch()
    sample = tmp_path / "probe_eigene.wav"
    widget.samples.addItem(sample.name)
    widget.samples.item(0).setData(256, str(sample))
    widget.samples.setCurrentRow(0)
    widget.sample_references[str(sample)] = str(first)
    widget.ref.setText(str(second))
    widget.select_sample()
    assert Path(widget.ref.text()) == first


def test_progress_handles_split_utf8_and_protocol(window):
    widget, _ = window
    class Output:
        def __init__(self):
            self.data = b""
        def readAllStandardOutput(self):
            data, self.data = self.data, b""
            return data
    import codecs
    output = Output()
    widget.process = output
    widget.pending = ""
    widget.decoder = codecs.getincrementaldecoder("utf-8")("replace")
    payload = '\rGUI_PROGRESS={"phase":"test","text":"Prüfung","erledigt":1,"gesamt":2}\n[99.0%] fremde Konsolenausgabe\nGUI_RESULT={"path":"ä.txt"}\n'.encode("utf-8")
    for byte in payload:
        output.data = bytes([byte])
        widget.read_output()
    widget.process = None
    assert widget.progress.value() == 500
    assert widget.result == {"path": "ä.txt"}
    assert "Prüfung" in widget.status.text()


@pytest.mark.parametrize("fmt", ["m4b", "mp3", "mp3-buch", "opus", "wav"])
def test_render_arguments_and_missing_export(window, tmp_path, monkeypatch, fmt):
    widget, _ = window
    book = tmp_path / "buch.txt"
    book.write_text("# Erstes Kapitel\n\nEin kurzer Text.", encoding="utf-8")
    ref = tmp_path / "stimme.wav"
    ref.touch()
    widget.prepared.setText(str(book))
    widget.ref.setText(str(ref))
    widget.transcript.setPlainText("Guten Morgen.")
    widget.destination.setText(str(tmp_path / "Ausgabe"))
    widget.title.setText("CON")
    widget.format.setCurrentIndex(widget.format.findData(fmt))
    monkeypatch.setattr(widget, "check_ffmpeg", lambda: None)
    calls = []
    monkeypatch.setattr(widget, "run", lambda *args: calls.append(args))
    widget.render()
    args, label, done = calls[0]
    assert args[args.index("--format") + 1] == fmt
    output = Path(args[args.index("--ausgabe") + 1])
    assert output.name.startswith("_CON")
    with pytest.raises(ValueError, match="fehlt"):
        done({})
    if fmt in ("mp3", "wav"):
        output.mkdir()
        with pytest.raises(ValueError, match="fehlt"):
            done({})
        (output / ("kapitel." + fmt)).write_bytes(b"audio")
    else:
        output.write_bytes(b"audio")
    done({})
    assert "Hörbuch fertig" in widget.status.text()


def test_changed_voice_description_gets_new_reference_directory(window, tmp_path, monkeypatch):
    widget, _ = window
    book = tmp_path / "buch.txt"
    book.write_text("Ein kurzer Text.", encoding="utf-8")
    widget.prepared.setText(str(book))
    calls = []
    monkeypatch.setattr(widget, "run", lambda *args: calls.append(args))
    widget.design.setText("Ruhige Erzählerin")
    widget.design_samples()
    widget.design.setText("Lebhafter Erzähler")
    widget.design_samples()
    directories = [args[0][args[0].index("--ausgabe") + 1] for args in calls]
    assert len(set(directories)) == 2


def test_voice_choices_are_exclusive_and_preserve_own_recording(window, tmp_path):
    widget, _ = window
    own = tmp_path / "eigene.wav"
    own.touch()
    own.with_suffix(".txt").write_text("Mein eigener Wortlaut.", encoding="utf-8")
    artificial = tmp_path / "entwurf.wav"
    artificial.touch()
    artificial.with_suffix(".txt").write_text("Anderer Wortlaut.", encoding="utf-8")
    widget.ref.setText(str(own))
    widget.artificial_voice.setChecked(True)
    with pytest.raises(ValueError, match="künstliche Stimme"):
        widget.ref_args()
    widget.designed_ref = str(artificial)
    args = widget.ref_args()
    assert str(artificial) in args
    assert "Mein eigener Wortlaut." not in args
    assert widget.voice_pages.currentIndex() == 1
    assert not widget.own_voice.isChecked()
    widget.own_voice.setChecked(True)
    assert widget.voice_pages.currentIndex() == 0
    assert str(own) in widget.ref_args()
    assert "Mein eigener Wortlaut." in widget.ref_args()


def test_play_without_selection_uses_first_sample_or_reference(window, tmp_path, monkeypatch):
    widget, _ = window
    ref = tmp_path / "stimme.wav"
    ref.touch()
    widget.ref.setText(str(ref))
    played = []
    monkeypatch.setattr(widget, "play", lambda path: played.append(path))
    click(widget, "Abspielen")
    assert played == [ref]
    probe = tmp_path / "probe_eigene.wav"
    probe.touch()
    widget.samples.addItem(probe.name)
    widget.samples.item(0).setData(256, str(probe))
    assert widget.samples.currentRow() == -1
    click(widget, "Abspielen")
    assert played[-1] == probe
    assert widget.samples.currentRow() == 0
    assert not widget.dialogs


def test_missing_audio_is_reported_instead_of_silently_ignored(window, tmp_path):
    widget, _ = window
    widget.samples.addItem("fehlt.wav")
    widget.samples.item(0).setData(256, str(tmp_path / "fehlt.wav"))
    click(widget, "Abspielen")
    assert "nicht gefunden" in widget.dialogs[-1]


def test_progress_is_per_phase_and_unknown_work_is_indeterminate(window):
    widget, _ = window
    widget.active_progress = widget.voice_progress
    widget.show_progress({"phase": "probe", "text": "Zwei von vier Hörproben", "erledigt": 2, "gesamt": 4})
    assert widget.progress.value() == 500
    assert widget.voice_progress[1].value() == 500
    widget.show_progress({"phase": "modell", "text": "Modell wird geladen"})
    assert widget.progress.minimum() == widget.progress.maximum() == 0
    assert widget.voice_progress[1].maximum() == 0
    assert "noch nicht messbar" in widget.status.text()
    widget.show_progress({"phase": "export", "text": "Export", "erledigt": 0.1, "gesamt": 1})
    assert widget.progress.value() == 100


def test_real_wav_playback_advances_position(window, tmp_path):
    if QMediaDevices.defaultAudioOutput().isNull():
        pytest.skip("Kein Audioausgabegerät in der Testumgebung")
    import numpy as np
    from hoerbuch.audio import write_wav
    widget, app = window
    path = tmp_path / "probe.wav"
    sr = 24000
    write_wav(path, np.sin(2 * np.pi * 440 * np.arange(sr * 2) / sr).astype("float32") * 0.02, sr)
    widget.samples.addItem(path.name)
    widget.samples.item(0).setData(256, str(path))
    click(widget, "Abspielen")
    deadline = time.monotonic() + 10
    while widget.player.position() < 100 and time.monotonic() < deadline and not widget.dialogs:
        app.processEvents()
        time.sleep(0.02)
    assert widget.player.duration() >= 1900, widget.player.errorString()
    assert widget.player.position() >= 100, widget.player.errorString()
    assert widget.playback_progress.value() >= 100
    assert widget.playback_progress.maximum() == widget.player.duration()
    assert widget.audio.volume() == 1.0
    click(widget, "Aufnahme stoppen")
    assert widget.player.playbackState() == QMediaPlayer.PlaybackState.StoppedState


def test_invalid_callback_never_shows_completed_progress(window, tmp_path):
    widget, app = window
    book = tmp_path / "buch.txt"
    book.write_text("Ein kurzer Satz zum Testen.", encoding="utf-8")
    def validate(_):
        raise ValueError("Ausgabe fehlt")
    widget.run(["bereinigen", str(book)], "Test", validate)
    wait_worker(widget, app)
    assert widget.result is None
    assert widget.progress.value() == 0
    assert widget.book_progress[1].value() == 0
    assert widget.progress.format() == "Fehlgeschlagen"
    assert "Ausgabe fehlt" in widget.dialogs[-1]


def test_new_samples_are_selected_automatically(window, tmp_path, monkeypatch):
    widget, _ = window
    book = tmp_path / "buch.txt"
    book.write_text("Ein kurzer Satz.", encoding="utf-8")
    ref = tmp_path / "ref.wav"
    ref.touch()
    widget.prepared.setText(str(book))
    widget.ref.setText(str(ref))
    captured = []
    monkeypatch.setattr(widget, "run", lambda *args: captured.append(args))
    widget.sample()
    args, _, callback = captured[0]
    directory = Path(args[args.index("--ausgabe") + 1])
    (directory / "probe_eigene.wav").touch()
    callback({})
    assert widget.samples.currentRow() == 0
    assert widget.selected_audio().name == "probe_eigene.wav"


def test_book_editor_resizes_without_outer_scrollbar(window):
    widget, app = window
    assert not isinstance(widget.tabs.widget(0), QScrollArea)
    widget.show()
    widget.resize(1050, 850)
    app.processEvents()
    small = widget.editor.height()
    assert widget.editor.verticalScrollBar().maximum() == 0
    widget.resize(1150, 1000)
    app.processEvents()
    assert widget.editor.height() > small
    widget.editor.setPlainText("Ein langer Text.\n" * 500)
    widget.editor.document().setModified(False)
    app.processEvents()
    assert widget.editor.verticalScrollBar().maximum() > 0
