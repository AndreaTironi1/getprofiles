"""CLI: verifica su App IO dei codici fiscali elencati in un file Excel/CSV."""

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import checkpoint as ckpt
import config as cfg
import excel_io
import validators
from api_client import CircuitBreakerTripped, ProfileApiClient, UnauthorizedError

logger = logging.getLogger("getprofiles")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="File Excel/CSV con i codici fiscali")
    parser.add_argument("--column", default="codice_fiscale", help="Nome colonna con i CF")
    parser.add_argument("--output", default=None, help="Excel di output (default: data/report.xlsx)")
    parser.add_argument("--checkpoint", default=None, help="Path del file di checkpoint JSONL")
    parser.add_argument("--config", default=None, help="File di configurazione (default: ./config.ini)")
    parser.add_argument("--rate", type=float, default=2.0, help="Richieste al secondo")
    parser.add_argument("--max-retries", type=int, default=5, help="Tentativi per errori transitori")
    parser.add_argument("--base-delay", type=float, default=1.0, help="Delay base del backoff (secondi)")
    parser.add_argument("--max-delay", type=float, default=60.0, help="Delay massimo del backoff (secondi)")
    parser.add_argument("--timeout", type=float, default=10.0, help="Timeout per chiamata HTTP (secondi)")
    skip_group = parser.add_mutually_exclusive_group()
    skip_group.add_argument(
        "--skip-existing", action="store_true",
        help="Salta i CF che hanno già un esito definitivo nel checkpoint (Sì/No/Forbidden/Scartato/Errore)",
    )
    skip_group.add_argument(
        "--retry-failed", action="store_true",
        help="Come --skip-existing, ma rilavora comunque i CF finiti in Errore",
    )
    parser.add_argument("--export-only", action="store_true", help="Rigenera solo l'Excel dal checkpoint")
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args()


def select_to_process(records, entries, retry_failed: bool, skip_existing: bool):
    """CF validi da interrogare in questo run, secondo la policy scelta.

    Default (nessuna delle due opzioni): rilavora TUTTI i CF validi,
    ignorando il checkpoint. --skip-existing/--retry-failed sono l'opt-in
    per saltare quelli già con un esito registrato (utile su grandi volumi
    per non rifare tutte le chiamate già fatte in run precedenti).
    """
    if not skip_existing and not retry_failed:
        return [r for r in records if r.valid]
    return [
        r for r in records
        if r.valid and not ckpt.should_skip(entries.get(r.normalized), retry_failed)
    ]


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=args.log_level, format="%(asctime)s %(levelname)s %(message)s")

    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else Path("data") / "report.xlsx"
    checkpoint_path = Path(args.checkpoint) if args.checkpoint else ckpt.default_path_for(input_path)

    raw_values = excel_io.read_cf_column(input_path, args.column)
    records, stats = validators.process_input(raw_values)
    logger.info(
        "Input: %d righe, %d vuote, %d duplicati, %d CF univoci (%d non validi)",
        stats["total_rows"], stats["blank"], stats["duplicates"],
        stats["unique_valid"] + stats["invalid_format"], stats["invalid_format"],
    )

    entries = ckpt.load(checkpoint_path)
    logger.info("Checkpoint: %d esiti già registrati in %s", len(entries), checkpoint_path)

    if not args.export_only:
        try:
            subscription_key = cfg.resolve_subscription_key(
                Path(args.config) if args.config else None
            )
        except cfg.ConfigError as exc:
            logger.error(str(exc))
            return 1

        to_process = select_to_process(records, entries, args.retry_failed, args.skip_existing)
        logger.info("CF da interrogare in questo run: %d", len(to_process))

        client = ProfileApiClient(
            subscription_key=subscription_key,
            rate=args.rate,
            max_retries=args.max_retries,
            base_delay=args.base_delay,
            max_delay=args.max_delay,
            timeout=args.timeout,
        )

        progress_every = max(1, min(50, len(to_process) // 20 or 1))
        started_at = time.monotonic()
        status_counts: dict[str, int] = {}

        for i, record in enumerate(to_process, start=1):
            try:
                result = client.get_profile(record.normalized)
            except UnauthorizedError as exc:
                logger.error(str(exc))
                return 1
            except CircuitBreakerTripped as exc:
                logger.error(str(exc))
                return 1

            status_label = str(result.http_status) if result.http_status is not None else "errore"
            status_counts[status_label] = status_counts.get(status_label, 0) + 1

            entry = ckpt.CheckpointEntry(
                codice_fiscale=record.normalized,
                timestamp=datetime.now().isoformat(timespec="seconds"),
                esito=result.esito,
                http_status=result.http_status,
                sender_allowed=result.sender_allowed,
                preferred_languages=result.preferred_languages,
                error_detail=result.error_detail,
                attempts=result.attempts,
            )
            ckpt.append(checkpoint_path, entry)
            entries[record.normalized] = entry

            logger.info("Progresso %d/%d: %s", i, len(to_process), status_label)

            if i % progress_every == 0 or i == len(to_process):
                elapsed = time.monotonic() - started_at
                rate = i / elapsed if elapsed > 0 else 0.0
                remaining = (len(to_process) - i) / rate if rate > 0 else 0.0
                logger.info(
                    "Progresso: %d/%d (%.1f%%), ~%.0fs residui",
                    i, len(to_process), i / len(to_process) * 100 if to_process else 100.0, remaining,
                )

        if to_process:
            totale = " ".join(
                f"{status}={count}" for status, count in sorted(status_counts.items())
            )
            logger.info("Totale per risultato: %s", totale)

    excel_io.write_report(output_path, records, entries, stats, input_path)
    logger.info("Report scritto in %s", output_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
