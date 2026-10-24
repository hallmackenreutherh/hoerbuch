"""Optionale zweite Bereinigungsstufe mit einem lokalen Sprachmodell
(mlx-lm auf Apple Silicon, sonst transformers/PyTorch).

Das Modell darf den Text nicht umschreiben. Es liefert nur eine Liste von
Ersetzungen ("von" → "nach"); jede wird nur übernommen, wenn "von" wörtlich im
Absatz vorkommt. Alles wird in einer Protokolldatei festgehalten."""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

from .bereinigung import CleanReport, is_text_par
from .hilfen import fmt_dur
from .konfig import BACKEND, KI_BLOCK_CHARS, torch_geraet_und_typ

KI_SYSTEM_ERSETZUNGEN = """Du bereitest deutschen Buchtext für ein Vorleseprogramm (Text-to-Speech) vor.
Du bekommst nummerierte Absätze. Finde ausschließlich Stellen, die ein Vorleseprogramm falsch aussprechen würde, und schreibe sie so aus, wie ein Sprecher sie vorlesen würde:
- römische Zahlen (II., XIV.)
- Abkürzungen, auch mehrdeutige (S. = Sankt oder Seite, Fr. = Frau oder Freitag, sen. = senior)
- Einheiten und Sonderzeichen (km, %, €, §, &)
- offensichtliche Scan- oder OCR-Fehler (falsche Buchstaben wie "Hirnrnel" statt "Himmel", zusammengeklebte Wörter)
Regeln:
1. Grammatik passend zum Satz (Fall und Endung): "Kaiser Wilhelms II." → "Kaiser Wilhelms des Zweiten", "Papst Johannes XXIII." → "Papst Johannes der Dreiundzwanzigste".
2. Ziffern (Zahlen, Jahreszahlen, Daten) sind bereits ausgeschrieben oder werden vom Programm ausgeschrieben. Fasse keine Ziffern und keine Zahlwörter an.
3. Einheiten und Abkürzungen ausschreiben: "km" → "Kilometer", "qm" → "Quadratmeter", "Mio." → "Millionen", "ehem." → "ehemaliger"/"ehemalige" passend zum Satz.
4. Verboten: Synonyme, Umformulierungen, Stil, Kürzungen, Zeichensetzung, das Ändern korrekt geschriebener Wörter. "circa", "halben", "ungefähr" usw. sind korrekt und bleiben.
Antworte ausschließlich mit einem JSON-Array aus Objekten der Form
{"absatz": <Nummer>, "von": "<exakte Textstelle>", "nach": "<Ersatz>"}
"von" muss wörtlich, mit identischer Schreibung und Zeichensetzung, im genannten Absatz vorkommen.
Gibt es nichts zu ändern, antworte mit []."""

KI_SYSTEM_UEBERSCHRIFTEN = """Du bekommst kurze Zeilen aus einem deutschen Buch, jeweils mit dem Text davor und danach.
Entscheide für jede Zeile, ob sie eine Kapitel- oder Teilüberschrift ist (z. B. "Die Nachricht", "Erster Teil", "1848", "Zweites Buch").
Keine Überschriften sind: Dialogzeilen, kurze Erzählsätze, Briefanreden, Ortsangaben im Fließtext, Buchtitel in der Kopfzeile.
Antworte ausschließlich mit einem JSON-Array der Nummern, die Überschriften sind, z. B. [2, 5]. Ist keine dabei, antworte mit []."""


