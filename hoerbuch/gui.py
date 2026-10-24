"""Lokale Desktopoberfläche für den vollständigen Hörbuchablauf."""
from __future__ import annotations

import codecs
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time

from PySide6.QtCore import QProcess, QProcessEnvironment, QSettings, QTimer, QUrl, Qt
from PySide6.QtGui import QColor, QDesktopServices, QFont, QPalette
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QMediaDevices
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSpinBox,
    QTabWidget, QVBoxLayout, QWidget, QRadioButton, QButtonGroup, QStackedWidget, QSlider, QScrollArea, QSizePolicy,
)

from .audio import FORMATE
from .konfig import MAX_CHUNK_CHARS, MODEL_BASE, MODEL_DESIGN, MODEL_KI, MODEL_STT, VOICE_DESIGNS


class Window(QMainWindow):
    def __init__(self, settings=None):
        super().__init__()
        self.setWindowTitle("Hörbuch · Bücher mit deiner Stimme")
        self.resize(1050, 850)
        self.settings = settings if settings is not None else QSettings("hoerbuch", "Desktop")
        self.sample_references = {}
        self.sample_kinds = {}
        self.designed_ref = ""
        self.process = None
        self.callback = None
        self.cancelled = False
        self.started = 0.0
        self.root = Path(__file__).resolve().parent.parent
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setDevice(QMediaDevices.defaultAudioOutput())
        self.audio.setVolume(1.0)
        self.player.setAudioOutput(self.audio)
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        title = QLabel("Dein Buch. Deine Stimme.")
        title.setStyleSheet("font-size: 26px; font-weight: 600; padding: 8px")
        layout.addWidget(title)
        layout.addWidget(QLabel("1  Buch vorbereiten     →     2  Stimme & Hörprobe     →     3  Hörbuch erstellen"))
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self.book_tab()
        self.voice_tab()
        self.output_tab()
        self.status = QLabel("Bereit. Wähle im ersten Schritt ein Buch aus.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addWidget(QLabel("Fortschritt des aktuellen Verarbeitungsschritts:"))
        self.progress = QProgressBar()
        layout.addWidget(self.progress)
        bar = QHBoxLayout()
        self.elapsed = QLabel("")
        bar.addWidget(self.elapsed, 1)
        self.cancel = QPushButton("Vorgang abbrechen")
        self.cancel.setEnabled(False)
        self.cancel.clicked.connect(self.stop)
        bar.addWidget(self.cancel)
        layout.addLayout(bar)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(3000)
        self.log.setMaximumHeight(150)
        self.log.setFixedHeight(100)
        self.log.setPlaceholderText("Hier erscheinen Fortschritt, Hinweise und Fehlermeldungen.")
        layout.addWidget(self.log)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(1000)
        self.player.errorOccurred.connect(self.playback_error)
        self.player.positionChanged.connect(self.update_playback)
        self.player.durationChanged.connect(self.update_playback)
        self.player.playbackStateChanged.connect(self.update_playback)

    def task_progress(self, layout):
        label = QLabel("Bereit")
        label.setWordWrap(True)
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(0)
        bar.setFormat("Noch nicht gestartet")
        layout.addWidget(label)
        layout.addWidget(bar)
        return label, bar

    def tab(self, name, scrollable=True):
        widget = QWidget()
        form = QVBoxLayout(widget)
        if scrollable:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(widget)
            self.tabs.addTab(scroll, name)
        else:
            self.tabs.addTab(widget, name)
        return form

    def path_field(self, form, label, key, file_filter="", directory=False, save=False):
        row = QWidget()
        box = QHBoxLayout(row)
        box.setContentsMargins(0, 0, 0, 0)
        field = QLineEdit(str(self.settings.value(key, "")))
        button = QPushButton("Auswählen …")
        def choose():
            if directory:
                path = QFileDialog.getExistingDirectory(self, label, field.text())
            elif save:
                path, _ = QFileDialog.getSaveFileName(self, label, field.text(), file_filter)
            else:
                path, _ = QFileDialog.getOpenFileName(self, label, field.text(), file_filter)
            if path:
                field.setText(path)
        button.clicked.connect(choose)
        field.textChanged.connect(lambda value: self.settings.setValue(key, value))
        box.addWidget(field, 1)
        box.addWidget(button)
        form.addRow(label, row)
        return field

    def button(self, layout, text, handler):
        button = QPushButton(text)
        button.setMinimumHeight(34)
        button.clicked.connect(lambda: self.guard(handler))
        layout.addWidget(button)
        return button

    def book_tab(self):
        box = self.tab("1 · Buch", scrollable=False)
        form = QFormLayout()
        box.addLayout(form)
        self.source = self.path_field(form, "EPUB oder Textdatei", "source", "Bücher (*.epub *.txt)")
        self.ki = QCheckBox("Zusätzlich mit lokalem Sprachmodell korrigieren (langsamer)")
        box.addWidget(self.ki)
        self.button(box, "Buch einlesen und Text bereinigen", self.prepare)
        self.book_progress = self.task_progress(box)
        form2 = QFormLayout()
        box.addLayout(form2)
        self.prepared = self.path_field(form2, "Vorbereiteter Text", "prepared", "Text (*.txt)")
        self.button(box, "Vorbereiteten Text laden", self.load_text)
        box.addWidget(QLabel("Text prüfen und bearbeiten. Kapitel beginnen mit #, Zwischenüberschriften mit ##."))
        self.editor = QPlainTextEdit()
        self.editor.setMinimumHeight(60)
        self.editor.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.editor.setPlaceholderText("Nach dem Bereinigen erscheint hier dein Buchtext.")
        box.addWidget(self.editor, 1)
        self.button(box, "Bearbeiteten Text speichern", self.save_text)

    def voice_tab(self):
        outer = self.tab("2 · Stimme & Hörprobe")
        columns = QHBoxLayout()
        outer.addLayout(columns, 1)
        box = QVBoxLayout()
        audition = QVBoxLayout()
        columns.addLayout(box, 1)
        columns.addLayout(audition, 1)
        choice = QVBoxLayout()
        self.own_voice = QRadioButton("Eigene Referenzaufnahme verwenden")
        self.artificial_voice = QRadioButton("Künstliche Stimme entwerfen")
        self.voice_modes = QButtonGroup(self)
        self.voice_modes.addButton(self.own_voice)
        self.voice_modes.addButton(self.artificial_voice)
        self.own_voice.setChecked(True)
        choice.addWidget(self.own_voice)
        choice.addWidget(self.artificial_voice)
        box.addLayout(choice)
        self.voice_pages = QStackedWidget()
        own_page = QGroupBox("Eigene Aufnahme · Stimme für dieses Hörbuch")
        own_box = QVBoxLayout(own_page)
        form = QFormLayout()
        own_box.addLayout(form)
        self.ref = self.path_field(form, "Referenzaufnahme", "ref", "WAV-Aufnahme (*.wav)")
        self.ref.textChanged.connect(lambda: self.guard(self.load_transcript))
        hint = QLabel("Ideal: 10–20 Sekunden deutlich gesprochene Sprache ohne Hintergrundgeräusche.")
        hint.setWordWrap(True)
        own_box.addWidget(hint)
        self.transcript = QPlainTextEdit()
        self.transcript.setPlaceholderText("Genauer Wortlaut der Aufnahme – manuell eingeben oder automatisch erkennen lassen.")
        self.transcript.setMaximumHeight(90)
        own_box.addWidget(self.transcript)
        ref_actions = QHBoxLayout()
        self.button(ref_actions, "Aufnahme anhören", lambda: self.play(self.file(self.ref, [".wav"])))
        self.button(ref_actions, "Aufnahme stoppen", self.player.stop)
        self.button(ref_actions, "Wortlaut speichern", self.save_transcript)
        own_box.addLayout(ref_actions)
        generation_actions = QHBoxLayout()
        self.button(generation_actions, "Wortlaut erkennen (Whisper)", self.transcribe)
        self.button(generation_actions, "Hörprobe erzeugen", self.sample)
        own_box.addLayout(generation_actions)
        design_group = QGroupBox("Künstliche Stimme · Alternative zur eigenen Aufnahme")
        design_box = QVBoxLayout(design_group)
        self.design = QLineEdit()
        self.design.setPlaceholderText("Optional: z. B. warme, ruhige Erzählerstimme, mittlere Tonlage")
        design_box.addWidget(self.design)
        self.button(design_box, "Stimmen und Hörproben erzeugen", self.design_samples)
        design_hint = QLabel("Beschreibung leer lassen, um die vier mitgelieferten Stimmen zu vergleichen.\n"
                             "Danach eine Hörprobe auswählen und die Stimme für das Hörbuch übernehmen.")
        design_hint.setWordWrap(True)
        design_box.addWidget(design_hint)
        design_box.addStretch()
        self.voice_pages.addWidget(own_page)
        self.voice_pages.addWidget(design_group)
        box.addWidget(self.voice_pages)
        self.own_voice.toggled.connect(self.voice_mode_changed)
        self.artificial_voice.toggled.connect(self.voice_mode_changed)
        self.voice_summary = QLabel()
        self.voice_summary.setWordWrap(True)
        box.addWidget(self.voice_summary)
        self.voice_progress = self.task_progress(box)
        box = audition
        box.addWidget(QLabel("Hörproben (zum Abspielen doppelklicken):"))
        self.button(box, "Vorhandene Hörprobe öffnen …", self.open_sample)
        self.samples = QListWidget()
        self.samples.itemDoubleClicked.connect(lambda item: self.guard(lambda: self.play(Path(item.data(256)))))
        box.addWidget(self.samples, 1)
        row = QHBoxLayout()
        self.play_button = self.button(row, "Abspielen", self.play_selected)
        self.button(row, "Wiedergabe stoppen", self.player.stop)
        box.addLayout(row)
        self.button(box, "Ausgewählte Stimme übernehmen", self.select_sample)
        self.playback_label = QLabel("Keine Wiedergabe")
        box.addWidget(self.playback_label)
        self.playback_progress = QSlider(Qt.Horizontal)
        self.playback_progress.setRange(0, 0)
        self.playback_progress.sliderMoved.connect(self.player.setPosition)
        box.addWidget(self.playback_progress)
        devices = QHBoxLayout()
        devices.addWidget(QLabel("Audioausgabe:"))
        self.audio_devices = QComboBox()
        self.audio_devices.addItem("Standardgerät", None)
        for device in QMediaDevices.audioOutputs():
            self.audio_devices.addItem(device.description(), device)
        self.audio_devices.currentIndexChanged.connect(self.change_audio_device)
        devices.addWidget(self.audio_devices, 1)
        box.addLayout(devices)
        volume_row = QHBoxLayout()
        volume_row.addWidget(QLabel("Lautstärke:"))
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(100)
        self.volume.valueChanged.connect(lambda value: self.audio.setVolume(value / 100))
        volume_row.addWidget(self.volume)
        box.addLayout(volume_row)
        self.button(box, "Ausgewählte Audiodatei im Standardplayer öffnen", self.external_player)
        # Ein veralteter oder nicht als UTF-8 lesbarer gespeicherter Pfad darf den Start nicht verhindern.
        try:
            self.load_transcript()
        except (OSError, ValueError):
            self.transcript.clear()
        self.voice_mode_changed()

    def output_tab(self):
        box = self.tab("3 · Hörbuch erstellen")
        self.output_voice_summary = QLabel(self.voice_summary.text())
        self.output_voice_summary.setWordWrap(True)
        box.addWidget(self.output_voice_summary)
        form = QFormLayout()
        box.addLayout(form)
        self.title = QLineEdit()
        self.author = QLineEdit()
        form.addRow("Titel", self.title)
        form.addRow("Autor / Autorin", self.author)
        self.destination = self.path_field(form, "Ausgabeordner", "destination", directory=True)
        self.cover = self.path_field(form, "Cover (optional)", "cover", "Bilder (*.jpg *.jpeg *.png)")
        self.format = QComboBox()
        for key, desc in FORMATE.items():
            self.format.addItem(f"{key.upper()} – {desc}", key)
        form.addRow("Ausgabeformat", self.format)
        self.advanced = QGroupBox("Erweiterte Einstellungen aktivieren")
        self.advanced.setCheckable(True)
        self.advanced.setChecked(False)
        advanced = QFormLayout(self.advanced)
        self.model = QLineEdit(MODEL_BASE)
        self.design_model = QLineEdit(MODEL_DESIGN)
        self.ki_model = QLineEdit(MODEL_KI)
        self.stt_model = QLineEdit(MODEL_STT)
        self.chunk = QSpinBox()
        self.chunk.setRange(100, 2000)
        self.chunk.setValue(MAX_CHUNK_CHARS)
        self.temperature = QDoubleSpinBox()
        self.temperature.setRange(0.1, 2.0)
        self.temperature.setSingleStep(0.1)
        self.temperature.setValue(0.8)
        self.bitrate = QComboBox()
        self.bitrate.addItems(["Automatisch", "64k", "96k", "128k", "192k"])
        self.ffmpeg = self.path_field(advanced, "FFmpeg (optional)", "ffmpeg", "FFmpeg (ffmpeg.exe);;Alle Dateien (*)")
        for name, widget in [("Sprachmodell", self.model), ("Stimmentwurf-Modell", self.design_model),
                             ("KI-Textkorrektur", self.ki_model), ("Whisper-Modell", self.stt_model),
                             ("Zeichen pro Abschnitt", self.chunk), ("Temperatur", self.temperature),
                             ("Bitrate", self.bitrate)]:
            advanced.addRow(name, widget)
        box.addWidget(self.advanced)
        box.addWidget(QLabel("Vorhandene Abschnitte werden bei gleichem Text und gleicher Stimme weiterverwendet.\n"
                                "Beim ersten Einsatz werden Modelle heruntergeladen. Das kann mehrere Minuten dauern."))
        self.button(box, "Hörbuch erstellen / fortsetzen", self.render)
        self.output_progress = self.task_progress(box)
        self.button(box, "Ausgabeordner öffnen", self.open_output)
        box.addStretch()

    def guard(self, action):
        try:
            action()
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Bitte prüfen", str(error))

    def file(self, field, suffixes=None):
        path = Path(field.text().strip())
        if not field.text().strip() or not path.is_file():
            raise ValueError("Bitte eine vorhandene Datei auswählen.")
        if suffixes and path.suffix.lower() not in suffixes:
            raise ValueError("Bitte eine Datei mit einer dieser Endungen wählen: " + ", ".join(suffixes))
        return path.resolve()

    def prepared_file(self):
        path = self.file(self.prepared, [".txt"])
        if self.editor.document().isModified():
            raise ValueError("Bitte den bearbeiteten Buchtext zuerst speichern.")
        if not path.read_text(encoding="utf-8-sig").strip():
            raise ValueError("Der Buchtext ist leer. Bitte einen Text mit Inhalt auswählen.")
        return path

    def prepare(self):
        if self.editor.document().isModified():
            raise ValueError("Bitte den bearbeiteten Buchtext zuerst speichern, bevor du ein weiteres Buch einliest.")
        src = self.file(self.source, [".epub", ".txt"])
        args = ["bereinigen", str(src)]
        if self.ki.isChecked():
            args += ["--ki", "--ki-modell", self.ki_model.text() if self.advanced.isChecked() else MODEL_KI]
        def done(result):
            self.prepared.setText(result["path"])
            self.load_text()
        self.run(args, "Buch wird vorbereitet …", done)

    def load_text(self):
        path = self.file(self.prepared, [".txt"])
        if self.editor.document().isModified() and QMessageBox.question(
                self, "Text neu laden?", "Ungespeicherte Textänderungen verwerfen?") != QMessageBox.Yes:
            return
        self.editor.setPlainText(path.read_text(encoding="utf-8-sig"))
        self.loaded_path = path
        self.editor.document().setModified(False)
        if not self.title.text() or getattr(self, "automatic_title", None) == self.title.text():
            self.title.setText(path.stem.replace(".bereinigt", "").replace("_", " "))
            self.automatic_title = self.title.text()
        if not self.destination.text():
            self.destination.setText(str(path.parent))

    def save_text(self):
        path = self.file(self.prepared, [".txt"])
        if getattr(self, "loaded_path", None) != path:
            raise ValueError("Bitte den ausgewählten Text zuerst laden.")
        path.write_text(self.editor.toPlainText(), encoding="utf-8")
        self.editor.document().setModified(False)
        self.status.setText("Buchtext gespeichert.")

    def load_transcript(self):
        txt = Path(self.ref.text()).with_suffix(".txt") if self.ref.text() else None
        self.transcript.setPlainText(txt.read_text(encoding="utf-8-sig") if txt and txt.is_file() else "")
        if hasattr(self, "voice_summary"):
            self.voice_mode_changed()

    def voice_mode_changed(self):
        own = self.own_voice.isChecked()
        self.voice_pages.setCurrentIndex(0 if own else 1)
        reference = self.ref.text().strip() if own else self.designed_ref
        prefix = "Eigene Aufnahme" if own else "Künstliche Stimme"
        self.voice_summary.setText(f"Für dieses Hörbuch: {prefix} · {reference or 'noch keine Stimme ausgewählt'}")
        if hasattr(self, "output_voice_summary"):
            self.output_voice_summary.setText(self.voice_summary.text())

    def selected_reference(self):
        if self.own_voice.isChecked():
            return self.file(self.ref, [".wav"])
        path = Path(self.designed_ref)
        if not self.designed_ref or not path.is_file():
            raise ValueError("Bitte zuerst eine künstliche Stimme entwerfen und mit 'Ausgewählte Stimme übernehmen' auswählen.")
        return path.resolve()

    def save_transcript(self):
        path = self.file(self.ref, [".wav"]).with_suffix(".txt")
        text = self.transcript.toPlainText().strip()
        if not text:
            raise ValueError("Bitte zuerst den Wortlaut erkennen lassen oder eingeben.")
        path.write_text(text, encoding="utf-8")
        self.status.setText(f"Wortlaut gespeichert: {path}")

    def transcribe(self):
        ref = self.file(self.ref, [".wav"])
        self.check_ffmpeg()
        def done(result):
            self.transcript.setPlainText(result["text"])
            self.status.setText("Wortlaut erkannt. Bitte prüfen und anschließend speichern.")
        self.run(["transkribieren", str(ref), self.stt_model.text() if self.advanced.isChecked() else MODEL_STT],
                 "Whisper erkennt den Wortlaut …", done)

    def sample_dir(self):
        path = self.prepared_file().with_suffix("").with_name(self.prepared_file().stem + "_proben")
        path.mkdir(parents=True, exist_ok=True)
        return path

    def ref_args(self, own=False):
        ref = self.file(self.ref, [".wav"]) if own else self.selected_reference()
        args = ["--ref", str(ref)]
        if (own or self.own_voice.isChecked()) and self.transcript.toPlainText().strip():
            args += ["--ref-text", self.transcript.toPlainText().strip()]
        if self.advanced.isChecked():
            args += ["--modell-stt", self.stt_model.text()]
        return args

    def sample(self):
        self.own_voice.setChecked(True)
        src = self.prepared_file()
        args = ["probe", str(src), "--nur-ref", *self.ref_args(own=True)]
        self.start_samples(args)

    def design_samples(self):
        self.artificial_voice.setChecked(True)
        args = ["probe", str(self.prepared_file()), "--nur-design"]
        descriptions = [self.design.text().strip()] if self.design.text().strip() else list(VOICE_DESIGNS.values())
        for description in descriptions:
            args += ["--design", description]
        self.start_samples(args)

    def start_samples(self, args):
        directory = self.sample_dir()
        if "--design" in args:
            description = json.dumps([args[i + 1] for i, value in enumerate(args) if value == "--design"], ensure_ascii=False)
            key = hashlib.sha256(description.encode("utf-8")).hexdigest()[:12]
            directory = directory / ("entwurf_" + key)
            directory.mkdir(parents=True, exist_ok=True)
        original_ref = self.ref.text()
        args += ["--ausgabe", str(directory)]
        if self.advanced.isChecked():
            args += ["--modell", self.model.text(), "--modell-design", self.design_model.text()]
        def done(_):
            self.samples.clear()
            for path in sorted(directory.glob("probe_*.wav")):
                self.samples.addItem(path.name)
                self.samples.item(self.samples.count() - 1).setData(256, str(path))
                reference = Path(original_ref) if path.stem == "probe_eigene" else path.with_name(path.name.replace("probe_", "stimme_", 1))
                self.sample_references[str(path)] = str(reference)
                self.sample_kinds[str(path)] = "own" if path.stem == "probe_eigene" else "design"
            if self.samples.count():
                self.samples.setCurrentRow(0)
        self.run(args, "Hörproben werden erzeugt …", done)

    def play(self, path):
        path = Path(path).resolve()
        if not path.is_file():
            raise ValueError("Die Audiodatei wurde nicht gefunden. Bitte eine vorhandene Hörprobe auswählen.")
        self.audio.setMuted(False)
        self.player.stop()
        self.playing_path = path
        self.playback_label.setText(f"Lade Audiodatei: {path.name}")
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        self.player.play()

    def play_selected(self):
        self.play(self.selected_audio())

    def open_sample(self):
        path, _ = QFileDialog.getOpenFileName(self, "Hörprobe öffnen", self.prepared.text(), "Audio (*.wav *.mp3 *.m4b *.opus)")
        if path:
            self.samples.addItem(Path(path).name)
            item = self.samples.item(self.samples.count() - 1)
            item.setData(256, path)
            self.samples.setCurrentItem(item)
            self.play(Path(path))

    def selected_audio(self):
        item = self.samples.currentItem()
        if item:
            return Path(item.data(256))
        if self.samples.count():
            self.samples.setCurrentRow(0)
            return Path(self.samples.item(0).data(256))
        return self.selected_reference()

    def external_player(self):
        path = self.selected_audio().resolve()
        if not path.is_file() or not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            raise ValueError("Die Audiodatei konnte nicht im Standardplayer geöffnet werden.")

    def change_audio_device(self):
        device = self.audio_devices.currentData()
        self.audio.setDevice(device if device is not None else QMediaDevices.defaultAudioOutput())

    def update_playback(self, *_):
        duration, position = self.player.duration(), self.player.position()
        self.playback_progress.setRange(0, max(0, duration))
        if not self.playback_progress.isSliderDown():
            self.playback_progress.setValue(position)
        state = {QMediaPlayer.PlayingState: "Wiedergabe", QMediaPlayer.PausedState: "Pausiert",
                 QMediaPlayer.StoppedState: "Gestoppt"}[self.player.playbackState()]
        def clock(ms):
            seconds = ms // 1000
            return f"{seconds // 60:02d}:{seconds % 60:02d}"
        name = getattr(self, "playing_path", Path("")).name
        self.playback_label.setText(f"{state}: {name} · {clock(position)} / {clock(duration)}")

    def playback_error(self, *_):
        message = self.player.errorString() or "Unbekannter Wiedergabefehler"
        self.playback_label.setText("Wiedergabe fehlgeschlagen: " + message)
        self.status.setText("Audiofehler: " + message)
        QMessageBox.warning(self, "Audiowiedergabe", message + "\nDu kannst unten ein anderes Ausgabegerät wählen oder die Datei im Standardplayer öffnen.")

    def select_sample(self):
        item = self.samples.currentItem()
        if not item:
            raise ValueError("Bitte zuerst eine Hörprobe auswählen.")
        path = Path(item.data(256))
        reference = Path(self.sample_references.get(str(path), str(path.with_name(path.name.replace("probe_", "stimme_", 1)))))
        if not reference.is_file():
            raise ValueError("Die zugehörige Referenzstimme wurde nicht gefunden.")
        kind = self.sample_kinds.get(str(path), "own" if path.stem == "probe_eigene" else "design")
        if kind == "own":
            self.ref.setText(str(reference))
            self.own_voice.setChecked(True)
        else:
            self.designed_ref = str(reference)
            self.artificial_voice.setChecked(True)
        self.voice_mode_changed()
        self.status.setText("Stimme übernommen. Du kannst jetzt das Hörbuch erstellen.")

    def environment(self):
        env = QProcessEnvironment.systemEnvironment()
        entries = [env.value("PATH")]
        if self.ffmpeg.text().strip() and Path(self.ffmpeg.text().strip()).is_file():
            entries.insert(0, str(Path(self.ffmpeg.text().strip()).resolve().parent))
        # Auch bei aus älteren Windows-Prozessen geerbtem PATH den Benutzer-PATH einlesen.
        if sys.platform == "win32":
            import winreg
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                    entries.append(os.path.expandvars(winreg.QueryValueEx(key, "Path")[0]))
            except OSError:
                pass
        env.insert("PATH", os.pathsep.join(entries))
        env.insert("PYTHONIOENCODING", "utf-8")
        return env

    def check_ffmpeg(self):
        if not shutil.which("ffmpeg", path=self.environment().value("PATH")):
            raise ValueError("FFmpeg wurde nicht gefunden. Wähle unter Erweiterte Einstellungen die ffmpeg.exe aus.")

    def render(self):
        src = self.prepared_file()
        fmt = self.format.currentData()
        if fmt != "wav":
            self.check_ffmpeg()
        destination = Path(self.destination.text().strip())
        if not self.destination.text().strip():
            raise ValueError("Bitte einen Ausgabeordner wählen.")
        destination.mkdir(parents=True, exist_ok=True)
        stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", self.title.text().strip() or src.stem).rstrip(". ")
        if not stem:
            raise ValueError("Bitte einen gültigen Titel eingeben.")
        if stem.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *[f"{p}{i}" for p in ("COM", "LPT") for i in range(1, 10)]}:
            stem = "_" + stem
        ending = {"m4b": ".m4b", "mp3-buch": ".mp3", "opus": ".opus"}.get(fmt, "_" + fmt)
        output = destination / (stem + ending)
        if output.exists() and QMessageBox.question(self, "Ausgabe vorhanden", "Vorhandene Ausgabe überschreiben?") != QMessageBox.Yes:
            return
        args = ["vertonen", str(src), *self.ref_args(), "--format", fmt, "--ausgabe", str(output),
                "--arbeitsordner", str(src.with_suffix("")) + "_audio", "--ohne-bereinigung"]
        for flag, value in [("--titel", self.title.text()), ("--autor", self.author.text())]:
            if value.strip():
                args += [flag, value.strip()]
        if self.cover.text().strip():
            args += ["--cover", str(self.file(self.cover))]
        if self.advanced.isChecked():
            args += ["--modell", self.model.text(), "--abschnitt", str(self.chunk.value()),
                     "--temperatur", str(self.temperature.value())]
            if self.bitrate.currentIndex():
                args += ["--bitrate", self.bitrate.currentText()]
        def done(_):
            valid = output.is_file() and output.stat().st_size > 0
            if output.is_dir():
                valid = any(p.stat().st_size > 0 for p in output.glob("*." + fmt))
            if not valid:
                raise ValueError("Die Verarbeitung meldet Erfolg, aber die erwartete Ausgabedatei fehlt. Bitte das Protokoll prüfen.")
            self.status.setText(f"Hörbuch fertig: {output}")
        self.run(args, "Hörbuch wird erstellt …", done)

    def open_output(self):
        path = Path(self.destination.text())
        if not self.destination.text() or not path.is_dir():
            raise ValueError("Bitte einen vorhandenen Ausgabeordner auswählen.")
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))

    def run(self, args, label, callback):
        if self.process is not None:
            raise ValueError("Es läuft bereits ein Vorgang.")
        env = self.environment()
        self.player.stop()
        self.callback = callback
        self.cancelled = False
        self.result = None
        self.pending = ""
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.started = time.monotonic()
        self.elapsed.setText("Verstrichen: 00:00:00")
        self.log.clear()
        self.status.setText(label)
        self.progress.setRange(0, 0)
        self.progress.setFormat("In Arbeit · Fortschritt noch nicht messbar")
        self.active_progress = (self.book_progress if args[0] in ("bereinigen", "exportieren") else
                                self.output_progress if args[0] == "vertonen" else self.voice_progress)
        self.active_progress[0].setText(label + " · Fortschritt noch nicht messbar")
        self.active_progress[1].setRange(0, 0)
        self.cancel.setEnabled(True)
        self.tabs.setEnabled(False)
        process = QProcess(self)
        self.process = process
        process.setWorkingDirectory(str(self.root))
        process.setProcessEnvironment(env)
        process.setProcessChannelMode(QProcess.MergedChannels)
        process.readyReadStandardOutput.connect(self.read_output)
        process.finished.connect(self.finished)
        process.errorOccurred.connect(self.process_error)
        executable = Path(sys.executable)
        if executable.name.lower() == "pythonw.exe":
            executable = executable.with_name("python.exe")
        process.start(str(executable), ["-u", "-m", "hoerbuch.gui_worker", *args])

    def read_output(self):
        if self.process is None:
            return
        self.pending += self.decoder.decode(bytes(self.process.readAllStandardOutput()))
        lines = re.split(r"[\r\n]", self.pending)
        self.pending = lines.pop()
        for line in lines:
            if not line:
                continue
            if line.startswith("GUI_RESULT="):
                try:
                    self.result = json.loads(line.removeprefix("GUI_RESULT="))
                    continue
                except json.JSONDecodeError:
                    pass
            if line.startswith("GUI_PROGRESS="):
                try:
                    self.show_progress(json.loads(line.removeprefix("GUI_PROGRESS=")))
                    continue
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass
            self.log.appendPlainText(line)

    def show_progress(self, event):
        text = str(event["text"])
        bars = [self.progress]
        if getattr(self, "active_progress", None):
            self.active_progress[0].setText(text)
            bars.append(self.active_progress[1])
        self.status.setText(text)
        total, done = event.get("gesamt"), event.get("erledigt")
        measured = isinstance(total, (int, float)) and total > 0 and isinstance(done, (int, float))
        for bar in bars:
            if measured:
                bar.setRange(0, 1000)
                bar.setValue(round(max(0, min(1, done / total)) * 1000))
                bar.setFormat("%p% dieses Schritts")
            else:
                bar.setRange(0, 0)
                bar.setFormat("In Arbeit · Fortschritt noch nicht messbar")
        if not measured:
            self.status.setText(text + " · Fortschritt noch nicht messbar")
            if getattr(self, "active_progress", None):
                self.active_progress[0].setText(self.status.text())

    def process_error(self, error):
        if error == QProcess.FailedToStart:
            self.log.appendPlainText(self.process.errorString())
            self.finished(-1, QProcess.CrashExit)

    def finished(self, code, exit_status):
        if self.process is None:
            return
        self.read_output()
        if self.pending:
            self.log.appendPlainText(self.pending)
        self.process.deleteLater()
        self.process = None
        self.tabs.setEnabled(True)
        self.cancel.setEnabled(False)
        self.progress.setRange(0, 100)
        if self.cancelled:
            self.progress.setValue(0)
            self.status.setText("Abgebrochen. Gespeicherte Hörbuchabschnitte bleiben zum Fortsetzen erhalten.")
        elif code == 0 and self.result is not None:
            try:
                self.callback(self.result)
            except (OSError, ValueError, KeyError) as error:
                self.result = None
                self.status.setText("Verarbeitung konnte nicht abgeschlossen werden: " + str(error))
                QMessageBox.warning(self, "Bitte prüfen", str(error))
            else:
                self.progress.setValue(100)
                if not self.status.text().startswith(("Hörbuch fertig:", "Wortlaut erkannt.")):
                    self.status.setText("Vorgang abgeschlossen.")
        else:
            self.progress.setValue(0)
            self.status.setText("Vorgang fehlgeschlagen. Details stehen im Protokoll.")
            QMessageBox.warning(self, "Verarbeitung fehlgeschlagen", self.log.toPlainText()[-2500:])
        success = not self.cancelled and code == 0 and self.result is not None
        for bar in (self.progress, self.active_progress[1]):
            bar.setRange(0, 100)
            bar.setValue(100 if success else 0)
            bar.setFormat("Abgeschlossen" if success else "Abgebrochen" if self.cancelled else "Fehlgeschlagen")
        self.active_progress[0].setText(self.status.text())

    def tick(self):
        if self.process is not None:
            seconds = int(time.monotonic() - self.started)
            self.elapsed.setText(f"Verstrichen: {seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}")

    def stop(self):
        if self.process is not None:
            self.cancelled = True
            self.cancel.setEnabled(False)
            self.process.kill()

    def closeEvent(self, event):
        if self.process is not None:
            QMessageBox.information(self, "Verarbeitung läuft", "Bitte den Vorgang zuerst abschließen oder abbrechen.")
            event.ignore()
            return
        if self.editor.document().isModified() and QMessageBox.question(
                self, "Ungespeicherter Buchtext", "Ohne Speichern schließen?") != QMessageBox.Yes:
            event.ignore()
            return
        self.player.stop()
        event.accept()


