from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path


class WorkspaceToolError(RuntimeError):
    """Base error for workspace tool operations."""


class WorkspaceSecurityError(WorkspaceToolError):
    """Raised when path or command access violates workspace policy."""


@dataclass(frozen=True)
class CommandResult:
    command: str
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool
    output_truncated: bool


_TEXT_SUFFIXES = {
    ".txt",
    ".md",
    ".rst",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".json",
    ".yml",
    ".yaml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".sh",
    ".bash",
    ".zsh",
    ".html",
    ".css",
    ".csv",
    ".sql",
    ".xml",
}


class LocalWorkspaceTools:
    def __init__(
        self,
        *,
        workspace_root: str,
        read_max_bytes: int,
        list_max_entries: int,
        find_max_results: int,
        summary_max_files: int,
        summary_file_chars: int,
    ) -> None:
        root = Path(workspace_root).expanduser().resolve()
        if not root.exists() or not root.is_dir():
            raise WorkspaceSecurityError(f"Workspace root does not exist or is not a directory: {root}")

        self.workspace_root = root
        self.read_max_bytes = max(2048, read_max_bytes)
        self.list_max_entries = max(50, list_max_entries)
        self.find_max_results = max(10, find_max_results)
        self.summary_max_files = max(1, summary_max_files)
        self.summary_file_chars = max(300, summary_file_chars)

    def resolve_path(self, raw_path: str | None) -> Path:
        candidate: Path
        if raw_path is None or not raw_path.strip():
            candidate = self.workspace_root
        else:
            proposed = Path(raw_path.strip()).expanduser()
            candidate = (self.workspace_root / proposed).resolve() if not proposed.is_absolute() else proposed.resolve()

        if not candidate.exists():
            raise WorkspaceToolError(f"Path does not exist: {candidate}")
        if not candidate.is_relative_to(self.workspace_root):
            raise WorkspaceSecurityError("Path is outside the configured workspace root.")
        return candidate

    def list_directory(self, raw_path: str | None) -> str:
        path = self.resolve_path(raw_path)
        if not path.is_dir():
            raise WorkspaceToolError(f"Not a directory: {path}")

        entries = sorted(path.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))
        shown = entries[: self.list_max_entries]

        rel_path = path.relative_to(self.workspace_root)
        header = f"Directory: /{rel_path.as_posix()}" if str(rel_path) != "." else "Directory: /"

        lines = [header, ""]
        for entry in shown:
            rel = entry.relative_to(self.workspace_root).as_posix()
            if entry.is_dir():
                lines.append(f"[DIR]  /{rel}/")
            else:
                size = entry.stat().st_size
                lines.append(f"[FILE] /{rel} ({size} bytes)")

        remaining = len(entries) - len(shown)
        if remaining > 0:
            lines.append("")
            lines.append(f"... truncated {remaining} additional entries")

        return "\n".join(lines)

    def render_tree(self, raw_path: str | None, *, max_depth: int = 3) -> str:
        base = self.resolve_path(raw_path)
        if not base.is_dir():
            raise WorkspaceToolError(f"Not a directory: {base}")

        rel_path = base.relative_to(self.workspace_root)
        root_label = "/" if str(rel_path) == "." else f"/{rel_path.as_posix()}"
        lines = [f"Tree: {root_label}"]
        visited = 0

        def walk(node: Path, prefix: str, depth: int) -> bool:
            nonlocal visited
            try:
                children = sorted(node.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))
            except OSError:
                lines.append(f"{prefix}[error] unable to list {node.name}")
                return False

            for index, child in enumerate(children):
                if visited >= self.list_max_entries:
                    lines.append("... output truncated")
                    return True

                connector = "└──" if index == len(children) - 1 else "├──"
                rel = child.relative_to(self.workspace_root).as_posix()
                label = f"/{rel}/" if child.is_dir() else f"/{rel}"
                lines.append(f"{prefix}{connector} {label}")
                visited += 1

                if child.is_dir() and depth < max_depth:
                    child_prefix = prefix + ("    " if index == len(children) - 1 else "│   ")
                    if walk(child, child_prefix, depth + 1):
                        return True
            return False

        walk(base, "", 1)
        return "\n".join(lines)

    def find_paths(self, *, query: str, raw_path: str | None) -> str:
        normalized_query = query.strip().lower()
        if not normalized_query:
            raise WorkspaceToolError("Query cannot be empty.")

        base = self.resolve_path(raw_path)
        if not base.is_dir():
            raise WorkspaceToolError(f"Not a directory: {base}")

        matches: list[str] = []
        try:
            iterator = sorted(base.rglob("*"), key=lambda item: item.as_posix().lower())
        except OSError as exc:
            raise WorkspaceToolError(f"Unable to search path: {exc}") from exc

        for item in iterator:
            rel = item.relative_to(self.workspace_root).as_posix()
            if normalized_query in item.name.lower() or normalized_query in rel.lower():
                suffix = "/" if item.is_dir() else ""
                matches.append(f"/{rel}{suffix}")
                if len(matches) >= self.find_max_results:
                    break

        if not matches:
            return f"No file or directory names matched '{query.strip()}'."

        lines = [f"Matches for '{query.strip()}':", ""]
        lines.extend(matches)
        return "\n".join(lines)

    def read_text_file(self, raw_path: str) -> str:
        path = self.resolve_path(raw_path)
        if not path.is_file():
            raise WorkspaceToolError(f"Not a file: {path}")

        data = path.read_bytes()
        if b"\x00" in data[:2048]:
            raise WorkspaceToolError(f"Binary file cannot be displayed as text: {path}")

        truncated = False
        if len(data) > self.read_max_bytes:
            data = data[: self.read_max_bytes]
            truncated = True

        rel = path.relative_to(self.workspace_root).as_posix()
        text = data.decode("utf-8", errors="replace")

        lines = [
            f"File: /{rel}",
            f"Bytes shown: {len(data)}",
            "",
            text,
        ]
        if truncated:
            lines.extend(["", "... file output truncated"])
        return "\n".join(lines)

    def build_summary_context(self, raw_path: str | None) -> str:
        target = self.resolve_path(raw_path)
        rel = target.relative_to(self.workspace_root)
        label = "/" if str(rel) == "." else f"/{rel.as_posix()}"

        if target.is_file():
            file_content = self.read_text_file(str(target))
            return (
                f"Workspace root: {self.workspace_root}\n"
                f"Summary target: file {label}\n\n"
                "Context:\n"
                f"{file_content[: self.summary_file_chars]}"
            )

        tree = self.render_tree(str(target), max_depth=3)
        snippets: list[str] = []
        considered = 0

        for item in sorted(target.rglob("*"), key=lambda p: p.as_posix().lower()):
            if not item.is_file():
                continue
            considered += 1
            if item.suffix.lower() not in _TEXT_SUFFIXES and item.name not in {"Dockerfile", "Makefile"}:
                continue
            try:
                content = item.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            rel_path = item.relative_to(self.workspace_root).as_posix()
            snippets.append(
                f"--- /{rel_path} ---\n{content[: self.summary_file_chars]}"
            )
            if len(snippets) >= self.summary_max_files:
                break

        snippets_text = "\n\n".join(snippets) if snippets else "(No text files sampled.)"
        return (
            f"Workspace root: {self.workspace_root}\n"
            f"Summary target: directory {label}\n"
            f"Files considered: {considered}\n"
            f"Sampled files: {len(snippets)}\n\n"
            f"Directory tree:\n{tree}\n\n"
            f"Sample file snippets:\n{snippets_text}"
        )

    async def run_command(
        self,
        *,
        command: str,
        timeout_seconds: int,
        max_output_bytes: int,
    ) -> CommandResult:
        normalized = command.strip()
        if not normalized:
            raise WorkspaceToolError("Command cannot be empty.")

        process = await asyncio.create_subprocess_shell(
            normalized,
            cwd=str(self.workspace_root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=os.environ.copy(),
        )

        timed_out = False
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=max(1, timeout_seconds),
            )
        except asyncio.TimeoutError:
            timed_out = True
            process.kill()
            stdout_bytes, stderr_bytes = await process.communicate()

        total = len(stdout_bytes) + len(stderr_bytes)
        output_truncated = total > max_output_bytes

        if output_truncated:
            if len(stdout_bytes) >= max_output_bytes:
                stdout_bytes = stdout_bytes[:max_output_bytes]
                stderr_bytes = b""
            else:
                remaining = max_output_bytes - len(stdout_bytes)
                stderr_bytes = stderr_bytes[: max(0, remaining)]

        stdout_text = stdout_bytes.decode("utf-8", errors="replace")
        stderr_text = stderr_bytes.decode("utf-8", errors="replace")

        return CommandResult(
            command=normalized,
            returncode=process.returncode if process.returncode is not None else -1,
            stdout=stdout_text,
            stderr=stderr_text,
            timed_out=timed_out,
            output_truncated=output_truncated,
        )
