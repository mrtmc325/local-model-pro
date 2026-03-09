from __future__ import annotations

import asyncio
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from local_model_pro.admin_profile_store import AdminProfileStore
from local_model_pro.devflow import DevflowJob, ROLE_ORDER, resolve_role_models, write_devflow_artifacts
from local_model_pro.server import (
    _job_payload,
    _run_devflow_job,
    _upsert_devflow_job,
    app,
    devflow_config,
    devflow_jobs,
    settings,
)


class DevflowModuleTests(unittest.TestCase):
    def test_resolve_role_models_is_deterministic(self) -> None:
        mapping = resolve_role_models(
            role_models={"intent_reasoner": "model-x", "doc_release": "model-z"},
            fallback_pool=["pool-a", "pool-b"],
            fallback_selected_model="selected-main",
        )

        self.assertEqual(mapping["intent_reasoner"], "model-x")
        self.assertEqual(mapping["doc_release"], "model-z")
        self.assertEqual(set(mapping.keys()), set(ROLE_ORDER))
        # Deterministic cycle for missing slots: pool-a -> pool-b -> selected-main -> repeat.
        self.assertEqual(mapping["intent_knowledge"], "pool-a")
        self.assertEqual(mapping["intent_feasibility"], "pool-b")
        self.assertEqual(mapping["code_model_1"], "selected-main")
        self.assertEqual(mapping["code_model_2"], "pool-a")

    def test_write_artifacts_creates_exact_zip_contents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            job = DevflowJob(
                job_id="job-artifact-test",
                actor_id="actor",
                prompt="build feature",
                selected_model="qwen2.5:7b",
                role_models={role: "qwen2.5:7b" for role in ROLE_ORDER},
            )
            artifacts = write_devflow_artifacts(
                base_dir=Path(tmp_dir),
                job=job,
                code_pack="# code\n",
                documentation="# docs\n",
            )

            zip_path = Path(artifacts["zip"])
            self.assertTrue(zip_path.exists())
            with zipfile.ZipFile(zip_path, "r") as archive:
                names = sorted(archive.namelist())
            self.assertEqual(names, ["code_pack.md", "documentation.md"])


class DevflowRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self._orig_artifact_dir = devflow_config.artifact_dir
        self._orig_retry_count = devflow_config.retry_count
        devflow_config.artifact_dir = Path(self._tmp_dir.name)
        devflow_config.retry_count = 0
        devflow_jobs.clear()

    async def asyncTearDown(self) -> None:
        devflow_jobs.clear()
        devflow_config.artifact_dir = self._orig_artifact_dir
        devflow_config.retry_count = self._orig_retry_count
        self._tmp_dir.cleanup()

    async def test_run_devflow_job_enforces_stage_order_and_round3_chain(self) -> None:
        class FakeOllama:
            def __init__(self) -> None:
                self.calls: list[dict[str, str]] = []

            async def chat(
                self,
                *,
                model: str,
                messages: list[dict[str, str]],
                temperature: float,
                num_ctx: int,
            ) -> str:
                _ = (temperature, num_ctx)
                prompt = str(messages[-1]["content"])
                output = f"OUT[{len(self.calls) + 1}]::{model}"
                self.calls.append({"model": model, "prompt": prompt, "output": output})
                return output

        role_models = {
            "intent_reasoner": "intent-r",
            "intent_knowledge": "intent-k",
            "intent_feasibility": "intent-f",
            "code_model_1": "code-1",
            "code_model_2": "code-2",
            "code_model_3": "code-3",
            "doc_inline": "doc-i",
            "doc_git": "doc-g",
            "doc_release": "doc-r",
        }
        job = DevflowJob(
            job_id="job-runner-test",
            actor_id="actor",
            prompt="Build a simple REST endpoint with tests.",
            selected_model="fallback-model",
            role_models=role_models,
        )

        events: list[dict[str, object]] = []

        async def emit(payload: dict[str, object]) -> None:
            events.append(payload)

        ollama = FakeOllama()
        await _run_devflow_job(job=job, ollama=ollama, emit_event=emit)

        self.assertEqual(job.status, "completed")
        self.assertEqual(job.stage, "completed")
        self.assertEqual(job.percent, 100)
        self.assertTrue(Path(job.artifacts["zip"]).exists())

        stage_results = [e for e in events if e.get("type") == "devflow_stage_result"]
        self.assertEqual(len(stage_results), 15)
        expected_model_sequence = [
            "intent-r",
            "intent-k",
            "intent-f",
            "code-1",
            "code-2",
            "code-3",
            "code-1",
            "code-2",
            "code-3",
            "code-1",
            "code-2",
            "code-3",
            "doc-i",
            "doc-g",
            "doc-r",
        ]
        self.assertEqual(
            [str(e.get("role")) for e in stage_results],
            [
                "intent_reasoner",
                "intent_knowledge",
                "intent_feasibility",
                "code_model_1",
                "code_model_2",
                "code_model_3",
                "code_model_1",
                "code_model_2",
                "code_model_3",
                "code_model_1",
                "code_model_2",
                "code_model_3",
                "doc_inline",
                "doc_git",
                "doc_release",
            ],
        )
        self.assertEqual(
            [str(call.get("model")) for call in ollama.calls],
            expected_model_sequence,
        )
        self.assertEqual(
            [str(e.get("model")) for e in stage_results],
            expected_model_sequence,
        )
        self.assertTrue(
            all(int(e.get("attempt_index", 0)) >= 1 for e in stage_results),
        )
        self.assertTrue(
            all(str(e.get("attempt_path", "")) in {"slot", "escalated", "fallback"} for e in stage_results),
        )
        role_progress_events = [
            e for e in events if e.get("type") == "devflow_progress" and e.get("role")
        ]
        self.assertTrue(
            any("model=intent-r" in str(e.get("message", "")) for e in role_progress_events)
        )

        prompt_step1 = next(c for c in ollama.calls if "Round 3 chain step 1" in c["prompt"])
        prompt_step2 = next(c for c in ollama.calls if "Round 3 chain step 2" in c["prompt"])
        prompt_step3 = next(c for c in ollama.calls if "Round 3 chain step 3" in c["prompt"])
        self.assertIn(prompt_step1["output"], prompt_step2["prompt"])
        self.assertIn(prompt_step1["output"], prompt_step3["prompt"])
        self.assertIn(prompt_step2["output"], prompt_step3["prompt"])

        with zipfile.ZipFile(job.artifacts["zip"], "r") as archive:
            self.assertEqual(sorted(archive.namelist()), ["code_pack.md", "documentation.md"])

    async def test_run_devflow_job_falls_back_when_doc_role_fails(self) -> None:
        class FakeOllama:
            def __init__(self) -> None:
                self.calls: list[dict[str, str]] = []

            async def chat(
                self,
                *,
                model: str,
                messages: list[dict[str, str]],
                temperature: float,
                num_ctx: int,
            ) -> str:
                _ = (temperature, num_ctx, model)
                prompt = str(messages[-1]["content"])
                self.calls.append({"prompt": prompt})
                if "Generate deterministic git notes for the generated code." in prompt:
                    raise TimeoutError("doc git timeout")
                return f"ok-{len(self.calls)}"

        job = DevflowJob(
            job_id="job-runner-doc-fallback",
            actor_id="actor",
            prompt="Build a simple API server.",
            selected_model="qwen3:8b",
            role_models={role: "qwen3:8b" for role in ROLE_ORDER},
        )
        events: list[dict[str, object]] = []

        async def emit(payload: dict[str, object]) -> None:
            events.append(payload)

        ollama = FakeOllama()
        await _run_devflow_job(job=job, ollama=ollama, emit_event=emit)

        self.assertEqual(job.status, "completed")
        self.assertIn("doc_git", job.outputs)
        self.assertEqual(job.outputs.get("doc_git_source"), "fallback")
        self.assertTrue(str(job.outputs.get("doc_git_error", "")).strip())
        self.assertIn("Commit Title:", job.outputs["doc_git"])
        self.assertIn("Commit Body:", job.outputs["doc_git"])
        fallback_events = [
            e
            for e in events
            if e.get("type") == "devflow_stage_result"
            and e.get("role") == "doc_git"
            and e.get("status") == "fallback"
        ]
        self.assertTrue(fallback_events)
        self.assertEqual(fallback_events[-1].get("attempt_path"), "fallback")
        done_events = [e for e in events if e.get("type") == "devflow_done"]
        self.assertTrue(done_events)

    async def test_run_devflow_job_inline_role_success_uses_model_output_source(self) -> None:
        class FakeOllama:
            async def chat(
                self,
                *,
                model: str,
                messages: list[dict[str, str]],
                temperature: float,
                num_ctx: int,
            ) -> str:
                _ = (model, temperature, num_ctx)
                prompt = str(messages[-1]["content"])
                if "Round 3 chain step 3" in prompt:
                    return "```python\ndef generated():\n    return {'ok': True}\n```"
                if "You are documenting existing code for maintainers." in prompt:
                    return "```python\ndef root():\n    return {'ok': True}\n```"
                if "Generate deterministic git notes for the generated code." in prompt:
                    return (
                        "Commit Title: add fastapi server\n\n"
                        "Commit Body:\n- Add server entrypoint\n\n"
                        "Validation Checklist:\n- Run tests\n\n"
                        "Risk Notes:\n- Review generated code"
                    )
                return "ok"

        job = DevflowJob(
            job_id="job-runner-inline-role-success",
            actor_id="actor",
            prompt="Create a tiny FastAPI service.",
            selected_model="qwen3:8b",
            role_models={role: "qwen3:8b" for role in ROLE_ORDER},
        )
        events: list[dict[str, object]] = []

        async def emit(payload: dict[str, object]) -> None:
            events.append(payload)

        await _run_devflow_job(job=job, ollama=FakeOllama(), emit_event=emit)

        self.assertEqual(job.status, "completed")
        self.assertEqual(job.outputs.get("doc_inline_source"), "role")
        inline_code = str(job.outputs.get("doc_inline_code", ""))
        self.assertIn("```python", inline_code)
        self.assertIn("def root()", inline_code)
        self.assertNotIn("Inline documentation fallback", inline_code)
        self.assertNotIn("inline documentation for behavior and intent", inline_code.lower())

    async def test_run_devflow_job_doc_inline_escalates_to_code_model_3(self) -> None:
        class FakeOllama:
            async def chat(
                self,
                *,
                model: str,
                messages: list[dict[str, str]],
                temperature: float,
                num_ctx: int,
            ) -> str:
                _ = (temperature, num_ctx)
                prompt = str(messages[-1]["content"])
                if "You are documenting existing code for maintainers." in prompt:
                    if model == "doc-i":
                        raise TimeoutError("doc inline slot timeout")
                    if model == "code-3":
                        return "```python\ndef root():\n    return {'ok': True}\n```"
                if "Generate deterministic git notes for the generated code." in prompt:
                    return (
                        "Commit Title: add generated implementation\n\n"
                        "Commit Body:\n- Add implementation\n\n"
                        "Validation Checklist:\n- Run tests\n\n"
                        "Risk Notes:\n- Review output"
                    )
                return "ok"

        role_models = {
            "intent_reasoner": "intent-r",
            "intent_knowledge": "intent-k",
            "intent_feasibility": "intent-f",
            "code_model_1": "code-1",
            "code_model_2": "code-2",
            "code_model_3": "code-3",
            "doc_inline": "doc-i",
            "doc_git": "doc-g",
            "doc_release": "doc-r",
        }
        job = DevflowJob(
            job_id="job-runner-inline-escalated",
            actor_id="actor",
            prompt="Create a tiny FastAPI service.",
            selected_model="fallback-model",
            role_models=role_models,
        )
        events: list[dict[str, object]] = []

        async def emit(payload: dict[str, object]) -> None:
            events.append(payload)

        await _run_devflow_job(job=job, ollama=FakeOllama(), emit_event=emit)

        self.assertEqual(job.status, "completed")
        self.assertEqual(job.outputs.get("doc_inline_source"), "escalated")
        self.assertTrue(str(job.outputs.get("doc_inline_error", "")).strip())

        doc_inline_stage_events = [
            e
            for e in events
            if e.get("type") == "devflow_stage_result"
            and e.get("role") == "doc_inline"
            and e.get("status") == "completed"
        ]
        self.assertTrue(doc_inline_stage_events)
        self.assertEqual(doc_inline_stage_events[-1].get("model"), "code-3")
        self.assertEqual(doc_inline_stage_events[-1].get("attempt_path"), "escalated")
        self.assertEqual(doc_inline_stage_events[-1].get("attempt_index"), 2)

    async def test_run_devflow_job_inline_fallback_generates_commented_code_block(self) -> None:
        class FakeOllama:
            async def chat(
                self,
                *,
                model: str,
                messages: list[dict[str, str]],
                temperature: float,
                num_ctx: int,
            ) -> str:
                _ = (model, temperature, num_ctx)
                prompt = str(messages[-1]["content"])
                if "return ONLY one fenced code block" in prompt:
                    raise TimeoutError("inline doc timeout")
                if "Round 3 chain step 3" in prompt:
                    return (
                        "```python\n"
                        "from fastapi import FastAPI\n\n"
                        "app = FastAPI()\n\n"
                        "@app.get('/')\n"
                        "# root: inline documentation for behavior and intent.\n"
                        "def root():\n"
                        "    return {'ok': True}\n"
                        "```"
                    )
                return "ok"

        job = DevflowJob(
            job_id="job-runner-inline-fallback",
            actor_id="actor",
            prompt="Create a tiny FastAPI service.",
            selected_model="qwen3:8b",
            role_models={role: "qwen3:8b" for role in ROLE_ORDER},
        )
        events: list[dict[str, object]] = []

        async def emit(payload: dict[str, object]) -> None:
            events.append(payload)

        await _run_devflow_job(job=job, ollama=FakeOllama(), emit_event=emit)

        self.assertEqual(job.status, "completed")
        inline_code = str(job.outputs.get("doc_inline_code", ""))
        self.assertIn("```python", inline_code)
        self.assertIn("# root:", inline_code)
        self.assertIn("Inline documentation fallback", inline_code)
        self.assertEqual(inline_code.count("# root:"), 1)
        self.assertNotIn("inline documentation for behavior and intent", inline_code.lower())
        self.assertIn('"""Handle GET / requests for this API endpoint.', inline_code)


class DevflowWebSocketTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        temp_state_path = Path(self._tmp_dir.name) / "admin_profile_state.json"
        temp_store = AdminProfileStore(
            state_path=temp_state_path,
            default_actor_id=settings.default_actor_id,
        )
        self._store_patcher = mock.patch("local_model_pro.server.admin_profile_store", new=temp_store)
        self._store_patcher.start()

        self._orig_artifact_dir = devflow_config.artifact_dir
        devflow_config.artifact_dir = Path(self._tmp_dir.name) / "runs"
        devflow_jobs.clear()

    def tearDown(self) -> None:
        devflow_jobs.clear()
        devflow_config.artifact_dir = self._orig_artifact_dir
        self._store_patcher.stop()
        self._tmp_dir.cleanup()

    @staticmethod
    def _consume_until_ready(ws: object) -> None:
        while True:
            message = ws.receive_json()
            if message.get("type") == "ready":
                return

    def test_websocket_devflow_start_and_http_download(self) -> None:
        async def fake_run_devflow_job(*, job: DevflowJob, ollama: object, emit_event: object) -> None:
            _ = ollama
            job.status = "running"
            job.stage = "intent"
            job.percent = 10
            job.message = "running"
            await emit_event({"type": "devflow_progress", **_job_payload(job), "role": "intent_reasoner"})

            artifacts = write_devflow_artifacts(
                base_dir=devflow_config.artifact_dir,
                job=job,
                code_pack="# code\n",
                documentation="# docs\n",
            )
            job.artifacts = artifacts
            job.status = "completed"
            job.stage = "completed"
            job.percent = 100
            job.message = "done"
            await _upsert_devflow_job(job)
            await emit_event(
                {
                    "type": "devflow_done",
                    **_job_payload(job),
                    "download_url": f"/api/devflow/jobs/{job.job_id}/download",
                }
            )

        with mock.patch("local_model_pro.server._run_devflow_job", new=fake_run_devflow_job):
            client = TestClient(app)
            with client.websocket_connect("/ws/chat") as ws:
                self._consume_until_ready(ws)

                ws.send_json({"type": "devflow_start", "prompt": "Create a Flask app"})

                seen_types: list[str] = []
                done_payload: dict[str, object] | None = None
                while True:
                    message = ws.receive_json()
                    msg_type = str(message.get("type"))
                    seen_types.append(msg_type)
                    if msg_type == "devflow_done":
                        done_payload = message
                        break

            self.assertIsNotNone(done_payload)
            self.assertEqual(seen_types[0], "devflow_started")
            self.assertIn("devflow_progress", seen_types)
            self.assertIn("devflow_done", seen_types)

            job_id = str(done_payload["job_id"])
            status_response = client.get(f"/api/devflow/jobs/{job_id}")
            self.assertEqual(status_response.status_code, 200)
            status_payload = status_response.json()
            self.assertEqual(status_payload["status"], "completed")
            self.assertTrue(status_payload["download_url"].endswith("/download"))

            download_response = client.get(f"/api/devflow/jobs/{job_id}/download")
            self.assertEqual(download_response.status_code, 200)
            with tempfile.NamedTemporaryFile(suffix=".zip") as handle:
                handle.write(download_response.content)
                handle.flush()
                with zipfile.ZipFile(handle.name, "r") as archive:
                    self.assertEqual(
                        sorted(archive.namelist()),
                        ["code_pack.md", "documentation.md"],
                    )

    def test_websocket_devflow_cancel_sets_flag(self) -> None:
        async def fake_run_devflow_job(*, job: DevflowJob, ollama: object, emit_event: object) -> None:
            _ = ollama
            await emit_event({"type": "devflow_progress", **_job_payload(job), "role": "intent_reasoner"})
            for _ in range(25):
                if job.cancel_requested:
                    job.status = "failed"
                    job.stage = "failed"
                    job.message = "cancelled"
                    job.error = "Cancelled by user."
                    await _upsert_devflow_job(job)
                    await emit_event({"type": "devflow_error", **_job_payload(job)})
                    return
                await asyncio.sleep(0.01)

        with mock.patch("local_model_pro.server._run_devflow_job", new=fake_run_devflow_job):
            client = TestClient(app)
            with client.websocket_connect("/ws/chat") as ws:
                self._consume_until_ready(ws)
                ws.send_json({"type": "devflow_start", "prompt": "Build a parser"})

                started = ws.receive_json()
                self.assertEqual(started.get("type"), "devflow_started")
                job_id = str(started.get("job_id"))

                # Consume one progress event from the fake runner.
                ws.receive_json()

                ws.send_json({"type": "devflow_cancel", "job_id": job_id})
                cancel_ack = ws.receive_json()
                self.assertEqual(cancel_ack.get("type"), "devflow_progress")
                self.assertEqual(cancel_ack.get("cancel_requested"), True)


if __name__ == "__main__":
    unittest.main()
