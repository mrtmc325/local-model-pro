from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class MemoryResult:
    insight: str
    score: float
    source_session: str
    speaker: str
    created_at: str


class QdrantError(RuntimeError):
    """Raised when Qdrant operations fail."""


class QdrantMemoryIndex:
    def __init__(
        self,
        *,
        base_url: str,
        collection: str,
        timeout: float = 20.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._collection = collection
        self._timeout = timeout
        self._vector_size: int | None = None

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_payload: dict[str, Any] | None = None,
        expected_status: set[int] | None = None,
    ) -> dict[str, Any]:
        expected = expected_status or {200}
        url = f"{self._base_url}{path}"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.request(method, url, json=json_payload)
        if response.status_code not in expected:
            text = response.text[:600]
            raise QdrantError(f"Qdrant error {response.status_code}: {text}")
        if not response.text:
            return {}
        try:
            payload = response.json()
        except ValueError as exc:
            raise QdrantError("Invalid JSON payload from Qdrant") from exc
        if not isinstance(payload, dict):
            raise QdrantError("Unexpected Qdrant payload shape")
        return payload

    async def ensure_collection(self, *, vector_size: int) -> None:
        if self._vector_size == vector_size:
            return

        path = f"/collections/{self._collection}"
        try:
            existing = await self._request("GET", path)
        except QdrantError as exc:
            if "404" not in str(exc):
                raise
            existing = {}

        if existing.get("result"):
            self._vector_size = vector_size
            return

        payload = {
            "vectors": {
                "size": vector_size,
                "distance": "Cosine",
            }
        }
        await self._request("PUT", path, json_payload=payload, expected_status={200, 201})
        self._vector_size = vector_size

    async def upsert(
        self,
        *,
        point_id: str,
        vector: list[float],
        payload: dict[str, Any],
    ) -> None:
        if not vector:
            raise QdrantError("Cannot upsert an empty vector.")
        await self.ensure_collection(vector_size=len(vector))
        await self._request(
            "PUT",
            f"/collections/{self._collection}/points",
            json_payload={
                "points": [
                    {
                        "id": point_id,
                        "vector": vector,
                        "payload": payload,
                    }
                ]
            },
            expected_status={200, 201},
        )

    async def search(
        self,
        *,
        vector: list[float],
        limit: int,
        score_threshold: float,
    ) -> list[MemoryResult]:
        if not vector:
            return []
        use_limit = max(1, min(limit, 20))
        payload = {
            "vector": vector,
            "limit": use_limit,
            "with_payload": True,
            "score_threshold": score_threshold,
        }
        response = await self._request(
            "POST",
            f"/collections/{self._collection}/points/search",
            json_payload=payload,
            expected_status={200},
        )
        raw_items = response.get("result", [])
        if not isinstance(raw_items, list):
            return []

        results: list[MemoryResult] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            payload_obj = item.get("payload", {})
            if not isinstance(payload_obj, dict):
                continue
            insight = str(payload_obj.get("insight", "")).strip()
            source_session = str(payload_obj.get("source_session", "")).strip()
            speaker = str(payload_obj.get("speaker", "")).strip()
            created_at = str(payload_obj.get("created_at", "")).strip()
            if not insight or not source_session:
                continue
            score_raw = item.get("score", 0.0)
            try:
                score = float(score_raw)
            except (TypeError, ValueError):
                score = 0.0
            results.append(
                MemoryResult(
                    insight=insight,
                    score=score,
                    source_session=source_session,
                    speaker=speaker or "unknown",
                    created_at=created_at,
                )
            )
        return results

