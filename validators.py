"""Normalizzazione e validazione dei codici fiscali in input."""

import re
from dataclasses import dataclass

CF_PATTERN = re.compile(
    r"^[A-Z]{6}[0-9LMNPQRSTUV]{2}[ABCDEHLMPRST][0-9LMNPQRSTUV]{2}"
    r"[A-Z][0-9LMNPQRSTUV]{3}[A-Z]$"
)


@dataclass
class CfRecord:
    original: str
    normalized: str
    valid: bool


def normalize_cf(raw: str) -> str:
    return re.sub(r"\s+", "", str(raw)).upper()


def is_valid_cf(cf: str) -> bool:
    return bool(CF_PATTERN.match(cf))


def process_input(raw_values: list) -> tuple[list[CfRecord], dict]:
    """Normalizza, valida e deduplica una lista grezza di valori CF.

    Ritorna (record univoci in ordine di prima apparizione, statistiche).
    I record con formato non valido sono inclusi (valid=False) ma non
    verranno mai inviati all'API dal chiamante.
    """
    blank_count = 0
    duplicate_count = 0
    seen: dict[str, CfRecord] = {}
    ordered: list[CfRecord] = []

    for raw in raw_values:
        if raw is None or str(raw).strip() == "" or str(raw).lower() == "nan":
            blank_count += 1
            continue

        normalized = normalize_cf(raw)
        if normalized in seen:
            duplicate_count += 1
            continue

        record = CfRecord(original=str(raw), normalized=normalized, valid=is_valid_cf(normalized))
        seen[normalized] = record
        ordered.append(record)

    stats = {
        "total_rows": len(raw_values),
        "blank": blank_count,
        "duplicates": duplicate_count,
        "invalid_format": sum(1 for r in ordered if not r.valid),
        "unique_valid": sum(1 for r in ordered if r.valid),
    }
    return ordered, stats
