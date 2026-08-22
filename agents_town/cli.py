"""Unified command line for source-mode Agents Town applications."""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path


COMMAND_MODULES = {
    "start": "agents_town.legacy.simulation.runner",
    "replay": "agents_town.legacy.replay.app",
    "interactive": "agents_town.interactive.web",
}
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Agents Town 统一运行入口")
    subcommands = parser.add_subparsers(dest="cmd")

    start = subcommands.add_parser("start", help="运行旧版开放世界模拟")
    start.add_argument("--name", type=str, default="", help="模拟名称")
    start.add_argument("--start", type=str, default="20240213-09:30")
    start.add_argument("--step", type=int, default=10)
    start.add_argument("--stride", type=int, default=10)
    start.add_argument("--resume", action="store_true")
    start.add_argument("--verbose", type=str, default="debug")
    start.add_argument("--log", type=str, default="")

    subcommands.add_parser("replay", help="启动旧版回放 Web 服务（默认端口 5000）")
    subcommands.add_parser("interactive", help="启动互动回合推演服务（默认端口 5001）")
    return parser


def build_subprocess_command(
    args: argparse.Namespace,
    *,
    python_executable: str | None = None,
) -> list[str] | None:
    """Translate parsed CLI arguments into a canonical module command."""

    if args.cmd not in COMMAND_MODULES:
        return None
    command = [
        python_executable or sys.executable,
        "-u",
        "-m",
        COMMAND_MODULES[args.cmd],
    ]
    if args.cmd == "start":
        command.extend(
            [
                "--name",
                args.name,
                "--start",
                args.start,
                "--step",
                str(args.step),
                "--stride",
                str(args.stride),
            ]
        )
        if args.resume:
            command.append("--resume")
        if args.verbose:
            command.extend(["--verbose", args.verbose])
        if args.log:
            command.extend(["--log", args.log])
    return command


def main(argv: Sequence[str] | None = None) -> None:
    parser = create_parser()
    args, _unknown = parser.parse_known_args(argv)
    command = build_subprocess_command(args)
    if command is None:
        parser.print_help()
        return
    raise SystemExit(subprocess.call(command, cwd=PROJECT_ROOT))


__all__ = [
    "COMMAND_MODULES",
    "PROJECT_ROOT",
    "build_subprocess_command",
    "create_parser",
    "main",
]


if __name__ == "__main__":
    main()
