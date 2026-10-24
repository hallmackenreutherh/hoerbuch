"""Sprachsynthese mit Qwen3-TTS, mit Längenprüfung und Wiederholung.

Zwei Backends hinter derselben Schnittstelle:
- "mlx":   mlx-audio auf Apple Silicon (quantisierte Modelle der mlx-community)
- "torch": offizielles Paket qwen-tts (PyTorch) für Windows, Linux und Intel-Macs,
           mit CUDA-GPU oder notfalls auf der CPU."""
from __future__ import annotations

import re
import sys

from .audio import lade_mono, normalize_level, trim_silence
from .fortschritt import melden
from .konfig import (BACKEND, LANGUAGE, MAX_CHARS_PER_SEC, MAX_TRIES, MIN_CHARS_PER_SEC,
                     MIN_SPEAKER_SIMILARITY, SPEAKER_MIN_SECONDS, torch_geraet_und_typ)

SPEAKER_RATE = 24000         # der Sprecher-Encoder von Qwen3-TTS rechnet mit 24 kHz


class _Sprecherpruefung:
    """Vergleicht erzeugtes Audio über den Sprecher-Encoder des Modells mit der Referenz.
    Die Backends liefern nur _embedding(audio); die Referenz wird einmal berechnet und gemerkt."""
    _ref_embedding = None        # (Pfad, normierter Vektor)
    _ohne_encoder = False

    def aehnlichkeit(self, audio, ref_audio) -> float | None:
        """Kosinus-Ähnlichkeit zur Referenzstimme, None wenn nicht messbar (zu kurz, kein Encoder)."""
        import numpy as np
        if self._ohne_encoder or self.sample_rate != SPEAKER_RATE \
                or audio.size < SPEAKER_MIN_SECONDS * SPEAKER_RATE:
            return None
        try:
            if self._ref_embedding is None or self._ref_embedding[0] != str(ref_audio):
                self._ref_embedding = (str(ref_audio), self._normiert(lade_mono(ref_audio, SPEAKER_RATE)))
            return float(np.dot(self._ref_embedding[1], self._normiert(audio)))
        except Exception as e:     # Modell ohne Encoder o. Ä.: Prüfung abschalten statt abbrechen
            print(f"Hinweis: Stimmprüfung nicht möglich ({e}) – wird übersprungen.")
            self._ohne_encoder = True
            return None

    def _normiert(self, audio):
        import numpy as np
        e = np.asarray(self._embedding(np.asarray(audio, dtype=np.float32)), dtype=np.float64).reshape(-1)
        return e / max(float(np.linalg.norm(e)), 1e-12)


class _VoiceMLX(_Sprecherpruefung):
    """mlx-audio: Modell + Stimme. Hält nur ein Modell gleichzeitig im Speicher."""

    def __init__(self, model_id: str, verbose: bool = False):
        melden("modell", "Sprachmodell wird geladen; beim ersten Einsatz auch heruntergeladen")
        try:
            import mlx.core as mx  # noqa: F401
            from mlx_audio.tts.utils import load_model
        except ImportError:
            sys.exit("mlx-audio fehlt. Installieren mit:  pip install -U mlx-audio")
        print(f"Lade Modell {model_id} … (beim ersten Mal wird es heruntergeladen)")
        self.model = load_model(model_id)
        self.model_id = model_id
        self.verbose = verbose
        langs = [l.lower() for l in getattr(self.model, "supported_languages", [])]
        if langs and LANGUAGE not in langs:
            print(f"Warnung: '{LANGUAGE}' nicht in {langs} – verwende 'auto'.")
            self.lang = "auto"
        else:
            self.lang = LANGUAGE
        self.sample_rate = int(self.model.sample_rate)

    def synth(self, text: str, *, ref_audio=None, ref_text=None, instruct=None,
              temperature=0.8, seed=None):
        import mlx.core as mx
        import numpy as np
        if seed is not None:
            mx.random.seed(seed)
        kwargs = dict(text=text, lang_code=self.lang, temperature=temperature,
                      split_pattern="", verbose=self.verbose)
        if ref_audio:
            kwargs.update(ref_audio=str(ref_audio), ref_text=ref_text)
        if instruct:
            kwargs.update(instruct=instruct)
        parts = [np.array(r.audio, dtype=np.float32).reshape(-1)
                 for r in self.model.generate(**kwargs)]
        audio = np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)
        return audio

    def _embedding(self, audio):
        import mlx.core as mx
        import numpy as np
        return np.array(self.model.extract_speaker_embedding(mx.array(audio), SPEAKER_RATE))

    def close(self):
        import gc
        self._ref_embedding = None
        del self.model
        gc.collect()
        try:
            import mlx.core as mx
            mx.clear_cache()
        except Exception:
            pass