def apply_theme(app):
    """Feste helle Palette verhindert weiße Systemschrift auf hellen Feldern."""
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    palette = QPalette()
    for role, color in {
        QPalette.Window: "#e8edf3", QPalette.WindowText: "#172536",
        QPalette.Base: "#ffffff", QPalette.AlternateBase: "#edf2f7",
        QPalette.Text: "#172536", QPalette.Button: "#dce5ef",
        QPalette.ButtonText: "#172536", QPalette.Highlight: "#164f86",
        QPalette.HighlightedText: "#ffffff", QPalette.PlaceholderText: "#536477",
        QPalette.ToolTipBase: "#172536", QPalette.ToolTipText: "#ffffff",
    }.items():
        palette.setColor(role, QColor(color))
    for role in (QPalette.Text, QPalette.WindowText, QPalette.ButtonText):
        palette.setColor(QPalette.Disabled, role, QColor("#596779"))
    app.setPalette(palette)
    app.setStyleSheet("""
        QWidget { color: #172536; }
        QMainWindow { background: #e8edf3; }
        QTabWidget::pane { background: #f8fafc; border: 1px solid #73849a; }
        QTabBar::tab { padding: 10px 20px; background: #dce5ef;
                      border: 1px solid #73849a; color: #172536; }
        QTabBar::tab:selected { background: #164f86; color: white; font-weight: bold; }
        QPushButton { padding: 6px 12px; background: #164f86; color: white;
                      border: 1px solid #103f6b; border-radius: 4px; }
        QPushButton:hover { background: #2068aa; }
        QPushButton:pressed { background: #103f6b; }
        QPushButton:disabled { background: #dce2e9; color: #596779; border-color: #9aa7b6; }
        QPushButton:focus { border: 2px solid #d59100; }
        QLineEdit, QPlainTextEdit, QListWidget, QComboBox, QSpinBox, QDoubleSpinBox {
            background: white; color: #172536; border: 1px solid #73849a;
            border-radius: 3px; padding: 4px; selection-background-color: #164f86;
            selection-color: white;
        }
        QLineEdit:focus, QPlainTextEdit:focus, QListWidget:focus { border: 2px solid #164f86; }
        QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {
            background: #e4e9ef; color: #596779;
        }
        QListWidget::item:selected { background: #164f86; color: white; }
        QComboBox QAbstractItemView { background: white; color: #172536;
                                    selection-background-color: #164f86; selection-color: white; }
        QGroupBox { border: 1px solid #73849a; border-radius: 4px; margin-top: 12px; padding-top: 12px; }
        QGroupBox::title { subcontrol-origin: margin; padding: 0 5px; }
        QProgressBar { text-align: center; min-height: 20px; background: white;
                       color: #172536; border: 1px solid #73849a; border-radius: 3px; }
        QProgressBar::chunk { background: #65a9d8; }
        QToolTip { background: #172536; color: white; border: 1px solid #73849a; }
    """)


def main():
    app = QApplication(sys.argv)
    apply_theme(app)
    window = Window()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
