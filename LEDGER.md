# 15 million web servers: handoff ledger

Updated: 2026-11-21. This file is the starting point for a fresh context.

## Objective and current state

Implement `/home/adam/projects/plan-docs/15_MILLION_WEBSERVERS_PLAN.md` in this repository. The user explicitly requires **`labctl` for all remote iximiuz Labs playground interactions**. The repository's `AGENTS.md` instruction points to `/home/adam/.codex/RTK.md`, which says to prefix local shell commands with `rtk`.

The learner material, runtime, probes, graders, rootfs Dockerfile, and two-VM playground are implemented. The selected Rust/TUN runtime passed 15,000,000 resident listeners in preflight and fresh runs of the pushed OCI rootfs.

**2026-11-21 command-first revision.** The learner now runs the port C loop, the AnyIP route and two C servers, a bounded `./server "$i" &` shell loop, a bounded socket C loop, and direct `curl` requests. Learner-facing Python experiment commands are gone. `toolbox/bounded.sh` creates 32 or 64 MiB cgroups, runs the supplied command as `laborant`, and prints the real OOM event. The article's literal `&;` and `seq 1 15_000_000` syntax is explained as pseudocode. The new `v5` image was pushed and tested in an isolated playground (`6b01f3c81bf49ab62d711c03`). Its digest is `sha256:b2d7f73c9826cde1b3fffb2b226336e9b8b9b38ff5145ecffa11f2fa578b41ea`. All direct-command checks and the 15-million runtime check passed. The registered playground and tutorial were updated to `v5`. A fresh tutorial session (`6b01f4e9a8263b1b6c7df1ee`) passed all eight tasks using the revised walkthrough, then was destroyed.

**2026-11-21 conversion to a tutorial.** A `labs-review-challenge` review of the challenge `15-million-webservers-449c3122` found three blockers. Every task passed by copying the given commands. Free-tier playgrounds get a 4 GiB server VM (2 CPUs, and 1 CPU / 1.3 GiB for client-01), where the 15M run is OOM-killed after about 5 million listeners. The documented `cat` of the probe reports failed because the reports were mode `0600`. The material is now the tutorial `tutorials/15-million-web-servers-on-one-vm/` (title kept, cover in `__static__/cover.png`). `solution.md` was folded into the tutorial text, without the build history and harness paths. The root `index.md` and `solution.md` are gone.

The registered image is `ghcr.io/lpmi-13/15million-rootfs:v5` (image ID `sha256:54e6c411c51441cbe3fe67bd5b5cf98e0e887644d4da3d418f9f9509a0c6bb74`). The runtime binary is unchanged from `v3` (SHA-256 `340b9cfc...`). `publish.sh` checks that the image tag resolves to the tested digest. Playground `15-million-webservers-lab-bb24aaad` lets anyone list, read, and start it.

**Authorization state:** The user approved pushing the image, registering the playground, publishing the challenge content, and testing the steps in a fresh learner session. These actions are complete. The user made the GHCR package public so iximiuz could pull it. On 2026-11-21 the user asked to convert the challenge to a tutorial and rebuild the image as `v4`. `v4` is pushed and tested. With the user's approval, `publish.sh` updated the registered playground to `v4` and created the tutorial [`15-million-web-servers-on-one-vm-87084d2a`](https://labs.iximiuz.com/tutorials/15-million-web-servers-on-one-vm-87084d2a) as a private draft. At the user's request, the challenge `15-million-webservers-449c3122` was removed with `labctl content remove`. Its sources remain in Git history.

## Implemented assets

| Area | Files and purpose |
|---|---|
| Learner material | `tutorials/15-million-web-servers-on-one-vm/index.md` has predictions, bounded experiments, the measured results and their meaning, hints, a memory-requirement warning, and six verification tasks with dynamic hints. Privileged commands use absolute `/opt/15m-lab` paths matching the narrow sudo policy. |
| Runtime | `runtime/` is an independent MIT-licensed Rust 1.96.0 project pinned by `Cargo.lock`, using `smoltcp 0.14.0`. It has one 16-byte task and one 24-byte resident entry/TCP listener per address, 48-byte RX/TX buffers, TUN by default, optional TAP compilation, an address-aware HTTP response, bounded active-flow state, and a live Unix status socket. |
| C baseline | `baseline/` has the implicit-bind HTTP server, explicit-bound server, indexed loopback server, port exhaustion probe, and idle socket probe. |
| Experiments and operations | `toolbox/` has the bounded cgroup shell wrapper, client probes, network setup, runtime control, status bridge, and reset. Process and socket reports are written under `/var/lib/15m-lab/runs/<run-id>/`. Reset stops the C servers and removes the AnyIP route. |
| Grading | `tasks/` checks readiness, live C HTTP, probe evidence, and the 15-million live runtime from `client-01`. `tasks/grading.py` turns every failure into one line and writes it to `/var/lib/15m-lab/hints/<task>.txt` for `hintcheck:`. The final check verifies distinct first/middle/last/random responses, repeats, an outside-range refusal, stable PID, accepted-flow growth, cgroup/whole-VM memory, and no OOM. |
| Packaging | `playground/iximiuz/` has a multi-stage rootfs Dockerfile, public two-VM FlexBox manifest, systemd units, narrow sudo policy, build script, and guarded publication script. The runtime is stopped at boot. `laborant` can read the journal without broad sudo access. |
| Harness | `harness/check_release.py` validates captured reports. `harness/remote_image_test.sh` tested the fresh custom playground and saved `harness/reports/image-15m/`, including image ID, registry digest, and binary SHA-256 in `image-meta.json`. `harness/tutorial_walkthrough.sh PLAY_ID` follows the tutorial's learner commands on both VMs and waits for every task. |

