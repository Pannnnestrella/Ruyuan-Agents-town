import importlib
import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from agents_town.common.config import (
    find_secret_fields,
    redact_text,
    redact_url,
    redact_value,
    resolve_credentials,
    runtime_api_keys,
    sanitize_for_persistence,
    validate_service_base_url,
)
from agents_town.common.paths import RuntimePaths
from agents_town.common.model import create_llm_model
from agents_town.legacy.launcher.commands import scoped_subprocess_environment
from agents_town.legacy.validation import cli as validation_cli


class CredentialResolutionTests(unittest.TestCase):
    def test_environment_precedes_legacy_config(self):
        config = {
            "api_keys": {"GEMINI_API_KEY": "legacy"},
            "services": {"gemini": {"api_key": "service"}},
        }
        credentials = resolve_credentials(
            "gemini", env={"GEMINI_API_KEY": "environment"}, config=config
        )
        self.assertEqual(credentials, {"api_key": "environment"})

    def test_gemini_never_borrows_openai_key(self):
        credentials = resolve_credentials(
            "gemini", env={"OPENAI_API_KEY": "must-not-cross"}, config={}
        )
        self.assertEqual(credentials, {"api_key": ""})

    def test_runtime_api_keys_preserve_legacy_factory_names(self):
        keys = runtime_api_keys(
            env={"OPENAI_API_KEY": "open", "ZHIPUAI_API_KEY": "zhipu"},
            config={},
        )
        self.assertEqual(keys["OPENAI_API_KEY"], "open")
        self.assertEqual(keys["ZHIPUAI_API_KEY"], "zhipu")

    def test_ollama_provider_is_explicit_and_needs_no_key(self):
        model = create_llm_model(
            provider="ollama",
            base_url="http://127.0.0.1:11434/v1",
            model="qwen2.5:7b-instruct",
            embedding_model="embeddinggemma",
            keys={},
        )
        self.assertEqual(type(model).__name__, "OllamaLLMModel")


class SecretSanitisingTests(unittest.TestCase):
    def test_persistence_copy_removes_only_authentication_fields(self):
        value = {
            "api_keys": {"OPENAI_API_KEY": "secret"},
            "agent": {
                "api_key": "secret-2",
                "token_usage": {"prompt_tokens": 3},
                "name": "傅融",
            },
        }
        clean = sanitize_for_persistence(value)
        self.assertNotIn("api_keys", clean)
        self.assertNotIn("api_key", clean["agent"])
        self.assertEqual(clean["agent"]["token_usage"]["prompt_tokens"], 3)
        self.assertEqual(value["api_keys"]["OPENAI_API_KEY"], "secret")

    def test_secret_scan_returns_paths_not_values(self):
        value = {"agent_base": {"associate": {"embedding": {"api_key": "sentinel"}}}}
        fields = find_secret_fields(value)
        self.assertEqual(fields, ["$.agent_base.associate.embedding.api_key"])
        self.assertNotIn("sentinel", json.dumps(fields))

    def test_environment_style_secret_fields_are_removed(self):
        value = {
            "LIBLIBAI_ACCESS_KEY": "access",
            "SPARK_API_SECRET": "secret",
            "token_usage": {"total_tokens": 8},
        }
        clean = sanitize_for_persistence(value)
        self.assertNotIn("LIBLIBAI_ACCESS_KEY", clean)
        self.assertNotIn("SPARK_API_SECRET", clean)
        self.assertEqual(clean["token_usage"]["total_tokens"], 8)

    def test_recursive_redaction_preserves_shape_without_secret_values(self):
        value = {
            "Authorization": "Bearer sentinel",
            "nested": [
                "https://example.test/run?AccessKey=abc&keep=yes",
                {"api_key": "private"},
            ],
        }
        safe = redact_value(value)
        rendered = json.dumps(safe)
        self.assertNotIn("sentinel", rendered)
        self.assertNotIn("abc", rendered)
        self.assertNotIn("private", rendered)
        self.assertIn("keep=yes", rendered)

    def test_url_and_exception_redaction(self):
        url = "https://example.test/run?AccessKey=abc&Signature=xyz&keep=yes"
        safe = redact_url(url)
        self.assertNotIn("abc", safe)
        self.assertNotIn("xyz", safe)
        self.assertIn("keep=yes", safe)
        message = redact_text("Authorization: Bearer top-secret")
        self.assertNotIn("top-secret", message)

    def test_cloud_http_is_rejected_but_loopback_can_be_allowed(self):
        with self.assertRaises(ValueError):
            validate_service_base_url("http://api.example.test")
        self.assertEqual(
            validate_service_base_url(
                "http://127.0.0.1:11434", allow_loopback_http=True
            ),
            "http://127.0.0.1:11434",
        )


class LauncherEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.env = {
            "PATH": "example",
            "OPENAI_API_KEY": "openai-secret",
            "LIBLIBAI_ACCESS_KEY": "lib-access",
            "LIBLIBAI_SECRET_KEY": "lib-secret",
            "SUNO_API_KEY": "suno-secret",
            "GEMINI_API_KEY": "gemini-secret",
        }

    def test_replay_receives_no_service_credentials(self):
        child = scoped_subprocess_environment("replay", base_env=self.env, config={})
        self.assertEqual(child, {"PATH": "example"})

    def test_liblib_receives_only_liblib_credentials(self):
        child = scoped_subprocess_environment("liblib", base_env=self.env, config={})
        self.assertEqual(child["LIBLIBAI_ACCESS_KEY"], "lib-access")
        self.assertEqual(child["LIBLIBAI_SECRET_KEY"], "lib-secret")
        self.assertNotIn("SUNO_API_KEY", child)
        self.assertNotIn("GEMINI_API_KEY", child)
        self.assertNotIn("OPENAI_API_KEY", child)

    def test_local_ollama_simulation_receives_no_cloud_credentials(self):
        config = {
            "agent_base": {
                "think": {"llm": {"provider": "ollama"}},
                "associate": {"embedding": {"type": "ollama"}},
            }
        }
        child = scoped_subprocess_environment("start", base_env=self.env, config=config)
        for name in (
            "OPENAI_API_KEY",
            "LIBLIBAI_ACCESS_KEY",
            "LIBLIBAI_SECRET_KEY",
            "SUNO_API_KEY",
            "GEMINI_API_KEY",
        ):
            self.assertNotIn(name, child)

    def test_google_embedding_receives_only_its_own_key(self):
        config = {
            "agent_base": {
                "think": {"llm": {"provider": "ollama"}},
                "associate": {"embedding": {"type": "google"}},
            }
        }
        env = dict(self.env)
        env.pop("GEMINI_API_KEY", None)
        env["GOOGLE_API_KEY"] = "google-only"
        child = scoped_subprocess_environment("start", base_env=env, config=config)
        self.assertEqual(child["GEMINI_API_KEY"], "google-only")
        self.assertNotIn("OPENAI_API_KEY", child)
        self.assertNotIn("SUNO_API_KEY", child)


