---
title: Can One VM Host 15 Million Web Servers?
description: Follow the resource failures behind a 15-million-listener HTTP experiment, then verify a compact TUN-backed runtime on a 10 GiB VM.
kind: challenge
playground:
  name: 15-million-webservers-lab-bb24aaad
difficulty: hard
categories:
  - linux
  - networking
tagz:
  - tcp
  - memory
  - rust
  - smoltcp
createdAt: 2026-11-21
tasks:
  init_wait_ready:
    name: init_wait_ready
    machine: dev-01
    init: true
    user: root
    timeout_seconds: 300
    run: |-
      #!/bin/bash
      /opt/15m-lab/tasks/wait_ready.sh server
  verify_baseline_http:
    machine: dev-01
    user: root
    run: |-
      #!/bin/bash
      /usr/bin/python3 /opt/15m-lab/tasks/verify_baseline.py
  verify_port_exhaustion:
    machine: dev-01
    user: root
    run: |-
      #!/bin/bash
      /usr/bin/python3 /opt/15m-lab/tasks/verify_evidence.py port
  verify_anyip:
    machine: dev-01
    user: root
    run: |-
      #!/bin/bash
      /usr/bin/python3 /opt/15m-lab/tasks/verify_evidence.py anyip
  verify_process_cost:
    machine: dev-01
    user: root
    run: |-
      #!/bin/bash
      /usr/bin/python3 /opt/15m-lab/tasks/verify_evidence.py process
  verify_kernel_socket_cost:
    machine: dev-01
    user: root
    run: |-
      #!/bin/bash
      /usr/bin/python3 /opt/15m-lab/tasks/verify_evidence.py socket
  verify_runtime_tun:
    machine: client-01
    user: root
    timeout_seconds: 120
    run: |-
      #!/bin/bash
      /usr/bin/python3 /opt/15m-lab/tasks/verify_runtime.py
---

