from __future__ import annotations

import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

from fastapi.testclient import TestClient

from local_model_pro.admin_profile_store import AdminProfileStore
from local_model_pro.server import app, pull_jobs, settings, uploaded_contexts


class ServerChatTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        temp_state_path = Path(self._tmp_dir.name) / "admin_profile_state.json"
        temp_store = AdminProfileStore(
            state_path=temp_state_path,
            default_actor_id=settings.default_actor_id,
        )
        self._store_patcher = mock.patch("local_model_pro.server.admin_profile_store", new=temp_store)
        self._store_patcher.start()
        uploaded_contexts.clear()

    def tearDown(self) -> None:
        uploaded_contexts.clear()
        self._store_patcher.stop()
        self._tmp_dir.cleanup()

    @staticmethod
    def _consume_until_ready(ws: object) -> None:
        while True:
            message = ws.receive_json()
            if message.get("type") == "ready":
                return

    @staticmethod
    def _run_turn(ws: object, prompt: str) -> list[dict[str, object]]:
        ws.send_json({"type": "chat", "prompt": prompt})
        events: list[dict[str, object]] = []
        while True:
            message = ws.receive_json()
            events.append(message)
            if message.get("type") == "done":
                return events

    def test_service_metadata_is_chat_only(self) -> None:
        client = TestClient(app)
        response = client.get("/api/service")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["capabilities"]["chat"], True)
        self.assertEqual(payload["capabilities"]["model_switching"], True)
        self.assertEqual(payload["capabilities"]["local_tools"], True)
        self.assertEqual(payload["capabilities"]["file_upload_review"], True)

    def test_upload_text_file_and_list_delete(self) -> None:
        client = TestClient(app)

        upload_response = client.post(
            "/api/uploads",
            files={"file": ("hello.py", b"print('hello')\n", "text/plain")},
            data={"actor_id": "anonymous"},
        )
        self.assertEqual(upload_response.status_code, 200)
        upload_payload = upload_response.json()
        upload = upload_payload.get("upload", {})
        upload_id = str(upload.get("upload_id", ""))
        self.assertTrue(upload_id)
        self.assertEqual(upload.get("kind"), "file")
        self.assertEqual(upload.get("included_files"), 1)

        list_response = client.get("/api/uploads?actor_id=anonymous")
        self.assertEqual(list_response.status_code, 200)
        list_payload = list_response.json()
        self.assertEqual(list_payload.get("count"), 1)
        self.assertEqual(list_payload.get("uploads", [])[0].get("upload_id"), upload_id)

        delete_response = client.delete(f"/api/uploads/{upload_id}?actor_id=anonymous")
        self.assertEqual(delete_response.status_code, 200)
        self.assertEqual(delete_response.json().get("status"), "deleted")

    def test_upload_zip_uses_text_members_for_chat_attachment(self) -> None:
        archive_buffer = io.BytesIO()
        with zipfile.ZipFile(archive_buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("src/main.py", "def add(a, b):\n    return a + b\n")
            archive.writestr("README.md", "# Sample\n")
        archive_bytes = archive_buffer.getvalue()

        async def fake_stream_chat(
            _self: object,
            *,
            model: str,
            messages: list[dict[str, str]],
            temperature: float,
            num_ctx: int,
            think: bool | str | None = None,
        ):
            _ = (model, temperature, num_ctx, think)
            final_user = messages[-1]["content"]
            self.assertIn("Uploaded file/ZIP context for review:", final_user)
            self.assertIn("src/main.py", final_user)
            self.assertIn("return a + b", final_user)
            yield "reviewed"

        client = TestClient(app)
        upload_response = client.post(
            "/api/uploads",
            files={"file": ("sample.zip", archive_bytes, "application/zip")},
            data={"actor_id": "anonymous"},
        )
        self.assertEqual(upload_response.status_code, 200)
        upload_id = upload_response.json()["upload"]["upload_id"]

        with mock.patch("local_model_pro.server.OllamaClient.stream_chat", new=fake_stream_chat):
            with client.websocket_connect("/ws/chat") as ws:
                self._consume_until_ready(ws)
                ws.send_json({"type": "hello", "model": "qwen2.5:7b", "actor_id": "anonymous"})
                self._consume_until_ready(ws)
                ws.send_json(
                    {
                        "type": "chat",
                        "prompt": "Review my code",
                        "attachments": [upload_id],
                    }
                )
                seen_done = False
                while True:
                    message = ws.receive_json()
                    if message.get("type") == "done":
                        seen_done = True
                        break
                self.assertTrue(seen_done)

    def test_api_models(self) -> None:
        async def fake_list_models(_self: object) -> list[dict[str, object]]:
            return [{"name": "qwen2.5:7b", "size": 1234}]

        with mock.patch("local_model_pro.server.OllamaClient.list_models", new=fake_list_models):
            client = TestClient(app)
            response = client.get("/api/models")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["models"], [{"name": "qwen2.5:7b", "size": 1234}])

    def test_model_stores_endpoint(self) -> None:
        client = TestClient(app)
        response = client.get("/api/model-stores")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        store_ids = {str(item.get("id", "")) for item in payload.get("stores", [])}
        self.assertIn("ollama_library", store_ids)
        self.assertIn("huggingface", store_ids)

    def test_pull_model_starts_job_and_status(self) -> None:
        pull_jobs.clear()

        with mock.patch("local_model_pro.server._start_pull_model_job") as start_job:
            client = TestClient(app)
            create_response = client.post("/api/models/pull", json={"model": "qwen2.5:7b"})

        self.assertEqual(create_response.status_code, 200)
        create_payload = create_response.json()
        self.assertEqual(create_payload["status"], "queued")
        self.assertTrue(create_payload["job_id"])
        start_job.assert_called_once()

        status_response = TestClient(app).get(f"/api/models/pull/{create_payload['job_id']}")
        self.assertEqual(status_response.status_code, 200)
        status_payload = status_response.json()
        self.assertEqual(status_payload["status"], "queued")
        self.assertEqual(status_payload["model"], "qwen2.5:7b")

    def test_delete_model_endpoint(self) -> None:
        async def fake_delete_model(model: str) -> dict[str, object]:
            self.assertEqual(model, "qwen2.5:7b")
            return {"status": "success"}

        with mock.patch("local_model_pro.server._delete_model_on_ollama", new=fake_delete_model):
            client = TestClient(app)
            response = client.post("/api/models/delete", json={"model": "qwen2.5:7b"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["model"], "qwen2.5:7b")
        self.assertEqual(payload["result"]["status"], "success")

    def test_store_api_search_endpoint(self) -> None:
        class FakeResponse:
            status_code = 200
            text = "ok"

            @staticmethod
            def json() -> list[dict[str, object]]:
                return [
                    {
                        "id": "Qwen/Qwen2.5-7B-Instruct",
                        "downloads": 123,
                        "likes": 10,
                        "lastModified": "2025-01-01T00:00:00.000Z",
                    }
                ]

        async def fake_get(_self: object, _url: str) -> FakeResponse:
            return FakeResponse()

        with mock.patch("httpx.AsyncClient.get", new=fake_get):
            client = TestClient(app)
            response = client.get("/api/model-stores/search?store_id=huggingface&q=qwen")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["store_id"], "huggingface")
        self.assertEqual(payload["count"], 1)
        self.assertIn("Qwen/Qwen2.5-7B-Instruct", payload["results"][0]["name"])

    def test_websocket_chat_stream(self) -> None:
        async def fake_stream_chat(
            _self: object,
            *,
            model: str,
            messages: list[dict[str, str]],
            temperature: float,
            num_ctx: int,
            think: bool | str | None = None,
        ):
            _ = (temperature, num_ctx, think)
            self.assertEqual(model, "qwen2.5:7b")
            self.assertEqual(messages[-1], {"role": "user", "content": "hello"})
            for chunk in ["hi", " there"]:
                yield chunk

        with mock.patch("local_model_pro.server.OllamaClient.stream_chat", new=fake_stream_chat):
            client = TestClient(app)
            with client.websocket_connect("/ws/chat") as ws:
                self._consume_until_ready(ws)

                ws.send_json({"type": "hello", "model": "qwen2.5:7b"})
                self._consume_until_ready(ws)
                events = self._run_turn(ws, "hello")

        event_types = [str(item.get("type")) for item in events]
        self.assertEqual(event_types[0], "start")
        self.assertIn("token", event_types)
        self.assertEqual(event_types[-1], "done")
        tokens = [str(item.get("text", "")) for item in events if item.get("type") == "token"]
        self.assertEqual(tokens, ["hi", " there"])

    def test_websocket_ls_command(self) -> None:
        tmp_path = Path()
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=settings.workspace_root,
            prefix="lmp_test_",
            suffix=".txt",
            delete=False,
        ) as handle:
            handle.write("hello")
            tmp_path = Path(handle.name)
            filename = handle.name.rsplit("/", 1)[-1]

        try:
            client = TestClient(app)
            with client.websocket_connect("/ws/chat") as ws:
                self._consume_until_ready(ws)
                events = self._run_turn(ws, "/ls .")
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

        tokens = [str(item.get("text", "")) for item in events if item.get("type") == "token"]
        self.assertTrue(tokens)
        self.assertIn(filename, "".join(tokens))

    def test_websocket_run_preview_then_execute(self) -> None:
        client = TestClient(app)
        with client.websocket_connect("/ws/chat") as ws:
            self._consume_until_ready(ws)
            preview_events = self._run_turn(ws, "/run echo hello")
            execution_events = self._run_turn(ws, "/run! echo hello")

        preview_text = "".join(
            str(item.get("text", "")) for item in preview_events if item.get("type") == "token"
        )
        execution_text = "".join(
            str(item.get("text", "")) for item in execution_events if item.get("type") == "token"
        )
        self.assertIn("Preview:", preview_text)
        self.assertIn("$ echo hello", execution_text)
        self.assertIn("exit_code: 0", execution_text)
        self.assertIn("stdout:", execution_text)

    def test_websocket_summary_command(self) -> None:
        async def fake_summary(
            _self: object,
            *,
            model: str,
            messages: list[dict[str, str]],
            temperature: float,
            num_ctx: int,
        ) -> str:
            _ = (model, messages, temperature, num_ctx)
            return "summary output"

        with mock.patch("local_model_pro.server.OllamaClient.chat", new=fake_summary):
            client = TestClient(app)
            with client.websocket_connect("/ws/chat") as ws:
                self._consume_until_ready(ws)
                events = self._run_turn(ws, "/summary .")

        tokens = [str(item.get("text", "")) for item in events if item.get("type") == "token"]
        self.assertTrue(tokens)
        self.assertIn("summary output", "".join(tokens))

    def test_websocket_path_traversal_is_blocked(self) -> None:
        client = TestClient(app)
        with client.websocket_connect("/ws/chat") as ws:
            self._consume_until_ready(ws)
            events = self._run_turn(ws, "/read ../")

        text = "".join(str(item.get("text", "")) for item in events if item.get("type") == "token")
        self.assertIn("Tool error:", text)
        self.assertIn("outside the configured workspace root", text)

    def test_reasoning_mode_sets_think_parameter(self) -> None:
        think_values: list[bool | str | None] = []

        async def fake_stream_chat(
            _self: object,
            *,
            model: str,
            messages: list[dict[str, str]],
            temperature: float,
            num_ctx: int,
            think: bool | str | None = None,
        ):
            _ = (model, messages, temperature, num_ctx)
            think_values.append(think)
            yield "ok"

        with mock.patch("local_model_pro.server.OllamaClient.stream_chat", new=fake_stream_chat):
            client = TestClient(app)
            with client.websocket_connect("/ws/chat") as ws:
                self._consume_until_ready(ws)

                ws.send_json({"type": "hello", "model": "qwen2.5:7b"})
                self._consume_until_ready(ws)
                self._run_turn(ws, "normal chat")

                self._run_turn(ws, "/tools")

                ws.send_json({"type": "chat", "prompt": "hidden", "reasoning_mode": "hidden"})
                while True:
                    msg = ws.receive_json()
                    if msg.get("type") == "done":
                        break

                ws.send_json({"type": "hello", "model": "gpt-oss:20b"})
                self._consume_until_ready(ws)
                ws.send_json({"type": "chat", "prompt": "full", "reasoning_mode": "full"})
                while True:
                    msg = ws.receive_json()
                    if msg.get("type") == "done":
                        break

        # First non-tool chat defaults to summary -> think enabled.
        self.assertEqual(think_values[0], True)
        # Hidden explicitly disables think for non gpt-oss models.
        self.assertEqual(think_values[1], False)
        # Full on gpt-oss maps to high effort.
        self.assertEqual(think_values[2], "high")

    def test_profile_preferences_patch_and_reset(self) -> None:
        client = TestClient(app)

        first = client.get("/api/v1/profile/preferences?actor_id=tristan")
        self.assertEqual(first.status_code, 200)
        first_payload = first.json()
        self.assertEqual(first_payload["version"], 1)
        self.assertEqual(first_payload["actor_id"], "tristan")

        patch = client.patch(
            "/api/v1/profile/preferences",
            json={
                "actor_id": "tristan",
                "base_version": first_payload["version"],
                "patch": {
                    "appearance": {"font_scale": 1.2},
                    "chat": {"reasoning_mode_default": "full"},
                },
            },
        )
        self.assertEqual(patch.status_code, 200)
        patch_payload = patch.json()
        self.assertEqual(patch_payload["version"], 2)
        self.assertIn("appearance.font_scale", patch_payload["updated_keys"])
        self.assertIn("chat.reasoning_mode_default", patch_payload["updated_keys"])

        reset = client.post(
            "/api/v1/profile/preferences/reset",
            json={"actor_id": "tristan", "scope": "chat"},
        )
        self.assertEqual(reset.status_code, 200)
        reset_payload = reset.json()
        self.assertEqual(reset_payload["preferences"]["chat"]["reasoning_mode_default"], "summary")

    def test_admin_user_crud_and_events(self) -> None:
        client = TestClient(app)

        create = client.post(
            "/api/v1/admin/users",
            json={"actor_id": "ops", "username": "qa-user", "role": "operator"},
        )
        self.assertEqual(create.status_code, 200)
        user_id = create.json()["user"]["id"]

        listing = client.get("/api/v1/admin/users")
        self.assertEqual(listing.status_code, 200)
        usernames = [item["username"] for item in listing.json()["users"]]
        self.assertIn("qa-user", usernames)

        update = client.patch(
            f"/api/v1/admin/users/{user_id}",
            json={"actor_id": "ops", "status": "disabled"},
        )
        self.assertEqual(update.status_code, 200)
        self.assertEqual(update.json()["user"]["status"], "disabled")

        events = client.get("/api/v1/admin/events?limit=20")
        self.assertEqual(events.status_code, 200)
        event_types = [item["event_type"] for item in events.json()["events"]]
        self.assertIn("admin.user.create", event_types)
        self.assertIn("admin.user.update", event_types)

    def test_admin_platform_policy_gates_model_mutations_and_tools(self) -> None:
        client = TestClient(app)
        apply_policy = client.patch(
            "/api/v1/admin/platform",
            json={
                "actor_id": "sys",
                "patch": {
                    "allow_model_pull": False,
                    "allow_model_delete": False,
                    "allow_terminal_tools": False,
                    "allow_shell_execute": False,
                },
            },
        )
        self.assertEqual(apply_policy.status_code, 200)

        with mock.patch("local_model_pro.server._start_pull_model_job") as start_job:
            pull = client.post("/api/models/pull", json={"model": "qwen2.5:7b"})
        self.assertEqual(pull.status_code, 403)
        start_job.assert_not_called()

        with mock.patch("local_model_pro.server._delete_model_on_ollama") as delete_job:
            delete = client.post("/api/models/delete", json={"model": "qwen2.5:7b"})
        self.assertEqual(delete.status_code, 403)
        delete_job.assert_not_called()

        with client.websocket_connect("/ws/chat") as ws:
            self._consume_until_ready(ws)
            events = self._run_turn(ws, "/run! echo test")
        text = "".join(str(item.get("text", "")) for item in events if item.get("type") == "token")
        self.assertIn("Tool error:", text)
        self.assertIn("disabled", text)

    def test_profile_sessions_models_defaults_apply_to_generation(self) -> None:
        client = TestClient(app)
        patch = client.patch(
            "/api/v1/profile/preferences",
            json={
                "actor_id": "anonymous",
                "patch": {
                    "sessions_models": {
                        "default_num_ctx": 8192,
                        "default_temperature": 0.55,
                        "startup_view": "models",
                        "tab_restore_policy": "none",
                        "auto_focus_terminal": True,
                    }
                },
            },
        )
        self.assertEqual(patch.status_code, 200)

        seen: list[tuple[float, int]] = []

        async def fake_stream_chat(
            _self: object,
            *,
            model: str,
            messages: list[dict[str, str]],
            temperature: float,
            num_ctx: int,
            think: bool | str | None = None,
        ):
            _ = (model, messages, think)
            seen.append((temperature, num_ctx))
            yield "ok"

        with mock.patch("local_model_pro.server.OllamaClient.stream_chat", new=fake_stream_chat):
            with client.websocket_connect("/ws/chat") as ws:
                self._consume_until_ready(ws)
                self._run_turn(ws, "hello")

        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][0], 0.55)
        self.assertEqual(seen[0][1], 8192)


if __name__ == "__main__":
    unittest.main()
