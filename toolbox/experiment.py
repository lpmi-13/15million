#!/usr/bin/env python3
"""Run the three bounded failures and the disposable AnyIP demonstration.

This entry point is installed root-owned. The learner invokes fixed sudo commands;
the parent stays outside each short-lived memory cgroup and records its outcome.
"""

import argparse
import json
import os
import re
import select
import signal
import socket
import subprocess
import tempfile
import time
from pathlib import Path


ROOT = Path("/opt/15m-lab")
CGROUP = Path("/sys/fs/cgroup")
RUNS = Path("/var/lib/15m-lab/runs")


def text(path: Path) -> str:
    return path.read_text().strip()


def fields(path: Path) -> dict[str, int]:
    return {key: int(value) for key, value in
            (line.split() for line in text(path).splitlines())}


def atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as temporary:
        json.dump(data, temporary, indent=2, sort_keys=True)
        temporary.write("\n")
        name = temporary.name
    # NamedTemporaryFile creates 0600 files. Reports must stay readable by the learner.
    os.chmod(name, 0o644)
    os.replace(name, path)


def command(*args: str) -> str:
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT, timeout=10).strip()


class Group:
    def __init__(self, name: str, max_bytes: int, max_pids: int = 512):
        self.path = CGROUP / f"15m-lab-{name}-{os.getpid()}"
        self.path.mkdir()
        (self.path / "memory.max").write_text(str(max_bytes))
        if (self.path / "memory.swap.max").exists():
            (self.path / "memory.swap.max").write_text("0")
        (self.path / "pids.max").write_text(str(max_pids))
        self.max_bytes = max_bytes

    def join_child(self) -> None:
        (self.path / "cgroup.procs").write_text(str(os.getpid()))

    def snapshot(self) -> dict:
        stat = fields(self.path / "memory.stat")
        return {
            "current": int(text(self.path / "memory.current")),
            "peak": int(text(self.path / "memory.peak")),
            "events": fields(self.path / "memory.events"),
            "slab": stat.get("slab", 0),
            "slab_unreclaimable": stat.get("slab_unreclaimable", 0),
        }

    def close(self) -> None:
        # All child processes must have been reaped before the cgroup is removed.
        for _ in range(20):
            try:
                self.path.rmdir()
                return
            except OSError:
                time.sleep(0.05)


def watched(group: Group, argv: list[str], timeout: float) -> tuple[int, str, list[dict]]:
    child = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             preexec_fn=group.join_child)
    assert child.stdout is not None
    deadline = time.monotonic() + timeout
    chunks = []
    samples = []
    while child.poll() is None:
        if time.monotonic() >= deadline:
            child.kill()
        readable, _, _ = select.select([child.stdout], [], [], 0.05)
        if readable:
            chunks.append(os.read(child.stdout.fileno(), 65536))
        samples.append(group.snapshot())
    chunks.append(child.stdout.read())
    child.wait()
    samples.append(group.snapshot())
    return child.returncode, b"".join(chunks).decode("utf-8", "replace"), samples


def namespace(name: str) -> str:
    ns = f"15m-{name}-{os.getpid()}"
    command("ip", "netns", "add", ns)
    command("ip", "-n", ns, "link", "set", "lo", "up")
    return ns


def port_exhaust() -> dict:
    ns = namespace("ports")
    group = Group("ports", 256 * 1024 * 1024)
    try:
        code, output, samples = watched(
            group, ["ip", "netns", "exec", ns, str(ROOT / "baseline/bin/port_exhaust")], 90)
        result = json.loads(output.splitlines()[-1])
        width = result["range_high"] - result["range_low"] + 1
        return {"kind": "port", "exit_code": code, "probe": result,
                "cgroup_limit": group.max_bytes, "memory_peak": max(s["peak"] for s in samples),
                "events": group.snapshot()["events"], "ok": code == 0 and
                result["failed_syscall"] == "listen" and result["errno"] == 98 and
                width - 64 <= result["count"] <= width}
    finally:
        command("ip", "netns", "del", ns)
        group.close()


