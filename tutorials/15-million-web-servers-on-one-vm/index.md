---
kind: tutorial

title: Can One VM Host 15 Million Web Servers?

description: |
  All credit to the original article "15 million web servers on one VM" (kapteko.com).
  Write and run C and Rust code while reproducing the Linux limits behind the source article:
  ephemeral ports, per-process memory, and idle kernel sockets. Then run 15,000,000 smoltcp listeners in one
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
    needs:
      - verify_indexed_server
    run: |
      /usr/bin/python3 /opt/15m-lab/tasks/verify_evidence.py process --hint-file /var/lib/15m-lab/hints/verify_process_cost.txt
    hintcheck: |
      cat /var/lib/15m-lab/hints/verify_process_cost.txt 2>/dev/null
      rm -f /var/lib/15m-lab/hints/verify_process_cost.txt
      exit 0

  verify_kernel_socket_cost:
    machine: dev-01
    needs:
      - verify_rust_context
    run: |
      /usr/bin/python3 /opt/15m-lab/tasks/verify_evidence.py socket --hint-file /var/lib/15m-lab/hints/verify_kernel_socket_cost.txt
    hintcheck: |
      cat /var/lib/15m-lab/hints/verify_kernel_socket_cost.txt 2>/dev/null
      rm -f /var/lib/15m-lab/hints/verify_kernel_socket_cost.txt
      exit 0

  verify_indexed_server:
    machine: dev-01
    run: |
      /usr/bin/python3 /opt/15m-lab/tasks/verify_indexed.py --hint-file /var/lib/15m-lab/hints/verify_indexed_server.txt
    hintcheck: |
      cat /var/lib/15m-lab/hints/verify_indexed_server.txt 2>/dev/null
      rm -f /var/lib/15m-lab/hints/verify_indexed_server.txt
      exit 0

  verify_rust_context:
    machine: dev-01
    run: |
      /usr/bin/python3 /opt/15m-lab/tasks/verify_rust.py --hint-file /var/lib/15m-lab/hints/verify_rust_context.txt
    hintcheck: |
      cat /var/lib/15m-lab/hints/verify_rust_context.txt 2>/dev/null
      rm -f /var/lib/15m-lab/hints/verify_rust_context.txt
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

The full tutorial only runs successfully in the premium tier. You can still work through the super cool article, but when
you get to the last step, you won't be able to run the full 15 million web servers in the 4GB VM.
On a 4 GiB server VM, steps 1 to 5 and the 1,000,000-listener run still work, but the kernel kills the 15,000,000-listener run after about 5 million listeners.
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
client-01 (2 CPUs, 2 GiB) ── 172.16.0.0/24 ── dev-01 (4 CPUs, 10 GiB)
       TCP probes          10/8 via dev-01        TUN → smoltcp → HTTP task
```

The read-only lab files are in `~/15m-lab` on both VMs. Edit the starter code in `~/15m-work` on the server VM.
Run the commands in steps 1 to 5 in the **Server** tab (dev-01).
Step 6 says which commands go to the **Client** tab (client-01).
The privileged commands use fixed sudo rules. The process loops in steps 2 and 4 and the socket loop in step 5 run inside small memory cgroups, so the VM stays usable after each OOM kill. The wrapper prints the kernel's `memory.events` counter and saves a report in `/var/lib/15m-lab/runs/`.

## 1. First HTTP response

Open `~/15m-work/server.c`. It creates a socket, accepts connections, and sends a small HTTP reply, but the `listen()` call is missing. Compile and run it once to see the error:

```bash
cd ~/15m-work
cc -O2 -Wall -Wextra -Werror -std=c11 server.c -o server
./server
```

It prints `port=0`, then `accept: Invalid argument`. Add the article's `listen()` call at the step 1 TODO in `server.c`, before `getsockname()`:

```c
if (listen(server, 128) < 0) { perror("listen"); return 1; }
```

Recompile the edited file, start the server, and send it a request:

```bash
cc -O2 -Wall -Wextra -Werror -std=c11 server.c -o server
PORT_FILE=/tmp/15m-baseline.port ./server >/tmp/15m-baseline.log 2>&1 &
for _ in $(seq 1 20); do [ -s /tmp/15m-baseline.port ] && break; sleep 0.1; done
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

