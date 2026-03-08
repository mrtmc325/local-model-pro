from __future__ import annotations

import asyncio
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from local_model_pro.config import Settings
from local_model_pro.conversation_store import ConversationStore
from local_model_pro.ollama_client import OllamaClient, OllamaStreamError
from local_model_pro.qdrant_memory import MemoryResult, QdrantError, QdrantMemoryIndex

_SQL_PATTERN = re.compile(r"\b(select|insert|update|delete|from|where|join|drop|table|into|values)\b", re.IGNORECASE)
_WORD_PATTERN = re.compile(r"[A-Za-z0-9']+")
_CAPITALIZED_PATTERN = re.compile(r"\b[A-Z][a-zA-Z]{2,}\b")
_EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_PATTERN = re.compile(r"\b(?:\+?\d{1,2}[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]?\d{3}[\s.-]?\d{4}\b")
_NEGATION_PATTERN = re.compile(r"\b(no|not|never|none|without|isn't|aren't|wasn't|weren't)\b", re.IGNORECASE)
_NUMERIC_PATTERN = re.compile(r"\b\d[\d,./:-]*\b")
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
_FORUM_HINTS = {"reddit.com", "quora.com", "stackexchange.com", "forum", "community"}
_SOCIAL_HINTS = {"facebook.com", "x.com", "twitter.com", "instagram.com", "linkedin.com", "tiktok.com"}
_OFFICIAL_HINTS = {".gov", ".edu", "fema.gov", "ready.gov", "weather.gov", "who.int", "cdc.gov"}
_MEDIA_HINTS = {
    "nytimes.com",
    "reuters.com",
    "apnews.com",
    "bbc.com",
    "cnn.com",
    "theguardian.com",
}


@dataclass(frozen=True)
class QueryPlan:
    reason: str
    meaning: str
    purpose: str
    db_query: str
    web_query: str
    fallback: bool = False


@dataclass(frozen=True)
class EvidenceCard:
    evidence_id: str
    source_type: str
    actor_scope: str
    label: str
    content: str
    url: str | None
    source_session: str | None
    confidence: float
    pii_flag: bool
    used_verbatim: bool


@dataclass(frozen=True)
class GroundedClaim:
    claim_id: str
    text: str
    evidence_ids: list[str]
    confidence: float
    status: str


