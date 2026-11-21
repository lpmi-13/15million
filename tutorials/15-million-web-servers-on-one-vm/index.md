---
kind: tutorial

title: Can One VM Host 15 Million Web Servers?

description: |
  Based on the article "15 million web servers on one VM" (kapteko.com).
  Measure the Linux limits that stop a naive 15-million-listener HTTP setup: ephemeral ports,
  per-process memory, and idle kernel sockets. Then run 15,000,000 smoltcp listeners in one
  user-space process and probe them from a second VM. The final step needs a 10 GiB server VM.

categories:
  - linux
  - networking

tagz:
  - tcp
  - socket
  - cgroups
  - syscalls
  - investigation

createdAt: 2026-11-21

cover: __static__/cover.png

playground:
  name: 15-million-webservers-lab-bb24aaad

tasks:
  verify_baseline_http:
    machine: dev-01
    run: |
      /usr/bin/python3 /opt/15m-lab/tasks/verify_baseline.py --hint-file /var/lib/15m-lab/hints/verify_baseline_http.txt
    hintcheck: |
      cat /var/lib/15m-lab/hints/verify_baseline_http.txt 2>/dev/null
      rm -f /var/lib/15m-lab/hints/verify_baseline_http.txt
      exit 0

  verify_port_exhaustion:
    machine: dev-01
    run: |
      /usr/bin/python3 /opt/15m-lab/tasks/verify_evidence.py port --hint-file /var/lib/15m-lab/hints/verify_port_exhaustion.txt
    hintcheck: |
      cat /var/lib/15m-lab/hints/verify_port_exhaustion.txt 2>/dev/null
      rm -f /var/lib/15m-lab/hints/verify_port_exhaustion.txt
      exit 0

  verify_anyip:
    machine: dev-01
    run: |
      /usr/bin/python3 /opt/15m-lab/tasks/verify_evidence.py anyip --hint-file /var/lib/15m-lab/hints/verify_anyip.txt
    hintcheck: |
      cat /var/lib/15m-lab/hints/verify_anyip.txt 2>/dev/null
      rm -f /var/lib/15m-lab/hints/verify_anyip.txt
      exit 0

  verify_process_cost:
    machine: dev-01
    run: |
      /usr/bin/python3 /opt/15m-lab/tasks/verify_evidence.py process --hint-file /var/lib/15m-lab/hints/verify_process_cost.txt
    hintcheck: |
      cat /var/lib/15m-lab/hints/verify_process_cost.txt 2>/dev/null
      rm -f /var/lib/15m-lab/hints/verify_process_cost.txt
      exit 0

  verify_kernel_socket_cost:
    machine: dev-01
    run: |
      /usr/bin/python3 /opt/15m-lab/tasks/verify_evidence.py socket --hint-file /var/lib/15m-lab/hints/verify_kernel_socket_cost.txt
    hintcheck: |
      cat /var/lib/15m-lab/hints/verify_kernel_socket_cost.txt 2>/dev/null
      rm -f /var/lib/15m-lab/hints/verify_kernel_socket_cost.txt
      exit 0

  verify_runtime_tun:
    machine: client-01
    run: |
      /usr/bin/python3 /opt/15m-lab/tasks/verify_runtime.py --hint-file /var/lib/15m-lab/hints/verify_runtime_tun.txt
    hintcheck: |
      cat /var/lib/15m-lab/hints/verify_runtime_tun.txt 2>/dev/null
      rm -f /var/lib/15m-lab/hints/verify_runtime_tun.txt
      exit 0
---

::remark-box
---
kind: warning
---

**This tutorial only runs successfully in the premium tier.**
The last step needs the full playground, with a 10 GiB server VM.
Free-tier playgrounds start with smaller VMs.
On a 4 GiB server VM, steps 1 to 5 and the 1,000,000-listener run still work, but the kernel kills the 15,000,000-listener run after about 5 million listeners.
::

