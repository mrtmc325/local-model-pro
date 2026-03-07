from __future__ import annotations

import asyncio
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from local_model_pro.config import Settings
from local_model_pro.conversation_store import ConversationStore, StoredTurn
from local_model_pro.ollama_client import OllamaClient, OllamaStreamError
from local_model_pro.qdrant_memory import MemoryResult, QdrantError, QdrantMemoryIndex

_SQL_PATTERN = re.compile(r"\b(select|insert|update|delete|from|where|join|drop|table|into|values)\b", re.IGNORECASE)
_WORD_PATTERN = re.compile(r"[A-Za-z0-9']+")
_CAPITALIZED_PATTERN = re.compile(r"\b[A-Z][a-zA-Z]{2,}\b")
_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "i",
    "in",
    "is",
    "it",
    "me",
    "my",
    "of",
    "on",
    "or",
    "our",
    "so",
    "that",
    "the",
    "their",
    "them",
    "they",
    "this",
    "to",
    "us",
    "was",
    "we",
    "what",
    "when",
    "where",
    "who",
    "why",
    "with",
    "you",
    "your",
}


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
        return re.sub(r"\s+", " ", value).strip()

    @staticmethod
    def _sanitize_lookup_query(
        candidate: str,
        *,
        prompt: str,
        meaning: str,
        purpose: str,
    ) -> str:
        normalized = re.sub(r"\s+", " ", candidate).strip()
        if not normalized:
            normalized = prompt.strip()

        if _SQL_PATTERN.search(normalized) or ";" in normalized:
            fallback = f"{meaning} {purpose}".strip()
            normalized = fallback or prompt.strip()

        if len(normalized) < 6:
            normalized = prompt.strip()

        if len(normalized) > 280:
            normalized = f"{normalized[:277]}..."
        return normalized

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
                "Use natural language only. Do not output SQL or code.\n"
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

        db_query = self._sanitize_lookup_query(
            self._normalize_string(pass2.get("db_query")) or prompt,
            prompt=prompt,
            meaning=meaning,
            purpose=purpose,
        )
        web_query = self._sanitize_lookup_query(
            self._normalize_string(pass2.get("web_query")) or prompt,
            prompt=prompt,
            meaning=meaning,
            purpose=purpose,
        )
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
                "Use natural language only. Do not output SQL or code.\n"
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

        final_reason = self._normalize_string(pass3.get("reason")) or reason
        final_meaning = self._normalize_string(pass3.get("meaning")) or meaning
        final_purpose = self._normalize_string(pass3.get("purpose")) or purpose

        return QueryPlan(
            reason=final_reason,
            meaning=final_meaning,
            purpose=final_purpose,
            db_query=self._sanitize_lookup_query(
                self._normalize_string(pass3.get("db_query")) or db_query,
                prompt=prompt,
                meaning=final_meaning,
                purpose=final_purpose,
            ),
            web_query=self._sanitize_lookup_query(
                self._normalize_string(pass3.get("web_query")) or web_query,
                prompt=prompt,
                meaning=final_meaning,
                purpose=final_purpose,
            ),
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

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return [token.lower() for token in _WORD_PATTERN.findall(text)]

    def _extract_terms(self, text: str, *, max_terms: int = 16) -> list[str]:
        terms: list[str] = []
        seen: set[str] = set()
        for token in self._tokenize(text):
            if len(token) < 2:
                continue
            if token in _STOP_WORDS:
                continue
            if token in seen:
                continue
            seen.add(token)
            terms.append(token)
            if len(terms) >= max_terms:
                break
        return terms

    @staticmethod
    def _short_phrases(terms: list[str], *, max_phrases: int = 8) -> list[str]:
        phrases: list[str] = []
        for size in (2, 3):
            for idx in range(0, len(terms) - size + 1):
                phrases.append(" ".join(terms[idx : idx + size]))
                if len(phrases) >= max_phrases:
                    return phrases
        return phrases

    def _expand_memory_queries(
        self,
        *,
        query: str,
        query_plan: QueryPlan | None,
    ) -> list[str]:
        candidates: list[str] = [query.strip()]
        if query_plan:
            candidates.extend(
                [
                    query_plan.db_query.strip(),
                    query_plan.meaning.strip(),
                    query_plan.purpose.strip(),
                    query_plan.reason.strip(),
                    f"{query_plan.meaning.strip()} {query_plan.purpose.strip()}".strip(),
                ]
            )

        terms = self._extract_terms(" ".join(candidates), max_terms=20)
        if terms:
            candidates.append(" ".join(terms[:8]))
            candidates.extend(self._short_phrases(terms, max_phrases=10))

        named_entities = []
        for candidate in candidates:
            for match in _CAPITALIZED_PATTERN.findall(candidate):
                if match.lower() in _STOP_WORDS:
                    continue
                named_entities.append(match)
        if named_entities:
            candidates.append(" ".join(named_entities[:5]))

        normalized: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            text = re.sub(r"\s+", " ", candidate).strip()
            if len(text) < 3:
                continue
            lowered = text.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            normalized.append(text)
            if len(normalized) >= 14:
                break
        return normalized

    @staticmethod
    def _term_overlap_score(text: str, terms: list[str]) -> float:
        if not terms:
            return 0.0
        lower_text = text.lower()
        hits = sum(1 for term in terms if term in lower_text)
        return hits / max(1, len(terms))

    @staticmethod
    def _memory_key(item: MemoryResult) -> str:
        return f"{item.source_session}::{item.speaker}::{item.insight.lower()}"

    @staticmethod
    def _heuristic_turn_abstraction(turn: StoredTurn, terms: list[str]) -> str:
        content = re.sub(r"\s+", " ", turn.content).strip()
        lower = content.lower()
        excluded_names = {
            "based",
            "what",
            "when",
            "where",
            "who",
            "why",
            "how",
            "if",
            "the",
            "this",
            "that",
            "from",
            "with",
        }
        names = [
            name
            for name in _CAPITALIZED_PATTERN.findall(content)
            if name.lower() not in excluded_names
        ]

        if ("love" in lower or "loves" in lower or "loved" in lower) and names:
            if "success" in lower or "key" in lower:
                return f"Speaker described {names[0]} as a central source of motivation and success."
            return f"Speaker expressed strong positive feelings toward {names[0]}."

        if ("key" in lower or "core" in lower) and ("success" in lower or "progress" in lower):
            return "Speaker emphasized a key personal factor driving success and execution."

        overlap_terms = [term for term in terms if term in lower][:6]
        if overlap_terms:
            return "Prior conversation referenced: " + ", ".join(overlap_terms) + "."

        extracted = [token for token in _WORD_PATTERN.findall(content.lower()) if len(token) >= 4]
        if not extracted:
            return "Prior conversation contained a relevant decision context from earlier chat."
        return "Prior conversation context included: " + ", ".join(extracted[:6]) + "."

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
                            "- Do not quote the original text verbatim.\n"
                            "- Preserve critical named entities when they are required for retrieval quality.\n"
                            "- Exclude secrets and sensitive tokens.\n"
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
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
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
            fallback_insight = self._heuristic_turn_abstraction(
                StoredTurn(
                    session_id=session_id,
                    speaker=speaker,
                    content=content,
                    created_at=datetime.now(timezone.utc).isoformat(),
                    request_id=None,
                    model=model,
                ),
                terms=self._extract_terms(content, max_terms=8),
            )
            insights = [fallback_insight]

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
                        "insight_id": stored.insight_id,
                        "insight": stored.insight,
                        "source_session": stored.session_id,
                        "speaker": stored.speaker,
                        "created_at": stored.created_at,
                    },
                )
            except (OllamaStreamError, QdrantError, ValueError):
                # Still persist insights even when embedding/indexing fails.
                try:
                    await asyncio.to_thread(
                        self._store.add_insight,
                        session_id=session_id,
                        speaker=speaker,
                        insight=insight,
                        insight_id=str(uuid.uuid4()),
                    )
                except ValueError:
                    pass
                continue

    async def search_memory(
        self,
        *,
        query: str,
        query_plan: QueryPlan | None = None,
    ) -> list[MemoryResult]:
        normalized = query.strip()
        if not normalized:
            return []

        expanded_queries = self._expand_memory_queries(query=normalized, query_plan=query_plan)
        terms = self._extract_terms(" ".join(expanded_queries), max_terms=24)
        results_map: dict[str, MemoryResult] = {}

        # Semantic retrieval across multiple phrase variants.
        for variant in expanded_queries:
            try:
                vector = await self._ollama.embed(
                    model=self._settings.embedding_model,
                    text=variant,
                )
                semantic_results = await self._memory_index.search(
                    vector=vector,
                    limit=self._settings.knowledge_memory_top_k,
                    score_threshold=self._settings.knowledge_memory_score_threshold,
                )
            except (OllamaStreamError, QdrantError):
                semantic_results = []

            for item in semantic_results:
                key = self._memory_key(item)
                existing = results_map.get(key)
                if existing is None:
                    results_map[key] = item
                    continue
                if item.score > existing.score:
                    results_map[key] = item

        # Lexical fallback from persisted insights.
        lexical_insights = await asyncio.to_thread(
            self._store.search_insights_by_terms,
            terms=terms,
            limit=max(4, self._settings.knowledge_memory_top_k * 3),
        )
        for insight in lexical_insights:
            overlap = self._term_overlap_score(insight.insight, terms)
            score = 0.38 + (overlap * 0.45)
            item = MemoryResult(
                insight=insight.insight,
                score=min(score, 0.89),
                source_session=insight.session_id,
                speaker=insight.speaker,
                created_at=insight.created_at,
            )
            key = self._memory_key(item)
            existing = results_map.get(key)
            if existing is None or item.score > existing.score:
                results_map[key] = item

        # Last fallback: abstract raw matched turns into non-verbatim memory cards.
        if len(results_map) < self._settings.knowledge_memory_top_k:
            turn_hits = await asyncio.to_thread(
                self._store.search_turns_by_terms,
                terms=terms,
                limit=max(4, self._settings.knowledge_memory_top_k * 2),
            )
            for turn in turn_hits:
                insight_text = self._heuristic_turn_abstraction(turn, terms)
                overlap = self._term_overlap_score(turn.content, terms)
                speaker_bonus = 0.12 if turn.speaker == "me" else 0.02
                item = MemoryResult(
                    insight=insight_text,
                    score=min(0.28 + speaker_bonus + (overlap * 0.35), 0.82),
                    source_session=turn.session_id,
                    speaker=turn.speaker,
                    created_at=turn.created_at,
                )
                key = self._memory_key(item)
                existing = results_map.get(key)
                if existing is None or item.score > existing.score:
                    results_map[key] = item

        ranked = sorted(
            results_map.values(),
            key=lambda item: (item.score, item.created_at),
            reverse=True,
        )
        return ranked[: self._settings.knowledge_memory_top_k]