class _VoiceTorch(_Sprecherpruefung):
    """qwen-tts (PyTorch): dieselbe Schnittstelle wie _VoiceMLX."""

    def __init__(self, model_id: str, verbose: bool = False):
        melden("modell", "Sprachmodell wird geladen; beim ersten Einsatz auch heruntergeladen")
        try:
            import torch
            from qwen_tts import Qwen3TTSModel
        except ImportError:
            sys.exit("qwen-tts fehlt. Installieren mit:  pip install -U qwen-tts\n"
                     "(PyTorch mit CUDA vorher passend zur Grafikkarte installieren, siehe README.)")
        self.device, dtype, geraet = torch_geraet_und_typ()
        print(f"Lade Modell {model_id} auf {geraet} ({str(dtype).replace('torch.', '')}) … "
              "(beim ersten Mal wird es heruntergeladen)")
        if self.device == "cpu":
            print("Hinweis: Ohne CUDA-Grafikkarte dauert das Vertonen um ein Vielfaches länger.")
        self.model = Qwen3TTSModel.from_pretrained(model_id, device_map=self.device, dtype=dtype)
        self.model_id = model_id
        self.verbose = verbose
        self.lang = LANGUAGE.capitalize()          # qwen-tts erwartet "German", "English", …
        try:
            langs = [str(l).lower() for l in (self.model.get_supported_languages() or [])]
            if langs and LANGUAGE not in langs:
                print(f"Warnung: '{LANGUAGE}' nicht in {langs} – verwende 'Auto'.")
                self.lang = "Auto"
        except Exception:
            pass
        self.sample_rate = 24000                   # Qwen3-TTS liefert 24 kHz; wird nach dem ersten Lauf übernommen
        self._clone_prompt = None                  # (ref_audio, ref_text) → vorberechnete Referenzmerkmale

    def _prompt_for(self, ref_audio, ref_text):
        key = (str(ref_audio), ref_text)
        if self._clone_prompt is None or self._clone_prompt[0] != key:
            prompt = self.model.create_voice_clone_prompt(ref_audio=str(ref_audio), ref_text=ref_text)
            self._clone_prompt = (key, prompt)
        return self._clone_prompt[1]

    def synth(self, text: str, *, ref_audio=None, ref_text=None, instruct=None,
              temperature=0.8, seed=None):
        import numpy as np
        import torch
        if seed is not None:
            torch.manual_seed(seed)
        gen = {}
        if temperature is not None:
            gen.update(do_sample=temperature > 0, temperature=max(temperature, 1e-3))
        if instruct:
            wavs, sr = self.model.generate_voice_design(text=text, language=self.lang,
                                                        instruct=instruct, **gen)
        elif ref_audio:
            wavs, sr = self.model.generate_voice_clone(text=text, language=self.lang,
                                                       voice_clone_prompt=self._prompt_for(ref_audio, ref_text),
                                                       **gen)
        else:
            sys.exit("Für die Sprachausgabe wird eine Referenzaufnahme (--ref) oder eine Stimmbeschreibung gebraucht.")
        self.sample_rate = int(sr)
        if not wavs:
            return np.zeros(0, dtype=np.float32)
        w = wavs[0]
        if hasattr(w, "detach"):
            w = w.detach().float().cpu().numpy()
        return np.asarray(w, dtype=np.float32).reshape(-1)

    def _embedding(self, audio):
        import torch
        with torch.inference_mode():
            e = self.model.model.extract_speaker_embedding(audio=audio, sr=SPEAKER_RATE)
        return e.detach().float().cpu().numpy()

    def close(self):
        import gc
        self._clone_prompt = None
        self._ref_embedding = None
        del self.model
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass


Voice = _VoiceMLX if BACKEND == "mlx" else _VoiceTorch


def plausible(text: str, seconds: float) -> bool:
    n = len(re.sub(r"\s", "", text))
    if seconds <= 0.2:
        return False
    if n < 15:
        return True
    cps = n / seconds
    return MIN_CHARS_PER_SEC <= cps <= MAX_CHARS_PER_SEC


def abrupt_ending(audio, sr: int, thresh: float = 0.01, max_drop_db: float = 8.0) -> bool:
    """Abgebrochener Schluss: Die letzten 40 ms Sprache sind noch fast so laut wie der ganze
    Abschnitt. Natürlich ausklingende Sprache liegt dort 10 dB und mehr darunter (gemessen an
    rund 70 Abschnitten: Median −16 dB, abgehackte Beispiele −7 bis 0 dB)."""
    import numpy as np
    if audio.size < int(0.4 * sr):
        return False
    idx = np.where(np.abs(audio) > thresh)[0]
    if idx.size == 0:
        return False
    end = int(idx[-1]) + 1
    a = end - int(0.04 * sr)
    if a <= 0:
        return False
    rms_all = float(np.sqrt(np.mean(audio[:end].astype(np.float64) ** 2)))
    rms_tail = float(np.sqrt(np.mean(audio[a:end].astype(np.float64) ** 2)))
    if rms_all < 1e-6 or rms_tail < 1e-6:
        return False
    return 20 * np.log10(rms_tail / rms_all) > -max_drop_db


def befund(text: str, audio, sr: int, similarity: float | None) -> str:
    """Leerer Text, wenn der Abschnitt unauffällig ist, sonst die Auffälligkeiten."""
    gruende = []
    if not plausible(text, audio.size / sr):
        gruende.append("Länge")
    if abrupt_ending(audio, sr):
        gruende.append("Schluss abgehackt")
    if similarity is not None and similarity < MIN_SPEAKER_SIMILARITY:
        gruende.append(f"Stimme weicht ab ({similarity:.3f})".replace(".", ","))
    return ", ".join(gruende)


def synth_checked(voice: Voice, text: str, **kw) -> tuple:
    """Erzeugt Audio, prüft Länge, Schluss und Stimme und versucht es bei Auffälligkeiten erneut.
    Liefert (Audio, Befund); der Befund ist leer, wenn alles passt."""
    best = None
    for attempt in range(MAX_TRIES):
        audio = trim_silence(voice.synth(text, seed=1000 + attempt * 7919, **kw), voice.sample_rate)
        audio = normalize_level(audio)
        secs = audio.size / voice.sample_rate
        sim = voice.aehnlichkeit(audio, kw["ref_audio"]) if kw.get("ref_audio") else None
        b = befund(text, audio, voice.sample_rate, sim)
        if not b:
            return audio, ""
        if voice.verbose:
            print(f"\n  Versuch {attempt + 1}: {b}")
        # Behalte bevorzugt einen Versuch in der richtigen Stimme, dann den, der am nächsten
        # an ~14 Zeichen/s liegt
        n = len(re.sub(r"\s", "", text))
        score = (sim is not None and sim < MIN_SPEAKER_SIMILARITY,
                 abs((n / secs if secs > 0 else 999) - 14))
        if best is None or score < best[0]:
            best = (score, audio, b)
    return best[1], best[2]