class LegacyValidationTests(unittest.TestCase):
    def _runtime(self, root: Path) -> RuntimePaths:
        return RuntimePaths(
            project_root=root,
            resource_root=root,
            results_root=root / "results",
        )

    def test_bootstrap_is_idempotent_and_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = self._runtime(root)
            resources = root / "agents_town/legacy/resources"
            template_root = resources / "character_templates/agents"
            for name in validation_cli.TEMPLATE_NAMES:
                folder = template_root / name
                folder.mkdir(parents=True)
                (folder / "agent.json").write_text(
                    json.dumps({"name": name}, ensure_ascii=False), encoding="utf-8"
                )
                (folder / "portrait.png").write_bytes(b"portrait")
                (folder / "texture.png").write_bytes(b"texture")
            (resources / "config.example.json").write_text(
                json.dumps({"agent_base": {}}), encoding="utf-8"
            )
            with mock.patch.object(validation_cli, "_paths", return_value=runtime):
                first = validation_cli.bootstrap()
                config_path = root / "data/config.json"
                config_path.write_text('{"user":"preserved"}', encoding="utf-8")
                second = validation_cli.bootstrap()
            self.assertTrue(first["created"])
            self.assertFalse(second["created"])
            self.assertEqual(config_path.read_text(encoding="utf-8"), '{"user":"preserved"}')

    def test_checkpoint_scan_reports_fields_without_secret_values(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "simulate-1.json"
            path.write_text(
                json.dumps({"api_keys": {"OPENAI_API_KEY": "sentinel-value"}}),
                encoding="utf-8",
            )
            report = validation_cli.secrets_scan(root)
            rendered = json.dumps(report)
            self.assertEqual(report["affected_count"], 1)
            self.assertNotIn("sentinel-value", rendered)

    def test_checkpoint_continuity_detects_lost_memory_ids(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base = {
                "stride": 10,
                "agents": {
                    "傅融": {"associate": {"memory": {"thought": ["memory-1"]}}}
                },
            }
            first = dict(base, step=1, time="20240213-09:30")
            second = dict(base, step=2, time="20240213-09:40")
            second["agents"] = {
                "傅融": {"associate": {"memory": {"thought": []}}}
            }
            (root / "simulate-1.json").write_text(
                json.dumps(first), encoding="utf-8"
            )
            (root / "simulate-2.json").write_text(
                json.dumps(second), encoding="utf-8"
            )
            (root / "conversation.json").write_text("{}", encoding="utf-8")
            report = validation_cli._checkpoint_continuity(root)
        self.assertFalse(report["memory_continuity"])


@unittest.skipUnless(importlib.util.find_spec("requests"), "requests is not installed")
class MediaIntegrationSecurityTests(unittest.TestCase):
    def test_suno_uses_header_timeout_and_does_not_log_key(self):
        suno = importlib.import_module("agents_town.legacy.integrations.suno")
        response = mock.Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"code": 200, "data": {"taskId": "task-1"}}
        secret = "suno-sentinel-secret"
        output = io.StringIO()
        with mock.patch.object(suno.requests, "post", return_value=response) as post:
            with redirect_stdout(output):
                client = suno.SunoAPIClient(
                    api_key=secret,
                    base_url="https://suno.example.test",
                    timeout=7,
                )
                result = client.generate_lyrics("short prompt")
        self.assertEqual(result["code"], 200)
        self.assertEqual(post.call_args.kwargs["timeout"], 7)
        self.assertEqual(
            post.call_args.kwargs["headers"]["Authorization"], f"Bearer {secret}"
        )
        self.assertNotIn(secret, output.getvalue())

    def test_liblib_logs_redacted_authenticated_url(self):
        liblib = importlib.import_module(
            "agents_town.legacy.integrations.liblib_starflow"
        )
        response = mock.Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"code": 0, "data": {"generateUuid": "job-1"}}
        access_key = "lib-access-sentinel"
        secret_key = "lib-secret-sentinel"
        output = io.StringIO()
        with mock.patch.object(liblib.requests, "post", return_value=response) as post:
            with redirect_stdout(output):
                client = liblib.LiblibF1Txt2ImgAPI(
                    access_key,
                    secret_key,
                    base_url="https://liblib.example.test",
                )
                result = client.submit_txt2img_task({"prompt": "test"})
        self.assertEqual(result["code"], 0)
        self.assertIn("AccessKey=lib-access-sentinel", post.call_args.args[0])
        self.assertEqual(post.call_args.kwargs["timeout"], liblib.DEFAULT_REQUEST_TIMEOUT)
        self.assertNotIn(access_key, output.getvalue())
        self.assertNotIn(secret_key, output.getvalue())

    def test_media_output_roots_follow_isolated_legacy_results(self):
        suno = importlib.import_module("agents_town.legacy.integrations.suno")
        liblib = importlib.import_module(
            "agents_town.legacy.integrations.liblib_starflow"
        )
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(
            "os.environ", {"GA_LEGACY_RESULTS_DIR": temp}
        ):
            music = Path(suno._resolve_records_dir("music-records"))
            paint = Path(liblib._resolve_records_dir("paint-records"))
        self.assertEqual(music, Path(temp) / "music-records")
        self.assertEqual(paint, Path(temp) / "paint-records")

    @unittest.skipUnless(importlib.util.find_spec("openai"), "openai is not installed")
    def test_gemini_client_is_created_lazily_with_gemini_key_only(self):
        gemini = importlib.import_module("agents_town.legacy.integrations.gemini")
        fake_client = object()
        config = {
            "services": {
                "gemini": {
                    "api_key": "gemini-sentinel",
                    "base_url": "https://gemini.example.test/v1",
                    "model": "gemini-test",
                }
            },
            "api_keys": {"OPENAI_API_KEY": "must-not-cross"},
        }
        with mock.patch.object(
            gemini,
            "_load_gemini_compatibility_config",
            return_value=(config, {}),
        ), mock.patch.object(gemini, "OpenAI", return_value=fake_client) as constructor:
            client, model, secret = gemini.create_gemini_client()
        self.assertIs(client, fake_client)
        self.assertEqual(model, "gemini-test")
        self.assertEqual(secret, "gemini-sentinel")
        self.assertEqual(constructor.call_args.kwargs["api_key"], "gemini-sentinel")
        self.assertEqual(constructor.call_args.kwargs["timeout"], 60)


if __name__ == "__main__":
    unittest.main()
