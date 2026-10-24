"""Kommandozeile: Argumente einlesen und den passenden Unterbefehl aufrufen."""
from __future__ import annotations

import argparse
import sys

from .audio import BITRATE_STANDARD, FORMATE
from .befehle import cmd_bereinigen, cmd_exportieren, cmd_probe, cmd_stimme, cmd_vertonen
from .epub import EPUB_SKIP_DEFAULT
from .konfig import (BACKEND, DEFAULT_VOICE, DESIGN_SEED, MAX_CHUNK_CHARS, MODEL_BASE, MODEL_DESIGN,
                     MODEL_KI, MODEL_STT)

EPILOG = """\
Ablauf:
  hoerbuch exportieren buch.epub            EPUB → buch.txt mit Kapitelmarken
  hoerbuch bereinigen buch.txt [--ki]       → buch.bereinigt.txt (Kapitel als "# "-Zeilen)
  hoerbuch probe buch.bereinigt.txt         Stimmen entwerfen, Hörproben in probe/
  hoerbuch stimme aufnahme.wav --text "…"   eigene Aufnahme als Standardstimme (optional)
  hoerbuch vertonen buch.bereinigt.txt --ref probe/stimme_erzaehler_m.wav
                                            → buch.bereinigt.m4b (Ctrl-C und später fortsetzen)
Ausführliche Anleitung: README.md
"""


