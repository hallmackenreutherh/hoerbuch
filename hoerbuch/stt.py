"""Spracherkennung (Whisper) für den Wortlaut einer Referenzaufnahme.

Qwen3-TTS braucht zum Stimmklonen den genauen Text der Referenz. Fehlt er, schreibt Whisper
ihn mit – einmalig, das Ergebnis landet als .txt neben der Aufnahme und lässt sich korrigieren.
Das Modell wird nur kurz geladen und gleich wieder freigegeben, damit es nicht neben dem
TTS-Modell im Speicher liegt."""
from __future__ import annotations

import re
import sys
from pathlib import Path

from .audio import lade_mono
from .konfig import BACKEND, torch_geraet_und_typ
from .zahlen import expand_numbers
from .fortschritt import melden

STT_RATE = 16000             # Whisper erwartet 16 kHz mono

# Bekannte Whisper-Halluzinationen am Ende deutscher Aufnahmen (aus Untertitel-Trainingsdaten).
_HALLUZINATION = re.compile(r"(?:^|(?<=[.!?]))\s*Untertitel\w*\b.*(?:ZDF|Amara).*$", re.I)


def referenztext_aufbereiten(text: str) -> str:
    """Transkript für die Referenz glätten: Leerraum, Halluzinationen, Ziffern als Zahlwörter
    (die Aufnahme spricht "zwölf", Whisper schreibt aber gern "12")."""
    text = re.sub(r"\s+", " ", text).strip()
    text = _HALLUZINATION.sub("", text).strip()
    return expand_numbers(text)


def _transkribieren_mlx(audio, model_id: str) -> str:
    import gc
    try:
        from mlx_audio.stt import load
    except ImportError:
        sys.exit("mlx-audio fehlt. Installieren mit:  pip install -U mlx-audio")
    model = load(model_id)
    try:
        melden("transkription", "Whisper erkennt den gesprochenen Wortlaut")
        return model.generate(audio, language="de", verbose=False).text
    finally:
        del model
        gc.collect()


def _transkribieren_torch(audio, model_id: str) -> str:
    import gc
    try:
        import torch
        from transformers import pipeline
    except ImportError:
        sys.exit("transformers fehlt (wird mit qwen-tts installiert):  pip install -U transformers")
    geraet, dtype, _ = torch_geraet_und_typ()
    asr = pipeline("automatic-speech-recognition", model=model_id, device=geraet, torch_dtype=dtype)
    try:
        melden("transkription", "Whisper erkennt den gesprochenen Wortlaut")
        return asr({"raw": audio, "sampling_rate": STT_RATE},
                   generate_kwargs={"language": "german", "task": "transcribe"})["text"]
    finally:
        del asr
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


def transkribieren(pfad: Path, model_id: str) -> str:
    """Wortlaut einer Aufnahme, aufbereitet als Referenztext für Qwen3-TTS."""
    print(f"Schreibe den Wortlaut von {pfad} mit {model_id} mit … (beim ersten Mal wird es heruntergeladen)")
    audio = lade_mono(pfad, STT_RATE)
    melden("modell", "Whisper-Modell wird geladen; beim ersten Einsatz auch heruntergeladen")
    roh = (_transkribieren_mlx if BACKEND == "mlx" else _transkribieren_torch)(audio, model_id)
    result = referenztext_aufbereiten(roh)
    melden("transkription", "Wortlaut erkannt", 1, 1)
    return result
