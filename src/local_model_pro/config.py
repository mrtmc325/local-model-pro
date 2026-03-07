from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    default_model: str = os.getenv("DEFAULT_MODEL", "qwen2.5:7b-instruct")
    default_temperature: float = float(os.getenv("DEFAULT_TEMPERATURE", "0.2"))
    default_num_ctx: int = int(os.getenv("DEFAULT_NUM_CTX", "4096"))


settings = Settings()

