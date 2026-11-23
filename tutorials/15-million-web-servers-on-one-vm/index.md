---
kind: tutorial

title: Can One VM Host 15 Million Web Servers?

description: |
  All credit to the original article "15 million web servers on one VM" (kapteko.com).
  Edit, compile, and run small C and Rust programs while reproducing the Linux limits behind the source article:
  ephemeral ports, per-process memory, and idle kernel sockets. Then run 15,000,000 smoltcp listeners in one
  user-space process and send requests to them. The final step needs a 10 GiB VM.

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
    run: |
      /usr/bin/python3 /opt/15m-lab/tasks/verify_baseline.py --hint-file /var/lib/15m-lab/hints/verify_baseline_http.txt
    hintcheck: |
      cat /var/lib/15m-lab/hints/verify_baseline_http.txt 2>/dev/null
      rm -f /var/lib/15m-lab/hints/verify_baseline_http.txt
      exit 0

  verify_port_exhaustion:
    run: |
      /usr/bin/python3 /opt/15m-lab/tasks/verify_evidence.py port --hint-file /var/lib/15m-lab/hints/verify_port_exhaustion.txt
    hintcheck: |
      cat /var/lib/15m-lab/hints/verify_port_exhaustion.txt 2>/dev/null
      rm -f /var/lib/15m-lab/hints/verify_port_exhaustion.txt
      exit 0

  verify_anyip:
    run: |
      /usr/bin/python3 /opt/15m-lab/tasks/verify_evidence.py anyip --hint-file /var/lib/15m-lab/hints/verify_anyip.txt
    hintcheck: |
      cat /var/lib/15m-lab/hints/verify_anyip.txt 2>/dev/null
      rm -f /var/lib/15m-lab/hints/verify_anyip.txt
      exit 0

  verify_process_cost:
    needs:
      - verify_indexed_server
    run: |
      /usr/bin/python3 /opt/15m-lab/tasks/verify_evidence.py process --hint-file /var/lib/15m-lab/hints/verify_process_cost.txt
    hintcheck: |
      cat /var/lib/15m-lab/hints/verify_process_cost.txt 2>/dev/null
      rm -f /var/lib/15m-lab/hints/verify_process_cost.txt
      exit 0

  verify_kernel_socket_cost:
    needs:
      - verify_rust_context
    run: |
      /usr/bin/python3 /opt/15m-lab/tasks/verify_evidence.py socket --hint-file /var/lib/15m-lab/hints/verify_kernel_socket_cost.txt
    hintcheck: |
      cat /var/lib/15m-lab/hints/verify_kernel_socket_cost.txt 2>/dev/null
      rm -f /var/lib/15m-lab/hints/verify_kernel_socket_cost.txt
      exit 0

  verify_indexed_server:
    run: |
      /usr/bin/python3 /opt/15m-lab/tasks/verify_indexed.py --hint-file /var/lib/15m-lab/hints/verify_indexed_server.txt
    hintcheck: |
      cat /var/lib/15m-lab/hints/verify_indexed_server.txt 2>/dev/null
      rm -f /var/lib/15m-lab/hints/verify_indexed_server.txt
      exit 0

  verify_rust_context:
    run: |
      /usr/bin/python3 /opt/15m-lab/tasks/verify_rust.py --hint-file /var/lib/15m-lab/hints/verify_rust_context.txt
    hintcheck: |
      cat /var/lib/15m-lab/hints/verify_rust_context.txt 2>/dev/null
      rm -f /var/lib/15m-lab/hints/verify_rust_context.txt
      exit 0

  verify_runtime_tun:
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

The full 15,000,000-listener run needs the 10 GiB VM. On the free tier's 4 GiB VM, steps 1 to 5 and the
1,000,000-listener run still work. In our test, the 15,000,000-listener process ran out of memory after about
5 million listeners, so the final check cannot pass on that VM.
::

