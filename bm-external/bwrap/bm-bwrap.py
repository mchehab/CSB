#!/usr/bin/env python3
# Copyright (C) Huawei Technologies Co., Ltd. 2026. All rights reserved.
# SPDX-License-Identifier: MIT

import argparse
import os
import shutil
import subprocess
import sys
import time


def existing_command(default: str) -> str:
    if os.path.exists(default):
        return default
    found = shutil.which(os.path.basename(default))
    if found:
        return found
    return default


def ro_bind_try_args(args: list[str], paths: list[str]):
    for path in paths:
        args.extend(["--ro-bind-try", path, path])


def minimal_runtime_binds() -> list[str]:
    args: list[str] = []
    ro_bind_try_args(args, ["/usr", "/bin", "/lib", "/lib64", "/sbin"])
    args.extend(["--dir", "/etc"])
    ro_bind_try_args(args, [
        "/etc/ld.so.cache",
        "/etc/ld.so.conf",
        "/etc/ld.so.conf.d",
        "/etc/nsswitch.conf",
        "/etc/passwd",
        "/etc/group",
    ])
    return args


def shared_sandbox_args(config: argparse.Namespace) -> list[str]:
    return [
        "--die-with-parent",
        "--new-session",
        "--clearenv",
        "--setenv",
        "PATH",
        "/usr/bin:/bin:/usr/sbin:/sbin",
        "--setenv",
        "HOME",
        "/home",
        "--chdir",
        "/",
    ]


def network_namespace_args(config: argparse.Namespace) -> list[str]:
    if getattr(config, "network_namespace_used", False):
        return ["--unshare-net"]
    return []


def namespace_args(config: argparse.Namespace) -> list[str]:
    hostname = f"csb-bwrap-{config.index}"
    return [
        "--unshare-user-try",
        "--unshare-ipc",
        "--unshare-pid",
        *network_namespace_args(config),
        "--unshare-uts",
        "--unshare-cgroup-try",
        "--hostname",
        hostname,
        "--ro-bind",
        "/",
        "/",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
        "--tmpfs",
        "/run",
    ]


def filesystem_args(config: argparse.Namespace) -> list[str]:
    return [
        "--unshare-user",
        "--unshare-ipc",
        "--unshare-pid",
        "--unshare-uts",
        "--unshare-cgroup-try",
        *minimal_runtime_binds(),
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
        "--tmpfs",
        "/run",
        "--tmpfs",
        "/home",
        "--dir",
        "/var",
        "--remount-ro",
        "/usr",
    ]


def max_isolation_args(config: argparse.Namespace) -> list[str]:
    hostname = f"csb-bwrap-{config.index}"
    return [
        "--unshare-user",
        "--unshare-ipc",
        "--unshare-pid",
        *network_namespace_args(config),
        "--unshare-uts",
        "--unshare-cgroup-try",
        "--disable-userns",
        "--hostname",
        hostname,
        *minimal_runtime_binds(),
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
        "--tmpfs",
        "/run",
        "--tmpfs",
        "/home",
        "--tmpfs",
        "/var",
        "--dir",
        "/var/tmp",
        "--remount-ro",
        "/usr",
    ]


def can_unshare_network(bwrap: str, command: list[str]) -> bool:
    probe = [
        bwrap,
        "--unshare-user-try",
        "--unshare-net",
        "--ro-bind",
        "/",
        "/",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--",
        *command,
    ]
    try:
        subprocess.run(probe, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=10)
        return True
    except Exception:
        return False


def build_command(config: argparse.Namespace) -> list[str]:
    command = [config.command, *config.command_args]
    if config.scenario == "baseline":
        config.network_namespace_used = False
        return command

    bwrap = shutil.which(config.bwrap)
    if bwrap is None:
        raise FileNotFoundError(f"bubblewrap executable not found: {config.bwrap}")

    config.network_namespace_used = False
    if config.scenario in {"namespaces", "max"}:
        config.network_namespace_used = can_unshare_network(bwrap, command)
        if config.require_netns and not config.network_namespace_used:
            raise RuntimeError("bubblewrap network namespace probe failed")

    if config.scenario == "namespaces":
        scenario_args = namespace_args(config)
    elif config.scenario == "filesystem":
        scenario_args = filesystem_args(config)
    elif config.scenario == "max":
        scenario_args = max_isolation_args(config)
    else:
        raise ValueError(f"unknown scenario: {config.scenario}")

    return [bwrap, *shared_sandbox_args(config), *scenario_args, "--", *command]


def run_once(command: list[str]) -> None:
    subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)


def run_benchmark(config: argparse.Namespace) -> tuple[str, float, int]:
    command = build_command(config)
    instance_name = f"bwrap_{config.scenario}_{config.index}"
    index_max = config.index + config.units * config.iterations
    success_count = 0

    start = time.perf_counter()
    try:
        for _ in range(config.index, index_max, config.units):
            run_once(command)
            success_count += 1
    except subprocess.CalledProcessError as err:
        stderr = err.stderr.decode(errors="replace") if err.stderr else ""
        print(f"Error running {config.scenario} command: {stderr}", file=sys.stderr)
        sys.exit(err.returncode or 1)
    elapsed = time.perf_counter() - start

    return instance_name, elapsed, success_count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bubblewrap isolation scalability benchmark")
    parser.add_argument("--index", type=int, default=0, help="Index of this execution unit")
    parser.add_argument("--units", type=int, default=1, help="Number of execution units")
    parser.add_argument("--iterations", type=int, default=100, help="Launches per execution unit")
    parser.add_argument(
        "--scenario",
        choices=["baseline", "namespaces", "filesystem", "max"],
        default="max",
        help="Bubblewrap feature profile to benchmark",
    )
    parser.add_argument("--bwrap", default="bwrap", help="Bubblewrap executable")
    parser.add_argument(
        "--require-netns",
        action="store_true",
        help="Fail if bwrap cannot create an isolated network namespace",
    )
    parser.add_argument(
        "--command",
        default=existing_command("/usr/bin/true"),
        help="Command to run inside the sandbox",
    )
    parser.add_argument(
        "--command-arg",
        action="append",
        dest="command_args",
        default=[],
        help="Argument passed to the sandboxed command; repeat for multiple args",
    )
    args, _ = parser.parse_known_args()

    instance_name, launch_time, success_count = run_benchmark(args)
    avg_launch_time = launch_time / args.iterations if args.iterations else 0.0

    print(
        f"instance_name={instance_name};"
        f"scenario={args.scenario};"
        f"network_namespace={int(getattr(args, 'network_namespace_used', False))};"
        f"success_count={success_count};"
        f"launch_time={launch_time:.6f};"
        f"avg_launch_time={avg_launch_time:.6f};"
        f"time={launch_time:.6f}"
    )
