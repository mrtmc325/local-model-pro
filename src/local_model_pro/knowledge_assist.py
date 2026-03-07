from __future__ import annotations

import asyncio
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from local_model_pro.config import Settings
from local_model_pro.conversation_store import ConversationStore
from local_model_pro.ollama_client import OllamaClient, OllamaStreamError
from local_model_pro.qdrant_memory import MemoryResult, QdrantError, QdrantMemoryIndex


@dataclass(frozen=True)
class QueryPlan:
    reason: str
    meaning: str
    purpose: str
    db_query: str
    web_query: str
    fallback: bool = False


class RecursivePlanner:
    def __init__(
        self,
        *,
        settings: Settings,
        ollama: OllamaClient,
    ) -> None:
        self._settings = settings
        self._ollama = ollama

    @staticmethod
    def _extract_json_object(raw_text: str) -> dict[str, Any] | None:
        cleaned = raw_text.strip()
        if not cleaned:
            return None
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            return None
        candidate = match.group(0)
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _normalize_string(value: Any) -> str:
        if not isinstance(value, str):
            return ""
        return value.strip()

    def _fallback(self, prompt: str) -> QueryPlan:
        text = prompt.strip()
        return QueryPlan(
            reason="User needs accurate and actionable help for a current request.",
            meaning=text,
            purpose="Provide a useful response backed by reliable context.",
            db_query=text,
            web_query=text,
            fallback=True,
        )

    async def _run_pass(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
    ) -> dict[str, Any] | None:
        try:
            raw = await self._ollama.chat(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
                num_ctx=max(1024, min(self._settings.default_num_ctx, 4096)),
            )
        except OllamaStreamError:
            return None
        return self._extract_json_object(raw)

    async def build_plan(
        self,
        *,
        prompt: str,
        history: list[dict[str, str]],
        model: str,
    ) -> QueryPlan:
        base = self._fallback(prompt)
        passes = max(0, self._settings.knowledge_recursion_passes)
        if passes == 0:
            return base

        planner_model = self._settings.knowledge_planner_model or model
        recent_lines = []
        for item in history[-6:]:
            role = item.get("role", "").strip().lower()
            content = item.get("content", "").strip()
            if role in {"user", "assistant"} and content:
                recent_lines.append(f"{role}: {content}")
        history_text = "\n".join(recent_lines) if recent_lines else "(none)"

        pass1 = await self._run_pass(
            model=planner_model,
            system_prompt=(
                "You break down user intent for retrieval planning.\n"
                "Return JSON only with keys: reason, meaning, purpose.\n"
                "Use plain concise text."
            ),
            user_prompt=(
                f"Prompt: {prompt}\n"
                f"Recent history:\n{history_text}\n"
            ),
        )
        if not pass1:
            return base

        reason = self._normalize_string(pass1.get("reason")) or base.reason
        meaning = self._normalize_string(pass1.get("meaning")) or base.meaning
        purpose = self._normalize_string(pass1.get("purpose")) or base.purpose
        if passes == 1:
            return QueryPlan(
                reason=reason,
                meaning=meaning,
                purpose=purpose,
                db_query=prompt,
                web_query=prompt,
                fallback=False,
            )

        pass2 = await self._run_pass(
            model=planner_model,
            system_prompt=(
                "You convert intent into retrieval queries.\n"
                "Return JSON only with keys: db_query, web_query.\n"
                "db_query should be semantic and context-rich.\n"
                "web_query should be internet-search friendly and concise."
            ),
            user_prompt=(
                f"Original prompt: {prompt}\n"
                f"Reason: {reason}\n"
                f"Meaning: {meaning}\n"
                f"Purpose: {purpose}\n"
            ),
        )
        if not pass2:
            return QueryPlan(
                reason=reason,
                meaning=meaning,
                purpose=purpose,
                db_query=prompt,
                web_query=prompt,
                fallback=False,
            )

        db_query = self._normalize_string(pass2.get("db_query")) or prompt
        web_query = self._normalize_string(pass2.get("web_query")) or prompt
        if passes == 2:
            return QueryPlan(
                reason=reason,
                meaning=meaning,
                purpose=purpose,
                db_query=db_query,
                web_query=web_query,
                fallback=False,
            )

        now_label = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
        pass3 = await self._run_pass(
            model=planner_model,
            system_prompt=(
                "You refine retrieval planning.\n"
                "Return JSON only with keys: reason, meaning, purpose, db_query, web_query.\n"
                "Adjust phrasing for the current date/time context."
            ),
            user_prompt=(
                f"UTC now: {now_label}\n"
                f"Original prompt: {prompt}\n"
                f"Current reason: {reason}\n"
                f"Current meaning: {meaning}\n"
                f"Current purpose: {purpose}\n"
                f"Current db_query: {db_query}\n"
                f"Current web_query: {web_query}\n"
            ),
        )
        if not pass3:
            return QueryPlan(
                reason=reason,
                meaning=meaning,
                purpose=purpose,
                db_query=db_query,
                web_query=web_query,
                fallback=False,
            )

        return QueryPlan(
            reason=self._normalize_string(pass3.get("reason")) or reason,
            meaning=self._normalize_string(pass3.get("meaning")) or meaning,
            purpose=self._normalize_string(pass3.get("purpose")) or purpose,
            db_query=self._normalize_string(pass3.get("db_query")) or db_query,
            web_query=self._normalize_string(pass3.get("web_query")) or web_query,
            fallback=False,
        )