This is **not** my original work; all credit goes to the author of [15 million web servers on one VM](https://kapteko.com/15-million-webservers/), a very cool article that I wanted to have a one-click environment to play through
(just since some of the commands are very low level and I didn't wanna risk borking my own system).

This is a tutorial to "play along" with as you read the article (which is an absolute *must read*, since it gives way more context and background details about what's going on with the networking stack).

First, you edit a C server and hit three Linux resource limits with bounded experiments.
Then you write a small Rust context and address calculation before starting a compact runtime with 15 million listeners.

In this tutorial, a "web server" is a distinct destination IP address and port with a resident listener and a small, fixed HTTP state machine.
All 15 million of them live in one Linux process.
The final check sends a few sampled requests to them.
It does not open 15 million connections at the same time.
Every address is in the private `10.0.0.0/8` range, which is routed only inside this playground.

```text
dev-01 (4 CPUs, 10 GiB)
curl ── 10.0.0.0/8 route ── smolbench (TUN) ── smoltcp ── HTTP task
```

The read-only lab files are in `/opt/15m-lab`, and `~/15m-lab` is a link to that directory.
The starter code that you edit is in `/home/laborant/15m-work`.
The commands use absolute paths, so you can run them from any directory.
The privileged commands use fixed sudo rules. `sudo` works only for the exact commands in this tutorial, and `sudo -l` lists them. The process loops in steps 2 and 4 and the socket loop in step 5 run inside small memory cgroups, so the VM stays usable after each OOM kill. The wrapper prints the kernel's `memory.events` counter and saves a report in `/var/lib/15m-lab/runs/`.

## 1. First HTTP response

Open `/home/laborant/15m-work/server.c`. It creates a socket, accepts connections, and sends a small HTTP reply, but the `listen()` call is missing. Compile and run it once to see the error:

```bash
cc -O2 -Wall -Wextra -Werror -std=c11 /home/laborant/15m-work/server.c -o /home/laborant/15m-work/server
/home/laborant/15m-work/server
```

It prints:

```text
port=0
accept: Invalid argument
```

The `listen()` call belongs at the step 1 TODO, before the `getsockname()` call:

```c
    // TODO (step 1): Call listen(server, 128) here and handle its error.

    if (argc == 1) {
        struct sockaddr_in address;
        socklen_t length = sizeof(address);
        if (getsockname(server, (struct sockaddr *)&address, &length) < 0) {
```

Replace the TODO comment with the article's `listen()` call:

```c
if (listen(server, 128) < 0) { perror("listen"); return 1; }
```

Recompile the edited file, start the server, and send it a request:

```bash
cc -O2 -Wall -Wextra -Werror -std=c11 /home/laborant/15m-work/server.c -o /home/laborant/15m-work/server
PORT_FILE=/tmp/15m-baseline.port /home/laborant/15m-work/server >/tmp/15m-baseline.log 2>&1 &
for _ in $(seq 1 20); do [ -s /tmp/15m-baseline.port ] && break; sleep 0.1; done
cat /tmp/15m-baseline.log
curl --noproxy '*' -w '\n' "http://127.0.0.1:$(cat /tmp/15m-baseline.port)/"
```

The log shows the port that Linux picked, and `curl` prints the response body. Your port number will differ:

```text
port=38407
ok
```

Add `-i` to the `curl` command to see the `HTTP/1.0 200 OK` status line as well.

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
To see them, run a second copy with `strace -e trace=network /home/laborant/15m-work/server` and send it a request.
On x86-64, `strace` shows `recv()` and `send()` as `recvfrom()` and `sendto()`, because glibc implements them with those system calls.

## 2. How many unbound listeners fit?

The article's first loop starts the no-argument server 15 million times. Each copy makes one unbound TCP listener. Run this version of the loop:

```bash
sudo /opt/15m-lab/toolbox/bounded.sh article 'for ((i=1; i<=15000000; i++)); do echo "$i"; /home/laborant/15m-work/server & done; wait'
```

> This command differs from the article's loop in three ways.
> Bash rejects the article's `&;`, so `&` alone ends each command here.
> GNU `seq` rejects the underscores in `15_000_000`, so Bash's arithmetic `for` counts to 15,000,000 instead. It also avoids building a 15-million-word list before the first server starts.
> The `bounded.sh` wrapper runs the loop in a 32 MiB memory cgroup, so the VM stays usable when the memory runs out.
> This cap stops the loop after fewer than 200 servers.
> Without the cap, the loop on the 10 GiB VM stops at about 26,400 servers, when `fork()` fails at the task limit of your user's systemd slice. That is still before the ephemeral ports run out.

The loop reaches the process-memory limit before it runs out of ports.
The wrapper first prints a `Killed` message for the loop's shell. On the test VM, the output ended like this:

```text
136
port=52579
137
port=46695
port=57573
port=57923
port=59383
port=40821
memory.peak=33554432 bytes; memory.events oom_kill=2
Out of memory
report=/var/lib/15m-lab/runs/1795450609-1050/article.json
```

The numbers are the last indexes that the loop attempted. Each `port=` line comes from a server that started and got an ephemeral port.
A non-zero `oom_kill` counter means that the kernel killed processes in the cgroup when it ran out of memory.
This is why a loop that starts a process for each listener does not isolate the port limit on this VM.

Now we'll use a different approach to keep all the listeners in one C process and measure the port limit alone. This is the main loop of `/opt/15m-lab/baseline/port_exhaust.c`:

```c
while (count < requested) {
    if (count == capacity) {
        fprintf(stderr, "the descriptor array filled before ports ran out\n");
        break;
    }
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) { failed_errno = errno; syscall_name = "socket"; break; }
    if (listen(fd, 1) < 0) {
        failed_errno = errno;
        syscall_name = "listen";
        close(fd);
        break;
    }
    fds[count++] = fd;
}
```

`requested` is the command-line argument, which is 15,000,000 here. Each iteration calls `socket()` and `listen()` without `bind()`, then keeps the open socket in `fds`. The loop stops as soon as `listen()` fails.

::remark-box
The `port_exhaust` command takes about 25 seconds and prints nothing until it finishes, because its output goes to files.
Each implicit bind searches the range for a free port, so each `listen()` call is slower than the one before it.
::

Run it in a fresh network namespace so that no other program uses a port from that namespace:

```bash
sudo ip netns add 15m-ports
sudo ip -n 15m-ports link set lo up
sudo ip netns exec 15m-ports /opt/15m-lab/baseline/bin/port_exhaust 15000000 > /tmp/15m-port.json 2>/tmp/15m-port.err
status=$?
sudo ip netns del 15m-ports
```

Check the listener count and the exit status of `port_exhaust`:

```bash
jq -r '.count' /tmp/15m-port.json
printf 'program exited with error %s\n' "$status"
```

With the test VM's port range, the two lines are:

```text
28232
program exited with error 1
```

Then check the port range, the error message, and the full JSON report:

```bash
sysctl net.ipv4.ip_local_port_range
cat /tmp/15m-port.err
jq . /tmp/15m-port.json
```

On the test VM, the output was:

```text
net.ipv4.ip_local_port_range = 32768	60999
listen: Address already in use
{
  "range_low": 32768,
  "range_high": 60999,
  "count": 28232,
  "maximum": 15000000,
  "failed_syscall": "listen",
  "errno": 98
}
```

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

The C loop held 28,232 listeners, and then `listen()` failed with `errno` 98 (`EADDRINUSE`).
That count is the full width of the range: 60999 - 32768 + 1 = 28,232.
Every implicit bind takes one port from this range, so one address cannot hold more implicitly bound listeners than the range is wide.
A TCP port is a 16-bit number, so even the full port space gives at most 65,535 ports per address.
More processes do not help, because all processes on one address share its ports.
The count on your VM depends on its ephemeral range. The fresh namespace keeps unrelated sockets out of the result.

::hint-box
---
:summary: "Hint: The check does not pass"
---

The check accepts only a run that stopped at `listen()` with `errno` 98 (`EADDRINUSE`) after it used up the ephemeral range.
Another `errno` means that a different limit was hit first, such as the open file limit.
Such a run shows nothing about ports. Check your open file limit with `ulimit -n`.
::

## 3. Add addresses with AnyIP

Predict whether two IPv6 addresses can use the **same port** at the same time.
Add the article's `local` route for the documentation prefix `2001:db8:1234:5678::/64`.
Then start two C servers on port 8081.
One binds `2001:db8:1234:5678::1`, and the other binds `2001:db8:1234:5678::2`.

```bash
sudo ip -6 route add local 2001:db8:1234:5678::/64 dev lo
sudo sysctl -w net.ipv6.ip_nonlocal_bind=1
/opt/15m-lab/baseline/bin/bound_server 2001:db8:1234:5678::1 8081 alpha &
/opt/15m-lab/baseline/bin/bound_server 2001:db8:1234:5678::2 8081 beta &
sleep 0.2
curl -g -6 --noproxy '*' -w '\n' 'http://[2001:db8:1234:5678::1]:8081/'
curl -g -6 --noproxy '*' -w '\n' 'http://[2001:db8:1234:5678::2]:8081/'
```

The `&` starts each server in the background, so the shell moves on to the next command right away.
`sleep 0.2` is only there for when you paste the whole block at once. It gives both servers time to bind their addresses before the first `curl` connects.

`sysctl` confirms the new setting, and each address answers with its own reply:

```text
net.ipv6.ip_nonlocal_bind = 1
alpha
beta
```

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
On this 6.1 kernel, the explicit IPv6 binds still failed with `EADDRNOTAVAIL` until `net.ipv6.ip_nonlocal_bind=1` was set.
The route and sysctl apply only to this disposable VM. `sudo /opt/15m-lab/toolbox/reset.sh` removes them.
The [kernel sysctl documentation](https://docs.kernel.org/networking/ip-sysctl.html) describes this setting.

The kernel identifies a listener by its address and port together.
Each new address brings its own full set of ports, so addresses scale where processes on one address did not.
Two other fixes might come to mind: many more network cards, or a wider port field in TCP.
Extra cards add hardware and drivers for something that a single route already gives.
A wider port field would change the TCP header that every other host expects.
The runtime in step 6 uses the same idea with private IPv4 addresses.

## 4. One process per address

Predict the memory cost if every address gets its own Linux process.
Return to your editable `/home/laborant/15m-work/server.c`. With an index argument, it binds to a fixed address. This is its indexed mode with the step 4 TODO:

```c
    if (argc == 2) {
        struct sockaddr_in address = {.sin_family = AF_INET, .sin_port = htons(8081)};
        // TODO (step 4): Shift the base address by index, as in the article.
        address.sin_addr.s_addr = htonl(0x7f000001u);
        if (bind(server, (struct sockaddr *)&address, sizeof(address)) < 0) {
            perror("bind"); return 1;
        }
    }
```

`0x7f000001` is `127.0.0.1`, so every indexed process binds the same `127.0.0.1:8081` address. Change the line under the TODO to shift the base address by the index, as the article does:

```c
address.sin_addr.s_addr = htonl(0x7f000001u + (uint32_t)index);
```

The first two indexes now use `127.0.0.2` and `127.0.0.3`. Compile your change and start one server on each address:

```bash
cc -O2 -Wall -Wextra -Werror -std=c11 /home/laborant/15m-work/server.c -o /home/laborant/15m-work/server
/home/laborant/15m-work/server 1 & first_pid=$!
/home/laborant/15m-work/server 2 & second_pid=$!
sleep 0.2
curl --noproxy '*' -w '\n' 'http://127.0.0.2:8081/'
curl --noproxy '*' -w '\n' 'http://127.0.0.3:8081/'
```

As in step 3, `sleep 0.2` gives the background servers time to bind before `curl` connects when you paste the whole block at once.
Each server replies with its index:

```text
1
2
```

::simple-task
---
:tasks: tasks
:name: verify_indexed_server
---
#active
Waiting for your rebuilt C server to answer on two indexed addresses...

#completed
Both indexed C servers answered.
::

Once the check completes, stop those two test servers so they do not occupy addresses used by the loop:

```bash
kill "$first_pid" "$second_pid"
```

The article's second loop passes the index to each server. Run this version of it with a **15,000,000 upper bound**:

```bash
sudo /opt/15m-lab/toolbox/bounded.sh process 'for ((i=1; i<=15000000; i++)); do echo "$i"; /home/laborant/15m-work/server "$i" & done; wait'
```

> This command differs from the article's loop for the same reasons as the loop in step 2.
> Bash rejects `&;`, GNU `seq` rejects `15_000_000`, and the wrapper keeps the loop in a 32 MiB cgroup.
> The wrapper also runs the loop as `laborant`, limits it to 45 seconds and 400 processes, and removes the whole group when the kernel records an OOM kill.

After the `Killed` message, the output on the test VM ended like this:

```text
161
162
163
164
165
166
167
168
memory.peak=33554432 bytes; memory.events oom_kill=2
Out of memory
report=/var/lib/15m-lab/runs/1795450688-1265/process.json
```

The last line is the path of a JSON report. Read the report with `jq`:

```bash
jq . /var/lib/15m-lab/runs/*/process.json
```

If you ran the loop more than once, `jq` prints one report for each run. The report from the test VM was:

```json
{
  "schema": 1,
  "kind": "process",
  "unix_time": 1795450688,
  "cgroup_limit": 33554432,
  "memory_peak": 33554432,
  "observed_count": 168,
  "requested_count": 0,
  "bytes_per_item_estimate": 199728.7619047619,
  "slab_peak_observed": 3746144,
  "events": {
    "oom_kill": 2
  },
  "ok": true
}
```

`bytes_per_item_estimate` is the peak memory divided by the last index. The estimate is approximate because several forks can race with the OOM kill.

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

On the test run above, the loop reached index 168 before the 32 MiB OOM kill. That is roughly 200 KB per attempt, or about 3 TB for 15 million processes. This is only a rough projection: the last index is not a count of live processes, and Bash and cgroup bookkeeping also use memory. Your result can differ with the executable, shared pages, kernel, and allocator.
The article reports about 1.5 MB per server, or about 20 TB for 15 million.
The OOM kill stays inside the probe's cgroup.

## 5. Do idle kernel sockets cost nothing?

The article sketches a Rust `Context` with a program counter and two file descriptors. Open `/home/laborant/15m-work/context.rs`. The starter program checks the context size and calculates the first, middle, and last listener addresses. Compile and run it before editing:

```bash
rustc /home/laborant/15m-work/context.rs -o /home/laborant/15m-work/context
/home/laborant/15m-work/context
```

It panics because the context is only eight bytes:

```text
thread 'main' panicked at /home/laborant/15m-work/context.rs:19:5:
assertion `left == right` failed: add both file descriptor fields
  left: 8
 right: 16
note: run with `RUST_BACKTRACE=1` environment variable to display a backtrace
```

This is the starter's `struct Context`:

```rust
struct Context {
    pc: u64,
    // TODO (step 5): Add fd_server and fd_client as i32 fields.
}
```

Replace the TODO comment with the two missing fields:

```rust
fd_server: i32,
fd_client: i32,
```

Then find `listener_address()`:

```rust
fn listener_address(_index: u32) -> Ipv4Addr {
    let base = u32::from(Ipv4Addr::new(10, 0, 0, 1));
    // TODO (step 5): Return the address for this 1-based listener index.
    Ipv4Addr::from(base)
}
```

The starter does not use its parameter yet. The leading underscore in `_index` tells the Rust compiler that this is on purpose, so the first compile prints no warning.
Rename the parameter to `index`, and shift the base address by the 1-based listener index:

```rust
fn listener_address(index: u32) -> Ipv4Addr {
    let base = u32::from(Ipv4Addr::new(10, 0, 0, 1));
    Ipv4Addr::from(base + index - 1)
}
```

Compile and run your Rust code again:

```bash
rustc /home/laborant/15m-work/context.rs -o /home/laborant/15m-work/context
/home/laborant/15m-work/context
```

It should print:

```text
context_bytes=16
all_contexts_bytes=240000000
1 -> 10.0.0.1
7500000 -> 10.114.112.224
15000000 -> 10.228.225.192
```

::simple-task
---
:tasks: tasks
:name: verify_rust_context
---
#active
Waiting for your compiled Rust context and address calculation...

#completed
The Rust context and addresses are correct.
::

Your Rust program models the article's context. The full runtime in step 6 has its own 16-byte `Task` layout.
Now predict whether **unbound, idle kernel TCP sockets** cost any memory.
This is the main loop of `/opt/15m-lab/baseline/socket_cost.c`:

```c
while (count < requested) {
    if (count == capacity) {
        fprintf(stderr, "the descriptor array filled before memory ran out\n");
        error = EMFILE;
        break;
    }
    int fd = socket(AF_INET, SOCK_STREAM, 0); /* deliberately unbound */
    if (fd < 0) { error = errno; break; }
    fds[count++] = fd;
    if (count % 1000 == 0) { printf("count=%zu\n", count); fflush(stdout); }
}
```

It follows the article's 10,000,000-socket loop. It creates TCP sockets without calling `listen()`, so it cannot run out of ports. It prints a `count=` line every 1,000 sockets. Run it in a **64 MiB** cgroup:

```bash
sudo /opt/15m-lab/toolbox/bounded.sh socket '/opt/15m-lab/baseline/bin/socket_cost 10000000'
```

After the `Killed` message, the output on the test VM ended like this:

```text
count=11000
count=12000
count=13000
count=14000
count=15000
count=16000
count=17000
count=18000
memory.peak=67108864 bytes; memory.events oom_kill=3
Out of memory
report=/var/lib/15m-lab/runs/1795450704-1501/socket.json
```

Read the report with `jq`:

```bash
jq . /var/lib/15m-lab/runs/*/socket.json
```

The report from the test VM was:

```json
{
  "schema": 1,
  "kind": "socket",
  "unix_time": 1795450704,
  "cgroup_limit": 67108864,
  "memory_peak": 67108864,
  "observed_count": 18000,
  "requested_count": 10000000,
  "bytes_per_item_estimate": 3728.2702222222224,
  "slab_peak_observed": 66733856,
  "events": {
    "oom_kill": 3
  },
  "ok": true
}
```

`slab_peak_observed` is the highest kernel slab memory that the wrapper saw in the cgroup.

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

The 15 million 16-byte contexts take 240,000,000 bytes, which is about 229 MiB.
Idle kernel sockets cost far more per entry.
On the test VM, the cgroup hit its limit at about 18,000 sockets, which is about 3.7 KB per socket.
Most of that memory was kernel slab.
The probe prints its count every 1,000 sockets, so the real count at the OOM kill was a little higher.
At 3.7 KB each, 15 million kernel sockets would need about 56 GB.
This is why the listeners in step 6 live in user space.

## 6. Fifteen million listeners in one process

The runtime in `/opt/15m-lab/runtime/src/` is a Rust program built on [`smoltcp`](https://github.com/smoltcp-rs/smoltcp), a TCP/IP stack that runs in user space.
On dev-01, Linux routes `10.0.0.0/8` to a TUN device called `smolbench`.
The runtime reads and writes raw IP packets on that device.
Each address has a 16-byte `Task` record and a `smoltcp` TCP listening socket with 48-byte receive and transmit buffers.
These are the parts of `/opt/15m-lab/runtime/src/worker.rs` that define them:

```rust
const BUFFER_SIZE: usize = 48;

pub(crate) struct Task {
    phase: u32,
    pending: u32,
    requests: u64,
}
const _: () = assert!(std::mem::size_of::<Task>() == 16);

pub(crate) struct Resident {
    sockets: SocketSet<'static>,
}
const _: () = assert!(std::mem::size_of::<Resident>() == 24);

fn fresh_socket_set() -> SocketSet<'static> {
    let mut set = SocketSet::new(Vec::with_capacity(1));
    set.add(Socket::new(
        SocketBuffer::new(vec![0; BUFFER_SIZE]),
        SocketBuffer::new(vec![0; BUFFER_SIZE]),
    ));
    set
}
```

A `Resident` holds the set with the one listening socket of its address.
A packet selects its listener by destination address, and the response body is the listener's number, starting from 1.
State for a connection exists only while the connection is open.

The runtime serves one fixed HTTP response.
It does not run compiled C programs or intercept their system calls.

Start with small counts.
Start 1,000 listeners and check the status:

```bash
sudo /opt/15m-lab/toolbox/runtime.sh start 1000
sudo /opt/15m-lab/toolbox/runtime.sh status | jq .
```

The status is a JSON object. On the test VM, the output was:

```text
Started 1000 listeners. Watch: journalctl -fu 15m-runtime.service
{
  "accepted": 0,
  "backend": "tun",
  "base": "10.0.0.1",
  "cgroup": {
    "exe": "/opt/15m-lab/bin/million-listeners",
    "exe_sha256": "340b9cfc26083d8955250b4d15d54fecbf457abfd4053d122dda9b7103b908c8",
    "memory_current": "1642496",
    "memory_events": "low 0\nhigh 0\nmax 0\noom 0\noom_kill 0\noom_group_kill 0",
    "memory_max": "9663676416",
    "memory_peak": "1961984",
    "path": "/sys/fs/cgroup/system.slice/15m-runtime.service",
    "pss_bytes": 1333248,
    "rss_bytes": 3018752,
    "vm_mem_available_kib": 9891276,
    "vm_mem_total_kib": 10264988
  },
  "initialized": 1000,
  "last": "10.0.3.232",
  "listener_bytes": 24,
  "pid": 1556,
  "port": 8080,
  "ready": true,
  "requested": 1000,
  "startup_ms": 0,
  "task_bytes": 16
}
```

When the status shows `"ready": true`, request the first and last listeners:

```bash
curl --noproxy '*' -w '\n' 'http://10.0.0.1:8080/'
curl --noproxy '*' -w '\n' 'http://10.0.3.232:8080/'
```

The responses are the listener numbers:

```text
1
1000
```

Repeat the server start with `100000` and `1000000`, then request their last addresses, `10.1.134.160` and `10.15.66.64`. They answer `100000` and `1000000`. The check at the end of the tutorial also samples other addresses and rejects an address beyond the range.

Note the `memory_peak` value in the `cgroup` part of the status output for each count.
On the test VM, the 1,000,000-listener run peaked at about 618 MB, which is about 618 bytes per listener.
Projected to 15 million, that is about 9.3 GB.
The runtime runs in a systemd service with `MemoryMax=9G` (9,663,676,416 bytes), which leaves room for the rest of the VM.
The buffers are 48 bytes because the longest response, from listener 15000000, is 46 bytes.
An earlier build of this runtime with 64-byte buffers used about 32 more bytes per listener, which is about 480 MB more at this scale.

Now start the full run.
The runtime is a prebuilt release binary.
Do not build anything during the run, because a build needs memory that the run does not leave free.

```bash
sudo /opt/15m-lab/toolbox/runtime.sh start 15000000
sudo /opt/15m-lab/toolbox/runtime.sh status | jq .
journalctl -u 15m-runtime.service -n 20 --no-pager
```

::remark-box
`Started 15000000 listeners` means the service launched with that target.
An immediate status may show `requested: 15000000`, `initialized: 0`, and `ready: false` while it builds the listeners.
The `last` address is calculated from the target count.
The 9 GiB `memory_max` is the service's configured limit, even on a 4 GiB VM.
Zero OOM counters in this early snapshot do not mean the full run will finish.
The last 20 journal lines can include an earlier run, so compare their timestamps and process IDs.
::

On the 10 GiB VM, initialization takes about 5 to 15 seconds after the service starts.
Run the `status` command again until it shows `"ready": true` and `"initialized": 15000000`.
The journal shows the listener count as it grows. On the test VM, its last lines were:

```text
Nov 23 16:18:43 dev-01 systemd[1]: Started 15m-runtime.service - 15 million smoltcp HTTP listeners.
Nov 23 16:18:43 dev-01 million-listeners[1573]: initialized=1000
Nov 23 16:18:43 dev-01 million-listeners[1573]: initialized=100000
Nov 23 16:18:44 dev-01 million-listeners[1573]: initialized=1000000
Nov 23 16:18:47 dev-01 million-listeners[1573]: initialized=5000000
Nov 23 16:18:50 dev-01 million-listeners[1573]: initialized=10000000
Nov 23 16:18:54 dev-01 million-listeners[1573]: initialized=15000000
Nov 23 16:18:54 dev-01 million-listeners[1573]: resident_listeners_verified=15000000 rx_bytes=48 tx_bytes=48
```

When the status shows `"ready": true`, request three addresses:

```bash
curl --noproxy '*' -w '\n' 'http://10.0.0.1:8080/'
curl --noproxy '*' -w '\n' 'http://10.114.112.224:8080/'
curl --noproxy '*' -w '\n' 'http://10.228.225.192:8080/'
```

The responses are the first, middle, and last listener numbers:

```text
1
7500000
15000000
```

The last check reads the live process through a read-only status service, and it checks the service's cgroup and the free memory of the VM.
Then it sends HTTP requests to sampled addresses and to the first address after the range.
At the end, it confirms that the process ID stayed the same and that the counter of accepted connections grew.
A run with fewer listeners does not pass.

::simple-task
---
:tasks: tasks
:name: verify_runtime_tun
---
#active
Waiting for 15,000,000 listeners to answer...

#completed
All 15,000,000 listeners are up, and the sampled ones answered.
::

::hint-box
---
:summary: "Hint: The runtime does not start"
---

Read the service log with `journalctl -u 15m-runtime.service -n 50 --no-pager`, and check the status with `sudo /opt/15m-lab/toolbox/runtime.sh status | jq .`.
`Failed with result 'oom-kill'` means that the VM has too little memory for the run.
Compare `MemTotal` in `/proc/meminfo` with the 10 GiB that the full run needs.
`ip route get 10.0.0.1` should show `dev smolbench`.
To go back to the starting state, run `sudo /opt/15m-lab/toolbox/reset.sh`.
It stops the lab services and moves the old reports to `/var/lib/15m-lab/archive/`.
::

## What the numbers show

On the test VM, the full run peaked at 9,258,868,736 bytes in its cgroup, which is about 617 bytes per listener.
The VM still had about 830 MiB of memory available.
The table compares the three ways to give every address its own listener.

| Approach | Measured cost per address | Projected for 15 million |
|---|---:|---:|
| One Linux process | roughly 200 KB | roughly 3 TB |
| One idle kernel socket | about 3.7 KB | about 56 GB |
| One `smoltcp` listener in one process | about 617 bytes | about 9.3 GB |

The result shows 15 million idle listeners in memory that answer sampled requests.
It does not measure throughput or how many connections the runtime can hold open at the same time.
