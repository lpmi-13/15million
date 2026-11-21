# x86_64 runtime feasibility record

## Environment and source decision

- Target: iximiuz Labs FlexBox session `6b0162dc3ac59e6193a9cac8`, `dev-01` (4 vCPU, 10 GiB configured, `/proc/meminfo` 10,264,988 KiB), `client-01` (2 vCPU, 2 GiB), private `172.16.0.0/24` link. Kernel `6.1.167`, x86_64, cgroup v2, `/dev/net/tun` present.
- Network path: TUN `smolbench`, client route `10.0.0.0/8 via 172.16.0.2`, server route to TUN, `smoltcp = 0.14.0`, Rust 1.96.0 release build, one resident `SocketSet`/TCP listener per address.
- Upstream PoC inspected at commit `8f47a6e420931d046d6b83565a9e1ce878adfcd3`. The checkout has no `LICENSE` or `COPYING` file; its AArch64 assembly and mandatory DPDK build could not be used as-is. This repository contains an independent MIT-licensed Rust state machine and C experiments. No upstream source file was vendored.
- The fixed response contains the listener's one-based index; no per-listener response string is stored. The final task size is asserted at 16 bytes and the resident struct at 24 bytes. The allocation slope includes their heap allocations and buffers.

## Candidate decision

| Candidate | Result | Decision |
|---|---|---|
| A. x86_64 fixed-guest assembly | Not implemented or benchmarked. Porting the unsafe syscall gate and proving ABI preservation remains a separate study. | Not selected. The learner material makes no assembly or syscall-interception claim. |
| B. explicit Rust state machine | Built and tested on the actual x86_64 TUN VM through 15 million listeners; sampled addresses returned distinct HTTP bodies. | Selected for the challenge. |
| C. stackless async task per listener | Not implemented or benchmarked. | No claim about its cost or suitability. |
| D. stackful fiber/thread per listener | Analytical negative control: 4 KiB of stack reservation alone is 61.44 billion bytes, about 57.2 GiB, at 15 million tasks. Not run at high scale. | Rejected for the 10 GiB target. |

The planned four-way same-network-path comparison is incomplete. The release evidence instead rests on candidate B's direct full-scale run. If the challenge is presented as a comparative architecture study, A and C need their own matched measurements before that claim is made.

## Measured memory and correctness

Each row used a fresh process and the same `smoltcp` TUN path except the first local allocation-only rows. The runtime service had `MemoryMax=9G` on the VM. Bytes are from cgroup `memory.current` after initialization; peak is `memory.peak`. Requests ran from `client-01` after the idle reading.

| RX/TX | Count | Idle current, bytes | Peak, bytes | Startup | Client sample |
|---|---:|---:|---:|---:|---|
| 64/64 | 100,000 | 66,248,704 | 66,375,680 | 68 ms | pass |
| 64/64 | 1,000,000 | 657,801,216 | 657,805,312 | 723 ms | pass |
| 48/48 | 1,000,000 | 625,745,920 | 625,885,184 | 282 ms | pass |
| 48/48 | 5,000,000 | 3,126,632,448 | 3,126,755,328 | 3,159 ms | pass |
| 48/48 | 10,000,000 | 6,252,740,608 | 6,252,797,952 | 4,980 ms | pass |
| 48/48, first layout | 15,000,000 | 9,378,832,384 | 9,379,094,528 initially; 9,379,106,816 after probes | 6,406 ms | pass |
| 48/48, compact task layout | 1,000,000 | 617,746,432 | 617,955,328 | 280 ms | pass |
| 48/48, compact task layout | 15,000,000 | 9,258,610,688 | 9,258,860,544 idle; 9,258,872,832 after probes | 4,172 ms | pass |

An independent local allocation-only process measured about 656.5 bytes/listener with 64-byte buffers and 624.4 bytes/listener with 48-byte buffers at one million. These runs lacked TUN and the VM cgroup, so the remote table governs acceptance.

From 1 million to 10 million, the first 48-byte layout's cgroup delta was about **625.2 bytes per listener**. Moving the pending counter into the 16-byte task reduced the resident struct by eight bytes and the local one-million PSS from about 624.4 MB to 616.5 MB. The final remote 1-million and 15-million points imply about **617.2 bytes per listener**. The 15-million measured peak is the actual acceptance value, not the projection. Against `MemoryMax=9,663,676,416`, the peak left about **404.8 MB** of service-cgroup headroom; the VM snapshot after the final concurrency probe showed `MemAvailable=881,836 KiB`. The service did not record an OOM or OOM kill. This budget should be remeasured after any allocator, buffer, compiler, library, or rootfs change.

