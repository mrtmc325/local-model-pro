from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_bool(name: str, default: str) -> bool:
    value = os.getenv(name, default).strip().lower()
    return value in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    default_model: str = os.getenv("DEFAULT_MODEL", "qwen2.5:7b")
    default_temperature: float = float(os.getenv("DEFAULT_TEMPERATURE", "0.2"))
    default_num_ctx: int = int(os.getenv("DEFAULT_NUM_CTX", "4096"))
    default_actor_id: str = os.getenv("DEFAULT_ACTOR_ID", "anonymous").strip() or "anonymous"
    workspace_root: str = str(
        Path(os.getenv("WORKSPACE_ROOT", os.getcwd())).expanduser().resolve()
    )
    filesystem_tools_enabled: bool = _env_bool("FILESYSTEM_TOOLS_ENABLED", "true")
    terminal_tools_enabled: bool = _env_bool("TERMINAL_TOOLS_ENABLED", "true")
    terminal_require_confirm: bool = _env_bool("TERMINAL_REQUIRE_CONFIRM", "true")
    terminal_timeout_seconds: int = int(os.getenv("TERMINAL_TIMEOUT_SECONDS", "25"))
    terminal_max_output_bytes: int = int(os.getenv("TERMINAL_MAX_OUTPUT_BYTES", "60000"))
    fs_read_max_bytes: int = int(os.getenv("FS_READ_MAX_BYTES", "120000"))
    fs_list_max_entries: int = int(os.getenv("FS_LIST_MAX_ENTRIES", "400"))
    fs_find_max_results: int = int(os.getenv("FS_FIND_MAX_RESULTS", "60"))
    fs_summary_max_files: int = int(os.getenv("FS_SUMMARY_MAX_FILES", "8"))
    fs_summary_file_chars: int = int(os.getenv("FS_SUMMARY_FILE_CHARS", "2400"))
    admin_state_path: str = str(
        Path(
            os.getenv(
                "ADMIN_STATE_PATH",
                str(
                    Path(os.getenv("WORKSPACE_ROOT", os.getcwd())).expanduser().resolve()
                    / "data"
                    / "admin_profile_state.json"
                ),
            )
        )
        .expanduser()
        .resolve()
    )
    admin_api_token: str = os.getenv("ADMIN_API_TOKEN", "").strip()
    devflow_enabled: bool = _env_bool("DEVFLOW_ENABLED", "true")
    devflow_max_concurrent_jobs: int = int(os.getenv("DEVFLOW_MAX_CONCURRENT_JOBS", "1"))
    devflow_role_timeout_seconds: int = int(os.getenv("DEVFLOW_ROLE_TIMEOUT_SECONDS", "90"))
    devflow_run_retention: int = int(os.getenv("DEVFLOW_RUN_RETENTION", "30"))
    devflow_artifact_dir: str = str(
        Path(
            os.getenv(
                "DEVFLOW_ARTIFACT_DIR",
                str(
                    Path(os.getenv("WORKSPACE_ROOT", os.getcwd())).expanduser().resolve()
                    / "data"
                    / "devflow_runs"
                ),
            )
        )
        .expanduser()
        .resolve()
    )


settings = Settings()
