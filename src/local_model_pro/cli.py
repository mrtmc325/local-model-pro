from __future__ import annotations

import argparse
import asyncio
import json
import shlex
import sys
from typing import Any

import websockets


def _flag(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Terminal CLI for local model WebSocket chat")
    parser.add_argument(
        "--url",
        default="ws://127.0.0.1:8765/ws/chat",
        help="WebSocket URL (default: ws://127.0.0.1:8765/ws/chat)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model name to request at connect time",
    )
    parser.add_argument(
        "--system-prompt",
        default=None,
        help="Optional system prompt to seed the session",
    )
    parser.add_argument(
        "--web-assist",
        default="off",
        choices=["on", "off"],
        help="Enable web assist by default at connect time (default: off)",
    )
    parser.add_argument(
        "--knowledge-assist",
        default="on",
        choices=["on", "off"],
        help="Enable knowledge assist by default at connect time (default: on)",
    )
    parser.add_argument(
        "--grounded-mode",
        default="on",
        choices=["on", "off"],
        help="Enable grounded mode by default at connect time (default: on)",
    )
    parser.add_argument(
        "--grounded-profile",
        default="balanced",
        choices=["strict", "balanced"],
        help="Grounded profile for responses (default: balanced)",
    )
    return parser


def _print_help() -> None:
    print("Commands:")
    print("  /help                   Show this help")
    print("  /model <name>           Switch model for this session")
    print("  /web <on|off>           Enable or disable web assist for prompts")
    print("  /knowledge <on|off>     Enable or disable recursive knowledge assist")
    print("  /grounded <on|off>      Enable or disable grounded mode")
    print("  /profile <strict|balanced>  Set grounded profile")
    print("  /search <query>         Run a direct web search")
    print("  /reset                  Clear chat memory")
    print("  /status                 Show server session status")
    print("  /exit                   Quit")


async def _send(ws: websockets.ClientConnection, payload: dict[str, Any]) -> None:
    await ws.send(json.dumps(payload))


async def _recv_json(ws: websockets.ClientConnection) -> dict[str, Any]:
    raw = await ws.recv()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="ignore")
    return json.loads(raw)


def _print_query_plan(msg: dict[str, Any]) -> None:
    print("plan> recursive query breakdown")
    print(f"plan> reason: {msg.get('reason')}")
    print(f"plan> meaning: {msg.get('meaning')}")
    print(f"plan> purpose: {msg.get('purpose')}")
    print(f"plan> db_query: {msg.get('db_query')}")
    print(f"plan> web_query: {msg.get('web_query')}")


def _print_memory_results(msg: dict[str, Any]) -> None:
    query = str(msg.get("query", "")).strip()
    results = msg.get("results", [])
    print(f"memory> results for: {query}")
    if not isinstance(results, list) or not results:
        print("memory> no results")
        return
    for idx, item in enumerate(results, start=1):
        if not isinstance(item, dict):
            continue
        insight = str(item.get("insight", "")).strip()
        score = item.get("score", 0.0)
        source_session = str(item.get("source_session", "")).strip()
        print(f"memory> {idx}. {insight}")
        print(f"memory>    score={score} source_session={source_session}")


def _print_web_results(msg: dict[str, Any]) -> None:
    query = str(msg.get("query", "")).strip()
    results = msg.get("results", [])
    retrieved_at = str(msg.get("retrieved_at", "")).strip()
    print(f"web> results for: {query}")
    if retrieved_at:
        print(f"web> retrieved_at: {retrieved_at}")
    if not isinstance(results, list) or not results:
        print("web> no results")
        return
    for idx, item in enumerate(results, start=1):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip() or "(untitled)"
        url = str(item.get("url", "")).strip()
        snippet = str(item.get("snippet", "")).strip()
        print(f"web> {idx}. {title}")
        if url:
            print(f"web>    {url}")
        if snippet:
            print(f"web>    {snippet}")