@dataclass(frozen=True)
class GroundedResponse:
    status: str
    answer_text: str
    claims: list[GroundedClaim]
    overall_confidence: float
    clarify_question: str
    note: str


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

    @staticmethod
    def _source_scope(*, item_actor_id: str, session_id: str, actor_id: str, current_session_id: str) -> str:
        if session_id == current_session_id:
            return "same_session"
        if item_actor_id == actor_id:
            return "same_user"
        return "shared"

    @staticmethod
    def _scope_priority(scope: str) -> int:
        if scope == "same_session":
            return 0
        if scope == "same_user":
            return 1
        return 2

    @staticmethod
    def _detect_pii(content: str) -> bool:
        lowered = content.lower()
        romantic_keywords = {
            "girlfriend",
            "boyfriend",
            "wife",
            "husband",
            "fiance",
            "fiancee",
            "my girl",
            "my guy",
            "romantic",
            "dating",
        }
        if _EMAIL_PATTERN.search(content) or _PHONE_PATTERN.search(content):
            return True
        return any(keyword in lowered for keyword in romantic_keywords)

    @staticmethod
    def _allow_cross_user_for_content(content: str) -> bool:
        return not KnowledgeAssistService._detect_pii(content)

    @staticmethod
    def classify_source_type_for_url(url: str) -> str:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        if host.startswith("www."):
            host = host[4:]

        if any(token in host for token in _FORUM_HINTS):
            return "web_user_story_forum"
        if any(token in host for token in _SOCIAL_HINTS):
            return "web_user_story_forum"
        if any(host.endswith(token) or token in host for token in _OFFICIAL_HINTS):
            return "web_official"
        if any(token in host for token in _MEDIA_HINTS):
            return "web_media"
        return "web_media"

    @staticmethod
    def source_confidence(source_type: str, base_score: float = 0.65) -> float:
        if source_type == "memory_same_session":
            return min(0.95, max(0.65, base_score + 0.18))
        if source_type == "memory_same_user":
            return min(0.92, max(0.60, base_score + 0.12))
        if source_type == "memory_shared":
            return min(0.88, max(0.50, base_score + 0.08))
        if source_type == "web_official":
            return min(0.90, max(0.58, base_score + 0.12))
        if source_type == "web_media":
            return min(0.82, max(0.48, base_score + 0.04))
        if source_type == "web_user_story_forum":
            return min(0.70, max(0.35, base_score - 0.10))
        return min(0.75, max(0.40, base_score))

    @staticmethod
    def _term_overlap_score(text: str, terms: list[str]) -> float:
        if not terms:
            return 0.0
        lower_text = text.lower()
        hits = sum(1 for term in terms if term in lower_text)
        return hits / max(1, len(terms))

    @staticmethod
    def _extract_terms(text: str, *, max_terms: int = 16) -> list[str]:
        terms: list[str] = []
        seen: set[str] = set()
        for token in [item.lower() for item in _WORD_PATTERN.findall(text)]:
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

        terms = self._extract_terms(" ".join(candidates), max_terms=24)
        if terms:
            candidates.append(" ".join(terms[:8]))
            candidates.extend(self._short_phrases(terms, max_phrases=12))

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
            if len(normalized) >= 16:
                break
        return normalized

    async def save_session(
        self,
        *,
        session_id: str,
        model: str,
        system_prompt: str | None,
        actor_id: str,
    ) -> None:
        await asyncio.to_thread(
            self._store.upsert_session,
            session_id=session_id,
            model=model,
            system_prompt=system_prompt,
            actor_id=actor_id,
        )

    async def save_turn(
        self,
        *,
        session_id: str,
        speaker: str,
        content: str,
        request_id: str | None,
        model: str | None,
        actor_id: str,
    ) -> int:
        pii_flag = self._detect_pii(content)
        allow_cross_user = self._allow_cross_user_for_content(content)
        return await asyncio.to_thread(
            self._store.append_turn,
            session_id=session_id,
            speaker=speaker,
            content=content,
            request_id=request_id,
            model=model,
            actor_id=actor_id,
            pii_flag=pii_flag,
            allow_cross_user=allow_cross_user,
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
                            "Return JSON only: {\"insights\": [\"...\", \"...\"]}.\n"
                            "Rules:\n"
                            "- Keep named entities when they matter for retrieval quality.\n"
                            "- No secrets, tokens, credentials, or contact details.\n"
                            "- Avoid exact long verbatim copy."
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

    @staticmethod
    def _fallback_insight_from_turn(content: str) -> str:
        flattened = re.sub(r"\s+", " ", content).strip()
        if not flattened:
            return "Prior discussion contained relevant context."
        if len(flattened) > 160:
            flattened = flattened[:157] + "..."
        return f"Prior conversation context: {flattened}"

    async def index_turn_insights(
        self,
        *,
        session_id: str,
        speaker: str,
        content: str,
        model: str,
        actor_id: str,
    ) -> None:
        pii_flag = self._detect_pii(content)
        allow_cross_user = self._allow_cross_user_for_content(content)
        quote_text = re.sub(r"\s+", " ", content).strip()
        if len(quote_text) > 240:
            quote_text = quote_text[:237] + "..."

        insights = await self._derive_insights(
            speaker=speaker,
            content=content,
            model=model,
        )
        if not insights:
            insights = [self._fallback_insight_from_turn(content)]

        for insight in insights:
            insight_id = str(uuid.uuid4())
            try:
                await asyncio.to_thread(
                    self._store.add_insight,
                    session_id=session_id,
                    speaker=speaker,
                    insight=insight,
                    insight_id=insight_id,
                    actor_id=actor_id,
                    pii_flag=pii_flag,
                    allow_cross_user=allow_cross_user,
                    source_type="insight",
                    quote_text=quote_text,
                )
                vector = await self._ollama.embed(
                    model=self._settings.embedding_model,
                    text=insight,
                )
                await self._memory_index.upsert(
                    point_id=insight_id,
                    vector=vector,
                    payload={
                        "insight_id": insight_id,
                        "insight": insight,
                        "source_session": session_id,
                        "speaker": speaker,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "actor_id": actor_id,
                        "pii_flag": pii_flag,
                        "allow_cross_user": allow_cross_user,
                        "source_type": "insight",
                        "quote_text": quote_text,
                    },
                )
            except (OllamaStreamError, QdrantError, ValueError):
                continue

    def _memory_key(self, item: MemoryResult) -> str:
        return f"{item.evidence_id}::{item.source_session}::{item.speaker}"

    def _scope_filter(self, *, item_actor_id: str, pii_flag: bool, allow_cross_user: bool, actor_id: str) -> bool:
        if item_actor_id == actor_id:
            return True
        if pii_flag:
            return False
        return bool(allow_cross_user)

    async def search_memory(
        self,
        *,
        query: str,
        actor_id: str,
        current_session_id: str,
        query_plan: QueryPlan | None = None,
    ) -> list[MemoryResult]:
        normalized = query.strip()
        if not normalized:
            return []

        expanded_queries = self._expand_memory_queries(query=normalized, query_plan=query_plan)
        terms = self._extract_terms(" ".join(expanded_queries), max_terms=28)
        results_map: dict[str, MemoryResult] = {}

        for variant in expanded_queries:
            try:
                vector = await self._ollama.embed(
                    model=self._settings.embedding_model,
                    text=variant,
                )
                semantic_results = await self._memory_index.search(
                    vector=vector,
                    limit=max(self._settings.knowledge_memory_top_k * 3, 8),
                    score_threshold=max(0.0, self._settings.knowledge_memory_score_threshold - 0.1),
                )
            except (OllamaStreamError, QdrantError):
                semantic_results = []

            for item in semantic_results:
                if not self._scope_filter(
                    item_actor_id=item.actor_id,
                    pii_flag=item.pii_flag,
                    allow_cross_user=item.allow_cross_user,
                    actor_id=actor_id,
                ):
                    continue
                rerank = self._term_overlap_score(f"{item.insight} {item.quote_text or ''}", terms)
                combined_score = max(item.score, min(1.0, (item.score * 0.65) + (rerank * 0.35)))
                candidate = MemoryResult(
                    evidence_id=item.evidence_id,
                    insight=item.insight,
                    score=combined_score,
                    source_session=item.source_session,
                    speaker=item.speaker,
                    created_at=item.created_at,
                    actor_id=item.actor_id,
                    pii_flag=item.pii_flag,
                    allow_cross_user=item.allow_cross_user,
                    source_type=item.source_type,
                    quote_text=item.quote_text,
                )
                key = self._memory_key(candidate)
                existing = results_map.get(key)
                if existing is None or candidate.score > existing.score:
                    results_map[key] = candidate

        lexical_insights = await asyncio.to_thread(
            self._store.search_insights_by_terms,
            terms=terms,
            actor_id=actor_id,
            current_session_id=current_session_id,
            include_shared=True,
            limit=max(self._settings.knowledge_memory_top_k * 4, 12),
        )
        for insight in lexical_insights:
            overlap = self._term_overlap_score(f"{insight.insight} {insight.quote_text or ''}", terms)
            score = min(0.25 + overlap * 0.55, 0.90)
            candidate = MemoryResult(
                evidence_id=insight.insight_id,
                insight=insight.insight,
                score=score,
                source_session=insight.session_id,
                speaker=insight.speaker,
                created_at=insight.created_at,
                actor_id=insight.actor_id,
                pii_flag=insight.pii_flag,
                allow_cross_user=insight.allow_cross_user,
                source_type=insight.source_type,
                quote_text=insight.quote_text,
            )
            key = self._memory_key(candidate)
            existing = results_map.get(key)
            if existing is None or candidate.score > existing.score:
                results_map[key] = candidate

        if len(results_map) < self._settings.knowledge_memory_top_k:
            turn_hits = await asyncio.to_thread(
                self._store.search_turns_by_terms,
                terms=terms,
                actor_id=actor_id,
                current_session_id=current_session_id,
                include_shared=True,
                limit=max(self._settings.knowledge_memory_top_k * 3, 10),
            )
            for turn in turn_hits:
                overlap = self._term_overlap_score(turn.content, terms)
                excerpt = re.sub(r"\s+", " ", turn.content).strip()
                if len(excerpt) > 220:
                    excerpt = excerpt[:217] + "..."
                candidate = MemoryResult(
                    evidence_id=f"turn:{turn.turn_id}",
                    insight=self._fallback_insight_from_turn(turn.content),
                    score=min(0.22 + overlap * 0.45, 0.82),
                    source_session=turn.session_id,
                    speaker=turn.speaker,
                    created_at=turn.created_at,
                    actor_id=turn.actor_id,
                    pii_flag=turn.pii_flag,
                    allow_cross_user=turn.allow_cross_user,
                    source_type="turn",
                    quote_text=excerpt,
                )
                key = self._memory_key(candidate)
                existing = results_map.get(key)
                if existing is None or candidate.score > existing.score:
                    results_map[key] = candidate

        ranked = sorted(
            results_map.values(),
            key=lambda item: (
                self._scope_priority(
                    self._source_scope(
                        item_actor_id=item.actor_id,
                        session_id=item.source_session,
                        actor_id=actor_id,
                        current_session_id=current_session_id,
                    )
                ),
                -item.score,
                item.created_at,
            )
        )
        return ranked[: self._settings.knowledge_memory_top_k]

    @staticmethod
    def is_exact_concrete_request(prompt: str, plan: QueryPlan | None) -> bool:
        text = f"{prompt} {plan.meaning if plan else ''} {plan.purpose if plan else ''}".lower()
        cues = [
            "exact",
            "concrete",
            "what did",
            "date",
            "time",
            "number",
            "how many",
            "which",
            "specific",
            "verbatim",
            "quote",
        ]
        return any(cue in text for cue in cues)

    def memory_to_evidence_cards(
        self,
        *,
        memory_results: list[MemoryResult],
        actor_id: str,
        current_session_id: str,
        start_index: int = 1,
    ) -> list[EvidenceCard]:
        cards: list[EvidenceCard] = []
        idx = start_index
        for item in memory_results:
            scope = self._source_scope(
                item_actor_id=item.actor_id,
                session_id=item.source_session,
                actor_id=actor_id,
                current_session_id=current_session_id,
            )
            source_type = {
                "same_session": "memory_same_session",
                "same_user": "memory_same_user",
                "shared": "memory_shared",
            }[scope]

            label = f"E{idx}"
            used_verbatim = bool(item.quote_text and scope in {"same_session", "same_user"})
            content = item.insight
            if used_verbatim:
                content = f"{item.insight}\nVerbatim: \"{item.quote_text}\""

            cards.append(
                EvidenceCard(
                    evidence_id=item.evidence_id,
                    source_type=source_type,
                    actor_scope=scope,
                    label=label,
                    content=content,
                    url=None,
                    source_session=item.source_session,
                    confidence=self.source_confidence(source_type, base_score=item.score),
                    pii_flag=item.pii_flag,
                    used_verbatim=used_verbatim,
                )
            )
            idx += 1
        return cards

    def web_to_evidence_cards(
        self,
        *,
        web_results: list[dict[str, str]],
        start_index: int,
    ) -> list[EvidenceCard]:
        cards: list[EvidenceCard] = []
        idx = start_index
        for row in web_results:
            url = str(row.get("url", "")).strip()
            title = str(row.get("title", "")).strip() or url
            snippet = str(row.get("snippet", "")).strip()
            if not url:
                continue
            source_type = self.classify_source_type_for_url(url)
            tag_hint = "user story / forum" if source_type == "web_user_story_forum" else source_type.replace("web_", "")
            label = f"E{idx}"
            cards.append(
                EvidenceCard(
                    evidence_id=f"web:{idx}:{uuid.uuid4().hex[:8]}",
                    source_type=source_type,
                    actor_scope="web",
                    label=label,
                    content=f"{title}\n{snippet}\nsource_tag={tag_hint}",
                    url=url,
                    source_session=None,
                    confidence=self.source_confidence(source_type, base_score=0.64),
                    pii_flag=False,
                    used_verbatim=False,
                )
            )
            idx += 1
        return cards

    @staticmethod
    def _split_claims(answer_text: str) -> list[str]:
        claims: list[str] = []
        for part in re.split(r"(?<=[.!?])\s+", answer_text.strip()):
            text = part.strip()
            if len(text) < 8:
                continue
            claims.append(text)
        return claims[:8]

    @staticmethod
    def _claim_support_score(claim_text: str, cards: list[EvidenceCard]) -> tuple[float, list[str], bool]:
        terms = KnowledgeAssistService._extract_terms(claim_text, max_terms=16)
        if not terms:
            return 0.0, [], False

        scored: list[tuple[float, EvidenceCard]] = []
        for card in cards:
            overlap = KnowledgeAssistService._term_overlap_score(card.content, terms)
            score = (overlap * 0.65) + (card.confidence * 0.35)
            scored.append((score, card))
        scored.sort(key=lambda item: item[0], reverse=True)

        selected: list[str] = []
        for score, card in scored[:3]:
            if score < 0.28:
                continue
            selected.append(card.label)

        if not selected:
            return 0.0, [], False
        best_score = scored[0][0]
        used_verbatim = any(card.used_verbatim and card.label in selected for _, card in scored[:3])
        return min(best_score, 1.0), selected, used_verbatim

    @staticmethod
    def _find_card_by_label(cards: list[EvidenceCard], label: str) -> EvidenceCard | None:
        for card in cards:
            if card.label == label:
                return card
        return None

    @staticmethod
    def _detect_claim_conflict(claim: GroundedClaim, cards: list[EvidenceCard]) -> bool:
        if len(claim.evidence_ids) < 2:
            return False
        bound_cards = [KnowledgeAssistService._find_card_by_label(cards, label) for label in claim.evidence_ids]
        usable = [card for card in bound_cards if card is not None]
        if len(usable) < 2:
            return False

        for idx, left in enumerate(usable):
            for right in usable[idx + 1 :]:
                left_terms = set(KnowledgeAssistService._extract_terms(left.content, max_terms=24))
                right_terms = set(KnowledgeAssistService._extract_terms(right.content, max_terms=24))
                if not left_terms or not right_terms:
                    continue
                overlap = len(left_terms & right_terms) / max(1, min(len(left_terms), len(right_terms)))
                if overlap < 0.35:
                    continue
                left_nums = set(_NUMERIC_PATTERN.findall(left.content))
                right_nums = set(_NUMERIC_PATTERN.findall(right.content))
                if left_nums and right_nums and left_nums != right_nums:
                    return True
                left_neg = bool(_NEGATION_PATTERN.search(left.content))
                right_neg = bool(_NEGATION_PATTERN.search(right.content))
                if left_neg != right_neg and overlap >= 0.5:
                    return True
        return False

    @staticmethod
    def _claim_line(claim: GroundedClaim) -> str:
        return f"- {claim.text} (conf:{claim.confidence:.2f}, status:{claim.status})"

    @staticmethod
    def _source_line(card: EvidenceCard) -> str:
        scope_part = f" scope={card.actor_scope}" if card.actor_scope else ""
        if card.url:
            return f"[{card.label}] {card.source_type}{scope_part} conf={card.confidence:.2f} {card.url}"
        if card.source_session:
            return (
                f"[{card.label}] {card.source_type}{scope_part} "
                f"conf={card.confidence:.2f} session={card.source_session}"
            )
        return f"[{card.label}] {card.source_type}{scope_part} conf={card.confidence:.2f}"

    @staticmethod
    def _strip_source_artifacts(answer_text: str) -> str:
        text = answer_text
        text = re.sub(r"\[E\d+\]", "", text)
        filtered_lines: list[str] = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            lower = line.lower()
            if lower.startswith("source:"):
                continue
            if lower.startswith("sources:"):
                continue
            if lower.startswith("url:"):
                continue
            filtered_lines.append(raw_line)
        cleaned = "\n".join(filtered_lines)
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    async def generate_grounded_response(
        self,
        *,
        prompt: str,
        model: str,
        grounded_profile: str,
        exact_required: bool,
        evidence_cards: list[EvidenceCard],
    ) -> GroundedResponse:
        if not evidence_cards:
            clarify = "I couldn't verify enough evidence yet. Can you clarify the exact fact or timeframe you want verified?"
            return GroundedResponse(
                status="insufficient",
                answer_text="",
                claims=[],
                overall_confidence=0.0,
                clarify_question=clarify,
                note="No evidence available.",
            )

        evidence_lines = []
        for card in evidence_cards:
            evidence_lines.append(f"{card.label} [{card.source_type}] conf={card.confidence:.2f}")
            evidence_lines.append(card.content)
            if card.url:
                evidence_lines.append(f"URL: {card.url}")
            evidence_lines.append("---")

        system_prompt = (
            "You produce grounded answers only from provided evidence.\n"
            "Return JSON only with fields: answer, note.\n"
            "Requirements:\n"
            "- Add confidence marker '(conf:0.xx)' to factual statements.\n"
            "- If evidence is weak, explicitly say not 100% factual.\n"
            "- Do not include source sections, URLs, or evidence labels in the final answer text.\n"
            "- Do not invent facts outside evidence."
        )
        user_prompt = (
            f"Grounded profile: {grounded_profile}\n"
            f"Exact required: {exact_required}\n"
            f"Question: {prompt}\n"
            "Evidence:\n"
            + "\n".join(evidence_lines)
        )

        try:
            raw = await self._ollama.chat(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
                num_ctx=max(2048, min(self._settings.default_num_ctx, 6144)),
            )
            payload = RecursivePlanner._extract_json_object(raw)
        except OllamaStreamError:
            payload = None

        if payload and isinstance(payload.get("answer"), str):
            answer_text = payload.get("answer", "").strip()
            note = str(payload.get("note", "")).strip()
        else:
            top = evidence_cards[0]
            answer_text = (
                f"Based on available evidence (conf:{top.confidence:.2f}), "
                f"I can state: {top.content}\n"
                "This is not 100% factual without additional corroboration."
            )
            note = "fallback synthesis"

        if not answer_text:
            answer_text = "I could not synthesize a grounded answer from the current evidence."
        answer_text = self._strip_source_artifacts(answer_text)

        claims_raw = self._split_claims(answer_text)
        claims: list[GroundedClaim] = []
        unsupported_count = 0
        for text in claims_raw:
            support_score, evidence_labels, used_verbatim = self._claim_support_score(text, evidence_cards)
            if support_score >= 0.72:
                status = "grounded"
            elif support_score >= 0.45:
                status = "weak"
            else:
                status = "unsupported"
                unsupported_count += 1
            if status != "unsupported" and not evidence_labels:
                status = "unsupported"
                unsupported_count += 1

            confidence = min(max(support_score, 0.0), 1.0)
            claims.append(
                GroundedClaim(
                    claim_id=str(uuid.uuid4()),
                    text=text,
                    evidence_ids=evidence_labels,
                    confidence=confidence,
                    status=status,
                )
            )

        conflict_pairs: list[tuple[str, str]] = []
        for claim in claims:
            if self._detect_claim_conflict(claim, evidence_cards):
                if len(claim.evidence_ids) >= 2:
                    pair = (claim.evidence_ids[0], claim.evidence_ids[1])
                    if pair not in conflict_pairs:
                        conflict_pairs.append(pair)

        if claims:
            overall = sum(item.confidence for item in claims) / len(claims)
        else:
            overall = 0.0

        if exact_required and (unsupported_count > 0 or conflict_pairs):
            conflict_note = " Conflicting evidence detected." if conflict_pairs else ""
            clarify = (
                "I can’t verify the exact concrete data yet. "
                "Which exact phrase, date, or field should I validate first?"
            )
            return GroundedResponse(
                status="insufficient",
                answer_text="",
                claims=claims,
                overall_confidence=overall,
                clarify_question=clarify,
                note=f"Exact request has unsupported or conflicting claims.{conflict_note}",
            )

        if unsupported_count == 0 and not conflict_pairs:
            status = "full"
        else:
            status = "partial"

        if conflict_pairs:
            answer_text = (
                answer_text.rstrip()
                + "\n\nPotential evidence conflict detected across retrieved records. "
                "Presenting both interpretations; clarify which source should be authoritative."
            )

        if (unsupported_count > 0 or conflict_pairs) and "not 100% factual" not in answer_text.lower():
            answer_text = answer_text.rstrip() + "\n\nThis response is not 100% factual; some claims are weakly grounded."

        if claims:
            answer_text = answer_text.rstrip() + "\n\nClaim confidence:\n" + "\n".join(
                self._claim_line(claim) for claim in claims
            )

        return GroundedResponse(
            status=status,
            answer_text=answer_text,
            claims=claims,
            overall_confidence=overall,
            clarify_question="",
            note=note,
        )

    async def log_grounded_run_start(
        self,
        *,
        run_id: str,
        session_id: str,
        actor_id: str,
        mode: str,
        profile: str,
        prompt: str,
    ) -> None:
        await asyncio.to_thread(
            self._store.start_grounded_run,
            run_id=run_id,
            session_id=session_id,
            actor_id=actor_id,
            mode=mode,
            profile=profile,
            prompt=prompt,
        )

    async def log_grounded_evidence(
        self,
        *,
        run_id: str,
        cards: list[EvidenceCard],
    ) -> None:
        for card in cards:
            await asyncio.to_thread(
                self._store.add_grounded_evidence,
                evidence_id=card.evidence_id,
                run_id=run_id,
                source_type=card.source_type,
                actor_scope=card.actor_scope,
                pii_flag=card.pii_flag,
                label=card.label,
                content=card.content,
                url=card.url,
                source_session=card.source_session,
                confidence=card.confidence,
            )

    async def log_grounded_claims(
        self,
        *,
        run_id: str,
        claims: list[GroundedClaim],
        cards: list[EvidenceCard],
        is_exact_required: bool,
    ) -> None:
        label_to_card = {card.label: card for card in cards}
        for claim in claims:
            await asyncio.to_thread(
                self._store.add_grounded_claim,
                claim_id=claim.claim_id,
                run_id=run_id,
                claim_text=claim.text,
                is_exact_required=is_exact_required,
                support_status=claim.status,
                confidence=claim.confidence,
            )
            for label in claim.evidence_ids:
                card = label_to_card.get(label)
                if not card:
                    continue
                await asyncio.to_thread(
                    self._store.link_claim_evidence,
                    claim_id=claim.claim_id,
                    evidence_id=card.evidence_id,
                    support_score=claim.confidence,
                    used_verbatim=card.used_verbatim,
                )

    async def log_grounded_run_finish(self, *, run_id: str, status: str, note: str | None) -> None:
        await asyncio.to_thread(
            self._store.finish_grounded_run,
            run_id=run_id,
            status=status,
            note=note,
        )
