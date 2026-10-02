"""Risoluzione della subscription key PagoPA senza mai hardcodarla nel codice."""

import configparser
import os
from pathlib import Path

ENV_VAR_NAME = "IO_API_SUBSCRIPTION_KEY"
DEFAULT_CONFIG_PATH = Path("config.ini")


class ConfigError(RuntimeError):
    pass


def resolve_subscription_key(config_path: Path | None = None) -> str:
    """Priorità: 1) variabile d'ambiente, 2) config.ini locale."""
    env_key = os.environ.get(ENV_VAR_NAME)
    if env_key:
        return env_key.strip()

    path = config_path or DEFAULT_CONFIG_PATH
    if path.exists():
        parser = configparser.ConfigParser()
        parser.read(path, encoding="utf-8")
        key = parser.get("api", "subscription_key", fallback="").strip()
        if key and key != "REPLACE_WITH_YOUR_OCP_APIM_SUBSCRIPTION_KEY":
            return key

    raise ConfigError(
        f"Subscription key non trovata. Impostare la variabile d'ambiente "
        f"{ENV_VAR_NAME} oppure creare '{path}' (copiando config.example.ini) "
        f"con la chiave nella sezione [api]."
    )


def mask_key(key: str) -> str:
    """Rappresentazione sicura della key per i log, mai il valore in chiaro."""
    if len(key) <= 4:
        return "***"
    return f"***{key[-4:]}"