def _print_evidence_used(msg: dict[str, Any]) -> None:
    results = msg.get("results", [])
    print("evidence> used")
    if not isinstance(results, list) or not results:
        print("evidence> none")
        return
    for item in results:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label", "")).strip() or "E?"
        source_type = str(item.get("source_type", "")).strip() or "unknown"
        confidence = item.get("confidence", 0.0)
        url = str(item.get("url", "")).strip()
        source_session = str(item.get("source_session", "")).strip()
        print(f"evidence> {label} {source_type} conf={confidence}")
        if url:
            print(f"evidence>    {url}")
        elif source_session:
            print(f"evidence>    session={source_session}")


def _print_grounding_status(msg: dict[str, Any]) -> None:
    print(
        "grounding> "
        f"status={msg.get('status')} "
        f"profile={msg.get('profile')} "
        f"exact_required={msg.get('exact_required')} "
        f"overall_confidence={msg.get('overall_confidence')}"
    )
    note = str(msg.get("note", "")).strip()
    if note:
        print(f"grounding> note={note}")


def _print_clarify_needed(msg: dict[str, Any]) -> None:
    question = str(msg.get("question", "")).strip() or "Please clarify the exact fact to verify."
    print(f"clarify> {question}")


def _print_memory_saved(msg: dict[str, Any]) -> None:
    artifact_id = str(msg.get("artifact_id", "")).strip() or "(none)"
    file_path = str(msg.get("file_path", "")).strip() or "(none)"
    indexed_count = int(msg.get("indexed_count", 0) or 0)
    note = str(msg.get("note", "")).strip()
    print(
        "memory_saved> "
        f"artifact_id={artifact_id} indexed_count={indexed_count} file={file_path}"
    )
    if note:
        print(f"memory_saved> note={note}")


def _print_url_review_saved(msg: dict[str, Any]) -> None:
    items = msg.get("items", [])
    print("url_review_saved> items")
    if not isinstance(items, list) or not items:
        print("url_review_saved> none")
        return
    for item in items:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url", "")).strip()
        status = str(item.get("status", "")).strip() or "unknown"
        indexed_count = int(item.get("indexed_count", 0) or 0)
        error = str(item.get("error", "")).strip()
        print(f"url_review_saved> {url} status={status} indexed_count={indexed_count}")
        if error:
            print(f"url_review_saved>    error={error}")


def _print_web_review_context(msg: dict[str, Any]) -> None:
    items = msg.get("items", [])
    print("web_review_context> items")
    if not isinstance(items, list) or not items:
        print("web_review_context> none")
        return
    for item in items:
        if not isinstance(item, dict):
            continue
        url = str(item.get("final_url") or item.get("url") or "").strip()
        status = str(item.get("status", "")).strip() or "unknown"
        meaning = str(item.get("meaning", "")).strip()
        error = str(item.get("error", "")).strip()
        print(f"web_review_context> {url} status={status}")
        if meaning:
            print(f"web_review_context>    meaning={meaning[:200]}")
        if error:
            print(f"web_review_context>    error={error}")


def _print_event(msg: dict[str, Any]) -> str:
    msg_type = str(msg.get("type", ""))
    if msg_type == "web_mode":
        print(f"web> enabled={msg.get('enabled')}")
    elif msg_type == "knowledge_mode":
        print(f"knowledge> enabled={msg.get('enabled')}")
    elif msg_type == "grounded_mode":
        print(f"grounded> enabled={msg.get('enabled')}")
    elif msg_type == "grounded_profile":
        print(f"grounded> profile={msg.get('profile')}")
    elif msg_type == "query_plan":
        _print_query_plan(msg)
    elif msg_type == "memory_results":
        _print_memory_results(msg)
    elif msg_type == "web_results":
        _print_web_results(msg)
    elif msg_type == "evidence_used":
        _print_evidence_used(msg)
    elif msg_type == "grounding_status":
        _print_grounding_status(msg)
    elif msg_type == "clarify_needed":
        _print_clarify_needed(msg)
    elif msg_type == "memory_saved":
        _print_memory_saved(msg)
    elif msg_type == "url_review_saved":
        _print_url_review_saved(msg)
    elif msg_type == "web_review_context":
        _print_web_review_context(msg)
    elif msg_type == "info":
        print(f"info> {msg.get('message')}")
    elif msg_type == "error":
        print(f"error> {msg.get('message')}")
    return msg_type


