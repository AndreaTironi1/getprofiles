"""Client per l'API PagoPA GetProfile: retry/backoff, rate limit, mapping esiti.

Endpoint: GET https://api.io.pagopa.it/api/v1/profiles/{fiscal_code}
Header:   Ocp-Apim-Subscription-Key

Mapping (verificato sulla spec OpenAPI ufficiale pagopa/io-functions-services):
  200 -> LimitedProfile{sender_allowed, preferred_languages} -> ha profilo IO
  404 -> nessun profilo IO
  401 -> subscription key non valida -> abort dell'intero run (UnauthorizedError)
  403 -> Forbidden, NON equivale a "niente app": marcato a parte
  429/5xx/timeout/connessione -> transitorio -> retry con backoff esponenziale
"""

import logging
import random
import time
from dataclasses import dataclass

import requests

from checkpoint import (
    OUTCOME_ERROR,
    OUTCOME_FORBIDDEN,
    OUTCOME_NO,
    OUTCOME_YES,
    OUTCOME_YES_BLOCKED,
)

BASE_URL = "https://api.io.pagopa.it/api/v1"

logger = logging.getLogger(__name__)


class UnauthorizedError(RuntimeError):
    """401: subscription key non valida. Non è un problema del singolo CF."""


class CircuitBreakerTripped(RuntimeError):
    """Troppi errori transitori consecutivi: probabile disservizio lato API."""


@dataclass
class ProfileResult:
    esito: str
    http_status: int | None
    sender_allowed: bool | None
    preferred_languages: list | None
    error_detail: str | None
    attempts: int


class ProfileApiClient:
    def __init__(
        self,
        subscription_key: str,
        rate: float = 2.0,
        max_retries: int = 5,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        timeout: float = 10.0,
        circuit_breaker_threshold: int = 10,
        session: requests.Session | None = None,
    ):
        self.subscription_key = subscription_key
        self.min_interval = 1.0 / rate if rate > 0 else 0.0
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.timeout = timeout
        self.circuit_breaker_threshold = circuit_breaker_threshold
        self.session = session or requests.Session()

        self._last_request_at: float | None = None
        self._consecutive_transient_failures = 0

    def _respect_rate_limit(self) -> None:
        if self.min_interval <= 0 or self._last_request_at is None:
            self._last_request_at = time.monotonic()
            return
        elapsed = time.monotonic() - self._last_request_at
        remaining = self.min_interval - elapsed
        if remaining > 0:
            time.sleep(remaining)
        self._last_request_at = time.monotonic()

    def _backoff_delay(self, attempt: int, retry_after: float | None) -> float:
        delay = min(self.base_delay * (2 ** (attempt - 1)), self.max_delay)
        delay += random.uniform(0, self.base_delay)
        if retry_after is not None:
            delay = max(delay, retry_after)
        return min(delay, self.max_delay)

    def get_profile(self, fiscal_code: str) -> ProfileResult:
        url = f"{BASE_URL}/profiles/{fiscal_code}"
        headers = {"Ocp-Apim-Subscription-Key": self.subscription_key}

        attempt = 0
        while True:
            attempt += 1
            self._respect_rate_limit()

            try:
                response = self.session.get(url, headers=headers, timeout=self.timeout)
            except (requests.Timeout, requests.ConnectionError) as exc:
                result = self._handle_transient(fiscal_code, attempt, None, str(exc))
                if result is not None:
                    return result
                continue

            status = response.status_code

            if status == 200:
                self._consecutive_transient_failures = 0
                body = response.json()
                sender_allowed = body.get("sender_allowed", True)
                esito = OUTCOME_YES if sender_allowed else OUTCOME_YES_BLOCKED
                return ProfileResult(
                    esito=esito,
                    http_status=status,
                    sender_allowed=sender_allowed,
                    preferred_languages=body.get("preferred_languages"),
                    error_detail=None,
                    attempts=attempt,
                )

            if status == 404:
                self._consecutive_transient_failures = 0
                return ProfileResult(
                    esito=OUTCOME_NO,
                    http_status=status,
                    sender_allowed=None,
                    preferred_languages=None,
                    error_detail=None,
                    attempts=attempt,
                )

            if status == 403:
                self._consecutive_transient_failures = 0
                return ProfileResult(
                    esito=OUTCOME_FORBIDDEN,
                    http_status=status,
                    sender_allowed=None,
                    preferred_languages=None,
                    error_detail="403 Forbidden: richiede verifica manuale",
                    attempts=attempt,
                )

            if status == 401:
                raise UnauthorizedError(
                    "401 Unauthorized: subscription key non valida, run interrotto"
                )

            if status == 429 or 500 <= status < 600:
                retry_after = self._parse_retry_after(response)
                result = self._handle_transient(
                    fiscal_code, attempt, retry_after, f"HTTP {status}"
                )
                if result is not None:
                    return result
                continue

            # Status inatteso, non documentato: non ritentato.
            self._consecutive_transient_failures = 0
            return ProfileResult(
                esito=OUTCOME_ERROR,
                http_status=status,
                sender_allowed=None,
                preferred_languages=None,
                error_detail=f"Status HTTP inatteso: {status}",
                attempts=attempt,
            )

    def _handle_transient(
        self, fiscal_code: str, attempt: int, retry_after: float | None, detail: str
    ) -> ProfileResult | None:
        """Ritorna un ProfileResult di errore se i retry sono esauriti, altrimenti
        dorme e ritorna None per far ritentare il chiamante."""
        if attempt > self.max_retries:
            self._consecutive_transient_failures += 1
            logger.warning("CF %s: errore dopo %d tentativi (%s)", fiscal_code, attempt - 1, detail)
            if self._consecutive_transient_failures >= self.circuit_breaker_threshold:
                raise CircuitBreakerTripped(
                    f"{self._consecutive_transient_failures} errori transitori consecutivi: "
                    "run interrotto, probabile disservizio lato API"
                )
            return ProfileResult(
                esito=OUTCOME_ERROR,
                http_status=None,
                sender_allowed=None,
                preferred_languages=None,
                error_detail=detail,
                attempts=attempt,
            )

        delay = self._backoff_delay(attempt, retry_after)
        logger.info("CF %s: tentativo %d fallito (%s), retry tra %.1fs", fiscal_code, attempt, detail, delay)
        time.sleep(delay)
        return None

    @staticmethod
    def _parse_retry_after(response: requests.Response) -> float | None:
        raw = response.headers.get("Retry-After")
        if not raw:
            return None
        try:
            return float(raw)
        except ValueError:
            return None