class Refiner:
    """Kapselt ein Sprachmodell: mlx-lm (Apple Silicon) oder transformers (PyTorch, sonst)."""

    def __init__(self, model_id: str, verbose: bool = False):
        self.backend = BACKEND
        self.verbose = verbose
        self.calls = 0
        self.seconds = 0.0
        print(f"Lade Sprachmodell {model_id} … (beim ersten Mal wird es heruntergeladen)")
        if self.backend == "mlx":
            try:
                from mlx_lm import load
            except ImportError:
                sys.exit("mlx-lm fehlt. Installieren mit:  pip install -U mlx-lm")
            self.model, self.tokenizer = load(model_id)
        else:
            try:
                import torch
                from transformers import AutoModelForCausalLM, AutoTokenizer
            except ImportError:
                sys.exit("transformers fehlt. Installieren mit:  pip install \".[ki]\"\n"
                         "(PyTorch mit CUDA vorher passend zur Grafikkarte installieren, siehe README.)")
            device, dtype, geraet = torch_geraet_und_typ()
            print(f"  auf {geraet} ({str(dtype).replace('torch.', '')})")
            kwargs = dict(device_map="auto", dtype=dtype)
            if device != "cpu":
                try:
                    # 4-bit-Quantisierung spart rund zwei Drittel des Grafikspeichers (bitsandbytes optional)
                    from transformers import BitsAndBytesConfig
                    import bitsandbytes  # noqa: F401
                    kwargs["quantization_config"] = BitsAndBytesConfig(
                        load_in_4bit=True, bnb_4bit_compute_dtype=dtype,
                        bnb_4bit_quant_type="nf4")
                except ImportError:
                    print("Hinweis: bitsandbytes fehlt, das Sprachmodell läuft unquantisiert "
                          "(braucht etwa doppelt so viel Grafikspeicher).")
            else:
                print("Hinweis: Ohne CUDA-Grafikkarte läuft das Sprachmodell auf der CPU und ist sehr langsam.")
            self.tokenizer = AutoTokenizer.from_pretrained(model_id)
            self.model = AutoModelForCausalLM.from_pretrained(model_id, **kwargs)

    def _generate(self, prompt: str, max_tokens: int) -> str:
        if self.backend == "mlx":
            from mlx_lm import generate
            from mlx_lm.sample_utils import make_sampler
            return generate(self.model, self.tokenizer, prompt, max_tokens=max_tokens,
                            sampler=make_sampler(temp=0.0), verbose=False)
        import torch
        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.model.device)
        with torch.no_grad():
            out = self.model.generate(**inputs, max_new_tokens=max_tokens, do_sample=False,
                                      pad_token_id=self.tokenizer.pad_token_id or self.tokenizer.eos_token_id)
        return self.tokenizer.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)

    def ask(self, system: str, user: str, max_tokens: int = 1500) -> str:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        try:
            prompt = self.tokenizer.apply_chat_template(
                messages, add_generation_prompt=True, tokenize=False, enable_thinking=False)
        except TypeError:   # Chat-Vorlage ohne Denkmodus
            prompt = self.tokenizer.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)
        t0 = time.time()
        out = self._generate(prompt, max_tokens)
        self.seconds += time.time() - t0
        self.calls += 1
        out = re.sub(r"<think>.*?</think>", "", out, flags=re.S).strip()
        if self.verbose:
            print(f"\n--- Modellantwort ---\n{out}\n")
        return out

    def ask_json(self, system: str, user: str, max_tokens: int = 1500):
        out = self.ask(system, user, max_tokens)
        m = re.search(r"\[.*\]", out, re.S)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            # häufige Fehler: abschließendes Komma, einfache Anführungszeichen
            try:
                return json.loads(re.sub(r",\s*([\]}])", r"\1", m.group(0)).replace("'", '"'))
            except json.JSONDecodeError:
                return None

    def close(self):
        import gc
        del self.model
        gc.collect()
        try:
            if self.backend == "mlx":
                import mlx.core as mx
                mx.clear_cache()
            else:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
        except Exception:
            pass


