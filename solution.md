# Editorial: 15 million HTTP listeners on one VM

The goal is a **measured live state**, not a shell loop of Linux processes. The selected runtime uses one `smoltcp` listening socket and one 16-byte Rust task record per destination. A packet from `client-01` selects the resident listener by destination IP. The response body is generated from its index. Active flow records appear only while connections exist. This is a fixed HTTP state machine; it does not intercept arbitrary compiled C syscalls or provide a POSIX/LFI sandbox.

## What the failures mean

1. **Implicit bind.** `webserver_libc.c` calls `socket`, then `listen` on an unbound socket. Linux picks an ephemeral port. `getsockname` exposes it; `accept`, `recv`, `send`, and `close` serve the request. `HTTP/1.0 200 OK` with body `ok` is the check. There is no RPS threshold.
2. **Port exhaustion.** The single-process probe holds listeners open in its own namespace. On the tested iximiuz kernel, `ip_local_port_range` was `32768–60999`, and `listen` failed with `EADDRINUSE` after **28,232** listeners. This is an example measurement; inspect the report in your own run. The probe closes all descriptors and has a 256 MiB cgroup limit.
3. **AnyIP.** A local route for `2001:db8:1234:5678::/64` lets traffic for the documentation prefix terminate in a disposable namespace. Two C servers bind `::1` and `::2` in that prefix on port 8081 and return `alpha` and `beta`. On the tested 6.1 kernel, the explicit IPv6 binds initially returned `EADDRNOTAVAIL` even with the route. Enabling `net.ipv6.ip_nonlocal_bind=1` **inside the namespace only** made the experiment work. The setting never affects the management namespace. The [Linux kernel sysctl documentation](https://docs.kernel.org/networking/ip-sysctl.html) describes this bind control.
4. **Process cost.** The probe's 32 MiB cgroup reached an OOM kill after about 210 tiny C servers in the tested VM. Its extrapolation was about 2.4 TB for 15 million processes. This is a measured cgroup slope, not the article's 1.5 MB estimate. The result demonstrates the direction and magnitude; exact process cost depends on executable, shared pages, kernel, and allocator.
5. **Idle kernel sockets.** The probe creates unbound TCP sockets and never calls `listen`. Its 64 MiB cgroup reached an OOM kill after observing 18,000 sockets and a substantial slab charge. `memory.peak / count` was about 3.7 KiB per socket in that run. The last observed count is a lower bound because the child was killed between progress lines. Idle kernel sockets were not free.

The root-owned JSON reports under `/var/lib/15m-lab/runs/<run-id>/` are the evidence. The grader reads these reports, validates their age and shape, and checks the recorded failure cause. The expected numbers above are **examples from one run**, not hard-coded grading targets.

## The memory budget

The context arithmetic is `15,000,000 × 16 = 240,000,000 bytes ≈ 229 MiB`. That is only the task vector. The resident `smoltcp` listener, its `SocketSet`, two buffers, allocations, and process overhead dominate the real total.

The first 64-byte RX/TX build measured about **657 bytes per idle listener** in the target VM. That projected too close to or beyond the protected service budget. The response with the largest listener ID takes 46 bytes; reducing both buffers to 48 bytes preserved the HTTP test and lowered the measured slope to about **625 bytes per listener**. This was a measured optimization after the 64-byte comparison, not a claim that `size_of::<Task>()` represents total cost.

The tested 4-vCPU, 10-GiB-class x86_64 server VM had 10,264,988 KiB reported by `/proc/meminfo`. Moving the pending count into the existing 16-byte task reduced the resident struct from 32 to 24 bytes. The final 15-million run's cgroup peak was **9,258,872,832 bytes**, below `MemoryMax=9G` (9,663,676,416 bytes), and the VM still reported **881,836 KiB available** after the probe and a small concurrency test. Startup took **4.172 seconds** in that run. The protected unit leaves at least 512 MiB outside its own ceiling. See `harness/reports/release-15m/` for the raw server and client snapshots.

The sampled bodies from `10.0.0.1`, `10.114.112.224`, and `10.228.225.192` were `1`, `7500000`, and `15000000`. Several deterministic random addresses answered with their own indices. `10.228.225.193`, immediately outside the configured range, refused the connection. The same PID remained alive and its accepted-flow counter advanced. These checks reject a smaller run and a single wildcard server that always returns `ok`.

This result shows 15 million **idle resident listeners** that answer sampled requests. It does not claim 15 million simultaneous active connections, one million active connections, a throughput target, or a general Linux guest runtime. A request/concurrency test should be reported separately from idle memory.

## If a check fails

- **Baseline:** inspect `/tmp/15m-baseline.log`, confirm the port file contains the port printed by the live C process, and retry `curl --noproxy '*'`.
- **Port probe:** inspect `failed_syscall`, `errno`, `memory_peak`, and `events`. If file descriptors or memory fail before ports, fix the probe limits; do not call that port exhaustion.
- **AnyIP:** inspect the two server bind errors. Keep both the route and `ip_nonlocal_bind` confined to the disposable namespace.
- **Process or socket probe:** inspect the cgroup's `oom_kill` counter and the child's last observed progress. A different first failure requires a new controlled run.
- **Runtime:** check `journalctl -u 15m-runtime.service -n 50 --no-pager`, then `sudo /opt/15m-lab/toolbox/runtime.sh status`. Confirm the client route uses `172.16.0.2` and that only the lab's `10/8` route points to `smolbench` on the server. `sudo /opt/15m-lab/toolbox/reset.sh` restores the starter state and archives prior reports.

TAP is a separate Ethernet comparison. AF_XDP and DPDK require verified VM/NIC capabilities and are outside the graded TUN path. No management NIC is rebound or advertised as a performance shortcut.