Try the first loop from the article in the **Server** tab. Copy it as printed:

```bash
cd ~/15m-work
for i in $(seq 1 15_000_000); do echo $i; ./server &; done
```

Bash stops at `&;` with `syntax error near unexpected token ';'`. It has not run `seq` or started a server. Check the second problem separately:

```bash
seq 1 15_000_000
```

GNU `seq` rejects the underscores. The article's `28232` result cannot come from that literal Bash command. The no-argument `./server` does make an unbound TCP listener. Run a corrected loop with the article's 15,000,000 upper bound inside a 32 MiB cgroup. Bash's arithmetic `for` avoids building a 15-million-word `$(seq ...)` expansion before the servers start. The loop reaches the process-memory limit first:

```bash
sudo /opt/15m-lab/toolbox/bounded.sh article 'for ((i=1; i<=15000000; i++)); do echo "$i"; ./server & done; wait'
```

The wrapper shows the last indexes attempted, the cgroup's `oom_kill` counter, and `Out of memory`. This is why a loop that starts a process for each listener does not isolate the port limit on this VM.

Now keep all the listeners in one C process and measure the port limit alone. Read `baseline/port_exhaust.c`. Its loop has an upper bound of 15,000,000 iterations. Each iteration calls `socket()` and `listen()` without `bind()`, then keeps the successful socket open. It stops as soon as `listen()` fails. Run it in a fresh network namespace so no other program uses a port from that namespace:

```bash
sysctl net.ipv4.ip_local_port_range
sudo ip netns add 15m-ports
sudo ip -n 15m-ports link set lo up
sudo ip netns exec 15m-ports /opt/15m-lab/baseline/bin/port_exhaust 15000000 > /tmp/15m-port.json 2>/tmp/15m-port.err
status=$?
jq -r '.count' /tmp/15m-port.json
printf 'program exited with error %s\n' "$status"
sudo ip netns del 15m-ports
```

With the test VM's `32768 60999` range, the two printed lines should be:

```text
28232
program exited with error 1
```

The count and exit code come from the real C run. The loop was allowed to attempt 15,000,000 listeners, but it stopped at the first port failure. Read `/tmp/15m-port.err` to see `listen: Address already in use`. The JSON file also records `maximum: 15000000`, `range_low`, `range_high`, `failed_syscall`, and `errno`.

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
cd ~/15m-lab/baseline/bin
./bound_server 2001:db8:1234:5678::1 8081 alpha &
./bound_server 2001:db8:1234:5678::2 8081 beta &
curl -g -6 --noproxy '*' 'http://[2001:db8:1234:5678::1]:8081/'
curl -g -6 --noproxy '*' 'http://[2001:db8:1234:5678::2]:8081/'
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
Return to your editable `~/15m-work/server.c`. Its indexed mode currently binds every process to the same `127.0.0.1:8081` address. Change the step 4 TODO to shift the base address by the command-line index, as the article does:

```c
address.sin_addr.s_addr = htonl(0x7f000001u + (uint32_t)index);
```

The first two indexes now use `127.0.0.2` and `127.0.0.3`. Compile your change and start one server on each address:

```bash
cd ~/15m-work
cc -O2 -Wall -Wextra -Werror -std=c11 server.c -o server
./server 1 & first_pid=$!
./server 2 & second_pid=$!
sleep 0.2
curl --noproxy '*' http://127.0.0.2:8081/
curl --noproxy '*' http://127.0.0.3:8081/
```

The replies should be `1` and `2`.

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

Try the article's second loop as printed. It has the same `&;` and underscore syntax problems as the first one:

