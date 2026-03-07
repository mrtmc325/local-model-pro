from __future__ import annotations

import os
from dataclasses import dataclass


def _env_flag(name: str, default: str = "false") -> bool:
    value = os.getenv(name, default).strip().lower()
    return value in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    default_model: str = os.getenv("DEFAULT_MODEL", "qwen2.5:7b")
    default_temperature: float = float(os.getenv("DEFAULT_TEMPERATURE", "0.2"))
    default_num_ctx: int = int(os.getenv("DEFAULT_NUM_CTX", "4096"))
    web_search_max_results: int = int(os.getenv("WEB_SEARCH_MAX_RESULTS", "5"))
    web_assist_default: bool = _env_flag("WEB_ASSIST_DEFAULT", "false")


settings = Settings()
