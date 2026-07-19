import os
import sys
import argparse
import subprocess

def main():
    parser = argparse.ArgumentParser(description="AI小镇 - 源码运行入口")
    sub = parser.add_subparsers(dest="cmd")

    p_start = sub.add_parser("start", help="运行模拟")
    p_start.add_argument("--name", type=str, default="", help="模拟名称")
    p_start.add_argument("--start", type=str, default="20240213-09:30")
    p_start.add_argument("--step", type=int, default=10)
    p_start.add_argument("--stride", type=int, default=10)
    p_start.add_argument("--resume", action="store_true")
    p_start.add_argument("--verbose", type=str, default="debug")
    p_start.add_argument("--log", type=str, default="")

    sub.add_parser("replay", help="启动回放 Web 服务 (5000)")
    sub.add_parser("interactive", help="启动互动回合推演服务 (5001)")

    args, unknown = parser.parse_known_args()

    # 始终在源码中用 python 解释器运行子脚本，冻结时由启动器重映射为 .exe
    py = sys.executable
    root = os.path.dirname(__file__)

    if args.cmd == "start":
        cmd = [py, "-u", os.path.join(root, "start.py"),
               "--name", args.name,
               "--start", args.start,
               "--step", str(args.step),
               "--stride", str(args.stride)]
        if args.resume:
            cmd.append("--resume")
        if args.verbose:
            cmd += ["--verbose", args.verbose]
        if args.log:
            cmd += ["--log", args.log]
    elif args.cmd == "replay":
        cmd = [py, "-u", os.path.join(root, "replay.py")]
    elif args.cmd == "interactive":
        cmd = [py, "-u", os.path.join(root, "interactive_server.py")]
    else:
        # 默认展示帮助
        parser.print_help()
        return

    # ``os.execv`` on Windows may flatten the argument vector without quoting
    # script paths, which breaks this repository's default directory name
    # (``Ruyuan - Agents-Town``).  ``subprocess`` preserves the list boundary.
    raise SystemExit(subprocess.call(cmd, cwd=root))


if __name__ == "__main__":
    main()


