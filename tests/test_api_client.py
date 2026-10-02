import pytest
import requests

import checkpoint as ckpt
from api_client import (
    BASE_URL,
    CircuitBreakerTripped,
    ProfileApiClient,
    UnauthorizedError,
)

CF = "RSSMRA85M01H501Z"
URL = f"{BASE_URL}/profiles/{CF}"


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    # Le pause di rate-limit/backoff non servono nei test: le azzeriamo.
    monkeypatch.setattr("api_client.time.sleep", lambda _seconds: None)


def make_client(**overrides):
    params = dict(subscription_key="test-key", rate=1000.0, max_retries=2, base_delay=0.01, max_delay=0.02, timeout=1.0)
    params.update(overrides)
    return ProfileApiClient(**params)


def test_get_profile_200_sender_allowed_true(requests_mock):
    requests_mock.get(URL, json={"sender_allowed": True, "preferred_languages": ["it_IT"]}, status_code=200)
    client = make_client()

    result = client.get_profile(CF)

    assert result.esito == ckpt.OUTCOME_YES
    assert result.sender_allowed is True
    assert result.http_status == 200
    assert result.attempts == 1


def test_get_profile_200_sender_allowed_false(requests_mock):
    requests_mock.get(URL, json={"sender_allowed": False}, status_code=200)
    client = make_client()

    result = client.get_profile(CF)

    assert result.esito == ckpt.OUTCOME_YES_BLOCKED
    assert result.sender_allowed is False


def test_get_profile_404_no_profile(requests_mock):
    requests_mock.get(URL, status_code=404)
    client = make_client()

    result = client.get_profile(CF)

    assert result.esito == ckpt.OUTCOME_NO
    assert result.http_status == 404


def test_get_profile_403_forbidden_not_retried(requests_mock):
    requests_mock.get(URL, status_code=403)
    client = make_client()

    result = client.get_profile(CF)

    assert result.esito == ckpt.OUTCOME_FORBIDDEN
    assert result.attempts == 1  # nessun retry per 403


def test_get_profile_401_raises_unauthorized(requests_mock):
    requests_mock.get(URL, status_code=401)
    client = make_client()

    with pytest.raises(UnauthorizedError):
        client.get_profile(CF)


def test_get_profile_429_then_200_recovers(requests_mock):
    requests_mock.get(
        URL,
        [
            {"status_code": 429},
            {"json": {"sender_allowed": True}, "status_code": 200},
        ],
    )
    client = make_client()

    result = client.get_profile(CF)

    assert result.esito == ckpt.OUTCOME_YES
    assert result.attempts == 2


def test_get_profile_exhausts_retries_on_repeated_timeout(requests_mock):
    requests_mock.get(URL, exc=requests.exceptions.ConnectTimeout)
    client = make_client(max_retries=2)

    result = client.get_profile(CF)

    assert result.esito == ckpt.OUTCOME_ERROR
    assert result.attempts == 3  # 1 tentativo iniziale + 2 retry


def test_circuit_breaker_trips_after_consecutive_transient_failures(requests_mock):
    requests_mock.get(URL, exc=requests.exceptions.ConnectTimeout)
    client = make_client(max_retries=0, circuit_breaker_threshold=3)

    client.get_profile(CF)
    client.get_profile(CF)
    with pytest.raises(CircuitBreakerTripped):
        client.get_profile(CF)
