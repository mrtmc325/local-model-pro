from __future__ import annotations

import argparse
import asyncio
import json
import shlex
import sys
from typing import Any

import websockets


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
    return parser


def _print_help() -> None:
    print("Commands:")
    print("  /help              Show this help")
    print("  /model <name>      Switch model for this session")
    print("  /web <on|off>      Enable or disable web assist for prompts")
    print("  /search <query>    Run a direct web search")
    print("  /reset             Clear chat memory")
    print("  /status            Show server session status")
    print("  /exit              Quit")


async def _send(ws: websockets.ClientConnection, payload: dict[str, Any]) -> None:
    await ws.send(json.dumps(payload))


async def _recv_json(ws: websockets.ClientConnection) -> dict[str, Any]:
    raw = await ws.recv()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="ignore")
    return json.loads(raw)


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


async def _consume_status(ws: websockets.ClientConnection) -> None:
    while True:
        msg = await _recv_json(ws)
        msg_type = msg.get("type")
        if msg_type == "status":
            print(
                "status> "
                f"model={msg.get('model')} "
                f"messages={msg.get('message_count')} "
                f"web_assist={msg.get('web_assist_enabled')}"
            )
            return
        if msg_type == "web_mode":
            print(f"web> enabled={msg.get('enabled')}")
            continue
        if msg_type == "web_results":
            _print_web_results(msg)
            continue
        if msg_type == "info":
            print(f"info> {msg.get('message')}")
            continue
        if msg_type == "error":
            print(f"error> {msg.get('message')}")
            return


async def _consume_web_search(ws: websockets.ClientConnection) -> None:
    while True:
        msg = await _recv_json(ws)
        msg_type = msg.get("type")
        if msg_type == "web_results":
            _print_web_results(msg)
            return
        if msg_type == "web_mode":
            print(f"web> enabled={msg.get('enabled')}")
            continue
        if msg_type == "info":
            print(f"info> {msg.get('message')}")
            continue
        if msg_type == "error":
            print(f"error> {msg.get('message')}")
            return


async def _consume_stream(ws: websockets.ClientConnection) -> None:
    print("ai> ", end="", flush=True)
    while True:
        msg = await _recv_json(ws)
        msg_type = msg.get("type")

        if msg_type == "start":
            continue
        if msg_type == "web_results":
            print("")
            _print_web_results(msg)
            print("ai> ", end="", flush=True)
            continue
        if msg_type == "web_mode":
            print(f"\nweb> enabled={msg.get('enabled')}")
            print("ai> ", end="", flush=True)
            continue
        if msg_type == "token":
            print(msg.get("text", ""), end="", flush=True)
            continue
        if msg_type == "done":
            print("")
            return
        if msg_type == "info":
            print(f"\ninfo> {msg.get('message')}")
            print("ai> ", end="", flush=True)
            continue
        if msg_type == "error":
            print(f"\nerror> {msg.get('message')}")
            return


async def run_cli(url: str, model: str | None, system_prompt: str | None) -> int:
    print(f"Connecting to {url}")
    async with websockets.connect(url, max_size=None) as ws:
        # Drain initial greeting frames.
        for _ in range(2):
            msg = await _recv_json(ws)
            if msg.get("type") == "ready":
                print(f"connected> session={msg.get('session_id')} model={msg.get('model')}")
            elif msg.get("type") == "info":
                print(f"info> {msg.get('message')}")

        hello_payload: dict[str, Any] = {"type": "hello"}
        if model:
            hello_payload["model"] = model
        if system_prompt:
            hello_payload["system_prompt"] = system_prompt
        await _send(ws, hello_payload)

        # Consume ready after hello.
        while True:
            msg = await _recv_json(ws)
            if msg.get("type") == "ready":
                print(
                    "ready> "
                    f"model={msg.get('model')} "
                    f"web_assist={msg.get('web_assist_enabled')}"
                )
                break
            if msg.get("type") == "info":
                print(f"info> {msg.get('message')}")
            elif msg.get("type") == "web_mode":
                print(f"web> enabled={msg.get('enabled')}")
            elif msg.get("type") == "web_results":
                _print_web_results(msg)
            elif msg.get("type") == "error":
                print(f"error> {msg.get('message')}")

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
                # Expect both web_mode and info payloads.
                for _ in range(2):
                    msg = await _recv_json(ws)
                    msg_type = msg.get("type")
                    if msg_type == "web_mode":
                        print(f"web> enabled={msg.get('enabled')}")
                    elif msg_type == "info":
                        print(f"info> {msg.get('message')}")
                    elif msg_type == "error":
                        print(f"error> {msg.get('message')}")
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
        raise_code = asyncio.run(run_cli(args.url, args.model, args.system_prompt))
    except KeyboardInterrupt:
        raise_code = 0
    except Exception as exc:
        print(f"fatal> {exc}", file=sys.stderr)
        raise_code = 1
    raise SystemExit(raise_code)


if __name__ == "__main__":
    main()
