"""Messwerte werden nur nach real erledigter Arbeit als Fortschritt gemeldet."""
import shutil
import subprocess
import sys
import json

import numpy as np
import pytest

from hoerbuch.audio import build_output, write_wav, _export_ffmpeg
from hoerbuch.fortschritt import aktiv, beobachten, melden


def test_listener_is_optional_and_scoped():
    assert not aktiv()
    events = []
    with beobachten(events.append):
        melden("modell", "Laden")
        melden("test", "Erledigt", 2, 4)
    assert not aktiv()
    melden("test", "Keine Ausgabe")
    assert events == [{"phase": "modell", "text": "Laden"},
                      {"phase": "test", "text": "Erledigt", "erledigt": 2, "gesamt": 4}]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg fehlt")
@pytest.mark.parametrize("fmt", ["m4b", "mp3", "mp3-buch", "opus", "wav"])
def test_real_export_progress_is_monotonic_and_finishes_after_success(tmp_path, fmt):
    chapters = []
    sr = 24000
    for n in range(2):
        path = tmp_path / f"kapitel_{n}.wav"
        write_wav(path, np.zeros(sr, dtype="float32"), sr)
        chapters.append((f"Kapitel {n + 1}", path, 1.0))
    events = []
    with beobachten(events.append):
        build_output(chapters, tmp_path / "buch.txt", "Buch", fmt=fmt)
    progress = [e["erledigt"] / e["gesamt"] for e in events if "gesamt" in e]
    assert progress[0] == 0
    assert progress[-1] == 1
    assert progress == sorted(progress)
    if fmt != "wav":
        assert any(0 < value < 1 for value in progress)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg fehlt")
def test_failed_encoder_never_reports_finished(tmp_path):
    events = []
    command = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=0.1",
               str(tmp_path / "missing" / "ausgabe.wav")]
    with beobachten(events.append), pytest.raises(subprocess.CalledProcessError):
        _export_ffmpeg(command, 0.1)
    assert not any(e.get("erledigt") == e.get("gesamt") for e in events if "gesamt" in e)


def test_synthesis_and_resume_report_saved_text_and_chapters(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from hoerbuch import befehle
    ref = tmp_path / "stimme.wav"
    write_wav(ref, np.zeros(24000, dtype="float32"), 24000)
    ref.with_suffix(".txt").write_text("Ein Referenzsatz.", encoding="utf-8")
    book = tmp_path / "buch.txt"
    book.write_text("# Erstes Kapitel\n\nEin kurzer Absatz zum Testen.\n\nNoch ein kurzer Absatz zum Testen.", encoding="utf-8")
    calls = []
    class Voice:
        sample_rate = 24000
        def __init__(self, *args, **kwargs):
            pass
        def close(self):
            pass
    def synth(*args, **kwargs):
        calls.append(args)
        return np.zeros(2400, dtype="float32"), None
    monkeypatch.setattr(befehle, "Voice", Voice)
    monkeypatch.setattr(befehle, "synth_checked", synth)
    args = SimpleNamespace(datei=str(book), ref=str(ref), ref_text=None, ohne_bereinigung=True,
                           titel="Buch", abschnitt=350, arbeitsordner=str(tmp_path / "arbeit"),
                           modell="test", verbose=False, temperatur=0.8, format="wav", ausgabe=str(tmp_path / "ausgabe"),
                           cover=None, autor=None, bitrate=None)
    events = []
    with beobachten(events.append):
        befehle.cmd_vertonen(args)
    values = [e["erledigt"] / e["gesamt"] for e in events if e["phase"] == "vertonen"]
    assert values[0] == 0 and values[-1] == 1
    assert values == sorted(values)
    assert any(e["phase"] == "kapitel" and e["erledigt"] == e["gesamt"] for e in events)
    original_calls = len(calls)
    events.clear()
    with beobachten(events.append):
        befehle.cmd_vertonen(args)
    assert len(calls) == original_calls
    resumed = [e for e in events if e["phase"] == "vertonen"]
    assert resumed[0]["erledigt"] == resumed[0]["gesamt"]


def test_console_entrypoint_keeps_success_exit_code(tmp_path):
    book = tmp_path / "buch.txt"
    book.write_text("Ein kurzer Satz zum Vorlesen.", encoding="utf-8")
    run = subprocess.run([sys.executable, "-c", "import sys; from hoerbuch.cli import main; sys.exit(main())",
                          "bereinigen", str(book)], capture_output=True, encoding="utf-8", timeout=30)
    assert run.returncode == 0, run.stderr
    assert book.with_name("buch.bereinigt.txt").is_file()
    assert "GUI_PROGRESS=" not in run.stdout


def test_gui_worker_returns_path_and_structured_progress(tmp_path):
    book = tmp_path / "buch.txt"
    book.write_text("Ein kurzer Satz zum Vorlesen.", encoding="utf-8")
    run = subprocess.run([sys.executable, "-m", "hoerbuch.gui_worker", "bereinigen", str(book)],
                         capture_output=True, encoding="utf-8", timeout=30)
    assert run.returncode == 0, run.stderr
    result = next(line for line in run.stdout.splitlines() if line.startswith("GUI_RESULT="))
    assert json.loads(result.split("=", 1)[1])["path"] == str(book.with_name("buch.bereinigt.txt"))
    assert "GUI_PROGRESS=" in run.stdout
