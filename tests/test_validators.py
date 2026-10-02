from validators import is_valid_cf, normalize_cf, process_input


def test_normalize_cf_strips_and_uppercases():
    assert normalize_cf(" rssmra85m01h501z ") == "RSSMRA85M01H501Z"


def test_normalize_cf_removes_internal_whitespace():
    assert normalize_cf("RSSMRA 85M01H501Z") == "RSSMRA85M01H501Z"


def test_is_valid_cf_accepts_well_formed_code():
    assert is_valid_cf("RSSMRA85M01H501Z") is True


def test_is_valid_cf_rejects_wrong_length():
    assert is_valid_cf("INVALIDCF12345") is False


def test_process_input_counts_blank_duplicates_and_invalid():
    raw = [
        "RSSMRA85M01H501Z",
        "rssmra85m01h501z",  # duplicate after normalization
        "VRDLGI90A41F205X",
        "INVALIDCF12345",  # invalid format
        "",
        None,
        "CSTFNC75B01F839F",
        "CSTFNC75B01F839F",  # duplicate
    ]

    records, stats = process_input(raw)

    assert stats["total_rows"] == 8
    assert stats["blank"] == 2
    assert stats["duplicates"] == 2
    assert stats["invalid_format"] == 1
    assert stats["unique_valid"] == 3

    normalized = {r.normalized for r in records}
    assert normalized == {
        "RSSMRA85M01H501Z",
        "VRDLGI90A41F205X",
        "INVALIDCF12345",
        "CSTFNC75B01F839F",
    }

    invalid_record = next(r for r in records if r.normalized == "INVALIDCF12345")
    assert invalid_record.valid is False


def test_process_input_preserves_first_occurrence_order():
    raw = ["BNCGPP70C15L219K", "RSSMRA85M01H501Z"]
    records, _ = process_input(raw)
    assert [r.normalized for r in records] == ["BNCGPP70C15L219K", "RSSMRA85M01H501Z"]