async def _consume_mode_update(
    ws: websockets.ClientConnection,
    *,
    expected_type: str,
) -> None:
    saw_expected = False
    for _ in range(4):
        try:
            msg = await asyncio.wait_for(_recv_json(ws), timeout=0.8 if not saw_expected else 0.2)
        except TimeoutError:
            break
        msg_type = _print_event(msg)
        if msg_type == expected_type:
            saw_expected = True
        if msg_type == "error":
            break
    if not saw_expected:
        print(f"info> no {expected_type} event received")


async def _consume_status(ws: websockets.ClientConnection) -> None:
    while True:
        msg = await _recv_json(ws)
        msg_type = msg.get("type")
        if msg_type == "status":
            print(
                "status> "
                f"model={msg.get('model')} "
                f"messages={msg.get('message_count')} "
                f"web_assist={msg.get('web_assist_enabled')} "
                f"knowledge_assist={msg.get('knowledge_assist_enabled')} "
                f"grounded_mode={msg.get('grounded_mode_enabled')} "
                f"grounded_profile={msg.get('grounded_profile')}"
            )
            return
        _print_event(msg)
        if msg_type == "error":
            return


async def _consume_web_search(ws: websockets.ClientConnection) -> None:
    saw_web_results = False
    while True:
        try:
            msg = await asyncio.wait_for(_recv_json(ws), timeout=2.0 if not saw_web_results else 0.25)
        except TimeoutError:
            return
        msg_type = msg.get("type")
        _print_event(msg)
        if msg_type == "web_results":
            saw_web_results = True
        elif msg_type == "error":
            return


async def _consume_stream(ws: websockets.ClientConnection) -> None:
    print("ai> ", end="", flush=True)
    while True:
        msg = await _recv_json(ws)
        msg_type = msg.get("type")

        if msg_type == "start":
            continue
        if msg_type in {
            "query_plan",
            "memory_results",
            "web_results",
            "web_mode",
            "knowledge_mode",
            "grounded_mode",
            "grounded_profile",
            "evidence_used",
            "grounding_status",
            "clarify_needed",
            "memory_saved",
            "url_review_saved",
            "web_review_context",
            "info",
        }:
            print("")
            _print_event(msg)
            print("ai> ", end="", flush=True)
            continue
        if msg_type == "token":
            print(msg.get("text", ""), end="", flush=True)
            continue
        if msg_type == "done":
            print("")
            return
        if msg_type == "error":
            print("")
            _print_event(msg)
            return