```bash
cd ~/15m-work
for i in $(seq 1 15_000_000); do echo $i; ./server $i &; done
```

Now run the corrected `./server "$i" &` loop with a **15,000,000 upper bound** inside a 32 MiB cgroup. Bash's arithmetic `for` avoids expanding 15 million words before any server starts. The wrapper runs the loop as `laborant`, limits it to 45 seconds and 400 processes, and removes the whole group when the kernel records an OOM kill.

```bash
cd ~/15m-work
sudo /opt/15m-lab/toolbox/bounded.sh process 'for ((i=1; i<=15000000; i++)); do echo "$i"; ./server "$i" & done; wait'
```

The tail of the output shows the last indexes attempted, the cgroup's peak memory, `oom_kill=1` or higher, and `Out of memory`. Read the report path printed by the wrapper to calculate an approximate memory cost per server. The count is approximate because several forks can race with the OOM kill.

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

On one test run, this loop reached index 179 before the 32 MiB OOM kill. Dividing the limit by that index gives roughly 190 KB per attempt, or about 2.8 TB for 15 million processes. This is only a rough projection: the last index is not a count of live processes, and Bash and cgroup bookkeeping also use memory. Your result can differ with the executable, shared pages, kernel, and allocator.
The OOM kill stays inside the probe's cgroup.

## 5. Do idle kernel sockets cost nothing?

The article sketches a Rust `Context` with a program counter and two file descriptors. Open `~/15m-work/context.rs`. The starter program checks the context size and calculates the first, middle, and last listener addresses. Compile and run it before editing:

```bash
cd ~/15m-work
rustc context.rs -o context
./context
```

It panics because the context is only eight bytes. Add the two missing fields to `struct Context`:

```rust
fd_server: i32,
fd_client: i32,
```

Then make `listener_address()` shift the base address by the 1-based listener index:

```rust
Ipv4Addr::from(base + index - 1)
```

Compile and run your Rust code again:

```bash
rustc context.rs -o context
./context
```

It should print `context_bytes=16`, `all_contexts_bytes=240000000`, and these address mappings: `1 -> 10.0.0.1`, `7500000 -> 10.114.112.224`, and `15000000 -> 10.228.225.192`.

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

Your Rust program models the article's context. The full runtime in step 6 has its own 16-byte `Task` layout in `runtime/src/worker.rs`.
Now predict whether **unbound, idle kernel TCP sockets** cost any memory.
Read `baseline/socket_cost.c`. It follows the article's 10,000,000-socket loop. It creates TCP sockets without calling `listen()`, so it cannot run out of ports. Run it in a **64 MiB** cgroup and watch the kernel memory counter rise.

```bash
cd ~/15m-lab/baseline/bin
sudo /opt/15m-lab/toolbox/bounded.sh socket './socket_cost 10000000'
```

The C program prints `count=1000`, `count=2000`, and so on. The wrapper prints the last few counts, `memory.peak`, the `oom_kill` counter, and `Out of memory`. Its report includes `slab_peak_observed`.

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

When the status shows `"ready": true`, request the first and last listeners from the **Client** tab:

```bash
curl --noproxy '*' http://10.0.0.1:8080/
curl --noproxy '*' http://10.0.3.232:8080/
```

The responses should be `1` and `1000`. Repeat the server start with `100000` and `1000000`, then request their last addresses, `10.1.134.160` and `10.15.66.64`. The check at the end of the tutorial also samples other addresses and rejects an address beyond the range.

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
When the status shows `"ready": true`, request three addresses in the **Client** tab:

```bash
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
| One Linux process | roughly 190 KB | roughly 2.8 TB |
| One idle kernel socket | about 3.7 KiB | about 56 GB |
| One `smoltcp` listener in one process | about 617 bytes | about 9.3 GB |

The result shows 15 million idle listeners in memory that answer sampled requests.
It does not measure throughput or how many connections the runtime can hold open at the same time.
