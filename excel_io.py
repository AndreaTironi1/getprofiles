"""Lettura input (xlsx/csv) e scrittura del report Excel (Riepilogo + Dettaglio)."""

from datetime import datetime
from pathlib import Path

import pandas as pd

from checkpoint import (
    CheckpointEntry,
    OUTCOME_ERROR,
    OUTCOME_FORBIDDEN,
    OUTCOME_INVALID_FORMAT,
    OUTCOME_NO,
    OUTCOME_PENDING,
    OUTCOME_YES,
    OUTCOME_YES_BLOCKED,
)
from validators import CfRecord

REPORT_OUTCOME_ORDER = [
    OUTCOME_YES,
    OUTCOME_YES_BLOCKED,
    OUTCOME_NO,
    OUTCOME_FORBIDDEN,
    OUTCOME_ERROR,
    OUTCOME_INVALID_FORMAT,
    OUTCOME_PENDING,
]


def read_cf_column(input_path: Path, column: str) -> list:
    if input_path.suffix.lower() == ".csv":
        df = pd.read_csv(input_path, dtype=str)
    else:
        df = pd.read_excel(input_path, dtype=str)

    if column not in df.columns:
        raise ValueError(
            f"Colonna '{column}' non trovata in {input_path}. "
            f"Colonne disponibili: {list(df.columns)}"
        )
    return df[column].tolist()


def build_detail_rows(records: list[CfRecord], entries: dict[str, CheckpointEntry]) -> list[dict]:
    rows = []
    for record in records:
        if not record.valid:
            rows.append(
                {
                    "codice_fiscale_originale": record.original,
                    "codice_fiscale": record.normalized,
                    "esito": OUTCOME_INVALID_FORMAT,
                    "sender_allowed": None,
                    "lingue_preferite": None,
                    "http_status": None,
                    "dettaglio_errore": "Formato CF non valido",
                    "timestamp": None,
                    "tentativi": 0,
                }
            )
            continue

        entry = entries.get(record.normalized)
        if entry is None:
            rows.append(
                {
                    "codice_fiscale_originale": record.original,
                    "codice_fiscale": record.normalized,
                    "esito": OUTCOME_PENDING,
                    "sender_allowed": None,
                    "lingue_preferite": None,
                    "http_status": None,
                    "dettaglio_errore": None,
                    "timestamp": None,
                    "tentativi": 0,
                }
            )
            continue

        rows.append(
            {
                "codice_fiscale_originale": record.original,
                "codice_fiscale": record.normalized,
                "esito": entry.esito,
                "sender_allowed": entry.sender_allowed,
                "lingue_preferite": ", ".join(entry.preferred_languages) if entry.preferred_languages else None,
                "http_status": entry.http_status,
                "dettaglio_errore": entry.error_detail,
                "timestamp": entry.timestamp,
                "tentativi": entry.attempts,
            }
        )
    return rows


def build_summary_rows(detail_rows: list[dict], stats: dict, input_path: Path) -> list[dict]:
    total_unique = len(detail_rows)
    counts = {outcome: 0 for outcome in REPORT_OUTCOME_ORDER}
    for row in detail_rows:
        counts[row["esito"]] = counts.get(row["esito"], 0) + 1

    rows = [
        {"voce": "File di input", "valore": str(input_path)},
        {"voce": "Data generazione report", "valore": datetime.now().isoformat(timespec="seconds")},
        {"voce": "Righe lette dal file", "valore": stats["total_rows"]},
        {"voce": "Righe vuote scartate", "valore": stats["blank"]},
        {"voce": "Duplicati rimossi", "valore": stats["duplicates"]},
        {"voce": "CF univoci considerati", "valore": total_unique},
        {"voce": "", "valore": ""},
    ]
    for outcome in REPORT_OUTCOME_ORDER:
        count = counts.get(outcome, 0)
        pct = (count / total_unique * 100) if total_unique else 0.0
        rows.append({"voce": outcome, "valore": count, "percentuale": f"{pct:.1f}%"})
    return rows


def write_report(
    output_path: Path,
    records: list[CfRecord],
    entries: dict[str, CheckpointEntry],
    stats: dict,
    input_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    detail_rows = build_detail_rows(records, entries)
    summary_rows = build_summary_rows(detail_rows, stats, input_path)

    detail_df = pd.DataFrame(detail_rows)
    summary_df = pd.DataFrame(summary_rows)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        summary_df.to_excel(writer, sheet_name="Riepilogo", index=False)
        detail_df.to_excel(writer, sheet_name="Dettaglio", index=False)