The upstream article PoC was inspected at commit `8f47a6e420931d046d6b83565a9e1ce878adfcd3`. That checkout had no license file and its AArch64/DPDK code was not copied. The runtime here is a fixed-purpose Rust state machine, not an assembly syscall shim or general POSIX sandbox. See `harness/architecture-study.md` for the technical decision and detailed measurements.

## Evidence already collected

The disposable preflight session was `6b0162dc3ac59e6193a9cac8` (`flexbox`, title `15m-runtime-preflight`). At last check it was **STOPPED**, with both machines stopped. It used `dev-01` (4 vCPU, configured 10 GiB, x86_64, kernel 6.1.167, cgroup v2, `/dev/net/tun`) and `client-01` (2 vCPU, 2 GiB), connected only on `172.16.0.0/24`. Client routing for the listeners was private `10.0.0.0/8 via 172.16.0.2`.

| Report directory | What passed | Service cgroup peak | Other evidence |
|---|---|---:|---|
| `harness/reports/release-15m/` | First compact-layout full run and 12-client check | 9,258,872,832 bytes | 4,172 ms startup; 881,836 KiB VM available after probes; no OOM. |
| `harness/reports/repeat-15m/` | Clean restart, updated status/grader, 12-client check | 9,259,585,536 bytes | 11,264 ms startup; 877,540 KiB available; no OOM. |
| `harness/reports/image-binary-15m/` | Exact binary extracted from local Docker image, 12-client check | 9,259,134,976 bytes | 4,270 ms startup; 892,612 KiB available; no OOM. |
| `harness/reports/image-v1-15m/` | Complete pushed `v1` OCI rootfs; baseline, bounded probes, 1,000 rejection, 15-million grader, 12-client check | 9,258,868,736 bytes | 7,168 ms startup; 895,704 KiB available after probes; no OOM. |
| `harness/reports/image-v2-15m/` | Complete pushed `v2` OCI rootfs | See report | Passed the release checker; superseded by `v3`. |
| `harness/reports/learner-v2-15m/` | Fresh learner walkthrough, session `6b01c6c6a8263b1b6c6f92c9` | 9,258,881,024 bytes | 10,596 ms startup; no OOM; all tasks red-to-green; 12-client check passed. |
| `harness/reports/image-v3-15m/` | Complete pushed `v3` OCI rootfs, session `6b01c89c1bf49ab62d63b9f3` | 9,258,876,928 bytes | 13,654 ms startup; 887,864 KiB available; no OOM; 12-client check passed. |
| `harness/reports/image-15m/` | Complete pushed `v5` OCI rootfs, session `6b01f3c81bf49ab62d711c03` | **9,258,885,120 bytes** | 5,594 ms startup; 879,844 KiB available; no OOM; direct C/shell steps and 12-client check passed. Current release report. |

The historical `v3` image ID was `sha256:5d27dfc56c00df1a1ec89409059b28d13927c31a6b1555666c40b6fe436d6e96`, registry digest `sha256:1f1df211025a8cdd9864ff4f046d5e62d0f8d4ad4aafb8085525a5389e7f309d`, and executable SHA-256 `340b9cfc26083d8955250b4d15d54fecbf457abfd4053d122dda9b7103b908c8`. The `v5` image has the same runtime binary. `harness/check_release.py` passed on the `v5` image report.

The bounded probes in `harness/reports/preflight-failures/` observed: ephemeral range `32768–60999` and 28,232 implicit-bind listeners before `EADDRINUSE`; two IPv6 AnyIP responses (`alpha`, `beta`) with namespace-local `ip_nonlocal_bind=1`; cgroup OOM after about 210 tiny processes under 32 MiB; and socket cgroup OOM after the last observed 18,000 unbound sockets under 64 MiB. Baseline, evidence, and final graders were checked red before their actions and green after them. The final grader rejected 1,000 listeners. A malformed route failed with a useful diagnostic, and reset restored a working start. Remote operations used `labctl ssh`, `labctl cp`, and playground lifecycle commands.