The full-scale client report in `harness/reports/release-15m/client.json` contains first, middle, last, deterministic random, repeated boundary, and outside-range outcomes. A separate 12-client check covered distinct and overlapping same-address requests; all passed. The matching server report contains the live PID, initialized count, backend, addresses, cgroup limits/events, and VM available memory. The report was captured before the runtime was stopped.

A clean restart of the same disposable playground produced a second 15-million run with the updated live-status grader. Its peak was **9,259,585,536 bytes**, startup was **11,264 ms**, and the VM still had **877,540 KiB** available after concurrent probes. The report is in `harness/reports/repeat-15m/`. The exact binary extracted from the locally built OCI image (`SHA-256 340b9cfc26083d8955250b4d15d54fecbf457abfd4053d122dda9b7103b908c8`) then passed a separate 15-million run in the disposable VM: **9,259,134,976 bytes** peak, **4,270 ms** startup, **892,612 KiB** available, no OOM, and all sampled and overlapping-client responses correct. Its report is in `harness/reports/image-binary-15m/`.

The complete pushed `v1` rootfs image passed in fresh owner-only playground run `6b01a79d1bf49ab62d5dd536`, using registered playground `15-million-webservers-lab-bb24aaad`. Both init tasks completed, the status bridge and client route boot units were active, and the baseline and four bounded probes passed. The final grader rejected a 1,000-listener run and passed the 15-million run with first, middle, last, random, repeated, and outside-range checks. All 12 concurrent requests passed. The service cgroup peak was **9,258,868,736 bytes**, startup was **7,168 ms**, VM `MemAvailable` after concurrency was **895,704 KiB**, and `memory.events` recorded no OOM or OOM kill. The live executable SHA-256 matched the image-binary run. Its report is preserved in `harness/reports/image-v1-15m/`.

The current pushed rootfs is `ghcr.io/lpmi-13/15million-rootfs:v3` (registry digest `sha256:1f1df211025a8cdd9864ff4f046d5e62d0f8d4ad4aafb8085525a5389e7f309d`). Fresh run `6b01c89c1bf49ab62d63b9f3` passed the same 15-million client grader and 12 concurrent requests. Its service cgroup peak was **9,258,876,928 bytes**, startup was **13,654 ms**, VM `MemAvailable` was **887,864 KiB**, and no OOM occurred. The release checker passed on `harness/reports/image-15m/`; the image ID, registry digest, and executable SHA-256 are in its `image-meta.json`. This is the current exact-image acceptance record.

A fresh learner walkthrough on `v2`, run `6b01c6c6a8263b1b6c6f92c9`, exercised every task red before the corresponding action and green afterward. The learner ran the baseline, four bounded probes, and the runtime at 1,000, 100,000, 1 million, and 15 million listeners. The final task rejected 1,000 and passed 15 million; client probes returned bodies `1`, `7500000`, and `15000000`. The 15-million release report in `harness/reports/learner-v2-15m/` passed the checker with **9,258,881,024 bytes** peak, **10,596 ms** startup, no OOM, and all 12 concurrent requests correct. A subsequent fresh `v3` session `6b01c964a8263b1b6c700954` verified that reset stops a baseline started via the lesson's relative path, clears reports, returns its grader to red, permits a 1,000-listener restart and client probe, and works a second time. These sessions are stopped.

## Bounded failure probes on the same VM

| Probe | Observed result | Confined limit |
|---|---|---:|
| Implicit-bind port loop | `32768–60999`; 28,232 listeners; `listen` → `EADDRINUSE` | 256 MiB |
| IPv6 AnyIP | `alpha` and `beta` on two addresses at port 8081; namespace-local `ip_nonlocal_bind=1` required | Disposable netns |
| Process growth | 210 tiny C servers started; cgroup `oom_kill=1`; estimated 160.5 KiB per process | 32 MiB |
| Unbound idle TCP sockets | Last observed 18,000; cgroup `oom_kill=1`; slab peak about 64.4 MB | 64 MiB |

Raw JSON is in `harness/reports/preflight-failures/`. The socket count is the last flushed progress marker before the kill, so its bytes/socket quotient is approximate.

## Release checks and remaining work

The preflight used a base Ubuntu playground and copied the binary and probes with `labctl`. After a clean reboot, the installed systemd units, sudo commands, readiness checks, final grader, bounded probes, and reset were exercised. The final grader rejected a 1,000-listener run and passed the 15-million run. A malformed route produced a clear failed-start diagnostic; removing that deliberate conflicting route and resetting restored a working start. Fresh versioned-rootfs and owner-session learner runs repeated the normal path and passed. The challenge content is uploaded at `https://labs.iximiuz.com/challenges/15-million-webservers-449c3122` and matches the local files. The playground manifest now grants anyone read/start access locally and remotely. A logged-out Playwright CLI visit still returned HTTP 404 for the challenge; challenge content access is stored separately in the site's content menu. A non-owner learner start remains unverified.
