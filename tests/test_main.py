import checkpoint as ckpt
from main import select_to_process
from validators import CfRecord


def make_entry(cf, esito):
    return ckpt.CheckpointEntry(
        codice_fiscale=cf, timestamp="t", esito=esito, http_status=200,
        sender_allowed=True, preferred_languages=None, error_detail=None, attempts=1,
    )


def build_records():
    return [
        CfRecord("RSSMRA85M01H501Z", "RSSMRA85M01H501Z", True),  # esito Sì nel checkpoint
        CfRecord("VRDLGI90A41F205X", "VRDLGI90A41F205X", True),  # esito Errore nel checkpoint
        CfRecord("BNCGPP70C15L219K", "BNCGPP70C15L219K", True),  # non ancora processato
        CfRecord("INVALIDCF12345", "INVALIDCF12345", False),      # formato non valido
    ]


def build_entries():
    return {
        "RSSMRA85M01H501Z": make_entry("RSSMRA85M01H501Z", ckpt.OUTCOME_YES),
        "VRDLGI90A41F205X": make_entry("VRDLGI90A41F205X", ckpt.OUTCOME_ERROR),
    }


def test_default_reprocesses_all_ignoring_checkpoint():
    records, entries = build_records(), build_entries()
    result = select_to_process(records, entries, retry_failed=False, skip_existing=False)
    assert {r.normalized for r in result} == {
        "RSSMRA85M01H501Z", "VRDLGI90A41F205X", "BNCGPP70C15L219K",
    }


def test_skip_existing_skips_terminal_outcomes():
    records, entries = build_records(), build_entries()
    result = select_to_process(records, entries, retry_failed=False, skip_existing=True)
    assert {r.normalized for r in result} == {"BNCGPP70C15L219K"}


def test_retry_failed_reprocesses_errors_too():
    records, entries = build_records(), build_entries()
    result = select_to_process(records, entries, retry_failed=True, skip_existing=False)
    assert {r.normalized for r in result} == {"VRDLGI90A41F205X", "BNCGPP70C15L219K"}


def test_invalid_format_never_included_in_any_mode():
    records, entries = build_records(), build_entries()
    for retry_failed, skip_existing in [(False, False), (False, True), (True, False)]:
        result = select_to_process(records, entries, retry_failed, skip_existing)
        assert "INVALIDCF12345" not in {r.normalized for r in result}
