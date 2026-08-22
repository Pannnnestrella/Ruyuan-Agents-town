from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from agents_town import cli
from agents_town.legacy.launcher.commands import COMMAND_SPECS, resolve_command


ROOT = Path(__file__).resolve().parent.parent


class CanonicalCommandTests(unittest.TestCase):
    def test_friendly_root_entry_defaults_to_interactive(self):
        import run

        with mock.patch.object(run, "agents_main") as main:
            run.main([])
        main.assert_called_once_with(["interactive"])

    def test_friendly_root_entry_forwards_explicit_commands(self):
        import run

        with mock.patch.object(run, "agents_main") as main:
            run.main(["replay"])
        main.assert_called_once_with(["replay"])

    def test_cli_builds_module_commands_without_root_scripts(self):
        parser = cli.create_parser()
        cases = {
            "interactive": "agents_town.interactive.web",
            "replay": "agents_town.legacy.replay.app",
            "start": "agents_town.legacy.simulation.runner",
        }
        for name, module in cases.items():
            with self.subTest(name=name):
                args = parser.parse_args([name])
                command = cli.build_subprocess_command(
                    args, python_executable="python-test"
                )
                self.assertEqual(["python-test", "-u", "-m", module], command[:4])
                self.assertNotIn(".py", " ".join(command))

    def test_cli_runs_canonical_command_from_project_root(self):
        with mock.patch("agents_town.cli.subprocess.call", return_value=0) as call:
            with self.assertRaises(SystemExit) as exit_context:
                cli.main(["interactive"])
        self.assertEqual(0, exit_context.exception.code)
        command = call.call_args.args[0]
        self.assertEqual(
            "agents_town.interactive.web",
            command[command.index("-m") + 1],
        )
        self.assertEqual(ROOT, call.call_args.kwargs["cwd"])

    def test_launcher_source_commands_use_modules(self):
        command, working_dir = resolve_command(
            "compress",
            ["--name", "demo"],
            frozen=False,
            python_executable="python-test",
            project_root=ROOT,
        )
        self.assertEqual(
            [
                "python-test",
                "-u",
                "-m",
                "agents_town.legacy.replay.report",
                "--name",
                "demo",
            ],
            command,
        )
        self.assertEqual(str(ROOT.resolve()), working_dir)

    def test_launcher_frozen_commands_keep_existing_executable_names(self):
        with TemporaryDirectory() as temp_dir:
            executable_dir = Path(temp_dir) / "launcher"
            executable_dir.mkdir()
            for command_name, spec in COMMAND_SPECS.items():
                executable = executable_dir / spec.frozen_executable
                executable.touch()
                with self.subTest(command_name=command_name):
                    command, working_dir = resolve_command(
                        command_name,
                        ["--example"],
                        frozen=True,
                        executable_dir=executable_dir,
                    )
                    self.assertEqual(
                        [str(executable.resolve()), "--example"], command
                    )
                    self.assertEqual(str(executable_dir.resolve()), working_dir)

    def test_launcher_supports_collected_frozen_layout(self):
        with TemporaryDirectory() as temp_dir:
            executable_dir = Path(temp_dir) / "launcher"
            executable_dir.mkdir()
            executable = Path(temp_dir) / "start" / "start.exe"
            executable.parent.mkdir()
            executable.touch()
            command, working_dir = resolve_command(
                "start",
                frozen=True,
                executable_dir=executable_dir,
            )
            self.assertEqual([str(executable.resolve())], command)
            self.assertEqual(str(executable.parent.resolve()), working_dir)

    def test_missing_frozen_executable_is_reported(self):
        with TemporaryDirectory() as temp_dir:
            with self.assertRaises(FileNotFoundError):
                resolve_command(
                    "start",
                    frozen=True,
                    executable_dir=temp_dir,
                )

    def test_frozen_executable_names_are_centralized(self):
        owner = ROOT / "agents_town" / "legacy" / "launcher" / "commands.py"
        executable_names = {
            spec.frozen_executable for spec in COMMAND_SPECS.values()
        }
        for path in (ROOT / "agents_town").rglob("*.py"):
            if path == owner:
                continue
            source = path.read_text(encoding="utf-8")
            for executable_name in executable_names:
                self.assertNotIn(executable_name, source, str(path.relative_to(ROOT)))


class ArchivedWrapperTests(unittest.TestCase):
    ARCHIVE = ROOT / "scripts" / "legacy_entrypoints"

    def test_root_contains_only_the_friendly_python_entrypoint(self):
        self.assertEqual(
            ["run.py"],
            sorted(path.name for path in ROOT.glob("*.py")),
        )

    def test_archived_wrapper_inventory_is_complete(self):
        expected = {
            "__main__.py",
            "AI小镇启动器.py",
            "compress.py",
            "gemini_API.py",
            "interactive_server.py",
            "liblib_starflow_txt2img_api.py",
            "replay.py",
            "start.py",
            "suno-api.py",
            "tiled_to_maze.py",
        }
        actual = {
            path.name
            for path in self.ARCHIVE.glob("*.py")
            if path.name != "_bootstrap.py"
        }
        self.assertEqual(expected, actual)

    def test_argument_based_wrappers_still_support_help(self):
        wrappers = [
            "__main__.py",
            "start.py",
            "compress.py",
            "liblib_starflow_txt2img_api.py",
            "suno-api.py",
            "gemini_API.py",
        ]
        for wrapper in wrappers:
            with self.subTest(wrapper=wrapper):
                result = subprocess.run(
                    [sys.executable, str(self.ARCHIVE / wrapper), "--help"],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                    check=False,
                )
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertIn("usage:", result.stdout.lower())

    def test_package_commands_do_not_name_root_python_wrappers(self):
        for relative_path in (
            "agents_town/cli.py",
            "agents_town/legacy/launcher/app.py",
        ):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertNotIn(".py", source, relative_path)

    def test_archived_wrappers_use_explicit_exports(self):
        wrappers = [
            "__main__.py",
            "AI小镇启动器.py",
            "compress.py",
            "gemini_API.py",
            "interactive_server.py",
            "liblib_starflow_txt2img_api.py",
            "replay.py",
            "start.py",
            "suno-api.py",
            "tiled_to_maze.py",
        ]
        for wrapper in wrappers:
            with self.subTest(wrapper=wrapper):
                source = (self.ARCHIVE / wrapper).read_text(encoding="utf-8")
                self.assertNotIn("import *", source)
                self.assertIn("__all__", source)


if __name__ == "__main__":
    unittest.main()
