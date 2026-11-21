# 15 million web servers lab

This is entirely based on the work in the article https://kapteko.com/15-million-webservers/, it is **not** my original work, and all credit to the author for a very cool and fun look at how many webservers can be started inside one linux process on a single VM.

> [!IMPORTANT]
> You can run this lab on iximiuz Labs as the tutorial [Can One VM Host 15 Million Web Servers?](https://labs.iximiuz.com/tutorials/15-million-web-servers-on-one-vm-87084d2a).
> **It only runs successfully in the premium tier.**
> The last step needs a 10 GiB server VM. Free-tier playgrounds get a 4 GiB server VM, and there the 15,000,000-listener run is killed after about 5 million listeners.

For the complete handoff state and next steps, read [LEDGER.md](LEDGER.md).

This repository contains the iximiuz Labs tutorial [`15-million-web-servers-on-one-vm-87084d2a`](https://labs.iximiuz.com/tutorials/15-million-web-servers-on-one-vm-87084d2a) (source in `tutorials/15-million-web-servers-on-one-vm/`, private draft), a TUN-backed Rust `smoltcp` runtime, bounded C/Linux resource experiments, root-owned graders, and a two-VM custom playground image. The selected runtime reached **15,000,000 resident listeners** on a remote x86_64 4-vCPU, 10-GiB-class server VM. It answered sampled first, middle, last, and random addresses from `client-01` while its service cgroup stayed below 9 GiB. See [the architecture study](harness/architecture-study.md) and [current image report](harness/reports/image-15m/).

A clean rerun, a run using the binary extracted from the local OCI image, and fresh runs of the complete pushed image all passed. Reports are in `harness/reports/repeat-15m/`, `harness/reports/image-binary-15m/`, and `harness/reports/image-15m/`. The current public image is `ghcr.io/lpmi-13/15million-rootfs:v4` (digest `sha256:2b33bc26a774c9ecb9eac5eba01a55d2c82d96dfb720637bbc1ba8ad0ab37c30`). The registered playground is `15-million-webservers-lab-bb24aaad`. The `v4` exact-image run passed the 15-million client grader and 12 concurrent probes with a 9,258,885,120-byte service-cgroup peak and no OOM. The earlier `v3` report is in `harness/reports/image-v3-15m/`.

The content was first uploaded as the challenge `15-million-webservers-449c3122`. A review found that every task passed by copying the given commands, so the material is now a tutorial, and the challenge was removed on 2026-11-21. Tutorials allow step-by-step commands. The 15,000,000-listener step needs the full 10 GiB server VM. Free-tier playgrounds get a 4 GiB server VM, where the full run is OOM-killed after about 5 million listeners.

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

The final custom playground source is `playground/iximiuz/manifest.yaml`. Its `name` points to the registered playground, and both drives use the `v4` tag. A `v4@sha256:...` pin booted in an ad-hoc FlexBox playground, but the registered playground failed to start with it (`could not get dynamic volume`), so the drives use the tag. `publish.sh` checks that the tag still resolves to the tested digest. Its local and remote access rules let anyone list, read, and start it. The tutorial front matter uses the registered playground name. `harness/remote_image_test.sh PLAYGROUND_RUN_ID` tests the exact OCI image in a playground started with `labctl playground start flexbox -f <manifest>` and saves `harness/reports/image-15m/`. The runtime is stopped at boot.

`publish.sh` checks the tested image ID, registry digest, and executable SHA-256, updates the registered playground, and pushes the tutorial's `index.md` and `__static__/cover.png`. With `CONTENT_CREATE=1`, it first creates the tutorial on iximiuz. `harness/tutorial_walkthrough.sh PLAY_ID` follows every learner command in a running tutorial session on both VMs and waits for all examiner tasks. [iximiuz access controls](https://labs.iximiuz.com/courses/labs-docs/content-authoring/access-control) are set in the content menu, separately from the playground.

## Report format

Probes write atomically under `/var/lib/15m-lab/runs/<run-id>/`. Each JSON file contains `schema: 1`, `run_id` or timestamp, `kind` for a bounded experiment, `ok`, and measured fields. Report files are mode `0644`, so the learner can read them. With `--output`, the final client grader also saves a report with live before/after status, cgroup memory/events, sampled TCP/HTTP responses, and out-of-range behavior. Every grader prints one line when it fails, and with `--hint-file` it writes that line to `/var/lib/15m-lab/hints/` for the task's `hintcheck:` script. Server status includes RSS/PSS, executable SHA-256, and VM total/available memory. `reset.sh` stops the lab services, removes only lab-created network/cgroup state, and archives reports before restoring an empty `runs/` directory.

## Source and scope

The upstream article's PoC was inspected at commit `8f47a6e420931d046d6b83565a9e1ce878adfcd3`. That checkout has no license file, so this repository does not vendor its source. The Rust runtime here is an independent, fixed-purpose state machine. It is not the upstream AArch64 assembly guest, a general syscall emulator, or an LFI/POSIX sandbox. No throughput or simultaneous-connection target is claimed. See `harness/architecture-study.md` for the remaining comparison work and release gates.