def anyip() -> dict:
    ns = namespace("anyip")
    servers = []
    try:
        route = "2001:db8:1234:5678::/64"
        command("ip", "-n", ns, "-6", "route", "add", "local", route, "dev", "lo")
        # This VM's IPv6 bind check still rejects unassigned addresses after
        # the local route. Enable nonlocal bind only inside this namespace.
        command("ip", "netns", "exec", ns, "sysctl", "-q", "-w",
                "net.ipv6.ip_nonlocal_bind=1")
        for address, label in (("2001:db8:1234:5678::1", "alpha"),
                               ("2001:db8:1234:5678::2", "beta")):
            servers.append(subprocess.Popen(["ip", "netns", "exec", ns,
                                             str(ROOT / "baseline/bin/bound_server"),
                                             address, "8081", label],
                                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE))
        time.sleep(0.2)
        exited = [server.stderr.read().decode("utf-8", "replace")
                  for server in servers if server.poll() is not None]
        if exited:
            return {"kind": "anyip", "route": route, "server_errors": exited,
                    "ok": False}
        replies = {}
        for address in ("2001:db8:1234:5678::1", "2001:db8:1234:5678::2"):
            try:
                replies[address] = command("ip", "netns", "exec", ns, "curl", "-g", "-6",
                                           "--noproxy", "*", "-fsS", "--max-time", "4",
                                           f"http://[{address}]:8081/")
            except subprocess.CalledProcessError as error:
                replies[address] = error.output.strip()
        return {"kind": "anyip", "route": route, "ipv6_nonlocal_bind_in_namespace": True,
                "replies": replies,
                "ok": list(replies.values()) == ["alpha", "beta"]}
    finally:
        for server in servers:
            server.terminate()
            try:
                server.wait(timeout=2)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
        command("ip", "netns", "del", ns)


def pss(pid: int) -> int:
    try:
        return next(int(line.split()[1]) * 1024 for line in
                    Path(f"/proc/{pid}/smaps_rollup").read_text().splitlines()
                    if line.startswith("Pss:"))
    except (FileNotFoundError, StopIteration):
        return 0


def process_cost() -> dict:
    group = Group("process", 32 * 1024 * 1024, 400)
    children = []
    start = time.monotonic()
    first_pss = 0
    before = group.snapshot()["current"]
    peak_live = 0
    try:
        for index in range(350):
            if time.monotonic() - start > 45:
                break
            child = subprocess.Popen([str(ROOT / "baseline/bin/bound_server"), "127.0.0.1", "0",
                                      str(index)], stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, preexec_fn=group.join_child)
            children.append(child)
            if index == 9:
                first_pss = sum(pss(item.pid) for item in children)
            snapshot = group.snapshot()
            peak_live = max(peak_live, sum(item.poll() is None for item in children))
            if snapshot["events"].get("oom_kill", 0) > 0:
                break
        snapshot = group.snapshot()
        delta = max(0, snapshot["peak"] - before)
        per_process = delta / max(peak_live, 1)
        return {"kind": "process", "cgroup_limit": group.max_bytes, "before": before,
                "memory_peak": snapshot["peak"], "peak_live": peak_live,
                "children_started": len(children), "first_ten_pss_bytes": first_pss,
                "events": snapshot["events"], "bytes_per_process_estimate": per_process,
                "extrapolated_15m_bytes": int(per_process * 15_000_000),
                "termination": "cgroup_oom_kill" if snapshot["events"].get("oom_kill", 0) else "bound_reached",
                "ok": snapshot["events"].get("oom_kill", 0) > 0 and per_process > 0}
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        group.close()


def socket_cost() -> dict:
    group = Group("socket", 64 * 1024 * 1024, 8)
    try:
        code, output, samples = watched(group,
                                         [str(ROOT / "baseline/bin/socket_cost"), "200000"], 45)
        counts = [int(line.split("=", 1)[1]) for line in output.splitlines()
                  if line.startswith("count=")]
        peak = max(sample["peak"] for sample in samples)
        max_count = max(counts, default=0)
        events = group.snapshot()["events"]
        return {"kind": "socket", "cgroup_limit": group.max_bytes,
                "exit_code": code, "max_observed_count": max_count, "memory_peak": peak,
                "bytes_per_socket_estimate": peak / max(max_count, 1),
                "slab_peak_observed": max(sample["slab"] for sample in samples),
                "events": events, "output_tail": output.splitlines()[-5:],
                "ok": max_count > 1000 and peak > max_count * 128 and
                (events.get("oom_kill", 0) > 0 or "errno=" in output)}
    finally:
        group.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=("port", "anyip", "process", "socket"))
    parser.add_argument("--run-id", default=time.strftime("%Y%m%d-%H%M%S"))
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", args.run_id):
        parser.error("run-id must contain only letters, digits, underscore, and hyphen")
    if os.geteuid() != 0:
        parser.error("run this root-owned experiment through its fixed sudo command")
    RUNS.mkdir(parents=True, exist_ok=True)
    action = {"port": port_exhaust, "anyip": anyip,
              "process": process_cost, "socket": socket_cost}[args.kind]
    report = action()
    report.update({"schema": 1, "run_id": args.run_id, "unix_time": time.time()})
    output = RUNS / args.run_id / f"{args.kind}.json"
    atomic_json(output, report)
    print(json.dumps(report, sort_keys=True))
    print(f"saved={output}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