Can one 10 GiB VM answer HTTP on **15,000,000 destination IPs**? This challenge follows the experiments in [15 million web servers on one VM](https://kapteko.com/15-million-webservers/). You will hit three real resource limits, then start a compact Rust runtime and check it from a separate client VM.

Here, a “web server” means a distinct destination IP and port with a **resident `smoltcp` listener** and a resumable, fixed HTTP state machine in one process. It does not mean a Linux process, a general Linux guest, or a simultaneous active connection. Every final address lies in the private `10/8` range, routed only inside this playground.

```text
client-01 (2 CPUs, 2 GiB) ── 172.16.0.0/24 ── dev-01 (4 CPUs, 10 GiB)
       TCP probes          10/8 via dev-01        TUN → smoltcp → HTTP task
```

The server files are under `~/15m-lab`. Use the `/opt/15m-lab` paths shown below for `sudo` commands. Commands in steps 1–5 run on **dev-01**. Commands marked client run on **client-01**. The failure probes have fixed memory and time limits and clean up their own namespaces and cgroups. Their root-owned reports are in `/var/lib/15m-lab/runs/`.

## 1. First HTTP response

Before you run the C baseline, predict which calls create and serve its listener. The source deliberately calls `listen()` without `bind()`; Linux assigns an ephemeral port. Start it and use the printed port:

```bash
cd ~/15m-lab
PORT_FILE=/tmp/15m-baseline.port ./baseline/bin/webserver_libc >/tmp/15m-baseline.log 2>&1 &
cat /tmp/15m-baseline.log
curl --noproxy '*' "http://127.0.0.1:$(cat /tmp/15m-baseline.port)/"
```

You should see `HTTP/1.0 200 OK` and body `ok`. Read `baseline/webserver_libc.c` or use `strace` to identify `socket`, implicit bind through `listen`, `accept`, `recv`, `send`, and `close`. Requests per second are optional to measure and are never graded.

::simple-task
---
:tasks: tasks
:name: verify_baseline_http
---
#active
Checking the learner-started baseline through a real TCP request...

#completed
The implicit-bind C server returned HTTP 200 and `ok`.
::

## 2. How many unbound listeners fit?

Predict the first limit when one process repeatedly calls `socket(); listen()` with no explicit bind. The probe logs the current ephemeral range and stops at exhaustion or a safe bound. It runs inside its own network namespace.

```bash
sudo python3 /opt/15m-lab/toolbox/experiment.py port
cat /var/lib/15m-lab/runs/*/port.json
```

Find `range_low`, `range_high`, `count`, `failed_syscall`, and `errno`. Explain why a 16-bit port and the configured ephemeral range constrain this version. The exact count depends on the kernel and other reservations.

::simple-task
---
:tasks: tasks
:name: verify_port_exhaustion
---
#active
Checking the bounded probe's observed port exhaustion...

#completed
The probe reached `EADDRINUSE` at `listen()` and recorded the actual range.
::

::hint-box
---
:summary: Which error matters?
---
Look for `errno=98` (`EADDRINUSE`) on this Linux VM. If another resource fails first, the probe should be fixed before drawing a conclusion about ports.
::

## 3. Add addresses with AnyIP

Predict whether two IPv6 addresses can use the **same port**. The next probe adds a local route for documentation prefix `2001:db8:1234:5678::/64` inside a disposable namespace and binds two separate C servers. This kernel also needs `ip_nonlocal_bind=1` **inside that namespace** for the explicit binds.

```bash
sudo python3 /opt/15m-lab/toolbox/experiment.py anyip
cat /var/lib/15m-lab/runs/*/anyip.json
```

The two responses should be `alpha` and `beta`. Why does adding addresses help where more processes on the same address did not? Why would 450 NICs or a wider TCP port field be poor fixes? The final Rust path uses private IPv4, not IPv6.

::simple-task
---
:tasks: tasks
:name: verify_anyip
---
#active
Checking two independent IPv6-bound HTTP responses...

#completed
Two addresses answered independently on port 8081.
::

## 4. One process per address

Predict the memory curve if every address has its own Linux process. The probe starts only a few hundred tiny C processes under a **32 MiB cgroup**, then records the cgroup OOM event and cleans up. It never launches millions of processes.

```bash
sudo python3 /opt/15m-lab/toolbox/experiment.py process
cat /var/lib/15m-lab/runs/*/process.json
```

Compare `peak_live`, `first_ten_pss_bytes`, `memory_peak`, and `extrapolated_15m_bytes`. The measured per-process cost here may differ from the article's estimate. The OOM kill is confined to the probe cgroup.

::simple-task
---
:tasks: tasks
:name: verify_process_cost
---
#active
Checking bounded process growth and a cgroup OOM event...

#completed
The process probe recorded memory growth and a confined OOM kill.
::

## 5. Do idle kernel sockets cost zero?

Before running the probe, calculate `15,000,000 × 16` bytes for the compact task context. Then predict whether **unbound, idle kernel TCP sockets** add any memory. This probe creates sockets without `listen()`, so ports cannot cause the failure. Its cgroup limit is **64 MiB**.

```bash
sudo python3 /opt/15m-lab/toolbox/experiment.py socket
cat /var/lib/15m-lab/runs/*/socket.json
```

Look at socket count, `memory_peak`, `slab_peak_observed`, and `events.oom_kill`. Which “free idle socket” assumption failed?

::simple-task
---
:tasks: tasks
:name: verify_kernel_socket_cost
---
#active
Checking that unused kernel sockets consume cgroup-accounted memory...

#completed
The idle sockets grew memory and hit the probe's cgroup limit.
::

## 6. Fifteen million resident user-space listeners

Inspect `runtime/src/worker.rs`. A `Task` is 16 bytes; each resident entry also owns a `smoltcp` TCP socket with 48-byte RX and TX buffers. Active flows are allocated only when packets arrive. This Rust state machine models the fixed HTTP loop; it does **not** intercept compiled C syscalls or provide a general sandbox.

Start at small scales. On **dev-01**:

```bash
sudo /opt/15m-lab/toolbox/runtime.sh start 1000
sudo /opt/15m-lab/toolbox/runtime.sh status
sudo /opt/15m-lab/toolbox/runtime.sh start 100000
sudo /opt/15m-lab/toolbox/runtime.sh start 1000000
```

On **client-01**, probe each count after the status says `ready: true`:

```bash
python3 ~/15m-lab/toolbox/probe_client.py --count 1000000 --check-outside
```

Now request the full run on **dev-01**. The prebuilt release binary runs in a systemd service with a 9 GiB memory ceiling, leaving capacity for the VM and graders. A Cargo build during this run would change the memory experiment.

```bash
sudo /opt/15m-lab/toolbox/runtime.sh start 15000000
sudo /opt/15m-lab/toolbox/runtime.sh status
journalctl -u 15m-runtime.service -n 20 --no-pager
```

When `ready` is true, use the **client-01** terminal:

```bash
python3 ~/15m-lab/toolbox/probe_client.py --count 15000000 --check-outside
curl --noproxy '*' http://10.0.0.1:8080/
curl --noproxy '*' http://10.114.112.224:8080/
curl --noproxy '*' http://10.228.225.192:8080/
```

The three bodies should be `1`, `7500000`, and `15000000`. The final check reads the **live process** through the server's read-only status bridge, checks its protected cgroup and VM headroom, probes deterministic addresses over real TCP, checks an address outside the range, and confirms the same PID and accepted-flow counter afterward. A smaller run cannot pass.

::simple-task
---
:tasks: tasks
:name: verify_runtime_tun
---
#active
Checking 15,000,000 resident listeners, memory, and distinct client-side HTTP replies...

#completed
The live TUN runtime passed the 15-million-listener check.
::

::hint-box
---
:summary: Recover and retry
---
If startup fails, inspect `journalctl -u 15m-runtime.service -n 50 --no-pager` and `sudo /opt/15m-lab/toolbox/runtime.sh status`. To restore the starter state, run `sudo /opt/15m-lab/toolbox/reset.sh`. Prior reports move to `/var/lib/15m-lab/archive/`.
::