Local verification passed: C baseline build with warnings as errors, Rust format and tests, Python compilation, shell syntax, `harness/check_release.py` on full-run reports, Docker build, and a Docker `--measure-only --count 1` runtime start. The latest shell/Python checks and image-binary release check also passed after the final script edits.

The GitHub CLI is authenticated as `lpmi-13` with `write:packages`, and `labctl` is authenticated. GHCR initially made the package private; the user made it public to allow iximiuz to boot the image. `labctl playground create` required `--base flexbox` even though the manifest specifies `base: flexbox`.

The initial `v1` learner run `6b01c38fa8263b1b6c6eeb17` found that `journalctl` required sudo and `laborant` inherited unrestricted `NOPASSWD ALL`. In `v2` and `v3`, the image removes that inherited grant, retains lab-specific sudo commands, and adds `laborant` to `systemd-journal`. Boot verification showed journal access and that `sudo -n /bin/true` is denied.

The fresh `v2` learner walkthrough found that `sudo python3 ~/15m-lab/toolbox/experiment.py` did not match the narrow sudo rule. The guide and solution now use `/opt/15m-lab` for privileged commands. The walkthrough completed the baseline, port, AnyIP, process, and socket steps, plus runtime starts at 1,000, 100,000, 1 million, and 15 million. Every task was checked red before the learner action and green after it. The final task rejected 1,000 listeners and passed 15 million; client probes and `curl` returned bodies `1`, `7500000`, and `15000000`.

That walkthrough also found reset left a baseline started using the lesson's relative path running. `toolbox/reset.sh` now uses `pkill -x webserver_libc`. A fresh `v3` learner session `6b01c964a8263b1b6c700954` started the baseline, confirmed its grader green, ran reset, verified the process gone, grader red, and runs directory empty, then started 1,000 listeners and passed the client probe. A second reset worked. The session is **STOPPED** with both machines stopped. The full-scale `v3` image session is also stopped.

The publication script checks the tested image ID, registry digest, and executable SHA-256 before updating the playground and uploading content. Its staging preserves the registered playground name. A final `labctl content pull` matched `index.md` and `solution.md` byte-for-byte. The remote playground manifest references `v3` on both machines. `labctl content list --kind challenge` lists the challenge and URL.

## Remaining work

Done on 2026-11-21: the tutorial is published as a private draft, and `labctl content pull` matched the local `index.md` and cover byte for byte. Two fresh default-tier sessions (`6b01d856...`, `6b01d8b2...`) passed `harness/tutorial_walkthrough.sh` with all 8 tasks completed. The second run's script stopped on a transient `labctl` API error after the 15M start, and the remaining client probes passed by hand. Its 15M run started in 12.2 s and peaked at 9,258,885,120 bytes with 867,380 KiB available. A free-tier session (`6b01d9f6...`, 4 GiB dev-01) showed the hint `dev-01 has 3.9 GiB of RAM. The 15,000,000-listener run needs the 10 GiB server VM` after the OOM-killed 15M start. No session is left running.

A task in the tutorial cannot `needs:` an init task defined by the playground manifest. The upload failed with `depends on non-existent task init_dev_01_ready`, so `verify_runtime_tun` has no cross-machine `needs:`.

Still open:

1. **Tier limit.** Ask the iximiuz team whether the tutorial can be limited to tiers that get the 10 GiB VM. The text warns about it already.
2. **Access.** Tutorial access is set in the iximiuz content menu, not by `labctl`. Check a logged-out visit after publishing.

The source plan also called for matched x86_64 fixed-guest assembly (candidate A) and stackless async (candidate C) comparisons. Neither was implemented or measured. The stackful candidate D is only an analytical negative control. TAP is compiled as an optional feature but has no matched remote benchmark; AF_XDP and DPDK were deferred. Do not claim that the four-way architecture study or backend comparison is complete. These are separate research tasks if the published lesson is to make comparative claims. The measured candidate B result is sufficient for the current learner task's fixed-purpose runtime claim.

## Working-tree and safety notes

No commit or PR was made for the tutorial conversion. The versioned Docker images are public on GHCR, and the playground is public and listed. `playground/iximiuz/manifest.yaml` and the tutorial's `index.md` contain the registered playground name. `harness/reports/image-15m/` contains the passing `v5` exact-image report. All revision test playgrounds were destroyed. No live 15-million service remains running.

For remote playground work use `labctl`; do not substitute SSH, `scp`, or a browser for remote interactions. The `rtk` prefix applies to local shell commands in this workspace. The tutorial uses private `10/8` only inside the playground; avoid changing host-wide port ranges or management NIC bindings. The exact-OCI acceptance test has passed.