class KnowledgeAssistService:
    def __init__(
        self,
        *,
        settings: Settings,
        ollama: OllamaClient,
        store: ConversationStore,
        memory_index: QdrantMemoryIndex,
    ) -> None:
        self._settings = settings
        self._ollama = ollama
        self._store = store
        self._memory_index = memory_index
        self._planner = RecursivePlanner(settings=settings, ollama=ollama)

    async def save_session(
        self,
        *,
        session_id: str,
        model: str,
        system_prompt: str | None,
    ) -> None:
        await asyncio.to_thread(
            self._store.upsert_session,
            session_id=session_id,
            model=model,
            system_prompt=system_prompt,
        )

    async def save_turn(
        self,
        *,
        session_id: str,
        speaker: str,
        content: str,
        request_id: str | None,
        model: str | None,
    ) -> int:
        return await asyncio.to_thread(
            self._store.append_turn,
            session_id=session_id,
            speaker=speaker,
            content=content,
            request_id=request_id,
            model=model,
        )

    async def build_query_plan(
        self,
        *,
        prompt: str,
        history: list[dict[str, str]],
        model: str,
    ) -> QueryPlan:
        return await self._planner.build_plan(
            prompt=prompt,
            history=history,
            model=model,
        )

    async def _derive_insights(
        self,
        *,
        speaker: str,
        content: str,
        model: str,
    ) -> list[str]:
        if not content.strip():
            return []

        insight_model = self._settings.knowledge_insight_model or model
        try:
            raw = await self._ollama.chat(
                model=insight_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Convert one chat turn into reusable abstract insights.\n"
                            "Return JSON only: {\"insights\": [\"...\", \"...\"]}\n"
                            "Rules:\n"
                            "- Do not quote the original text.\n"
                            "- Do not include names, secrets, or exact identifiers.\n"
                            "- Keep each insight generic and useful for problem solving."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Speaker: {speaker}\nTurn:\n{content}",
                    },
                ],
                temperature=0.0,
                num_ctx=max(1024, min(self._settings.default_num_ctx, 4096)),
            )
        except OllamaStreamError:
            return []

        parsed = RecursivePlanner._extract_json_object(raw)
        if not parsed:
            return []
        raw_insights = parsed.get("insights", [])
        if not isinstance(raw_insights, list):
            return []

        seen: set[str] = set()
        clean: list[str] = []
        for item in raw_insights:
            text = str(item).strip()
            if not text:
                continue
            if len(text) > 360:
                text = f"{text[:357]}..."
            if text in seen:
                continue
            seen.add(text)
            clean.append(text)
            if len(clean) >= 4:
                break
        return clean

    async def index_turn_insights(
        self,
        *,
        session_id: str,
        speaker: str,
        content: str,
        model: str,
    ) -> None:
        insights = await self._derive_insights(
            speaker=speaker,
            content=content,
            model=model,
        )
        if not insights:
            return

        for insight in insights:
            try:
                vector = await self._ollama.embed(
                    model=self._settings.embedding_model,
                    text=insight,
                )
                insight_id = str(uuid.uuid4())
                stored = await asyncio.to_thread(
                    self._store.add_insight,
                    session_id=session_id,
                    speaker=speaker,
                    insight=insight,
                    insight_id=insight_id,
                )
                await self._memory_index.upsert(
                    point_id=stored.insight_id,
                    vector=vector,
                    payload={
                        "insight": stored.insight,
                        "source_session": stored.session_id,
                        "speaker": stored.speaker,
                        "created_at": stored.created_at,
                    },
                )
            except (OllamaStreamError, QdrantError, ValueError):
                continue

    async def search_memory(
        self,
        *,
        query: str,
    ) -> list[MemoryResult]:
        normalized = query.strip()
        if not normalized:
            return []
        try:
            vector = await self._ollama.embed(
                model=self._settings.embedding_model,
                text=normalized,
            )
            return await self._memory_index.search(
                vector=vector,
                limit=self._settings.knowledge_memory_top_k,
                score_threshold=self._settings.knowledge_memory_score_threshold,
            )
        except (OllamaStreamError, QdrantError):
            return []

