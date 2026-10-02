"""Checkpoint incrementale (JSON Lines) e logica di resume.

Ogni riga del file è un esito terminale (o d'errore) per un CF. Il file è
append-only: un CF rilavorato (es. con --retry-failed) scrive una nuova riga
e l'ultima occorrenza vince in lettura. Questo rende il checkpoint resiliente
a interruzioni brusche: al più si perde la riga in corso di scrittura.
"""

import json
from dataclasses import asdict, dataclass
from pathlib import Path

OUTCOME_YES = "Sì (attivo)"
OUTCOME_YES_BLOCKED = "Sì (attivo, messaggi bloccati)"
OUTCOME_NO = "No (nessun profilo)"
OUTCOME_FORBIDDEN = "Forbidden (da verificare)"
OUTCOME_ERROR = "Errore (non verificabile)"
OUTCOME_INVALID_FORMAT = "Scartato (formato non valido)"
OUTCOME_PENDING = "In sospeso (rieseguire)"

# Esiti che per default non vengono ripetuti in un resume.
TERMINAL_OUTCOMES = {
    OUTCOME_YES,
    OUTCOME_YES_BLOCKED,
    OUTCOME_NO,
    OUTCOME_FORBIDDEN,
    OUTCOME_ERROR,
    OUTCOME_INVALID_FORMAT,
}

# Esiti che --retry-failed considera nuovamente lavorabili.
RETRYABLE_OUTCOMES = {OUTCOME_ERROR}


@dataclass
class CheckpointEntry:
    codice_fiscale: str
    timestamp: str
    esito: str
    http_status: int | None = None
    sender_allowed: bool | None = None
    preferred_languages: list | None = None
    error_detail: str | None = None
    attempts: int = 0

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @staticmethod
    def from_dict(data: dict) -> "CheckpointEntry":
        return CheckpointEntry(
            codice_fiscale=data["codice_fiscale"],
            timestamp=data["timestamp"],
            esito=data["esito"],
            http_status=data.get("http_status"),
            sender_allowed=data.get("sender_allowed"),
            preferred_languages=data.get("preferred_languages"),
            error_detail=data.get("error_detail"),
            attempts=data.get("attempts", 0),
        )


def load(path: Path) -> dict[str, CheckpointEntry]:
    """Rilegge il checkpoint tenendo, per ogni CF, l'ultima occorrenza valida.

    Una eventuale ultima riga troncata (crash a metà scrittura) viene
    scartata silenziosamente senza invalidare le righe precedenti.
    """
    entries: dict[str, CheckpointEntry] = {}
    if not path.exists():
        return entries

    with path.open("r", encoding="utf-8") as f:
        lines = f.readlines()

    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            if i == len(lines) - 1:
                continue  # ultima riga troncata: run interrotto a metà scrittura
            raise
        entry = CheckpointEntry.from_dict(data)
        entries[entry.codice_fiscale] = entry

    return entries


def append(path: Path, entry: CheckpointEntry) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(entry.to_json() + "\n")
        f.flush()


def should_skip(entry: CheckpointEntry | None, retry_failed: bool) -> bool:
    if entry is None:
        return False
    if entry.esito not in TERMINAL_OUTCOMES:
        return False
    if retry_failed and entry.esito in RETRYABLE_OUTCOMES:
        return False
    return True


def default_path_for(input_path: Path) -> Path:
    return Path("data") / f"checkpoint__{input_path.stem}.jsonl"
