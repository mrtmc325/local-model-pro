from __future__ import annotations

import copy
import json
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_preferences() -> dict[str, dict[str, Any]]:
    return {
        "appearance": {
            "theme_id": "aurora-dusk",
            "density": "comfortable",
            "font_scale": 1.0,
        },
        "chat": {
            "reasoning_mode_default": "summary",
            "system_prompt": "",
            "send_shortcut": "enter",
        },
        "tools": {
            "terminal_require_confirm": True,
            "show_tool_tips": True,
        },
        "notifications": {
            "show_system_messages": True,
            "verbose_errors": False,
        },
    }


def _default_platform_settings() -> dict[str, Any]:
    return {
        "allow_model_pull": True,
        "allow_model_delete": True,
        "allow_model_store_search": True,
        "allow_filesystem_tools": True,
        "allow_terminal_tools": True,
        "allow_shell_execute": True,
        "readonly_mode": False,
    }


@dataclass(frozen=True)
class PreferenceSnapshot:
    actor_id: str
    version: int
    preferences: dict[str, dict[str, Any]]
    updated_at: str


class PreferenceConflictError(ValueError):
    pass


class PreferenceValidationError(ValueError):
    pass


class AdminProfileStore:
    def __init__(self, *, state_path: Path, default_actor_id: str) -> None:
        self._path = state_path
        self._default_actor_id = default_actor_id.strip() or "anonymous"
        self._lock = threading.Lock()
        self._state = self._load()
        self._ensure_bootstrap_user()
        self._persist()

    @property
    def path(self) -> Path:
        return self._path

    def _empty_state(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "profile": {
                "actors": {},
            },
            "admin": {
                "platform": _default_platform_settings(),
                "users": [],
                "events": [],
            },
        }

    def _load(self) -> dict[str, Any]:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            return self._empty_state()
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self._empty_state()
        if not isinstance(payload, dict):
            return self._empty_state()
        return self._normalize_state(payload)

    def _normalize_state(self, payload: dict[str, Any]) -> dict[str, Any]:
        state = self._empty_state()
        if isinstance(payload.get("profile"), dict):
            profile_payload = payload["profile"]
            actors = profile_payload.get("actors", {})
            if isinstance(actors, dict):
                for actor_id, actor_data in actors.items():
                    if not isinstance(actor_id, str) or not isinstance(actor_data, dict):
                        continue
                    state["profile"]["actors"][actor_id] = {
                        "version": int(actor_data.get("version", 1)),
                        "updated_at": str(actor_data.get("updated_at") or _utc_now_iso()),
                        "preferences": self._normalize_preferences(
                            actor_data.get("preferences", _default_preferences())
                        ),
                    }

        if isinstance(payload.get("admin"), dict):
            admin_payload = payload["admin"]
            state["admin"]["platform"] = self._normalize_platform(
                admin_payload.get("platform", _default_platform_settings())
            )
            users = admin_payload.get("users", [])
            if isinstance(users, list):
                state["admin"]["users"] = [user for user in users if self._valid_user_record(user)]
            events = admin_payload.get("events", [])
            if isinstance(events, list):
                state["admin"]["events"] = [event for event in events if isinstance(event, dict)][-400:]

        return state

    def _persist(self) -> None:
        encoded = json.dumps(self._state, indent=2, sort_keys=True)
        tmp = self._path.with_suffix(f"{self._path.suffix}.tmp")
        tmp.write_text(encoded, encoding="utf-8")
        tmp.replace(self._path)

    def _ensure_bootstrap_user(self) -> None:
        users = self._state["admin"]["users"]
        for user in users:
            if bool(user.get("is_bootstrap_root")):
                return
        users.append(
            {
                "id": str(uuid.uuid4()),
                "username": "local-admin",
                "role": "sysadmin",
                "status": "active",
                "external_auth_only": False,
                "is_bootstrap_root": True,
                "created_at": _utc_now_iso(),
                "updated_at": _utc_now_iso(),
                "disabled_reason": "",
            }
        )
        self._record_event_unlocked(
            actor_id="system",
            event_type="admin.user.bootstrap",
            resource_type="user",
            resource_id="local-admin",
            detail="Bootstrap sysadmin created.",
        )

    def _actor_row(self, actor_id: str) -> dict[str, Any]:
        cleaned_actor = actor_id.strip() or self._default_actor_id
        actors = self._state["profile"]["actors"]
        row = actors.get(cleaned_actor)
        if row is None:
            row = {
                "version": 1,
                "updated_at": _utc_now_iso(),
                "preferences": _default_preferences(),
            }
            actors[cleaned_actor] = row
        return row

    def get_preferences(self, actor_id: str) -> PreferenceSnapshot:
        with self._lock:
            row = self._actor_row(actor_id)
            actor_key = actor_id.strip() or self._default_actor_id
            return PreferenceSnapshot(
                actor_id=actor_key,
                version=int(row["version"]),
                preferences=copy.deepcopy(row["preferences"]),
                updated_at=str(row["updated_at"]),
            )

    def patch_preferences(
        self,
        *,
        actor_id: str,
        base_version: int | None,
        patch: dict[str, Any],
    ) -> tuple[PreferenceSnapshot, list[str]]:
        if not isinstance(patch, dict) or not patch:
            raise PreferenceValidationError("patch must be a non-empty object")
        with self._lock:
            row = self._actor_row(actor_id)
            current_version = int(row["version"])
            if base_version is not None and int(base_version) != current_version:
                raise PreferenceConflictError("preferences changed; refresh and retry")

            next_preferences = copy.deepcopy(row["preferences"])
            changed_keys = self._apply_preference_patch(next_preferences, patch)
            if not changed_keys:
                return (
                    PreferenceSnapshot(
                        actor_id=actor_id.strip() or self._default_actor_id,
                        version=current_version,
                        preferences=copy.deepcopy(row["preferences"]),
                        updated_at=str(row["updated_at"]),
                    ),
                    [],
                )

            self._validate_preferences(next_preferences)
            row["preferences"] = next_preferences
            row["version"] = current_version + 1
            row["updated_at"] = _utc_now_iso()
            snapshot = PreferenceSnapshot(
                actor_id=actor_id.strip() or self._default_actor_id,
                version=int(row["version"]),
                preferences=copy.deepcopy(row["preferences"]),
                updated_at=str(row["updated_at"]),
            )
            self._record_event_unlocked(
                actor_id=actor_id.strip() or self._default_actor_id,
                event_type="profile.preferences.patch",
                resource_type="profile",
                resource_id=snapshot.actor_id,
                detail="Updated preference keys: " + ", ".join(changed_keys),
            )
            self._persist()
            return snapshot, changed_keys

    def reset_preferences(
        self,
        *,
        actor_id: str,
        scope: str | None,
    ) -> tuple[PreferenceSnapshot, list[str]]:
        normalized_scope = (scope or "all").strip().lower()
        defaults = _default_preferences()
        with self._lock:
            row = self._actor_row(actor_id)
            next_preferences = copy.deepcopy(row["preferences"])
            if normalized_scope in {"all", ""}:
                next_preferences = defaults
            else:
                if normalized_scope not in defaults:
                    raise PreferenceValidationError(f"Unknown reset scope '{scope}'")
                next_preferences[normalized_scope] = copy.deepcopy(defaults[normalized_scope])

            changed_keys = self._changed_keys(row["preferences"], next_preferences)
            if changed_keys:
                row["preferences"] = next_preferences
                row["version"] = int(row["version"]) + 1
                row["updated_at"] = _utc_now_iso()
                self._record_event_unlocked(
                    actor_id=actor_id.strip() or self._default_actor_id,
                    event_type="profile.preferences.reset",
                    resource_type="profile",
                    resource_id=actor_id.strip() or self._default_actor_id,
                    detail=f"Reset scope={normalized_scope}",
                )
                self._persist()

            snapshot = PreferenceSnapshot(
                actor_id=actor_id.strip() or self._default_actor_id,
                version=int(row["version"]),
                preferences=copy.deepcopy(row["preferences"]),
                updated_at=str(row["updated_at"]),
            )
            return snapshot, changed_keys

    def get_platform(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._state["admin"]["platform"])

    def update_platform(self, *, patch: dict[str, Any], actor_id: str) -> dict[str, Any]:
        if not isinstance(patch, dict) or not patch:
            raise PreferenceValidationError("patch must be a non-empty object")
        with self._lock:
            platform = self._state["admin"]["platform"]
            before = copy.deepcopy(platform)
            for key, value in patch.items():
                if key not in platform:
                    raise PreferenceValidationError(f"Unknown platform key '{key}'")
                if not isinstance(value, bool):
                    raise PreferenceValidationError(f"Platform key '{key}' must be boolean")
                platform[key] = value
            if platform != before:
                self._record_event_unlocked(
                    actor_id=actor_id.strip() or self._default_actor_id,
                    event_type="admin.platform.update",
                    resource_type="platform",
                    resource_id=None,
                    detail="Updated platform controls",
                )
                self._persist()
            return copy.deepcopy(platform)

    def list_users(self) -> list[dict[str, Any]]:
        with self._lock:
            users = copy.deepcopy(self._state["admin"]["users"])
        users.sort(key=lambda item: str(item.get("username", "")).lower())
        return users

    def create_user(self, *, actor_id: str, username: str, role: str) -> dict[str, Any]:
        cleaned_username = username.strip().lower()
        if not cleaned_username:
            raise PreferenceValidationError("username cannot be empty")
        if role not in {"sysadmin", "operator"}:
            raise PreferenceValidationError("role must be sysadmin or operator")
        with self._lock:
            users = self._state["admin"]["users"]
            if any(str(user.get("username", "")).lower() == cleaned_username for user in users):
                raise PreferenceValidationError("username already exists")
            now = _utc_now_iso()
            record = {
                "id": str(uuid.uuid4()),
                "username": cleaned_username,
                "role": role,
                "status": "active",
                "external_auth_only": False,
                "is_bootstrap_root": False,
                "created_at": now,
                "updated_at": now,
                "disabled_reason": "",
            }
            users.append(record)
            self._record_event_unlocked(
                actor_id=actor_id.strip() or self._default_actor_id,
                event_type="admin.user.create",
                resource_type="user",
                resource_id=record["id"],
                detail=f"Created {cleaned_username} ({role})",
            )
            self._persist()
            return copy.deepcopy(record)

    def update_user(self, *, actor_id: str, user_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(patch, dict) or not patch:
            raise PreferenceValidationError("patch must be a non-empty object")
        with self._lock:
            target = None
            for user in self._state["admin"]["users"]:
                if str(user.get("id")) == user_id:
                    target = user
                    break
            if target is None:
                raise PreferenceValidationError("user not found")
            if bool(target.get("is_bootstrap_root")) and ("role" in patch or "status" in patch):
                raise PreferenceValidationError("bootstrap user role/status cannot be modified")

            if "role" in patch:
                role = str(patch["role"])
                if role not in {"sysadmin", "operator"}:
                    raise PreferenceValidationError("role must be sysadmin or operator")
                target["role"] = role
            if "status" in patch:
                status = str(patch["status"])
                if status not in {"active", "disabled"}:
                    raise PreferenceValidationError("status must be active or disabled")
                target["status"] = status
            if "disabled_reason" in patch:
                target["disabled_reason"] = str(patch["disabled_reason"] or "")[:200]

            target["updated_at"] = _utc_now_iso()
            self._record_event_unlocked(
                actor_id=actor_id.strip() or self._default_actor_id,
                event_type="admin.user.update",
                resource_type="user",
                resource_id=user_id,
                detail="Updated user controls",
            )
            self._persist()
            return copy.deepcopy(target)

    def disable_user(self, *, actor_id: str, user_id: str) -> None:
        self.update_user(
            actor_id=actor_id,
            user_id=user_id,
            patch={"status": "disabled", "disabled_reason": "Disabled by admin"},
        )

    def list_events(self, *, limit: int = 100) -> list[dict[str, Any]]:
        capped_limit = max(1, min(300, int(limit)))
        with self._lock:
            events = copy.deepcopy(self._state["admin"]["events"][-capped_limit:])
        events.reverse()
        return events

    def is_enabled(self, key: str) -> bool:
        with self._lock:
            platform = self._state["admin"]["platform"]
            return bool(platform.get(key, True))

    def _normalize_preferences(self, raw: Any) -> dict[str, dict[str, Any]]:
        defaults = _default_preferences()
        if not isinstance(raw, dict):
            return defaults
        normalized = copy.deepcopy(defaults)
        for category, values in raw.items():
            if category not in normalized or not isinstance(values, dict):
                continue
            for key, value in values.items():
                if key in normalized[category]:
                    normalized[category][key] = value
        self._validate_preferences(normalized)
        return normalized

    def _normalize_platform(self, raw: Any) -> dict[str, Any]:
        defaults = _default_platform_settings()
        if not isinstance(raw, dict):
            return defaults
        normalized = copy.deepcopy(defaults)
        for key, value in raw.items():
            if key not in normalized:
                continue
            normalized[key] = bool(value)
        return normalized

    def _valid_user_record(self, raw: Any) -> bool:
        if not isinstance(raw, dict):
            return False
        try:
            role = str(raw.get("role"))
            status = str(raw.get("status"))
            username = str(raw.get("username", "")).strip()
            user_id = str(raw.get("id", "")).strip()
            if role not in {"sysadmin", "operator"}:
                return False
            if status not in {"active", "disabled"}:
                return False
            if not username or not user_id:
                return False
            return True
        except Exception:
            return False

    def _validate_preferences(self, preferences: dict[str, dict[str, Any]]) -> None:
        appearance = preferences["appearance"]
        if appearance.get("theme_id") not in {"aurora-dusk", "graphite-ocean"}:
            raise PreferenceValidationError("appearance.theme_id is invalid")
        if appearance.get("density") not in {"comfortable", "compact"}:
            raise PreferenceValidationError("appearance.density is invalid")
        font_scale = appearance.get("font_scale")
        if not isinstance(font_scale, (int, float)) or not (0.8 <= float(font_scale) <= 1.5):
            raise PreferenceValidationError("appearance.font_scale must be between 0.8 and 1.5")

        chat = preferences["chat"]
        if chat.get("reasoning_mode_default") not in {"hidden", "summary", "full"}:
            raise PreferenceValidationError("chat.reasoning_mode_default is invalid")
        if chat.get("send_shortcut") not in {"enter", "ctrl_enter"}:
            raise PreferenceValidationError("chat.send_shortcut is invalid")
        system_prompt = chat.get("system_prompt")
        if not isinstance(system_prompt, str) or len(system_prompt) > 4000:
            raise PreferenceValidationError("chat.system_prompt must be a string <= 4000 chars")

        tools = preferences["tools"]
        if not isinstance(tools.get("terminal_require_confirm"), bool):
            raise PreferenceValidationError("tools.terminal_require_confirm must be boolean")
        if not isinstance(tools.get("show_tool_tips"), bool):
            raise PreferenceValidationError("tools.show_tool_tips must be boolean")

        notifications = preferences["notifications"]
        if not isinstance(notifications.get("show_system_messages"), bool):
            raise PreferenceValidationError("notifications.show_system_messages must be boolean")
        if not isinstance(notifications.get("verbose_errors"), bool):
            raise PreferenceValidationError("notifications.verbose_errors must be boolean")

    def _apply_preference_patch(
        self,
        preferences: dict[str, dict[str, Any]],
        patch: dict[str, Any],
    ) -> list[str]:
        changed: list[str] = []
        for category, payload in patch.items():
            if category not in preferences:
                raise PreferenceValidationError(f"Unknown preference category '{category}'")
            if not isinstance(payload, dict):
                raise PreferenceValidationError(f"Preference category '{category}' must be an object")
            for key, value in payload.items():
                if key not in preferences[category]:
                    raise PreferenceValidationError(f"Unknown preference key '{category}.{key}'")
                if preferences[category][key] != value:
                    preferences[category][key] = value
                    changed.append(f"{category}.{key}")
        return changed

    def _changed_keys(
        self,
        current: dict[str, dict[str, Any]],
        next_preferences: dict[str, dict[str, Any]],
    ) -> list[str]:
        changed: list[str] = []
        for category, values in current.items():
            for key, value in values.items():
                if next_preferences.get(category, {}).get(key) != value:
                    changed.append(f"{category}.{key}")
        return changed

    def _record_event_unlocked(
        self,
        *,
        actor_id: str,
        event_type: str,
        resource_type: str,
        resource_id: str | None,
        detail: str,
    ) -> None:
        events = self._state["admin"]["events"]
        events.append(
            {
                "id": str(uuid.uuid4()),
                "at": _utc_now_iso(),
                "actor_id": actor_id,
                "event_type": event_type,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "detail": detail,
            }
        )
        if len(events) > 400:
            del events[: len(events) - 400]