def run_command():
    # Umlaute und Sonderzeichen auch dann ausgeben, wenn die Konsole (z. B. unter Windows bei
    # Umleitung in eine Datei) nicht auf UTF-8 steht.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure") and (stream.encoding or "").lower().replace("-", "") != "utf8":
            stream.reconfigure(encoding="utf-8", errors="replace")
    backend_info = ("mlx-audio auf Apple Silicon" if BACKEND == "mlx"
                    else "qwen-tts/PyTorch (CUDA-Grafikkarte empfohlen)")
    p = argparse.ArgumentParser(
        prog="hoerbuch",
        description=f"EPUB oder TXT → deutsches Hörbuch (M4B) mit Qwen3-TTS über {backend_info}.",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=EPILOG)
    sub = p.add_subparsers(dest="befehl", required=True)

    e = sub.add_parser("exportieren", help="EPUB → Textdatei mit Kapitelmarken")
    e.add_argument("datei", help="EPUB-Datei")
    e.add_argument("--ausgabe", help="Zieldatei (Standard: <Buchtitel>.txt neben dem EPUB)")
    e.add_argument("--ohne", help="Regex für auszulassende Dokumente (Dateiname oder Kapitelname), "
                                  f"Standard: {EPUB_SKIP_DEFAULT!r}; leer = nichts auslassen")
    e.add_argument("--ohne-intro", action="store_true", help="keine Ansage von Titel und Autor am Anfang")
    e.set_defaults(func=cmd_exportieren)

    b = sub.add_parser("bereinigen", help="Text (TXT oder EPUB) für die Sprachausgabe säubern")
    b.add_argument("datei", help="Textdatei oder EPUB")
    b.add_argument("--ausgabe", help="nur bei EPUB: Zieldatei des Exports")
    b.add_argument("--ohne", help="nur bei EPUB: Regex für auszulassende Dokumente")
    b.add_argument("--ohne-intro", action="store_true", help="nur bei EPUB: keine Titelansage")
    b.add_argument("--ziffern-lassen", action="store_true",
                   help="Zahlen nicht als Zahlwörter ausschreiben")
    b.add_argument("--ki", action="store_true",
                   help="zweite Stufe mit lokalem Sprachmodell: Zahlen, Daten, Abkürzungen, "
                        "OCR-Fehler, Überschriften (dauert deutlich länger)")
    b.add_argument("--ki-modell", default=MODEL_KI, help=f"Sprachmodell für --ki (Standard {MODEL_KI})")
    b.add_argument("--ki-protokoll", help="Protokolldatei der KI-Änderungen (Standard: DATEI.ki-protokoll.txt)")
    b.add_argument("--ki-bloecke", type=int, help="nur die ersten N Textblöcke prüfen (Probelauf)")
    b.add_argument("--ki-ueberschriften", action="store_true",
                   help="Modell auch nach unerkannten Kapitelüberschriften suchen lassen "
                        "(nur für Texte ohne Kapitelmarken sinnvoll)")
    b.add_argument("--verbose", action="store_true", help="Modellantworten anzeigen")
    b.set_defaults(func=cmd_bereinigen)

    pr = sub.add_parser("probe", help="Stimmen entwerfen und Hörproben erzeugen")
    pr.add_argument("datei", help="(bereinigte) Textdatei")
    pr.add_argument("--ref", help="eigene Referenzaufnahme (WAV, 10–20 s)")
    pr.add_argument("--ref-text", help="genauer Wortlaut der eigenen Referenzaufnahme "
                                       "(sonst aus gleichnamiger .txt, sonst mit Whisper mitgeschrieben)")
    pr.add_argument("--nur-ref", action="store_true",
                    help="keine Stimmen entwerfen, nur die eigene Referenz testen")
    pr.add_argument("--modell-stt", default=MODEL_STT, help="Whisper-Modell für fehlenden Referenztext")
    pr.add_argument("--design", action="append", metavar="BESCHREIBUNG",
                    help="zusätzliche Stimme nach eigener Beschreibung entwerfen (mehrfach möglich; "
                         "Alter, Tonlage, Klang, Tempo, Haltung – keine Personennamen). "
                         "Dateien heißen stimme_entwurf_1.wav, stimme_entwurf_2.wav …")
    pr.add_argument("--nur-design", action="store_true",
                    help="nur die mit --design beschriebenen Stimmen entwerfen, nicht die eingebauten")
    pr.add_argument("--seed", type=int,
                    help=f"anderer Startwert für den Stimmentwurf (Standard {DESIGN_SEED}); "
                         "liefert eine andere Variante derselben Beschreibung")
    pr.add_argument("--ausgabe", help="Ordner für die Proben (Standard: probe)")
    pr.add_argument("--modell", default=MODEL_BASE, help=f"TTS-Modell (Standard {MODEL_BASE})")
    pr.add_argument("--modell-design", default=MODEL_DESIGN,
                    help=f"VoiceDesign-Modell (Standard {MODEL_DESIGN})")
    pr.add_argument("--verbose", action="store_true")
    pr.set_defaults(func=cmd_probe)

    st = sub.add_parser("stimme", help="eigene Aufnahme als Standardstimme einrichten")
    st.add_argument("datei", help="Aufnahme (WAV/M4A/MP3, 10–20 s, ruhig gesprochen)")
    st.add_argument("--text", help="genauer Wortlaut der Aufnahme (sonst aus gleichnamiger .txt, "
                                   "sonst mit Whisper mitgeschrieben)")
    st.add_argument("--ziel", help=f"Speicherort (Standard {DEFAULT_VOICE})")
    st.add_argument("--modell-stt", default=MODEL_STT,
                    help=f"Spracherkennung für den Wortlaut (Standard {MODEL_STT})")
    st.set_defaults(func=cmd_stimme)

    v = sub.add_parser("vertonen", help="ganzes Buch vertonen")
    v.add_argument("datei", help="(bereinigte) Textdatei")
    v.add_argument("--ref", help="Referenzstimme (WAV), z. B. probe/stimme_erzaehler_m.wav; "
                                 "Standard: eingerichtete eigene Stimme")
    v.add_argument("--ref-text", help="Wortlaut der Referenz (sonst aus gleichnamiger .txt, "
                                      "sonst mit Whisper mitgeschrieben)")
    v.add_argument("--titel", help="Titel des Hörbuchs")
    v.add_argument("--modell-stt", default=MODEL_STT, help="Whisper-Modell für fehlenden Referenztext")
    v.add_argument("--autor", help="Autor, wird als Interpret in die Datei geschrieben")
    v.add_argument("--cover", help="Coverbild (JPG/PNG), eingebettet in M4B und MP3")
    v.add_argument("--format", choices=list(FORMATE), default="m4b",
                   help="Ausgabeformat: " + "; ".join(f"{k} = {v}" for k, v in FORMATE.items()))
    v.add_argument("--bitrate", help="Bitrate der Ausgabe, z. B. 96k (Standard: "
                                     + ", ".join(f"{k} {v}" for k, v in BITRATE_STANDARD.items()) + ")")
    v.add_argument("--ausgabe", help="Ausgabedatei bzw. -ordner")
    v.add_argument("--arbeitsordner", help="Ordner für Zwischendateien")
    v.add_argument("--abschnitt", type=int, default=MAX_CHUNK_CHARS,
                   help=f"max. Zeichen pro Abschnitt (Standard {MAX_CHUNK_CHARS})")
    v.add_argument("--temperatur", type=float, default=0.8,
                   help="niedriger = gleichmäßiger, höher = lebendiger (Standard 0.8)")
    v.add_argument("--ohne-bereinigung", action="store_true")
    v.add_argument("--modell", default=MODEL_BASE, help=f"TTS-Modell (Standard {MODEL_BASE})")
    v.add_argument("--verbose", action="store_true")
    v.set_defaults(func=cmd_vertonen)

    args = p.parse_args()
    return args.func(args)


def main():
    # Console-Script-Launcher übergibt diesen Rückgabewert an sys.exit.
    # Dateipfade sind Ergebnisse für die GUI, keine CLI-Exitcodes.
    run_command()
