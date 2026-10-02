from pathlib import Path

import checkpoint as ckpt


def make_entry(cf, esito, timestamp="2026-07-31T10:00:00"):
    return ckpt.CheckpointEntry(
        codice_fiscale=cf,
        timestamp=timestamp,
        esito=esito,
        http_status=200,
        sender_allowed=True,
        preferred_languages=["it_IT"],
        error_detail=None,
        attempts=1,
    )


def test_append_and_load_round_trip(tmp_path: Path):
    path = tmp_path / "checkpoint.jsonl"
    entry = make_entry("RSSMRA85M01H501Z", ckpt.OUTCOME_YES)

    ckpt.append(path, entry)
    loaded = ckpt.load(path)

    assert "RSSMRA85M01H501Z" in loaded
    assert loaded["RSSMRA85M01H501Z"].esito == ckpt.OUTCOME_YES


def test_load_keeps_last_occurrence_per_cf(tmp_path: Path):
    path = tmp_path / "checkpoint.jsonl"
    ckpt.append(path, make_entry("RSSMRA85M01H501Z", ckpt.OUTCOME_ERROR, timestamp="t1"))
    ckpt.append(path, make_entry("RSSMRA85M01H501Z", ckpt.OUTCOME_YES, timestamp="t2"))

    loaded = ckpt.load(path)

    assert loaded["RSSMRA85M01H501Z"].esito == ckpt.OUTCOME_YES
    assert loaded["RSSMRA85M01H501Z"].timestamp == "t2"


def test_load_ignores_truncated_last_line(tmp_path: Path):
    path = tmp_path / "checkpoint.jsonl"
    ckpt.append(path, make_entry("RSSMRA85M01H501Z", ckpt.OUTCOME_YES))
    with path.open("a", encoding="utf-8") as f:
        f.write('{"codice_fiscale": "VRDLGI90A41F205X", "esito": "S')  # riga troncata, no newline

    loaded = ckpt.load(path)

    assert "RSSMRA85M01H501Z" in loaded
    assert "VRDLGI90A41F205X" not in loaded


def test_load_returns_empty_dict_when_file_missing(tmp_path: Path):
    assert ckpt.load(tmp_path / "missing.jsonl") == {}


def test_should_skip_terminal_outcomes():
    entry = make_entry("RSSMRA85M01H501Z", ckpt.OUTCOME_NO)
    assert ckpt.should_skip(entry, retry_failed=False) is True
    assert ckpt.should_skip(entry, retry_failed=True) is True


def test_should_skip_error_outcome_respects_retry_failed():
    entry = make_entry("RSSMRA85M01H501Z", ckpt.OUTCOME_ERROR)
    assert ckpt.should_skip(entry, retry_failed=False) is True
    assert ckpt.should_skip(entry, retry_failed=True) is False


def test_should_skip_returns_false_when_no_entry():
    assert ckpt.should_skip(None, retry_failed=False) is False
