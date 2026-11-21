# 15 million web servers lab

For the complete handoff state and next steps, read [LEDGER.md](LEDGER.md).

This repository contains an [author-visible iximiuz Labs challenge](https://labs.iximiuz.com/challenges/15-million-webservers-449c3122), a TUN-backed Rust `smoltcp` runtime, bounded C/Linux resource experiments, root-owned graders, and a two-VM custom playground image. The selected runtime reached **15,000,000 resident listeners** on a remote x86_64 4-vCPU, 10-GiB-class server VM. It answered sampled first, middle, last, and random addresses from `client-01` while its service cgroup stayed below 9 GiB. See [the architecture study](harness/architecture-study.md) and [current image report](harness/reports/image-15m/).

A clean rerun, a run using the binary extracted from the local OCI image, and fresh runs of the complete pushed image all passed. Reports are in `harness/reports/repeat-15m/`, `harness/reports/image-binary-15m/`, and `harness/reports/image-15m/`. The current public image is `ghcr.io/lpmi-13/15million-rootfs:v3` (digest `sha256:1f1df211025a8cdd9864ff4f046d5e62d0f8d4ad4aafb8085525a5389e7f309d`); the registered playground is `15-million-webservers-lab-bb24aaad`. The `v3` exact-image run passed the 15-million client grader and 12 concurrent probes with a 9,258,876,928-byte service-cgroup peak and no OOM. A separate fresh learner walkthrough completed every step and grader using `v2`; a `v3` session verified reset and restart. The challenge content is uploaded as an author-visible draft. A logged-out browser visit currently shows “Challenge not found.”

## Local build

```bash
make -C baseline
cargo test --locked --manifest-path runtime/Cargo.toml
cargo build --release --locked --manifest-path runtime/Cargo.toml
docker build -f playground/iximiuz/Dockerfile -t 15million-rootfs:dev .
```

The Dockerfile compiles the runtime in a pinned Rust 1.96.0 builder and the C tools in the Ubuntu 24.04 rootfs. The final listener run uses the prebuilt release binary; it never invokes Cargo. `tun` is the default Cargo feature; `tap` can be compiled separately for comparison. AF_XDP and DPDK are excluded from the required image until compatible VM hardware is proven.

## Remote validation with labctl

`harness/preflight.yaml` starts an isolated FlexBox server and client with the intended CPU, RAM, and private IPs. The preflight session used `labctl playground start flexbox -f harness/preflight.yaml`, `labctl cp`, and `labctl ssh` for all remote operations. The session ID and measurements are in the architecture study. The only route for `10/8` is the playground-local client-to-server route and the server-to-TUN route; no public address range is used.

The final custom playground source is `playground/iximiuz/manifest.yaml`. Its `name` and OCI image references point to the registered owner-only playground and `v3` image. The challenge front matter in `index.md` uses the registered playground name. `harness/remote_image_test.sh PLAYGROUND_RUN_ID` tested the exact OCI image using `labctl` and saved `harness/reports/image-15m/`. Both init tasks and boot units passed; the runtime is stopped at boot. The `v3` full-scale session `6b01c89c1bf49ab62d63b9f3` and reset-check session `6b01c964a8263b1b6c700954` are stopped. `publish.sh` was run with the authorized challenge name; it checked the tested image ID, registry digest, and executable SHA-256 before uploading content. A final `labctl content pull` matched the local lesson and solution byte-for-byte. [iximiuz access controls](https://labs.iximiuz.com/courses/labs-docs/content-authoring/access-control) require a separate content-menu change for public access and matching playground permissions.

## Report format

Probes write atomically under `/var/lib/15m-lab/runs/<run-id>/`. Each JSON file contains `schema: 1`, `run_id` or timestamp, `kind` for a bounded experiment, `ok`, and measured fields. The final client grader writes `final.json` with live before/after status, cgroup memory/events, sampled TCP/HTTP responses, and out-of-range behavior. Server status includes RSS/PSS, executable SHA-256, and VM total/available memory. `reset.sh` stops the lab services, removes only lab-created network/cgroup state, and archives reports before restoring an empty `runs/` directory.

## Source and scope

The upstream article's PoC was inspected at commit `8f47a6e420931d046d6b83565a9e1ce878adfcd3`. That checkout has no license file, so this repository does not vendor its source. The Rust runtime here is an independent, fixed-purpose state machine. It is not the upstream AArch64 assembly guest, a general syscall emulator, or an LFI/POSIX sandbox. No throughput or simultaneous-connection target is claimed. See `harness/architecture-study.md` for the remaining comparison work and release gates.
