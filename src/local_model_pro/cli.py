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
    print("  /help            Show this help")
    print("  /model <name>    Switch model for this session")
    print("  /reset           Clear chat memory")
    print("  /status          Show server session status")
    print("  /tools           Show local tool command help")
    print("  /ls [path]       List directory entries")
    print("  /tree [path]     Show directory tree")
    print("  /find <q> [path] Find files/folders by name")
    print("  /read <path>     Read a text file")
    print("  /summary [path]  Summarize a file or folder")
    print("  /run <cmd>       Preview shell command")
    print("  /run! <cmd>      Execute shell command")
    print("  /exit            Quit")


async def _send(ws: websockets.ClientConnection, payload: dict[str, Any]) -> None:
    await ws.send(json.dumps(payload))


async def _recv_json(ws: websockets.ClientConnection) -> dict[str, Any]:
    raw = await ws.recv()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="ignore")
    return json.loads(raw)


def _print_event(msg: dict[str, Any]) -> str:
    msg_type = str(msg.get("type", ""))
    if msg_type == "info":
        print(f"info> {msg.get('message')}")
    elif msg_type == "error":
        print(f"error> {msg.get('message')}")
    elif msg_type == "status":
        print(
            "status> "
            f"model={msg.get('model')} "
            f"message_count={msg.get('message_count')} "
            f"actor_id={msg.get('actor_id')}"
        )
    return msg_type


async def _consume_status(ws: websockets.ClientConnection) -> None:
    while True:
        msg = await _recv_json(ws)
        msg_type = _print_event(msg)
        if msg_type == "status":
            return


async def _consume_chat_turn(ws: websockets.ClientConnection) -> None:
    request_id = ""
    while True:
        msg = await _recv_json(ws)
        msg_type = str(msg.get("type", ""))

        if msg_type in {"info", "error", "status"}:
            _print_event(msg)
            if msg_type == "error":
                print()
                return
            continue

        if msg_type == "start":
            request_id = str(msg.get("request_id", ""))
            print("ai> ", end="", flush=True)
            continue

        if msg_type == "token":
            if request_id and str(msg.get("request_id", "")) != request_id:
                continue
            print(str(msg.get("text", "")), end="", flush=True)
            continue

        if msg_type == "done":
            if request_id and str(msg.get("request_id", "")) != request_id:
                continue
            print()
            return


def _parse_command(raw_input: str) -> list[str]:
    try:
        return shlex.split(raw_input)
    except ValueError:
        return []


async def _chat_loop(
    *,
    url: str,
    model: str | None,
    system_prompt: str | None,
) -> None:
    async with websockets.connect(url) as ws:
        hello = {"type": "hello"}
        if model:
            hello["model"] = model
        if system_prompt:
            hello["system_prompt"] = system_prompt
        await _send(ws, hello)

        while True:
            msg = await _recv_json(ws)
            msg_type = str(msg.get("type", ""))
            if msg_type == "ready":
                print(
                    f"ready> session_id={msg.get('session_id')} "
                    f"actor_id={msg.get('actor_id')} model={msg.get('model')}"
                )
                break
            _print_event(msg)

        _print_help()

        while True:
            try:
                user_input = await asyncio.to_thread(input, "you> ")
            except EOFError:
                print()
                return

            if not user_input.strip():
                continue

            if user_input.startswith("/"):
                parts = _parse_command(user_input)
                if not parts:
                    print("error> invalid command")
                    continue

                cmd = parts[0].lower()
                if cmd == "/help":
                    _print_help()
                    continue

                if cmd == "/exit":
                    return

                if cmd == "/model":
                    if len(parts) < 2:
                        print("error> usage: /model <name>")
                        continue
                    await _send(ws, {"type": "set_model", "model": parts[1]})
                    msg = await _recv_json(ws)
                    _print_event(msg)
                    continue

                if cmd == "/reset":
                    await _send(ws, {"type": "reset"})
                    msg = await _recv_json(ws)
                    _print_event(msg)
                    continue

                if cmd == "/status":
                    await _send(ws, {"type": "status"})
                    await _consume_status(ws)
                    continue

                if cmd in {"/tools", "/ls", "/tree", "/find", "/read", "/summary"}:
                    await _send(ws, {"type": "chat", "prompt": user_input})
                    await _consume_chat_turn(ws)
                    continue

                if user_input.startswith("/run"):
                    await _send(ws, {"type": "chat", "prompt": user_input})
                    await _consume_chat_turn(ws)
                    continue

                print("error> unknown command")
                continue

            await _send(ws, {"type": "chat", "prompt": user_input})
            await _consume_chat_turn(ws)


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    try:
        asyncio.run(
            _chat_loop(
                url=args.url,
                model=args.model,
                system_prompt=args.system_prompt,
            )
        )
    except KeyboardInterrupt:
        print("\nbye")
    except Exception as exc:  # pragma: no cover
        print(f"fatal> {exc}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