def ki_refine(text: str, model_id: str, report: CleanReport, log_path: Path,
              verbose: bool = False, max_blocks: int | None = None, headings: bool = False) -> str:
    """Zweite Bereinigungsstufe mit Sprachmodell. Gibt den geänderten Text zurück."""
    from .fortschritt import melden
    melden("modell", "Sprachmodell für die Textkorrektur wird geladen")
    pars = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    pars = [" ".join(p.split()) if is_text_par(p) else p for p in pars]
    refiner = Refiner(model_id, verbose)
    log = log_path.open("w", encoding="utf-8")
    log.write(f"KI-Bereinigung mit {model_id}\n\n")
    t_start = time.time()

    # --- A: Überschriften erkennen -----------------------------------------
    # Die Überschriftensuche ist nur auf Wunsch aktiv: In Romanen hält das Modell Zeitungs-
    # schlagzeilen, Betreffzeilen und Adressen für Kapitel. Bei EPUB-Exporten stehen die
    # echten Überschriften ohnehin schon als "# "/"## " im Text.
    if not headings:
        log.write("Überschriftensuche aus (nur mit --ki-ueberschriften).\n")
    cands = [i for i, p in enumerate(pars)
             if headings and is_text_par(p) and len(p) <= 60
             and not re.search(r"[.!?…,;:\"“”»«]$", p)
             and not re.search(r"[.!?…]\s", p)]
    heading_idx: set[int] = set()
    for k in range(0, len(cands), 20):
        melden("ueberschriften", "Kapitelüberschriften werden geprüft", k, len(cands))
        group = cands[k:k + 20]
        lines = []
        for n, i in enumerate(group, 1):
            before = pars[i - 1][:80] if i > 0 else "(Anfang)"
            after = pars[i + 1][:80] if i + 1 < len(pars) else "(Ende)"
            lines.append(f"{n}. Zeile: {pars[i]!r}\n   davor: {before!r}\n   danach: {after!r}")
        ans = refiner.ask_json(KI_SYSTEM_UEBERSCHRIFTEN, "\n".join(lines), max_tokens=200)
        if isinstance(ans, list):
            for n in ans:
                if isinstance(n, int) and 1 <= n <= len(group):
                    heading_idx.add(group[n - 1])
        print(f"\r  Überschriften geprüft: {min(k + 20, len(cands))}/{len(cands)}", end="", flush=True)
        melden("ueberschriften", "Kapitelüberschriften geprüft", min(k + 20, len(cands)), len(cands))
    if cands:
        print()
    for i in sorted(heading_idx):
        title = pars[i]
        if i > 0 and pars[i - 1].startswith("# ") and ":" not in pars[i - 1]:
            # Untertitel direkt nach einer Kapitelzeile → "# Kapitel 1: Der alte Bahnhof"
            pars[i - 1] = pars[i - 1] + ": " + title
            pars[i] = ""
            log.write(f"ÜBERSCHRIFT  {title!r} → an {pars[i - 1]!r} angehängt\n")
        else:
            pars[i] = "# " + title
            log.write(f"ÜBERSCHRIFT  {title!r}\n")
        report.ki_headings += 1
    pars = [p for p in pars if p]

    # --- B: Ersetzungen in Textblöcken --------------------------------------
    text_idx = [i for i, p in enumerate(pars) if is_text_par(p)]
    blocks: list[list[int]] = []
    cur: list[int] = []
    size = 0
    for i in text_idx:
        if cur and size + len(pars[i]) > KI_BLOCK_CHARS:
            blocks.append(cur)
            cur, size = [], 0
        cur.append(i)
        size += len(pars[i])
    if cur:
        blocks.append(cur)

    if max_blocks is not None and max_blocks < len(blocks):
        log.write(f"Nur die ersten {max_blocks} von {len(blocks)} Blöcken werden geprüft (--ki-bloecke).\n")
        blocks = blocks[:max_blocks]
    total_chars = sum(len(pars[i]) for b in blocks for i in b)
    done_chars = 0
    for bi, block in enumerate(blocks):
        melden("ki", f"Textblock {bi + 1} von {len(blocks)} wird geprüft", bi, len(blocks))
        user = "\n\n".join(f"[{n}] {pars[i]}" for n, i in enumerate(block, 1))
        ans = refiner.ask_json(KI_SYSTEM_ERSETZUNGEN, user)
        if not isinstance(ans, list):
            log.write(f"BLOCK {bi + 1}: Antwort nicht lesbar\n")
            report.ki_rejected += 1
        else:
            for item in ans:
                if not isinstance(item, dict):
                    continue
                von = str(item.get("von", "")).strip()
                nach = str(item.get("nach", "")).strip()
                n = item.get("absatz")
                if not von or von == nach:
                    continue
                if re.search(r"\d", von) or re.search(r"\d", nach):
                    log.write(f"VERWORFEN    {von!r} → {nach!r}  (Ziffern übernimmt das Skript)\n")
                    report.ki_rejected += 1
                    continue
                targets = []
                if isinstance(n, int) and 1 <= n <= len(block):
                    targets.append(block[n - 1])
                targets += [i for i in block if i not in targets]
                hit = next((i for i in targets if von in pars[i]), None)
                if hit is None:
                    log.write(f"VERWORFEN    {von!r} → {nach!r}  (nicht im Text gefunden)\n")
                    report.ki_rejected += 1
                    continue
                if len(nach) > 12 * max(1, len(von)) + 40:
                    log.write(f"VERWORFEN    {von!r} → {nach!r}  (Ersatz unplausibel lang)\n")
                    report.ki_rejected += 1
                    continue
                if re.fullmatch(r"[A-Za-zÄÖÜäöüß\s\-]+", von) and " " in von.strip():
                    log.write(f"VERWORFEN    {von!r} → {nach!r}  (mehrere Wörter ohne Abkürzung: kein Ausschreiben)\n")
                    report.ki_rejected += 1
                    continue
                if re.fullmatch(r"[A-Za-zÄÖÜäöüß]+", von):
                    # Reines Wort ohne Ziffer/Punkt/Sonderzeichen: nur als OCR-Korrektur erlaubt,
                    # d. h. der Ersatz muss dem Original ähneln und darf es nicht nur kürzen.
                    import difflib
                    sim = difflib.SequenceMatcher(None, von.lower(), nach.lower()).ratio()
                    if sim < 0.5 or von.lower().startswith(nach.lower()):
                        log.write(f"VERWORFEN    {von!r} → {nach!r}  (kein Ausschreiben, kein OCR-Fehler)\n")
                        report.ki_rejected += 1
                        continue
                pars[hit] = pars[hit].replace(von, nach)
                log.write(f"ERSETZT      {von!r} → {nach!r}\n")
                report.ki_applied += 1
        log.flush()   # Protokoll sofort lesbar, auch während langer Läufe
        done_chars += sum(len(pars[i]) for i in block)
        melden("ki", f"{bi + 1} von {len(blocks)} Textblöcken geprüft", bi + 1, len(blocks))
        el = time.time() - t_start
        rate = done_chars / el if el > 0 else 0
        eta = (total_chars - done_chars) / rate if rate > 0 else 0
        print(f"\r  Block {bi + 1}/{len(blocks)} · {rate * 60:,.0f} Z/min · Rest ≈ {fmt_dur(eta)}   "
              .replace(",", "."), end="", flush=True)
    print()
    report.ki_seconds = time.time() - t_start
    log.write(f"\n{report.ki_applied} Ersetzungen übernommen, {report.ki_rejected} verworfen, "
              f"{report.ki_headings} Überschriften, {refiner.calls} Modellanfragen, "
              f"{report.ki_seconds:.0f} s\n")
    log.close()
    refiner.close()
    return "\n\n".join(pars).strip() + "\n"
