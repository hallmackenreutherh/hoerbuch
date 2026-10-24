"""Isolierter Arbeitsprozess der Oberfläche; Modelle blockieren niemals Qt."""
import json
import sys
from pathlib import Path
from .fortschritt import beobachten, melden


def main():
    with beobachten(lambda event: print("\nGUI_PROGRESS=" + json.dumps(event, ensure_ascii=False), flush=True)):
        ausfuehren()


def ausfuehren():
    melden("start", "Verarbeitung wird gestartet")
    if sys.argv[1] == "transkribieren":
        from .stt import transkribieren
        text = transkribieren(Path(sys.argv[2]), sys.argv[3])
        if not text.strip():
            raise ValueError("Kein gesprochener Text erkannt.")
        result = {"text": text}
    else:
        from .cli import run_command as cli_main
        result_path = cli_main()
        result = {"path": str(result_path)} if result_path else {}
    print("\nGUI_RESULT=" + json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
