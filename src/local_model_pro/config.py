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
    knowledge_assist_default: bool = _env_flag("KNOWLEDGE_ASSIST_DEFAULT", "true")
    knowledge_recursion_passes: int = int(os.getenv("KNOWLEDGE_RECURSION_PASSES", "3"))
    knowledge_planner_model: str = os.getenv("KNOWLEDGE_PLANNER_MODEL", "").strip()
    knowledge_insight_model: str = os.getenv("KNOWLEDGE_INSIGHT_MODEL", "").strip()
    sqlite_db_path: str = os.getenv("SQLITE_DB_PATH", "./data/local_model_pro.db")
    qdrant_url: str = os.getenv("QDRANT_URL", "http://127.0.0.1:6333")
    qdrant_collection: str = os.getenv("QDRANT_COLLECTION", "local_model_pro_insights")
    knowledge_memory_top_k: int = int(os.getenv("KNOWLEDGE_MEMORY_TOP_K", "5"))
    knowledge_memory_score_threshold: float = float(
        os.getenv("KNOWLEDGE_MEMORY_SCORE_THRESHOLD", "0.25")
    )
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")
    grounded_mode_default: bool = _env_flag("GROUNDED_MODE_DEFAULT", "true")
    grounded_profile_default: str = (
        os.getenv("GROUNDED_PROFILE_DEFAULT", "balanced").strip().lower()
        if os.getenv("GROUNDED_PROFILE_DEFAULT", "balanced").strip().lower() in {"strict", "balanced"}
        else "balanced"
    )
    grounded_timeout_seconds: int = int(os.getenv("GROUNDED_TIMEOUT_SECONDS", "25"))
    default_actor_id: str = os.getenv("DEFAULT_ACTOR_ID", "anonymous").strip() or "anonymous"
    direct_save_enabled: bool = _env_flag("DIRECT_SAVE_ENABLED", "true")
    memory_export_dir: str = os.getenv("MEMORY_EXPORT_DIR", "/data/memory_exports").strip() or "/data/memory_exports"
    direct_save_max_turns: int = int(os.getenv("DIRECT_SAVE_MAX_TURNS", "5000"))
    url_review_enabled: bool = _env_flag("URL_REVIEW_ENABLED", "true")
    url_review_max_urls: int = int(os.getenv("URL_REVIEW_MAX_URLS", "3"))
    url_review_timeout_seconds: int = int(os.getenv("URL_REVIEW_TIMEOUT_SECONDS", "20"))
    url_review_max_bytes: int = int(os.getenv("URL_REVIEW_MAX_BYTES", "2000000"))
    web_assist_page_review_enabled: bool = _env_flag("WEB_ASSIST_PAGE_REVIEW_ENABLED", "true")
    web_assist_page_review_max_urls: int = int(os.getenv("WEB_ASSIST_PAGE_REVIEW_MAX_URLS", "2"))


settings = Settings()
