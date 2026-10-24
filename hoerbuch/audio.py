"""WAV lesen/schreiben, Pegel normalisieren, Stille kürzen, M4B/MP3 mit ffmpeg bauen."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import wave
from pathlib import Path

from .hilfen import fmt_dur
from .konfig import FFMPEG_HINT, MAX_PEAK_DB, TARGET_RMS_DB
from .fortschritt import aktiv, melden


def _export_ffmpeg(cmd, duration, offset=0.0, total=None):
    """FFmpeg meldet tatsächlich codierte Audiozeit; 100 % erst nach erfolgreichem Ende."""
    if not aktiv():
        subprocess.run(cmd, check=True)
        return
    total = total or duration
    melden("export", "Audio wird exportiert", offset, total)
    progress_cmd = cmd[:1] + ["-progress", "pipe:1", "-nostats"] + cmd[1:]
    with subprocess.Popen(progress_cmd, stdout=subprocess.PIPE, text=True, encoding="utf-8", errors="replace") as process:
        for line in process.stdout:
            key, _, value = line.strip().partition("=")
            if key == "out_time_us":
                try:
                    elapsed = max(0, min(float(value) / 1_000_000, duration))
                except ValueError:
                    continue
                # Der Encoder kann vor Schreiben des Dateikopfs schon die volle Audiozeit melden.
                melden("export", "Audio wird exportiert", min(offset + elapsed, total * 0.999), total)
        if process.wait():
            raise subprocess.CalledProcessError(process.returncode, progress_cmd)
    melden("export", "Audioexport gespeichert", offset + duration, total)

def normalize_level(audio, target_rms_db: float = TARGET_RMS_DB, max_peak_db: float = MAX_PEAK_DB):
    """Statische Verstärkung auf Ziel-RMS, begrenzt durch den maximalen Spitzenpegel."""
    import numpy as np
    if audio.size == 0:
        return audio
    rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))
    peak = float(np.max(np.abs(audio)))
    if rms < 1e-6 or peak < 1e-6:
        return audio
    gain = 10 ** (target_rms_db / 20) / rms
    gain = min(gain, 10 ** (max_peak_db / 20) / peak)
    return (audio * gain).astype(np.float32)


def trim_silence(audio, sr: int, thresh: float = 0.01, keep: float = 0.05):
    import numpy as np
    if audio.size == 0:
        return audio
    idx = np.where(np.abs(audio) > thresh)[0]
    if idx.size == 0:
        return audio[:0]
    pad = int(keep * sr)
    return audio[max(0, idx[0] - pad): min(audio.size, idx[-1] + pad)]


def write_wav(path: Path, audio, sr: int):
    import numpy as np
    a = np.clip(audio, -1.0, 1.0)
    pcm = (a * 32767).astype("<i2")
    tmp = path.with_suffix(".tmp.wav")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    os.replace(tmp, path)


def lade_mono(pfad: Path, rate: int):
    """Beliebige Audiodatei über ffmpeg als Mono-float32 mit der gewünschten Abtastrate einlesen."""
    import numpy as np
    if not shutil.which("ffmpeg"):
        raise SystemExit(f"ffmpeg fehlt ({FFMPEG_HINT}).")
    roh = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(pfad),
                          "-ac", "1", "-ar", str(rate), "-f", "f32le", "-"],
                         check=True, capture_output=True).stdout
    return np.frombuffer(roh, dtype=np.float32).copy()


def read_wav(path: Path):
    import numpy as np
    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    return data.astype(np.float32) / 32767, sr


# Ausgabeformate: Name → Beschreibung für die Hilfe. Alle außer "wav" brauchen ffmpeg.
FORMATE = {
    "m4b": "eine Datei (AAC) mit Kapitelmarken und Cover, für Apple Books und die meisten Hörbuch-Apps",
    "mp3": "eine MP3-Datei je Kapitel, mit Cover",
    "mp3-buch": "eine MP3-Datei mit Kapitelmarken (ID3) und Cover",
    "opus": "eine Opus-Datei mit Kapitelmarken, etwa halb so groß wie M4B (kein Cover)",
    "wav": "eine WAV-Datei je Kapitel, unkomprimiert, ohne ffmpeg",
}
BITRATE_STANDARD = {"m4b": "64k", "mp3": "64k", "mp3-buch": "64k", "opus": "32k"}


def sicherer_name(titel: str, n: int) -> str:
    """Kapiteltitel als Dateiname: nur unbedenkliche Zeichen, unter Windows kein Punkt oder
    Leerzeichen am Ende, höchstens 60 Zeichen."""
    return re.sub(r"[^\w äöüÄÖÜß.-]", "", titel)[:60].strip(" .") or f"Kapitel {n}"


def _esc(s: str) -> str:
    """Sonderzeichen für das ffmetadata-Format maskieren."""
    return re.sub(r"([=;#\\\n])", r"\\\1", s)


def ffmetadata(chapter_files, title: str, autor: str | None = None) -> str:
    """Metadaten-Datei für ffmpeg: Titel, Autor, Genre und eine Kapitelmarke je Kapitel."""
    meta = [";FFMETADATA1", f"title={_esc(title)}", "genre=Hörbuch"]
    if autor:
        meta += [f"artist={_esc(autor)}", f"album_artist={_esc(autor)}", f"album={_esc(title)}"]
    pos = 0
    total = 0.0
    for t, _, dur in chapter_files:
        start = pos
        total += dur
        pos = int(round(total * 1000))
        meta += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={start}", f"END={pos}", f"title={_esc(t)}"]
    return "\n".join(meta) + "\n"


def _tags(title: str, autor: str | None, **extra) -> list[str]:
    tags = {"title": title, "genre": "Hörbuch", **extra}
    if autor:
        tags.update(artist=autor, album_artist=autor)
    out = []
    for k, v in tags.items():
        out += ["-metadata", f"{k}={v}"]
    return out


def _cover_args(cover: str | None, fmt: str, index: int) -> list[str]:
    """Cover als eingebettetes Bild; index = Nummer des Cover-Eingangs im ffmpeg-Aufruf."""
    if not cover:
        return []
    if fmt == "m4b":
        return ["-map", f"{index}:v", "-c:v", "mjpeg", "-disposition:v", "attached_pic"]
    # MP3: ID3-Bild (APIC); JPEG und PNG werden unverändert eingebettet
    return ["-map", f"{index}:v", "-c:v", "copy", "-id3v2_version", "3",
            "-metadata:s:v", "title=Album cover", "-metadata:s:v", "comment=Cover (front)"]


def build_output(chapter_files, src: Path, title: str, *, fmt: str = "m4b",
                 ausgabe: str | None = None, cover: str | None = None,
                 autor: str | None = None, bitrate: str | None = None):
    """Setzt die Kapitel-WAVs zum Hörbuch zusammen: m4b, mp3 (je Kapitel), mp3-buch, opus oder wav."""
    if fmt not in FORMATE:
        raise ValueError(f"Unbekanntes Format {fmt!r}, erlaubt: {', '.join(FORMATE)}")
    work = chapter_files[0][1].parent
    stem = src.with_suffix("").as_posix()
    total = sum(dur for _, _, dur in chapter_files)
    melden("export", "Ausgabe wird vorbereitet")

    if fmt == "wav":
        outdir = Path(ausgabe or stem + "_wav")
        outdir.mkdir(exist_ok=True)
        melden("export", "WAV-Kapitel werden kopiert", 0, len(chapter_files))
        for n, (t, wav, _) in enumerate(chapter_files, 1):
            shutil.copyfile(wav, outdir / f"{n:03d} - {sicherer_name(t, n)}.wav")
            melden("export", f"{n} von {len(chapter_files)} WAV-Kapiteln kopiert", n, len(chapter_files))
        print(f"Fertig: {outdir}/ ({len(chapter_files)} WAV-Dateien, {fmt_dur(total)})")
        return

    if not shutil.which("ffmpeg"):
        print(f"ffmpeg fehlt ({FFMPEG_HINT}). Die Kapitel liegen als WAV im Arbeitsordner.")
        return
    bitrate = bitrate or BITRATE_STANDARD[fmt]
    if cover and fmt == "opus":
        print("Hinweis: In Opus-Dateien wird kein Cover eingebettet.")
        cover = None

    if fmt == "mp3":
        outdir = Path(ausgabe or stem + "_mp3")
        outdir.mkdir(exist_ok=True)
        offset = 0.0
        for n, (t, wav, duration) in enumerate(chapter_files, 1):
            mp3 = outdir / f"{n:03d} - {sicherer_name(t, n)}.mp3"
            cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav)]
            if cover:
                cmd += ["-i", str(cover)]
            cmd += ["-map", "0:a", "-codec:a", "libmp3lame", "-b:a", bitrate]
            cmd += _cover_args(cover, fmt, 1)
            cmd += _tags(t, autor, album=title, track=f"{n}/{len(chapter_files)}")
            _export_ffmpeg(cmd + [str(mp3)], duration, offset, total)
            offset += duration
        print(f"Fertig: {outdir}/ ({len(chapter_files)} MP3-Dateien, {fmt_dur(total)})")
        return

    listfile = work / "liste.txt"
    # Pfade mit Schrägstrichen: so versteht sie ffmpeg auf allen Plattformen, auch unter Windows
    listfile.write_text("".join(f"file '{w.resolve().as_posix()}'\n" for _, w, _ in chapter_files),
                        encoding="utf-8")
    metafile = work / "kapitel.ffmeta"
    metafile.write_text(ffmetadata(chapter_files, title, autor), encoding="utf-8")

    endung = {"m4b": ".m4b", "mp3-buch": ".mp3", "opus": ".opus"}[fmt]
    out = Path(ausgabe or src.with_suffix(endung))
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-f", "concat", "-safe", "0", "-i", str(listfile),
           "-i", str(metafile)]
    if cover:
        cmd += ["-i", str(cover)]
    cmd += ["-map_metadata", "1", "-map_chapters", "1", "-map", "0:a"]
    cmd += _cover_args(cover, fmt, 2)
    if fmt == "m4b":
        cmd += ["-c:a", "aac", "-b:a", bitrate, "-ac", "1", "-movflags", "+faststart", "-f", "mp4"]
    elif fmt == "mp3-buch":
        cmd += ["-c:a", "libmp3lame", "-b:a", bitrate, "-ac", "1", "-id3v2_version", "3", "-f", "mp3"]
    else:
        cmd += ["-c:a", "libopus", "-b:a", bitrate, "-ac", "1", "-vbr", "on", "-f", "opus"]
    _export_ffmpeg(cmd + [str(out)], total)
    print(f"Fertig: {out}  ({fmt_dur(total)}, {len(chapter_files)} Kapitel, {bitrate}bit/s)")
