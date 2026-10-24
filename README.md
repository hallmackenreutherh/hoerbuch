# hoerbuch – EPUB oder TXT zum deutschen Hörbuch, lokal auf Apple Silicon oder mit CUDA-Grafikkarte

> **English summary:** `hoerbuch` turns an EPUB or plain-text book into an M4B audiobook with chapter marks, entirely offline using [Qwen3-TTS](https://huggingface.co/collections/Qwen/qwen3-tts): on Apple Silicon via [mlx-audio](https://github.com/Blaizzy/mlx-audio), on Windows and Linux via the official PyTorch package [qwen-tts](https://github.com/QwenLM/Qwen3-TTS) (NVIDIA GPU recommended). Its focus is **German**: a deterministic text-preparation stage spells out numbers, dates, times, percentages and abbreviations with correct German inflection (via `num2words`), strips page numbers, running headers and footnote marks, merges hyphenated lines, and turns EPUB headings into chapter marks. One voice is designed once and then cloned for the whole book, every chunk is length-checked and regenerated on failure, and runs can be interrupted and resumed. An optional local-LLM pass handles ambiguous abbreviations and OCR errors. Documentation below is in German.

`hoerbuch` verwandelt eine EPUB- oder TXT-Datei in ein Hörbuch mit Kapitelmarken (M4B) oder in eine MP3-Datei pro Kapitel. Die Sprachausgabe läuft komplett lokal mit [Qwen3-TTS](https://huggingface.co/collections/Qwen/qwen3-tts): auf Apple Silicon (M1–M4) über [mlx-audio](https://github.com/Blaizzy/mlx-audio), unter Windows und Linux über das offizielle PyTorch-Paket [qwen-tts](https://github.com/QwenLM/Qwen3-TTS). Es werden keine Daten ins Internet geschickt, nur die Modelle werden beim ersten Start einmalig heruntergeladen.

Das Programm wählt das Backend selbst: auf einem Mac mit Apple Silicon MLX, sonst PyTorch. Mit der Umgebungsvariable `HOERBUCH_BACKEND=mlx` oder `=torch` lässt sich das erzwingen. Entwickelt und durchgemessen ist die Kette auf dem Mac; der PyTorch-Weg nutzt dieselben Modelle in ihrer Originalfassung und dieselbe Textstufe. Unter Windows wurde er sowohl auf der CPU als auch mit einer NVIDIA-CUDA-Grafikkarte erprobt (siehe [Stand der Erprobung](#stand-der-erprobung)). Rückmeldungen zu weiteren Grafikkarten sind willkommen.

## Grafische Oberfläche (Windows, PySide6)

Die Desktopoberfläche führt durch Buchvorbereitung, Stimmenauswahl und Hörbucherstellung.
Einmalig im Projektordner installieren:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[gui]"
```

Danach **Hoerbuch starten.bat** doppelt anklicken. Alternativ:

```powershell
.\.venv\Scripts\python.exe -m hoerbuch.gui
```

1. Unter **Buch** EPUB oder TXT auswählen, bereinigen und den Text kontrollieren. Änderungen speichern.
2. Unter **Stimme & Hörprobe** eine WAV-Aufnahme auswählen. Whisper kann den Wortlaut erkennen;
   anschließend gegenlesen und speichern. Eine Hörprobe erzeugen und direkt abspielen.
   Alternativ künstliche Stimmen entwerfen und eine davon übernehmen.
3. Unter **Hörbuch erstellen** Titel, Ausgabeordner und Format wählen und starten.
   Erweiterte Einstellungen enthalten Modelle, Bitrate und einen Dateiwähler für FFmpeg.

Die Anzeige zeigt Fortschritt, Restzeit (während der Vertonung), verstrichene Zeit und ein Protokoll.
Eigene Aufnahme und künstliche Stimme sind alternativ auswählbar; die für das Hörbuch aktive
Stimme wird auch vor dem Export angezeigt. Hörproben lassen sich ohne vorherige Listenauswahl
abspielen. Ausgabegerät, Lautstärke und Abspielposition können direkt eingestellt werden.
Die Fortschrittsbalken gelten jeweils für den benannten Verarbeitungsschritt: abgeschlossene
Textblöcke, Stimmen, Hörproben, vertonte Textzeichen, Kapitel oder tatsächlich exportierte Audiozeit.
Beim Modellladen und bei der Whisper-Erkennung läuft eine ausdrücklich unbestimmte Aktivitätsanzeige;
es werden keine zeitgesteuerten oder geschätzten Prozentwerte als gemessener Fortschritt ausgegeben.
Abbrechen beendet den Arbeitsprozess; vollständig gespeicherte Hörbuchabschnitte bleiben erhalten.
Zum Fortsetzen dieselbe vorbereitete Textdatei und Referenzstimme wählen. Modelle werden beim
ersten Einsatz heruntergeladen. Die Oberfläche speichert zuletzt verwendete Dateipfade lokal.

## Voraussetzungen

- Python 3.10 oder neuer (für den PyTorch-Weg empfiehlt qwen-tts Python 3.12)
- `ffmpeg` für den M4B/MP3-Export
- Beim ersten Start eine Internetverbindung für den Modell-Download
- **Mac:** Apple Silicon (M1 oder neuer), empfohlen mindestens 16 GB RAM, [Homebrew](https://brew.sh); die 8-bit-Modelle brauchen je rund 2 GB Platz
- **Windows/Linux:** NVIDIA-Grafikkarte mit aktuellem Treiber, Einzelheiten im nächsten Abschnitt

### Hardware unter Windows und Linux

Entscheidend ist die Grafikkarte. PyTorch nutzt unter Windows nur NVIDIA-Karten mit CUDA; AMD- und Intel-Karten fallen weg. Ohne CUDA läuft alles auf der CPU, das Programm meldet das beim Laden („auf CPU“), und ein Roman dauert dann Tage statt Stunden (gemessen: rund 100 Zeichen pro Minute auf einem Core i5-9400T, siehe [Stand der Erprobung](#stand-der-erprobung)).

Die TTS-Modelle (1.7B) laufen in 16-bit-Genauigkeit: die Gewichte belegen laut Qwen rund 3,4 GB, dazu kommen 2 bis 4 GB für die Berechnung. Erfahrungsberichte nennen 4 bis 7 GB Grafikspeicher im Betrieb.

| Grafikspeicher | Was geht |
|---|---|
| 8 GB (z. B. RTX 3060 Ti, RTX 4060) | `probe` und `vertonen` mit den 1.7B-Modellen. Empfehlung. |
| 6 GB | Knapp. Zum Vertonen besser `--modell Qwen/Qwen3-TTS-12Hz-0.6B-Base`. |
| 12 GB oder mehr | Zusätzlich `--ki` mit Qwen3-8B in 4-bit über bitsandbytes (etwa 5 bis 6 GB). |
| 16 GB oder mehr | `--ki` auch ohne bitsandbytes in 16 bit (Qwen3-8B belegt dann rund 16 GB, mit Berechnung mehr). |

- **RTX 50er (Blackwell):** Karten wie die RTX 5070 Ti (16 GB) sind gut geeignet und decken alle Zeilen der Tabelle bis einschließlich `--ki` in 4 bit ab. Sie brauchen aber zwingend PyTorch-Pakete mit CUDA 12.8 oder neuer, also den `cu128`-Index aus der Installationsanleitung; ältere Builds (`cu126` und früher) kennen die Architektur nicht und brechen beim ersten Modellaufruf ab. Für `--ki` muss auch `bitsandbytes` neu genug sein, bei einer Fehlermeldung zur Rechenarchitektur hilft `pip install -U bitsandbytes`.
- **Rechengenauigkeit:** Ab NVIDIA Ampere (RTX 30er) rechnet das Programm in bfloat16. Ältere Karten (GTX 10er, RTX 20er) können das nur langsam emulieren; dort schaltet es automatisch auf float16 um und sagt das beim Laden. Mit `HOERBUCH_DTYPE=bf16`, `fp16` oder `fp32` lässt sich die Genauigkeit erzwingen, etwa um bei Störgeräuschen float32 auf der Grafikkarte zu testen (doppelter Speicherbedarf).
- **FlashAttention** ist optional, unter Windows mühsam zu bauen und wird nicht vorausgesetzt.
- **Arbeitsspeicher:** 16 GB reichen; die Gewichte liegen beim Laden kurz im RAM.
- **Festplatte:** TTS-Modelle je rund 4,3 GB im Cache (Base und VoiceDesign, davon 3,9 GB Gewichte), Qwen3-8B für `--ki` rund 16 GB, PyTorch mit CUDA rund 3 GB. Also etwa 12 GB ohne `--ki`, rund 30 GB mit.
- **Prozessor:** Nebensache. Die Textstufe (`exportieren`, `bereinigen` ohne `--ki`) ist reines Python und läuft auf jedem Rechner.

Diese Werte stammen aus der Qwen-Dokumentation und aus Erfahrungsberichten, nicht aus eigenen Messungen des Autors.

## Installation (einmalig)

### Mac mit Apple Silicon

```bash
brew install python ffmpeg
git clone https://github.com/egdels/hoerbuch.git
cd hoerbuch
python3 -m venv ~/hoerbuch-venv
source ~/hoerbuch-venv/bin/activate
pip install .
```

Damit stehen der Befehl `hoerbuch` und die Abhängigkeiten mlx-audio, numpy, num2words und ftfy in der virtuellen Umgebung bereit. Ohne Installation geht es aus dem geklonten Ordner auch mit `python -m hoerbuch …`.

`num2words` schreibt Zahlen als Zahlwörter aus (ohne das Paket bleiben Ziffern stehen). `ftfy` ist optional, repariert aber kaputte Umlaute (z. B. `Ã¤` statt `ä`) deutlich zuverlässiger.

Für die optionale KI-Bereinigung (siehe unten) wird zusätzlich mlx-lm gebraucht:

```bash
pip install ".[ki]"
```

Vor jeder Benutzung die virtuelle Umgebung aktivieren:

```bash
source ~/hoerbuch-venv/bin/activate
```

### Windows (NVIDIA-Grafikkarte)

Python, ffmpeg und Git kommen am einfachsten über `winget` (in Windows 10/11 enthalten). In der PowerShell:

```powershell
winget install Python.Python.3.12
winget install ffmpeg
winget install Git.Git
```

Bewusst Python 3.12 und nicht die neueste Version: `qwen-tts` ist bis 3.13 freigegeben, und die CUDA-Pakete von PyTorch erscheinen für ganz neue Python-Versionen oft erst Monate später. Python aus dem Microsoft Store besser meiden, es bringt keinen `py`-Launcher mit und legt Pakete in einem versteckten Ordner ab. Nach der Installation ein neues Terminal öffnen, damit die Programme gefunden werden. Dann:

```powershell
git clone https://github.com/egdels/hoerbuch.git
cd hoerbuch
py -3.12 -m venv .venv
.venv\Scripts\activate
```

Meldet die PowerShell „Die Ausführung von Skripts ist auf diesem System deaktiviert“, einmalig `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` ausführen und `activate` wiederholen. In der klassischen Eingabeaufforderung (`cmd`) gibt es diese Sperre nicht.

**Treiber:** Für CUDA genügt der normale NVIDIA-Grafiktreiber (GeForce- oder Studio-Treiber); das CUDA-Toolkit von NVIDIA wird nicht gebraucht, die PyTorch-Pakete bringen die CUDA-Bibliotheken selbst mit. Der Treiber muss nur neu genug für die gewählte CUDA-Version sein. Das zeigt `nvidia-smi` in der obersten Zeile unter „CUDA Version“: Steht dort 12.8 oder höher, passt der `cu128`-Build unten; bei einer kleineren Zahl den Treiber aktualisieren oder im Auswahlhelfer einen älteren Build (z. B. `cu126`) wählen. Letzteres geht nur bis zur RTX 40er-Serie, die RTX 50er braucht `cu128` oder neuer.

Dann zuerst PyTorch mit CUDA installieren, zusammen mit `torchaudio`, das `qwen-tts` ebenfalls braucht und das zur Torch-Version passen muss. Den passenden Befehl für deine CUDA-Version liefert der Auswahlhelfer auf [pytorch.org/get-started/locally](https://pytorch.org/get-started/locally/) (Windows, Pip, CUDA), zum Beispiel:

```powershell
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128
```

Erst danach das Projekt installieren, sonst zieht `qwen-tts` die reine CPU-Variante von PyTorch und ein unpassendes `torchaudio` von PyPI:

```powershell
pip install .
```

Für die optionale KI-Bereinigung (`--ki`) kommt `pip install ".[ki]"` dazu, das installiert transformers, accelerate und bitsandbytes. Vor jeder Benutzung im Projektordner die virtuelle Umgebung aktivieren:

```powershell
.venv\Scripts\activate
```

Die Befehle in dieser Anleitung sind für alle Plattformen gleich. Ob die Grafikkarte erkannt wurde, zeigt die Zeile „Lade Modell … auf <Grafikkarte>“ beim ersten Start von `probe`. Steht dort „auf CPU“, fehlt die CUDA-Variante von PyTorch.

Beim ersten Start erscheinen unter Windows einige Warnungen, die harmlos sind: „SoX could not be found!“ (das Paket `sox` wird von `qwen-tts` nur für die 25-Hz-Modelle gebraucht, die hier nicht verwendet werden), „flash-attn is not installed“ (optional, siehe oben), ein Hinweis von Hugging Face, dass der Modell-Cache keine Symlinks nutzen kann, und der Tipp, `hf_xet` für schnellere Downloads zu installieren. Einzelheiten dazu unter [Hinweise und Fehlerbehebung](#hinweise-und-fehlerbehebung).

**Umgebungsvariablen:** Diese Anleitung nennt `HOERBUCH_BACKEND`, `HOERBUCH_DTYPE`, `HOERBUCH_STIMME` und `HF_HOME`. In der PowerShell setzt man sie so:

```powershell
$env:HOERBUCH_DTYPE = "fp16"      # gilt nur in dieser PowerShell-Sitzung
setx HF_HOME "D:\hf-cache"        # dauerhaft, gilt ab dem nächsten Terminal
```

In der klassischen Eingabeaufforderung (`cmd`) lautet die Sitzungsvariante `set HOERBUCH_DTYPE=fp16`. `HF_HOME` lohnt sich, wenn das Systemlaufwerk knapp ist: Ohne die Variable landen die Modelle (bis zu 30 GB mit `--ki`) unter `C:\Users\<Name>\.cache\huggingface`.

**Pfade:** Wo diese Anleitung `~` schreibt, ist unter Windows das Benutzerprofil gemeint, also `C:\Users\<Name>`. Die eigene Standardstimme liegt dann unter `C:\Users\<Name>\.hoerbuch\stimme.wav`.

Unter Linux gilt derselbe Weg, mit `python3 -m venv` und `source ~/hoerbuch-venv/bin/activate` wie auf dem Mac.

### Modelle je Backend

| | Apple Silicon (MLX) | Windows/Linux (PyTorch) |
|---|---|---|
| Vertonen (`--modell`) | `mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit` | `Qwen/Qwen3-TTS-12Hz-1.7B-Base` |
| Stimmen entwerfen (`--modell-design`) | `mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-8bit` | `Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign` |
| KI-Bereinigung (`--ki-modell`) | `mlx-community/Qwen3.5-9B-MLX-4bit` | `Qwen/Qwen3-8B` (4-bit über bitsandbytes, sonst bf16) |

Die Werte in den Tabellen unten (Qualität, Tempo) wurden mit den MLX-Modellen gemessen, und die Standardwerte in der Befehlsreferenz sind die MLX-Modelle; unter Windows und Linux gelten stattdessen die PyTorch-Spalte dieser Tabelle. Für `--ki` unter PyTorch ist `Qwen/Qwen3-8B` als textbasiertes Modell gesetzt, weil Qwen3.5 9B im Transformers-Format ein multimodales Modell ist; mit `--ki-modell` lässt sich jedes Modell wählen, das `AutoModelForCausalLM` laden kann.

## Ablauf in drei Schritten

### 0. EPUB vorhanden? Erst exportieren

```bash
hoerbuch exportieren buch.epub
```

Liest die Kapitel in Buchreihenfolge und schreibt `<Buchtitel>.txt` neben das EPUB. Dabei werden Überschriften direkt als Kapitelmarken (`# `) und Zwischenüberschriften (`## `) übernommen (nackte Nummern wie „1 Vertreibung“ werden zu „Kapitel 1: Vertreibung“), Cover, Titelei, Impressum, Inhaltsverzeichnis und Werbeseiten weggelassen, Fußnotenziffern entfernt und Tabellen zeilenweise übernommen. Am Anfang steht eine Ansage „Titel. Von Autor.“ (abschaltbar mit `--ohne-intro`). Mit `--ohne REGEX` steuerst du, welche Dokumente ausgelassen werden. `bereinigen` akzeptiert auch direkt eine EPUB-Datei und exportiert dann selbst.

### 1. Text bereinigen (Sekunden, ohne KI)

```bash
hoerbuch bereinigen buch.txt
```

Erzeugt `buch.bereinigt.txt` und gibt aus, was erkannt und entfernt wurde: Kodierung, Seitenzahlen, Kopf-/Fußzeilen, aufgelöste Silbentrennungen, ersetzte Abkürzungen, URLs und die gefundenen Kapitel. Eine kurze Zeile ohne Satzschluss direkt unter einer Kapitelzeile (auch mit Leerzeile dazwischen) gilt als Untertitel und wird angehängt: aus „Kapitel 1“ und „Der alte Bahnhof“ wird `# Kapitel 1: Der alte Bahnhof`. Am Ende steht eine Schätzung der Hörzeit.

Kapitel stehen in der bereinigten Datei als Zeilen mit `# ` am Anfang, zum Beispiel `# Kapitel 3: Die Rückkehr`. Diese Datei solltest du vor dem Vertonen kurz durchsehen:

- Fehlende Kapitel: einfach eine Zeile `# Kapitelname` einfügen.
- Falsch erkannte Kapitel: das `# ` am Zeilenanfang entfernen.
- Zwischenüberschriften: eine Zeile mit `## Titel` wird mit Pause vorgelesen, bekommt aber keine Kapitelmarke.
- Szenenwechsel: eine Zeile mit `***` erzeugt eine längere Pause.

Wird die bereinigte Datei noch einmal bereinigt, entsteht `buch.bereinigt.neu.txt`, damit nichts überschrieben wird.

**Optional: zweite Stufe mit Sprachmodell (`--ki`)**

```bash
hoerbuch bereinigen buch.txt --ki
```

Nach der Regex-Bereinigung geht ein lokales Sprachmodell über den Text (Standard auf dem Mac: Qwen3.5 9B, 4bit, etwa 6 GB; unter Windows/Linux: Qwen3-8B in 4 bit über bitsandbytes, siehe [Modelle je Backend](#modelle-je-backend)) und kümmert sich um das, was Regeln nicht können:

- römische Zahlen im richtigen Fall („Kaiser Wilhelms II.“ → „Kaiser Wilhelms des Zweiten“)
- mehrdeutige Abkürzungen aus dem Kontext („S. 12“ → „Seite zwölf“, „Fr. Berger“ → „Frau Berger“, „ehem.“ → „ehemaliger“)
- Einheiten und Abkürzungen, die die Regelliste nicht kennt
- offensichtliche Scan-Fehler („Hirnrnel“ → „Himmel“)
- nur mit `--ki-ueberschriften`: Kapitelüberschriften ohne Schlüsselwort („Die Mühle“) und Untertitel („Kapitel 1: Der alte Bahnhof“). Standardmäßig aus, denn in Romanen hält das Modell Zeitungsschlagzeilen, Betreffzeilen und Adressen für Kapitel.

Zahlen fasst das Modell nicht an. Das haben Läufe an längeren Texten gezeigt: Selbst das 9B-Modell vertauscht bei deutschen Zahlwörtern regelmäßig Zehner und Einer („85 %“ → „achtundfünfzig Prozent“, „2021“ → „zweitausendzwanzig“). Zahlen schreibt deshalb der Code mit num2words aus, und Vorschläge des Modells, die Ziffern enthalten, werden verworfen.

Das Modell darf den Text auch sonst nicht umschreiben. Es liefert nur Ersetzungsvorschläge, und das Skript übernimmt jeden nur, wenn die Stelle wörtlich im Absatz vorkommt und der Vorschlag plausibel ist (keine Synonyme, keine Kürzungen). Jede Änderung steht in `buch.ki-protokoll.txt`. Rechnet mit etwa 5.000 Zeichen pro Minute auf einem M4, also rund 1,5 Stunden für einen Roman. Mit `--ki-modell NAME` lässt sich ein anderes Modell wählen (auf dem Mac aus der mlx-community, unter PyTorch jedes Modell im Transformers-Format), mit `--verbose` siehst du die rohen Modellantworten.

### 2. Probelauf: Stimmen anhören (einige Minuten)

```bash
hoerbuch probe buch.bereinigt.txt
```

Das Skript entwirft vier Erzählerstimmen per Beschreibung (VoiceDesign-Modell) und spricht mit jeder davon einen Absatz aus deinem Buch. Im Ordner `probe/` entstehen:

| Datei | Inhalt |
|---|---|
| `stimme_erzaehler_m.wav` | Referenzstimme: ruhiger, warmer männlicher Sprecher |
| `stimme_erzaehlerin_w.wav` | Referenzstimme: warme, klare weibliche Sprecherin |
| `stimme_erzaehler_alt.wav` | Referenzstimme: älterer Erzähler mit sonorer Stimme |
| `stimme_erzaehler_sf.wav` | Referenzstimme: markanter, sachlicher Sprecher mit unterschwelliger Spannung, im Stil klassischer Synchronsprecher (für Science-Fiction und Thriller) |
| `stimme_*.txt` | Wortlaut der jeweiligen Referenzaufnahme |
| `probe_*.wav` | Hörprobe mit einem Absatz aus deinem Buch, so klingt später das ganze Hörbuch |

Hör dir die `probe_*.wav`-Dateien an und merk dir die passende `stimme_*.wav`. Am Ende zeigt der Probelauf das Tempo in Zeichen pro Minute. Damit kannst du abschätzen, wie lange das ganze Buch dauert.

**Eigene Stimmbeschreibung:** Mit `--design` entwirfst du zusätzliche Stimmen nach eigener Beschreibung, mehrfach angebbar. `--nur-design` lässt die vier eingebauten weg, `--seed` liefert eine andere Variante derselben Beschreibung:

```bash
hoerbuch probe buch.bereinigt.txt --nur-design --seed 7 \
  --design "Eine junge Sprecherin mit heller, klarer Stimme, spricht lebhaft und schnell, leicht ironisch."
```

Die Dateien heißen `stimme_entwurf_1.wav` (mit `--seed 7`: `stimme_entwurf_1_seed7.wav`), die Beschreibung liegt daneben in `stimme_entwurf_1.beschreibung.txt`. Beschreibe Alter, Tonlage, Klang, Tempo und Haltung. Namen von Sprechern oder Rollen helfen nicht: Das Modell kennt keine Personen und setzt nur Klangmerkmale um. Die eingebauten Beschreibungen in `hoerbuch/konfig.py` (`VOICE_DESIGNS`) sind gute Vorlagen.

**Eigene Stimme testen:** Du kannst zusätzlich eine eigene Aufnahme (WAV, 10–20 Sekunden, sauber gesprochen) mitgeben:

```bash
hoerbuch probe buch.bereinigt.txt --ref meine_stimme.wav
```

Mit `--nur-ref` werden keine Stimmen entworfen, sondern nur die eigene Aufnahme getestet. Den Wortlaut der Aufnahme sucht `probe` in `--ref-text "…"` oder in einer Datei `meine_stimme.txt` daneben. Fehlt beides, schreibt Whisper ihn mit (siehe [Wortlaut der Aufnahme](#wortlaut-der-aufnahme)).

### Eigene Stimme als Standard (optional, einmalig)

```bash
hoerbuch stimme aufnahme.wav
```

Nimm 10 bis 20 Sekunden ruhig gesprochenen Text auf, mono, ohne Hall und Hintergrundgeräusche, am besten in dem Ton, in dem das Buch klingen soll. Der Befehl bringt die Aufnahme auf Mono, 24 kHz und einheitliche Lautheit, kürzt Stille an den Enden und speichert sie mit dem Wortlaut unter `~/.hoerbuch/stimme.wav` (Windows: `C:\Users\<Name>\.hoerbuch\stimme.wav`). Ab dann verwenden `probe` und `vertonen` diese Stimme automatisch, wenn kein `--ref` angegeben ist. `probe` erzeugt zusätzlich zu den vier entworfenen Stimmen eine Hörprobe damit, `probe --nur-ref` nur diese. Ein anderer Speicherort lässt sich mit `--ziel` oder der Umgebungsvariable `HOERBUCH_STIMME` festlegen.

Klone nur deine eigene Stimme oder eine, deren Sprecher zugestimmt hat.

#### Wortlaut der Aufnahme

Zum Stimmklonen braucht Qwen3-TTS den genauen Text, der in der Aufnahme gesprochen wird. Du kannst ihn mit `--text "…"` angeben oder als `aufnahme.txt` neben die Aufnahme legen. Fehlt beides, schreibt die Spracherkennung Whisper (`whisper-large-v3-turbo`, beim ersten Mal ≈1,6 GB Download) den Wortlaut mit. Ziffern werden dabei als Zahlwörter ausgeschrieben, so wie sie gesprochen wurden. Das Ergebnis wird angezeigt und als `.txt` neben der Stimme gespeichert, Whisper läuft also nur einmal. Lies den Text gegen und korrigiere die `.txt` bei Bedarf: Weicht der Wortlaut von der Aufnahme ab, etwa bei Namen oder ausgelassenen Wörtern, klingt die geklonte Stimme schlechter oder spricht Reste der Referenz mit. Abweichende Satzzeichen sind unkritisch. Dasselbe gilt für `probe --ref` und `vertonen --ref` mit einer Aufnahme ohne `.txt`.

Erfahrungen aus vier Testaufnahmen, verglichen am Testbuch:

- **Pegel:** Spitze um -15 bis -20 dB anpeilen. Zu leise Aufnahmen (Spitze unter -30 dB) funktionieren nach der Normalisierung, haben aber weniger Rauschabstand.
- **Mono statt Stereo mit leerem Kanal:** Beim Zusammenmischen halbiert sich sonst der Pegel, und das Modell driftet beim Klonen stärker in der Lautstärke.
- **Stille an den Enden lassen:** Mindestens eine Sekunde vor dem ersten und nach dem letzten Wort. Endet die Aufnahme mitten im letzten Wort, während der Wortlaut vollständig ist, baut das Modell die fehlenden Silben in jeden Abschnitt des Hörbuchs ein.
- **Länge:** 15 bis 20 Sekunden mit vier bis fünf Sätzen, darunter eine Frage, geben dem Modell mehr Satzmelodie als zwei Sätze. Gegen die Lautstärkedrift innerhalb langer Passagen hilft die Länge nur begrenzt; dafür gibt es die Pegelnormalisierung je Abschnitt und `--abschnitt 250`.
- **Tempo und Pausen** der Aufnahme übernimmt das Modell. Lies so, wie das Buch klingen soll.

### 3. Ganzes Buch vertonen (Stunden, z. B. über Nacht)

```bash
hoerbuch vertonen buch.bereinigt.txt --ref probe/stimme_erzaehler_m.wav --titel "Mein Buch"
```

Das ganze Buch wird per Voice Cloning aus genau dieser einen Referenzaufnahme gesprochen. So bleibt die Stimme über alle Kapitel gleich. Das Ergebnis ist `buch.bereinigt.m4b` mit Kapitelmarken.

Varianten:

```bash
# Eine MP3-Datei pro Kapitel statt einer M4B-Datei
hoerbuch vertonen buch.bereinigt.txt --ref probe/stimme_erzaehlerin_w.wav --format mp3

# Mit Cover und Autor (landen als Tags in der Datei)
hoerbuch vertonen buch.bereinigt.txt --ref probe/stimme_erzaehler_m.wav --titel "Mein Buch" --autor "Erika Muster" --cover cover.jpg

# Kleinste Datei: Opus mit 32 kbit/s
hoerbuch vertonen buch.bereinigt.txt --ref probe/stimme_erzaehler_m.wav --format opus

# Gleichmäßigere Betonung (Standard 0.8)
hoerbuch vertonen buch.bereinigt.txt --ref probe/stimme_erzaehler_m.wav --temperatur 0.6
```

**Abbrechen und Fortsetzen:** Mit `Ctrl-C` kannst du jederzeit abbrechen. Beim nächsten Aufruf mit denselben Parametern geht es an derselben Stelle weiter. Ändert sich der Text oder die Referenzstimme, werden die alten Abschnitte automatisch verworfen.

## Befehlsreferenz

### `exportieren`

```
hoerbuch exportieren BUCH.epub [--ausgabe DATEI] [--ohne REGEX] [--ohne-intro]
```

| Option | Bedeutung |
|---|---|
| `--ausgabe DATEI` | Zieldatei (Standard: `<Buchtitel>.txt` neben dem EPUB) |
| `--ohne REGEX` | auszulassende Dokumente nach Dateiname oder Kapitelname; Standard lässt Cover, Titel, Impressum, Inhalt, Werbung (auch Bookwire-Anzeigen) und QR-Code-Seiten weg, leer = nichts auslassen |
| `--ohne-intro` | keine Ansage von Titel und Autor am Anfang |

### `bereinigen`

```
hoerbuch bereinigen DATEI [--ki] [--ki-modell NAME] [--ki-protokoll DATEI] [--verbose]
```

Schreibt `DATEI.bereinigt.txt` neben die Eingabedatei. Ist `DATEI` ein EPUB, wird es vorher exportiert.

| Option | Bedeutung |
|---|---|
| `--ziffern-lassen` | Zahlen nicht ausschreiben |
| `--ki` | zweite Stufe mit lokalem Sprachmodell (Abkürzungen, Einheiten, römische Zahlen, OCR-Fehler, Überschriften) |
| `--ki-modell NAME` | Sprachmodell für `--ki` (Standard Mac: `mlx-community/Qwen3.5-9B-MLX-4bit`, Windows/Linux: `Qwen/Qwen3-8B`) |
| `--ki-protokoll DATEI` | Protokoll der KI-Änderungen (Standard: `DATEI.ki-protokoll.txt`) |
| `--ki-bloecke N` | nur die ersten N Textblöcke prüfen, als Probelauf |
| `--ki-ueberschriften` | Modell zusätzlich nach Kapitelüberschriften suchen lassen |
| `--verbose` | rohe Modellantworten anzeigen |

### `probe`

| Option | Bedeutung |
|---|---|
| `--ref WAV` | eigene Referenzaufnahme (10–20 s) zusätzlich testen; ohne Angabe wird eine eingerichtete Standardstimme mitgetestet |
| `--ref-text "…"` | genauer Wortlaut der eigenen Referenzaufnahme (sonst aus gleichnamiger `.txt`, sonst mit Whisper mitgeschrieben) |
| `--nur-ref` | keine Stimmen entwerfen, nur die eigene Referenz testen |
| `--ausgabe ORDNER` | Ordner für die Proben (Standard: `probe`) |
| `--modell NAME` | TTS-Modell (Standard Mac: `mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit`, Windows/Linux: `Qwen/Qwen3-TTS-12Hz-1.7B-Base`) |
| `--modell-design NAME` | VoiceDesign-Modell (Standard Mac: `mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-8bit`, Windows/Linux: `Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign`) |
| `--verbose` | ausführliche Ausgabe |

### `stimme`

```
hoerbuch stimme AUFNAHME [--text "…"] [--ziel PFAD] [--modell-stt MODELL]
```

| Option | Bedeutung |
|---|---|
| `--text "…"` | genauer Wortlaut der Aufnahme (sonst aus gleichnamiger `.txt`, sonst mit Whisper mitgeschrieben) |
| `--ziel PFAD` | Speicherort (Standard `~/.hoerbuch/stimme.wav`) |
| `--modell-stt MODELL` | Spracherkennung für den Wortlaut (Standard `mlx-community/whisper-large-v3-turbo-asr-fp16`, unter PyTorch `openai/whisper-large-v3-turbo`) |

### `vertonen`

| Option | Bedeutung |
|---|---|
| `--ref WAV` | Referenzstimme, z. B. `probe/stimme_erzaehler_m.wav`; ohne Angabe die eingerichtete eigene Stimme |
| `--ref-text "…"` | Wortlaut der Referenz (sonst aus der gleichnamigen `.txt`, sonst mit Whisper mitgeschrieben) |
| `--titel "…"` | Titel des Hörbuchs (Standard: Dateiname) |
| `--cover BILD` | Coverbild (JPG/PNG) für die M4B-Datei |
| `--format m4b\|mp3` | `m4b` = eine Datei mit Kapitelmarken (Standard), `mp3` = eine Datei pro Kapitel |
| `--ausgabe PFAD` | Ausgabedatei (M4B) bzw. Ausgabeordner (MP3) |
| `--arbeitsordner ORDNER` | Ordner für Zwischendateien (Standard: `buch.bereinigt_audio/`) |
| `--abschnitt N` | max. Zeichen pro Abschnitt (Standard 350, kürzer = weniger Aussetzer) |
| `--temperatur T` | niedriger = gleichmäßiger, höher = lebendiger (Standard 0.8) |
| `--ohne-bereinigung` | Text nicht automatisch bereinigen, wenn keine `# `-Kapitel gefunden werden |
| `--modell NAME` | TTS-Modell (Standard wie bei `probe`) |
| `--verbose` | ausführliche Ausgabe |

## Was die Bereinigung macht

- Kodierung erkennen (UTF-8, Latin-1, Windows-1252) und kaputte Umlaute reparieren
- Seitenzahlen und wiederkehrende Kopf-/Fußzeilen entfernen
- Silbentrennungen am Zeilenende auflösen
- Umbrochene Zeilen zu Absätzen zusammenfügen
- Ligaturen, unsichtbare Zeichen, Sonderleerzeichen und Emojis normalisieren
- URLs entfernen
- Guillemets »…« zu deutschen Anführungszeichen, Gendersternchen („Freund*innen“ → „Freund-innen“), fehlende Leerzeichen nach Satzpunkten („Fisch.Wir“)
- Gängige Abkürzungen ausschreiben (`z. B.` → „zum Beispiel“, `Dr.` → „Doktor“, `usw.` → „und so weiter“ …)
- Zahlen als Zahlwörter ausschreiben, deterministisch mit num2words: Jahreszahlen („1848“ → „achtzehnhundertachtundvierzig“), Daten mit passender Endung („am 27. Januar 2020“ → „am siebenundzwanzigsten Januar zweitausendzwanzig“, auch „9. 12. 21“), Uhrzeiten, Prozent, Dezimalzahlen und Preise („3.99 Euro“), Tausenderpunkte, Jahrzehnte („70er“), Bereiche („8 – 12-Jährigen“ → „acht- bis zwölf-Jährigen“), Kürzel mit Ziffern („MI5“ → „MI fünf“), Einheiten (km, kg, €) und Paragrafen. Kapitelmarken behalten ihre Ziffern, gesprochen werden sie trotzdem ausgeschrieben. Abschaltbar mit `--ziffern-lassen`.
- Kapitelüberschriften erkennen (z. B. „Kapitel 7“, „7. Die Rückkehr“, „III“, „Prolog“, „Epilog“) und als `# `-Zeilen markieren; bereits markierte `# `- und `## `-Zeilen bleiben erhalten
- Szenenwechsel (`***` und Ähnliches) als längere Pause markieren

## Dateien und Ordner

Nach einem vollständigen Durchlauf für `buch.txt`:

```
buch.txt                    Original
buch.bereinigt.txt          bereinigter Text mit # Kapitelzeilen
buch.ki-protokoll.txt       Änderungen der KI-Stufe (nur mit --ki)
probe/                      Referenzstimmen und Hörproben
buch.bereinigt_audio/       Arbeitsordner
  k000_0000.wav …           einzelne Abschnitte (Kapitel_Abschnitt)
  kapitel_001.wav …         zusammengesetzte Kapitel
  plan.json                 Prüfsumme von Text und Stimme fürs Fortsetzen
  auffaellig.txt            Abschnitte mit auffälliger Länge (falls vorhanden)
buch.bereinigt.m4b          fertiges Hörbuch (oder buch.bereinigt_mp3/ bei --format mp3)
```

Der Arbeitsordner kann nach dem Export gelöscht werden. Solange er existiert, lässt sich der Export jederzeit ohne neue Berechnung wiederholen, auch in einem anderen Format: `vertonen` erneut mit `--format …` aufrufen, die fertigen Abschnitte werden wiederverwendet.

### Ausgabeformate

| `--format` | Ergebnis | Kapitelmarken | Cover | Standard-Bitrate |
|---|---|---|---|---|
| `m4b` (Standard) | eine Datei, AAC | ja | ja | 64 kbit/s |
| `mp3-buch` | eine MP3-Datei | ja (ID3-Kapitel, u. a. Apple Books, VLC, Smart AudioBook Player) | ja | 64 kbit/s |
| `mp3` | eine MP3-Datei je Kapitel, nummeriert | über die Dateien | ja | 64 kbit/s |
| `opus` | eine Datei, Opus | ja (VLC, Android-Player; Apple-Geräte ignorieren sie) | nein | 32 kbit/s |
| `wav` | eine WAV-Datei je Kapitel, unkomprimiert | über die Dateien | nein | – |

Alle Ausgaben sind mono. `--bitrate 96k` setzt eine andere Bitrate, `--autor` schreibt den Autor als Interpret in die Tags, `--ausgabe` legt Dateinamen oder Zielordner fest. Opus liefert bei gleicher Bitrate die beste Sprachqualität und etwa halb so große Dateien wie M4B. `wav` braucht kein ffmpeg und eignet sich zur Nachbearbeitung in einem Audio-Editor.

## Qualitätskontrolle

Jeder Abschnitt wird auf plausible Länge geprüft. Eine deutsche Erzählstimme spricht etwa 12–17 Zeichen pro Sekunde. Liegt ein Abschnitt weit darunter (vermutlich Wiederholung oder Gestammel) oder weit darüber (vermutlich Text verschluckt), wird er bis zu dreimal neu erzeugt. Ebenso, wenn der Schluss abgehackt ist, also der Pegel kurz vor dem Ende noch nicht abfällt; das passiert dem Modell gelegentlich bei sehr kurzen Texten. Außerdem wird jeder Abschnitt ab drei Sekunden über den Sprecher-Encoder von Qwen3-TTS mit der Referenz verglichen. Das Modell klont die Stimme für jeden Abschnitt neu und kippt dabei gelegentlich in eine andere Stimme, besonders bei wörtlicher Rede und schwachen Referenzen (komprimierte oder bearbeitete Aufnahmen, etwa aus dem Radio). Liegt die Ähnlichkeit unter 0,96 (saubere Abschnitte liegen um 0,99, fremde Stimmen bei 0,91–0,94), wird der Abschnitt ebenfalls neu erzeugt. Bleibt ein Abschnitt auffällig, wird er trotzdem verwendet und mit dem Grund in `auffaellig.txt` im Arbeitsordner protokolliert; bei der Stimme wird dabei der Versuch behalten, der der Referenz am nächsten kommt. Damit das Modell Sätze sauber abschließt, bekommt jeder Absatz ohne Schlusszeichen beim Vertonen einen Punkt angehängt.

Jeder Abschnitt wird außerdem auf denselben Effektivpegel gebracht (RMS −20 dBFS, Spitze höchstens −2 dB), damit die Lautstärke über das Buch nicht driftet. Das Voice-Cloning-Modell wird sonst innerhalb längerer Passagen allmählich leiser, besonders bei leisen Referenzaufnahmen.

Um einen einzelnen Abschnitt neu erzeugen zu lassen, lösche die zugehörige `k…_….wav` im Arbeitsordner und starte `vertonen` erneut. Nur die fehlenden Abschnitte werden nachberechnet. Änderst du den Text, werden nur die Abschnitte neu erzeugt, deren Wortlaut sich geändert hat; `plan.json` im Arbeitsordner merkt sich dazu je Abschnitt eine Prüfsumme. Eingefügte oder gelöschte Absätze verschieben die übrigen Abschnitte nur, sie werden nicht neu berechnet. Bei einer anderen Referenzstimme wird alles neu erzeugt.

## Hinweise und Fehlerbehebung

- **Modell nicht gefunden (Mac):** Nimm die bf16-Variante, z. B. `--modell mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16` (und entsprechend `--modell-design …-VoiceDesign-bf16`).
- **Windows: „auf CPU“ statt Grafikkarte:** Entweder ist PyTorch ohne CUDA installiert, oder der Treiber ist zu alt für den gewählten Build. Erst `nvidia-smi` prüfen (siehe Installation), dann in der aktivierten Umgebung `pip uninstall torch torchaudio` und den CUDA-Befehl von pytorch.org erneut ausführen. `python -c "import torch; print(torch.cuda.is_available())"` muss `True` ergeben.
- **Windows: Speicher der Grafikkarte reicht nicht:** Für `vertonen` genügt das 0.6B-Modell mit `--modell Qwen/Qwen3-TTS-12Hz-0.6B-Base`, die Qualität ist etwas geringer. Für `--ki` hilft `bitsandbytes` (4-bit) oder ein kleineres Modell per `--ki-modell`.
- **Windows: „SoX could not be found!“ beim Start:** Harmlos. `qwen-tts` lädt das Python-Paket `sox` immer mit, ruft das SoX-Programm aber nur für die 25-Hz-Modelle auf; die hier verwendeten 12-Hz-Modelle brauchen es nicht.
- **Windows: Hugging Face warnt wegen fehlender Symlinks:** Harmlos. Ohne Symlinks legt der Cache die Modelldateien direkt im Snapshot-Ordner ab statt sie zu verlinken; im Test belegte jedes Modell damit die erwarteten 4,3 GB. Mehr Platz kostet das nur, wenn dasselbe Modell in mehreren Revisionen geladen wird. Wer die Warnung nicht sehen will, schaltet in den Windows-Einstellungen den Entwicklermodus ein (System → Für Entwickler) oder setzt `HF_HUB_DISABLE_SYMLINKS_WARNING=1`.
- **Stimme wechselt zwischendurch** (etwa in eine Männerstimme bei wörtlicher Rede): Die Stimmprüfung erzeugt solche Abschnitte bis zu dreimal neu. Bleiben viele in `auffaellig.txt` mit „Stimme weicht ab“ stehen, ist die Referenz zu schwach: eine saubere Aufnahme mit nur einer Stimme wählen und `--temperatur 0.5` versuchen.
- **Zu viele Aussetzer oder Wiederholungen:** `--abschnitt 250` setzt kürzere Abschnitte, `--temperatur 0.6` macht die Ausgabe gleichmäßiger.
- **`ffmpeg fehlt`:** `brew install ffmpeg` (Mac) bzw. `winget install ffmpeg` (Windows). Die Kapitel liegen trotzdem als WAV im Arbeitsordner und können später exportiert werden.
- **Eigene Referenzaufnahme:** 10–20 Sekunden, ohne Hintergrundgeräusche, möglichst in dem Tempo und Ton, in dem das Buch gelesen werden soll. Der Wortlaut muss exakt stimmen; einen von Whisper mitgeschriebenen Text in der `.txt` gegenlesen.
- **Dauer abschätzen:** Zeichen des Buchs geteilt durch das im Probelauf angezeigte Tempo (Zeichen/Minute). Auf einem M4 sind es rund 1.000 Zeichen pro Minute, ein Roman mit 500.000 Zeichen braucht also etwa 8 Stunden.
- **Hugging-Face-Cache:** Die Modelle landen im Standard-Cache unter `~/.cache/huggingface` (Windows: `C:\Users\<Name>\.cache\huggingface`). Ist die Umgebungsvariable `HF_HOME` gesetzt, liegen sie entsprechend woanders; unter Windows z. B. dauerhaft mit `setx HF_HOME "D:\hf-cache"`.
- **Hängt beim „Lade Modell …“:** Vor dem Laden prüft die Hugging-Face-Bibliothek online, ob das Modell aktuell ist. Ohne Internet oder bei gestörter Verbindung (etwa IPv6 ohne Route) kann das minutenlang hängen. Mit `HF_HUB_OFFLINE=1 hoerbuch probe …` (Windows PowerShell: `$env:HF_HUB_OFFLINE=1`) wird nur der lokale Cache benutzt; das geht, sobald die Modelle einmal geladen wurden.

## Schnelltest

Im Ordner `beispiel/` liegt `testbuch.txt`, ein kurzer Beispieltext mit Seitenzahlen, Kopfzeilen, Silbentrennungen, Abkürzungen und zwei Kapiteln. Damit lässt sich die ganze Kette in wenigen Minuten durchspielen:

```bash
cd beispiel
hoerbuch bereinigen testbuch.txt --ki   # oder ohne --ki
hoerbuch probe testbuch.bereinigt.txt
hoerbuch vertonen testbuch.bereinigt.txt --ref probe/stimme_erzaehler_m.wav --titel "Der Nebel über Lindenbach"
```

Wie das Ergebnis klingt, zeigt `beispiel/testbuch.m4b`: das Testbuch, gesprochen per Voice Cloning aus einer eigenen 20-Sekunden-Aufnahme des Autors, 4:39 Minuten mit zwei Kapitelmarken.

In `beispiel/probe/` liegen bereits die drei auf dem Mac entworfenen Stimmen samt Hörproben. `probe` übernimmt vorhandene `stimme_*.wav` und überschreibt nur die `probe_*.wav`. Wer die mitgelieferten Dateien unberührt lassen will, kopiert `testbuch.txt` vorher in einen eigenen Ordner oder gibt mit `--ausgabe` einen anderen Probenordner an.


## Modellvergleich für `--ki`

Getestet am Testbuch mit zwölf absichtlich eingebauten Stolperstellen (Datum, Jahreszahl, Tausenderpunkt, Prozent, Paragraf, Uhrzeit, Dezimalzahl mit Einheit, drei Abkürzungen, römische Zahl, OCR-Fehler) und drei Überschriften, die die Regex nicht erkennt.

| Modell | Treffer | Fehler | Überschriften | Dauer |
|---|---|---|---|---|
| Qwen3.5 9B (4bit) | 12 von 12 | 0 | 3 von 3 | 40 s |
| Gemma 4 12B (4bit) | 11 von 12 | 0 | 0 von 3 | 76 s |
| Qwen3 4B Instruct (4bit) | 0 von 12 | 2 falsche Ersetzungen | 2 von 3 | 26 s |

Das 4B-Modell ist für diese Aufgabe unbrauchbar. Gemma ist bei den Ersetzungen gleichwertig, erkennt aber keine Überschriften und braucht doppelt so lang. Qwen3.5 9B ist deshalb Standard. Mit dem ersten, lockerer formulierten Prompt hatte auch das 9B-Modell vier Fehler (Synonyme eingesetzt, „1.200“ als „eintausendzwanzig“, falscher Fall beim Genitiv). Die Beispiele im Prompt und die Prüfregeln im Skript haben das behoben.

## Stand der Erprobung

Die komplette Kette wurde mit mlx-audio 0.5.8, mlx-lm 0.32, Python 3.14 und den 8-bit-TTS-Modellen auf einem Mac mit Apple M4 (16 GB) durchlaufen: Bereinigung mit und ohne `--ki`, Probelauf mit drei entworfenen Stimmen, Vertonung per Voice Cloning und M4B-Export mit Kapitelmarken. Gemessene Werte auf diesem Gerät:

| Schritt | Dauer |
|---|---|
| Modell laden | etwa 10 s je Modell |
| Referenzstimme entwerfen | 6–13 s je Stimme |
| KI-Bereinigung (Qwen3.5 9B) | rund 5.000 Zeichen pro Minute |
| Vertonen | rund 1.000 Zeichen pro Minute Rechenzeit |
| Testbuch (3.800 Zeichen) | 4 Minuten Hörbuch in gut 3 Minuten |

Ein Roman mit 500.000 Zeichen braucht demnach etwa 8 Stunden. Falls etwas hakt, hilft die vollständige Fehlermeldung mit `--verbose` weiter.

### Windows mit NVIDIA-Grafikkarte (PyTorch/CUDA)

Der Windows-/CUDA-Weg wurde im Oktober 2026 auf einem Windows-11-Rechner mit einer **NVIDIA GeForce RTX 5070 Ti Laptop GPU (12 GB Grafikspeicher)** erprobt. Die Laptop-GPU ist von der oben genannten Desktop-RTX 5070 Ti mit 16 GB zu unterscheiden. Verwendete Umgebung:

| Komponente | Version / Konfiguration |
|---|---|
| Python | 3.12.10 |
| PyTorch / torchaudio | 2.11.0+cu128 / 2.11.0+cu128 |
| qwen-tts | 0.1.1 |
| transformers | 4.57.3 |
| NVIDIA-Treiber | 610.88 |
| FFmpeg | 9.0.2 |
| TTS-Modelle | Qwen3-TTS-12Hz-1.7B-VoiceDesign und Qwen3-TTS-12Hz-1.7B-Base |

Getestet wurden Textbereinigung, Stimmentwurf und Hörproben sowie die Vertonung mit einer Referenzaufnahme. PyTorch erkennt die CUDA-Grafikkarte (`torch.cuda.is_available()` ergibt `True`). Die Hinweise zu fehlendem FlashAttention und SoX verhindern die Nutzung der hier verwendeten 12-Hz-Modelle nicht.

Beim abschließenden Export muss FFmpeg für den laufenden Prozess im `PATH` erreichbar sein. War FFmpeg erst nach dem Öffnen des Terminals eingetragen worden, musste dessen Umgebung aktualisiert beziehungsweise das Terminal einschließlich der übergeordneten Anwendung neu gestartet werden. Bereits erzeugte WAV-Abschnitte können anschließend mit demselben `vertonen`-Befehl weiterverwendet werden.

Für diese Konfiguration liegen keine systematischen Geschwindigkeitsmessungen vor. Die optionale KI-Textbereinigung (`--ki`) ist durch diesen Test nicht abgedeckt.

### Windows ohne Grafikkarte (PyTorch auf der CPU)

Der PyTorch-Weg wurde am 16. Oktober 2026 auf einem Windows-11-Rechner ohne NVIDIA-Karte komplett durchgespielt: Intel Core i5-9400T (6 Kerne, 1,8 GHz), 24 GB RAM, Intel UHD Graphics 630, 50 GB frei auf `C:`. Das ist der ungünstigste Fall aus der Hardware-Tabelle und zeigt, dass die Kette auch dort funktioniert, nur langsam.

**Installation**, genau wie oben beschrieben, in der PowerShell:

```powershell
winget install --id Python.Python.3.12 --exact
winget install --id Gyan.FFmpeg --exact
cd C:\wc\hoerbuch
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install .
```

Der CUDA-Schritt entfällt ohne NVIDIA-Karte; `pip install .` zieht dann die CPU-Variante von PyTorch von PyPI. Installiert wurden Python 3.12.10, ffmpeg 9.0.2, torch 2.14.1+cpu, torchaudio 2.11.0, transformers 4.57.3 und qwen-tts 0.1.1; die virtuelle Umgebung belegt 1,5 GB. Ein neues Terminal nach `winget` ist nötig, damit `py` und `ffmpeg` gefunden werden. Beim Import von `qwen-tts` erscheinen die Warnungen zu SoX und flash-attn, die Prüfung `torch.cuda.is_available()` liefert erwartungsgemäß `False`.

**Durchlauf** mit einer Kopie von `beispiel/testbuch.txt` in einem eigenen Ordner:

```powershell
hoerbuch bereinigen testbuch.txt
hoerbuch probe testbuch.bereinigt.txt
hoerbuch vertonen testbuch.bereinigt.txt --ref probe\stimme_erzaehler_m.wav --titel "Der Nebel über Lindenbach"
```

Die Bereinigung lief in unter einer Sekunde und lieferte dasselbe Ergebnis wie auf dem Mac (6 Seitenzahlen, 4 Trennungen, 10 Abkürzungen, 11 Zahlen, 7 Kopfzeilen, 2 Kapitel, 4.501 Zeichen). Die Modelle wurden beim ersten Start geladen: VoiceDesign und Base je 4,3 GB, jeweils rund 10 Minuten Download. Die Symlink-Warnung von Hugging Face erschien, die Dateien lagen danach einfach im Snapshot-Ordner, ohne Verdopplung. Zwei abgebrochene HEAD-Anfragen an Hugging Face während des Probelaufs hat `huggingface_hub` selbst wiederholt.

Gemessene Werte auf diesem Rechner (float32, 6 Threads):

| Schritt | Dauer |
|---|---|
| Modell laden (nach dem Download) | etwa 1 Minute je Modell |
| Referenzstimme entwerfen | 10–11 s Audio in 109–125 s |
| Hörprobe (264 Zeichen) | 16 s Audio in 151–161 s |
| Tempo im Probelauf | rund 100 Zeichen pro Minute, also etwa ein Zehntel Echtzeit |
| Vertonen (4.501 Zeichen, 32 Abschnitte) | 5:11 Minuten Hörbuch in 53 Minuten, rund 84 Zeichen pro Minute |

Das Vertonen lief ohne Abbruch durch, kein Abschnitt fiel bei der Längenprüfung auf (keine `auffaellig.txt`), und ffmpeg schrieb die M4B-Datei mit Titel, Genre und zwei Kapitelmarken (2,5 MB bei 64 kbit/s). Der Mac mit M4 ist rund zehnmal schneller. Ein Roman mit 500.000 Zeichen bräuchte auf dieser CPU etwa 100 Stunden. Zum Ausprobieren und für kurze Texte reicht das, für ganze Bücher ist eine CUDA-Karte gesetzt.

## Aufbau des Projekts

```
hoerbuch/               Python-Paket
  cli.py                Kommandozeile (Unterbefehle und Optionen)
  befehle.py            exportieren, bereinigen, probe, stimme, vertonen
  epub.py               EPUB → Text mit Kapitelmarken
  bereinigung.py        regelbasierte Textbereinigung
  zahlen.py             Zahlen, Daten, Uhrzeiten als Zahlwörter (num2words)
  ki.py                 optionale Stufe mit lokalem Sprachmodell (mlx-lm oder transformers)
  kapitel.py            Text in Kapitel und sprechbare Abschnitte zerlegen
  tts.py                Sprachsynthese mit Qwen3-TTS (mlx-audio oder qwen-tts), Längenprüfung
  audio.py              WAV, Pegel, Stille, M4B/MP3-Export mit ffmpeg
  konfig.py             Backend-Wahl, Modelle, Pausen, Pegel, Standardstimme
tests/                  pytest-Tests für Text, Zahlen, Kapitel, EPUB und Audio (ohne Modelle)
beispiel/               Testbuch, fertiges Hörbuch dazu und Hörproben der drei entworfenen Stimmen
```

## Entwicklung

```bash
pip install -e ".[ki,dev]"
pytest
```

Die Tests brauchen weder Modelle noch Metal oder CUDA und laufen in unter einer Sekunde auf allen Plattformen. Die Textstufe (`bereinigung`, `zahlen`, `kapitel`, `epub`) ist reines Python. Die Modellaufrufe stecken ausschließlich in `tts.py` (Klassen `_VoiceMLX` und `_VoiceTorch`) und `ki.py` (`Refiner`); ein weiteres Backend braucht nur dieselbe kleine Schnittstelle (`synth`, `sample_rate`, `close` bzw. `ask`).

## Abgrenzung zu anderen Projekten

[audiblez](https://github.com/santinic/audiblez) ist schlanker, kann mit Kokoro aber kein Deutsch. [ebook2audiobook](https://github.com/DrewThomasson/ebook2audiobook) und [epub2tts](https://github.com/aedocw/epub2tts) unterstützen viele Engines und Formate, bereiten den Text aber nicht sprachspezifisch auf und nutzen auf dem Mac keine Metal-Beschleunigung für Qwen3-TTS. Der Schwerpunkt dieses Projekts ist die deutsche Textstufe: Zahlen, Daten und Abkürzungen werden deterministisch und grammatisch korrekt ausgeschrieben, statt sie dem Sprachmodell zu überlassen.

## Verantwortliche Nutzung

- Vertone nur Texte, an denen du die Rechte hast, etwa eigene Werke, gemeinfreie Bücher oder gekaufte E-Books für den privaten Gebrauch. Dieses Repository enthält bewusst keine Bücher, nur einen selbst geschriebenen Testtext.
- Klone nur deine eigene Stimme oder eine, deren Sprecher ausdrücklich zugestimmt hat. Die im Probelauf entworfenen Stimmen entstehen aus einer Textbeschreibung, nicht aus der Aufnahme einer realen Person.
- Die Modelle werden beim ersten Start von Hugging Face geladen und unterliegen ihren eigenen Lizenzen.

## Lizenz und Modelle

Der Code steht unter der [MIT-Lizenz](LICENSE). Die Modelle stammen von [Qwen](https://huggingface.co/Qwen) (Apache 2.0); auf Apple Silicon werden sie in der MLX-Umsetzung der [mlx-community](https://huggingface.co/mlx-community) geladen, unter PyTorch im Original. Das optionale Sprachmodell für `--ki` ebenso. Bitte die jeweiligen Lizenzbedingungen beachten.