Can one 10 GiB VM answer HTTP on **15,000,000 destination IP addresses**?
This tutorial repeats the experiments from [15 million web servers on one VM](https://kapteko.com/15-million-webservers/) in a two-VM playground.
First, you hit three Linux resource limits with small, bounded probes.
Then you start a compact Rust runtime that holds 15 million listeners in one process, and you check it from a separate client VM.

In this tutorial, a "web server" is a distinct destination IP address and port with a resident listener and a small, fixed HTTP state machine.
All 15 million of them live in one Linux process.
The final check sends a few sampled requests to them.
It does not open 15 million connections at the same time.
Every address is in the private `10.0.0.0/8` range, which is routed only inside this playground.

```text
client-01 (2 CPUs, 2 GiB) ── 172.16.0.0/24 ── dev-01 (4 CPUs, 10 GiB)
       TCP probes          10/8 via dev-01        TUN → smoltcp → HTTP task
```

The lab files are in `~/15m-lab` on both VMs.
Run the commands in steps 1 to 5 in the **Server** tab (dev-01).
Step 6 says which commands go to the **Client** tab (client-01).
The sudo rules allow only the `/opt/15m-lab` paths, so the `sudo` commands below use them.

The probes in steps 2 to 5 run with fixed memory and time limits, and they clean up their own namespaces and cgroups.
Each probe prints its report and saves a copy in `/var/lib/15m-lab/runs/`.

## 1. First HTTP response

The C baseline in `baseline/webserver_libc.c` calls `listen()` on a socket that it never passed to `bind()`.
Linux then binds the socket to a free port from the ephemeral range, and the program prints that port.
Read the source and predict which system calls create and serve the listener.
Then start it and send it a request:

```bash
cd ~/15m-lab
PORT_FILE=/tmp/15m-baseline.port ./baseline/bin/webserver_libc >/tmp/15m-baseline.log 2>&1 &
cat /tmp/15m-baseline.log
curl --noproxy '*' "http://127.0.0.1:$(cat /tmp/15m-baseline.port)/"
```

`curl` should print `ok`.
Add `-i` to see the `HTTP/1.0 200 OK` status line as well.

::simple-task
---
:tasks: tasks
:name: verify_baseline_http
---
#active
Waiting for the C baseline to answer an HTTP request...

#completed
The baseline answered with HTTP 200.
::

The program uses seven calls.
`socket()` creates an unbound TCP socket.
`listen()` makes Linux pick a free ephemeral port for it, and `getsockname()` reads that port back.
`accept()`, `recv()`, `send()`, and `close()` then serve each request.
To see them, run a second copy under `strace -e trace=network` and send it a request.
On x86-64, `strace` shows `recv()` and `send()` as `recvfrom()` and `sendto()`, because glibc implements them with those system calls.

## 2. How many unbound listeners fit?

Predict the first limit that one process hits when it calls `socket()` and `listen()` in a loop without `bind()`.
The probe below does this in its own network namespace and stops at the first error or at a safe upper bound.
It also records the ephemeral port range.

```bash
sudo python3 /opt/15m-lab/toolbox/experiment.py port
cat /var/lib/15m-lab/runs/*/port.json
```

In the report, find `range_low`, `range_high`, `count`, `failed_syscall`, and `errno`.

::simple-task
---
:tasks: tasks
:name: verify_port_exhaustion
---
#active
Waiting for a port probe report that ends in port exhaustion...

#completed
The probe ran out of ephemeral ports.
::

On the test VM, `ip_local_port_range` was `32768 60999`.
The probe held 28,232 listeners, and then `listen()` failed with `errno` 98 (`EADDRINUSE`).
That count is the full width of the range: 60999 - 32768 + 1 = 28,232.
Every implicit bind takes one port from this range, so one address cannot hold more implicitly bound listeners than the range is wide.
A TCP port is a 16-bit number, so even the full port space gives at most 65,535 ports per address.
More processes do not help, because all processes on one address share its ports.
The count on your VM depends on the kernel and on the ports that other sockets already use.

::hint-box
---
:summary: "Hint: The check does not pass"
---

The check accepts only a run that stopped at `listen()` with `errno` 98 (`EADDRINUSE`) after it used up the ephemeral range.
Another `errno` means that a different limit was hit first, such as the open file limit.
Such a run shows nothing about ports.
Run the probe again and compare `failed_syscall`, `errno`, and `events` in the new report.
::

## 3. Add addresses with AnyIP

Predict whether two IPv6 addresses can use the **same port** at the same time.
The next probe creates a disposable network namespace and adds a `local` route for the documentation prefix `2001:db8:1234:5678::/64`.
Then it starts two C servers on port 8081.
One binds `2001:db8:1234:5678::1`, and the other binds `2001:db8:1234:5678::2`.

```bash
sudo python3 /opt/15m-lab/toolbox/experiment.py anyip
cat /var/lib/15m-lab/runs/*/anyip.json
```

The two replies should be `alpha` and `beta`.

::simple-task
---
:tasks: tasks
:name: verify_anyip
---
#active
Waiting for two IPv6 servers to answer on the same port...

#completed
Both addresses answered on port 8081.
::

A `local` route makes the kernel accept traffic for a whole prefix as local, without assigning each address to an interface.
This technique is called AnyIP.
On this 6.1 kernel, the explicit IPv6 binds still failed with `EADDRNOTAVAIL` until the probe set `net.ipv6.ip_nonlocal_bind=1`.
The probe sets it only inside the disposable namespace, so the rest of the VM keeps the default.
The [kernel sysctl documentation](https://docs.kernel.org/networking/ip-sysctl.html) describes this setting.

The kernel identifies a listener by its address and port together.
Each new address brings its own full set of ports, so addresses scale where processes on one address did not.
Two other fixes might come to mind: many more network cards, or a wider port field in TCP.
Extra cards add hardware and drivers for something that a single route already gives.
A wider port field would change the TCP header that every other host expects.
The runtime in step 6 uses the same idea with private IPv4 addresses.

## 4. One process per address

Predict the memory cost if every address gets its own Linux process.
The probe starts tiny C servers one by one in a cgroup with a **32 MiB** memory limit.
It stops when the cgroup records an OOM kill, and then it removes all the servers.
It never starts more than 350 processes.

```bash
sudo python3 /opt/15m-lab/toolbox/experiment.py process
cat /var/lib/15m-lab/runs/*/process.json
```

Compare `peak_live`, `first_ten_pss_bytes`, `memory_peak`, and `extrapolated_15m_bytes`.

::simple-task
---
:tasks: tasks
:name: verify_process_cost
---
#active
Waiting for a process probe report with a cgroup OOM kill...

#completed
The process probe reached its memory limit.
::

On the test VM, the cgroup reached its limit at about 210 processes, which is about 160 KB per process.
At that rate, 15 million processes would need about 2.4 TB.
Your numbers may differ, because the cost depends on the executable, the shared pages, the kernel, and the allocator.
The OOM kill stays inside the probe's cgroup.

## 5. Do idle kernel sockets cost nothing?

Before you run the next probe, calculate `15,000,000 × 16` bytes.
It is the memory for one 16-byte task record per listener, which the runtime in step 6 uses.
Then predict whether **unbound, idle kernel TCP sockets** cost any memory.
The probe creates TCP sockets without calling `listen()`, so it cannot run out of ports.
It runs in a cgroup with a **64 MiB** limit.

```bash
sudo python3 /opt/15m-lab/toolbox/experiment.py socket
cat /var/lib/15m-lab/runs/*/socket.json
```

Look at `max_observed_count`, `memory_peak`, `slab_peak_observed`, and `events.oom_kill`.

::simple-task
---
:tasks: tasks
:name: verify_kernel_socket_cost
---
#active
Waiting for a socket probe report with a cgroup OOM kill...

#completed
The idle sockets filled the probe's memory limit.
::

The task records take 240,000,000 bytes, which is about 229 MiB.
Idle kernel sockets cost far more per entry.
On the test VM, the cgroup hit its limit at about 18,000 sockets, which is about 3.7 KiB per socket.
Most of that memory was kernel slab.
The probe prints its count every 1,000 sockets, so the real count at the OOM kill was a little higher.
At 3.7 KiB each, 15 million kernel sockets would need about 56 GB.
This is why the listeners in step 6 live in user space.

## 6. Fifteen million listeners in one process

The runtime in `runtime/src/` is a Rust program built on [`smoltcp`](https://github.com/smoltcp-rs/smoltcp), a TCP/IP stack that runs in user space.
On dev-01, Linux routes `10.0.0.0/8` to a TUN device called `smolbench`.
The runtime reads and writes raw IP packets on that device.
Each address has a 16-byte `Task` record and a `smoltcp` TCP listening socket with 48-byte receive and transmit buffers.
A packet selects its listener by destination address, and the response body is the listener's number, starting from 1.
State for a connection exists only while the connection is open.
Read `runtime/src/worker.rs` to see the layout.

The runtime serves one fixed HTTP response.
It does not run compiled C programs or intercept their system calls.

Start with small counts.
In the **Server** tab, start 1,000 listeners and check the status:

```bash
sudo /opt/15m-lab/toolbox/runtime.sh start 1000
sudo /opt/15m-lab/toolbox/runtime.sh status
```

When the status shows `"ready": true`, probe the listeners from the **Client** tab:

```bash
python3 ~/15m-lab/toolbox/probe_client.py --count 1000 --check-outside
```

The probe sends requests to the first, middle, and last addresses and to five random ones.
It expects a refused connection from the first address after the range.
Repeat both steps with `100000` and `1000000`.

Note the `memory_peak` value in the status output for each count.
On the test VM, the 1,000,000-listener run peaked at about 618 MB, which is about 618 bytes per listener.
Projected to 15 million, that is about 9.3 GB.
The runtime runs in a systemd service with `MemoryMax=9G` (9,663,676,416 bytes), which leaves room for the rest of the VM.
The buffers are 48 bytes because the longest response, from listener 15000000, is 46 bytes.
An earlier build of this runtime with 64-byte buffers used about 32 more bytes per listener, which is about 480 MB more at this scale.

Now start the full run in the **Server** tab.
The runtime is a prebuilt release binary.
Do not build anything during the run, because a build needs memory that the run does not leave free.

```bash
sudo /opt/15m-lab/toolbox/runtime.sh start 15000000
sudo /opt/15m-lab/toolbox/runtime.sh status
journalctl -u 15m-runtime.service -n 20 --no-pager
```

The start takes about 5 to 15 seconds.
When the status shows `"ready": true`, run the probes in the **Client** tab:

```bash
python3 ~/15m-lab/toolbox/probe_client.py --count 15000000 --check-outside
curl --noproxy '*' http://10.0.0.1:8080/
curl --noproxy '*' http://10.114.112.224:8080/
curl --noproxy '*' http://10.228.225.192:8080/
```

The three responses should be `1`, `7500000`, and `15000000`.

The last check runs on client-01.
It reads the live process through a read-only status service on dev-01, and it checks the service's cgroup and the free memory of the VM.
Then it sends HTTP requests to sampled addresses and to the first address after the range.
At the end, it confirms that the process ID stayed the same and that the counter of accepted connections grew.
A run with fewer listeners does not pass.

::simple-task
---
:tasks: tasks
:name: verify_runtime_tun
---
#active
Waiting for 15,000,000 listeners to answer from client-01...

#completed
All 15,000,000 listeners are up, and the sampled ones answered.
::

::hint-box
---
:summary: "Hint: The runtime does not start"
---

Read the service log with `journalctl -u 15m-runtime.service -n 50 --no-pager`, and check the status with `runtime.sh status`.
`Failed with result 'oom-kill'` means that the server VM has too little memory for the run.
Compare `MemTotal` in `/proc/meminfo` with the 10 GiB that the full run needs.
On client-01, `ip route get 10.0.0.1` should show `via 172.16.0.2`.
To go back to the starting state, run `reset.sh` from `/opt/15m-lab/toolbox/` with `sudo`.
It stops the lab services and moves the old reports to `/var/lib/15m-lab/archive/`.
::

## What the numbers show

On the test VM, the full run peaked at 9,258,868,736 bytes in its cgroup, which is about 617 bytes per listener.
The VM still had about 870 MiB of memory available.
The table compares the three ways to give every address its own listener.

| Approach | Measured cost per address | Projected for 15 million |
|---|---:|---:|
| One Linux process | about 160 KB | about 2.4 TB |
| One idle kernel socket | about 3.7 KiB | about 56 GB |
| One `smoltcp` listener in one process | about 617 bytes | about 9.3 GB |

The result shows 15 million idle listeners in memory that answer sampled requests.
It does not measure throughput or how many connections the runtime can hold open at the same time.