async def run_cli(
    url: str,
    model: str | None,
    system_prompt: str | None,
    *,
    web_assist: bool,
    knowledge_assist: bool,
    grounded_mode: bool,
    grounded_profile: str,
) -> int:
    print(f"Connecting to {url}")
    async with websockets.connect(url, max_size=None) as ws:
        for _ in range(2):
            msg = await _recv_json(ws)
            if msg.get("type") == "ready":
                print(f"connected> session={msg.get('session_id')} model={msg.get('model')}")
            elif msg.get("type") == "info":
                print(f"info> {msg.get('message')}")

        hello_payload: dict[str, Any] = {
            "type": "hello",
            "web_assist_enabled": web_assist,
            "knowledge_assist_enabled": knowledge_assist,
            "grounded_mode_enabled": grounded_mode,
            "grounded_profile": grounded_profile,
        }
        if model:
            hello_payload["model"] = model
        if system_prompt:
            hello_payload["system_prompt"] = system_prompt
        await _send(ws, hello_payload)

        while True:
            msg = await _recv_json(ws)
            msg_type = msg.get("type")
            if msg_type == "ready":
                print(
                    "ready> "
                    f"model={msg.get('model')} "
                    f"web_assist={msg.get('web_assist_enabled')} "
                    f"knowledge_assist={msg.get('knowledge_assist_enabled')} "
                    f"grounded_mode={msg.get('grounded_mode_enabled')} "
                    f"grounded_profile={msg.get('grounded_profile')}"
                )
                break
            _print_event(msg)

        _print_help()

        while True:
            user_input = (await asyncio.to_thread(input, "you> ")).strip()
            if not user_input:
                continue
            if user_input == "/exit":
                return 0
            if user_input == "/help":
                _print_help()
                continue
            if user_input == "/reset":
                await _send(ws, {"type": "reset"})
                msg = await _recv_json(ws)
                print(f"{msg.get('type')}> {msg.get('message')}")
                continue
            if user_input == "/status":
                await _send(ws, {"type": "status"})
                await _consume_status(ws)
                continue
            if user_input.startswith("/model"):
                parts = shlex.split(user_input)
                if len(parts) < 2:
                    print("error> usage: /model <name>")
                    continue
                await _send(ws, {"type": "set_model", "model": parts[1]})
                msg = await _recv_json(ws)
                print(f"{msg.get('type')}> {msg.get('message')}")
                continue
            if user_input.startswith("/web"):
                parts = shlex.split(user_input)
                if len(parts) != 2 or parts[1] not in {"on", "off"}:
                    print("error> usage: /web <on|off>")
                    continue
                await _send(ws, {"type": "set_web_mode", "enabled": parts[1] == "on"})
                await _consume_mode_update(ws, expected_type="web_mode")
                continue
            if user_input.startswith("/knowledge"):
                parts = shlex.split(user_input)
                if len(parts) != 2 or parts[1] not in {"on", "off"}:
                    print("error> usage: /knowledge <on|off>")
                    continue
                await _send(ws, {"type": "set_knowledge_mode", "enabled": parts[1] == "on"})
                await _consume_mode_update(ws, expected_type="knowledge_mode")
                continue
            if user_input.startswith("/grounded"):
                parts = shlex.split(user_input)
                if len(parts) != 2 or parts[1] not in {"on", "off"}:
                    print("error> usage: /grounded <on|off>")
                    continue
                await _send(ws, {"type": "set_grounded_mode", "enabled": parts[1] == "on"})
                await _consume_mode_update(ws, expected_type="grounded_mode")
                continue
            if user_input.startswith("/profile"):
                parts = shlex.split(user_input)
                if len(parts) != 2 or parts[1] not in {"strict", "balanced"}:
                    print("error> usage: /profile <strict|balanced>")
                    continue
                await _send(ws, {"type": "set_grounded_profile", "profile": parts[1]})
                await _consume_mode_update(ws, expected_type="grounded_profile")
                continue
            if user_input.startswith("/search"):
                parts = shlex.split(user_input)
                if len(parts) < 2:
                    print("error> usage: /search <query>")
                    continue
                query = " ".join(parts[1:]).strip()
                await _send(ws, {"type": "web_search", "query": query})
                await _consume_web_search(ws)
                continue

            await _send(ws, {"type": "chat", "prompt": user_input})
            await _consume_stream(ws)


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    try:
        raise_code = asyncio.run(
            run_cli(
                args.url,
                args.model,
                args.system_prompt,
                web_assist=_flag(args.web_assist),
                knowledge_assist=_flag(args.knowledge_assist),
                grounded_mode=_flag(args.grounded_mode),
                grounded_profile=args.grounded_profile,
            )
        )
    except KeyboardInterrupt:
        raise_code = 0
    except Exception as exc:
        print(f"fatal> {exc}", file=sys.stderr)
        raise_code = 1
    raise SystemExit(raise_code)


if __name__ == "__main__":
    main()
