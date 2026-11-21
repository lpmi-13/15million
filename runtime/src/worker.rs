use crate::Metrics;
use smoltcp::iface::{Interface, SocketHandle, SocketSet};
use smoltcp::phy::{Device, DeviceCapabilities, Medium, RxToken, TxToken};
use smoltcp::socket::tcp::{Socket, SocketBuffer, State};
use smoltcp::time::Instant;
use smoltcp::wire::{
    EthernetFrame, EthernetProtocol, IpListenEndpoint, IpProtocol, Ipv4Packet, TcpPacket,
};
use std::collections::HashMap;
use std::io::Write;
use std::net::Ipv4Addr;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};

const PORT: u16 = 8080;
// The largest response ("15000000") is 46 bytes. A 48-byte buffer leaves
// space for it while avoiding 32 bytes of idle allocation per listener.
const BUFFER_SIZE: usize = 48;
const ACTIVE_LIMIT: usize = 65_536;
const PER_LISTENER_BACKLOG: u16 = 128;

const IDLE: u32 = 0;
const WAITING_FOR_ACCEPT: u32 = 1;
const WAITING_FOR_READ: u32 = 2;

// This is the entire resident guest state. TCP receive and transmit storage
// belongs to Resident; active flow records are allocated only after a SYN.
#[repr(C)]
#[derive(Clone, Copy, Default)]
pub(crate) struct Task {
    phase: u32,
    pending: u32,
    requests: u64,
}
const _: () = assert!(std::mem::size_of::<Task>() == 16);

impl Task {
    fn begin(&mut self) {
        assert!(self.pending < u32::from(PER_LISTENER_BACKLOG));
        self.pending += 1;
        self.phase = WAITING_FOR_ACCEPT;
    }

    fn established(&mut self) {
        assert!(self.pending > 0 && self.phase != IDLE);
        self.phase = WAITING_FOR_READ;
    }

    fn response(&self, index: usize) -> String {
        assert!(self.pending > 0 && self.phase != IDLE);
        let body = (index + 1).to_string();
        let reply = format!(
            "HTTP/1.0 200 OK\r\nContent-Length: {}\r\n\r\n{}",
            body.len(),
            body
        );
        assert!(reply.len() <= BUFFER_SIZE);
        reply
    }

    fn complete(&mut self, replied: bool) {
        assert!(self.pending > 0);
        if replied {
            self.requests = self.requests.saturating_add(1);
        }
        self.pending -= 1;
        self.phase = if self.pending == 0 {
            IDLE
        } else {
            WAITING_FOR_ACCEPT
        };
    }
}

pub(crate) struct Resident {
    sockets: SocketSet<'static>,
}
const _: () = assert!(std::mem::size_of::<Resident>() == 24);

impl Resident {
    fn new(ip: Ipv4Addr) -> Self {
        let mut sockets = fresh_socket_set();
        sockets
            .get_mut::<Socket>(SocketHandle::default())
            .listen(IpListenEndpoint::from((ip, PORT)))
            .expect("valid listener endpoint");
        Self { sockets }
    }
}

fn fresh_socket_set() -> SocketSet<'static> {
    let mut set = SocketSet::new(Vec::with_capacity(1));
    set.add(Socket::new(
        SocketBuffer::new(vec![0; BUFFER_SIZE]),
        SocketBuffer::new(vec![0; BUFFER_SIZE]),
    ));
    set
}

#[derive(Clone, Copy, Eq, Hash, PartialEq)]
struct Flow {
    index: usize,
    peer: Ipv4Addr,
    peer_port: u16,
}

#[derive(Clone, Copy, Eq, PartialEq)]
enum Phase {
    Handshake,
    Reading,
    Closing,
}

struct Active {
    sockets: SocketSet<'static>,
    phase: Phase,
}

struct Engine {
    interface: Interface,
    first: u32,
    tasks: Vec<Task>,
    listeners: Vec<Resident>,
    flows: HashMap<Flow, Active>,
    empty: SocketSet<'static>,
    metrics: Arc<Metrics>,
}

impl Engine {
    fn initialize(&mut self, count: usize) {
        for index in 0..count {
            let ip = Ipv4Addr::from(self.first + index as u32);
            self.listeners.push(Resident::new(ip));
            let initialized = index + 1;
            if initialized % 1_000 == 0 || initialized == count {
                self.metrics
                    .initialized
                    .store(initialized, Ordering::Release);
            }
            if [1_000, 100_000, 1_000_000, 5_000_000, 10_000_000, 15_000_000].contains(&initialized)
            {
                println!("initialized={initialized}");
                let _ = std::io::stdout().flush();
            }
        }
        // Count only sockets that were built and entered Listen state.
        assert_eq!(self.listeners.len(), count);
        self.metrics.initialized.store(count, Ordering::Release);
        self.metrics.startup_ms.store(
            self.metrics.started.elapsed().as_millis() as u64,
            Ordering::Release,
        );
        self.metrics.ready.store(true, Ordering::Release);
        println!(
            "resident_listeners_verified={count} rx_bytes={BUFFER_SIZE} tx_bytes={BUFFER_SIZE}"
        );
    }

    fn decode(&self, bytes: &[u8], medium: Medium) -> Option<(Flow, bool)> {
        let ipv4 = ipv4(bytes, medium)?;
        if ipv4.next_header() != IpProtocol::Tcp || ipv4.more_frags() || ipv4.frag_offset() != 0 {
            return None;
        }
        let index = u32::from(ipv4.dst_addr()).checked_sub(self.first)? as usize;
        if index >= self.listeners.len() {
            return None;
        }
        let tcp = TcpPacket::new_checked(ipv4.payload()).ok()?;
        if tcp.dst_port() != PORT {
            return None;
        }
        Some((
            Flow {
                index,
                peer: ipv4.src_addr(),
                peer_port: tcp.src_port(),
            },
            tcp.syn() && !tcp.ack(),
        ))
    }

    fn receive<T: TxToken>(
        &mut self,
        now: Instant,
        data: &[u8],
        tx: T,
        caps: &DeviceCapabilities,
    ) -> Option<Flow> {
        let selected = self.decode(data, caps.medium);
        let mut packet = OnePacket::new(Some(data), Some(tx), caps.clone());
        if let Some((flow, syn)) = selected {
            if let Some(active) = self.flows.get_mut(&flow) {
                self.interface
                    .poll_ingress_single(now, &mut packet, &mut active.sockets);
                return Some(flow);
            }
            if syn
                && self.tasks[flow.index].pending < u32::from(PER_LISTENER_BACKLOG)
                && self.flows.len() < ACTIVE_LIMIT
            {
                let resident = &mut self.listeners[flow.index];
                self.interface
                    .poll_ingress_single(now, &mut packet, &mut resident.sockets);
                if resident
                    .sockets
                    .get::<Socket>(SocketHandle::default())
                    .state()
                    == State::SynReceived
                {
                    let ip = Ipv4Addr::from(self.first + flow.index as u32);
                    let replacement = Resident::new(ip);
                    let old = std::mem::replace(&mut resident.sockets, replacement.sockets);
                    self.tasks[flow.index].begin();
                    self.flows.insert(
                        flow,
                        Active {
                            sockets: old,
                            phase: Phase::Handshake,
                        },
                    );
                    return Some(flow);
                }
            }
        }
        self.interface
            .poll_ingress_single(now, &mut packet, &mut self.empty);
        None
    }

    fn advance(&mut self, flow: Flow, now: Instant, device: &mut impl Device) {
        let Some(active) = self.flows.get_mut(&flow) else {
            return;
        };
        let socket = active.sockets.get_mut::<Socket>(SocketHandle::default());
        let state = socket.state();
        if active.phase == Phase::Handshake
            && matches!(state, State::Established | State::CloseWait)
        {
            active.phase = Phase::Reading;
            self.tasks[flow.index].established();
        }
        if active.phase == Phase::Reading && socket.can_recv() {
            // The fixed HTTP guest needs only the first nonempty request chunk.
            // Consume it, generate the response from the destination index, and
            // immediately release the guest task for the next connection.
            let _ = socket.recv(|input| (input.len(), input.len()));
            let reply = self.tasks[flow.index].response(flow.index);
            let sent = socket.send_slice(reply.as_bytes()).is_ok();
            if sent {
                socket.close();
                active.phase = Phase::Closing;
                self.metrics.accepted.fetch_add(1, Ordering::Relaxed);
            } else {
                socket.abort();
                active.phase = Phase::Closing;
            }
            self.tasks[flow.index].complete(sent);
        } else if active.phase == Phase::Reading && !socket.may_recv() {
            socket.close();
            active.phase = Phase::Closing;
            self.tasks[flow.index].complete(false);
        }
        let caps = device.capabilities();
        let mut packet = OnePacket::new(None, device.transmit(now), caps);
        self.interface
            .poll_egress(now, &mut packet, &mut active.sockets);
        let state = active
            .sockets
            .get::<Socket>(SocketHandle::default())
            .state();
        if state == State::Closed {
            if active.phase != Phase::Closing {
                self.tasks[flow.index].complete(false);
            }
            self.flows.remove(&flow);
        }
    }

    fn loop_packets(&mut self, mut device: impl Device, stop: &AtomicBool) {
        let caps = device.capabilities();
        while !stop.load(Ordering::Relaxed) {
            let now = Instant::now();
            self.interface.poll_maintenance(now);
            let mut received = 0;
            for _ in 0..64 {
                let Some((rx, tx)) = device.receive(now) else {
                    break;
                };
                received += 1;
                if let Some(flow) = rx.consume(|data| self.receive(now, data, tx, &caps)) {
                    self.advance(flow, now, &mut device);
                }
            }
            // Active flows are bounded and are the only records that need TCP
            // timers. Idle listeners are never scanned by the packet loop.
            if !self.flows.is_empty() {
                let keys: Vec<_> = self.flows.keys().copied().collect();
                for key in keys {
                    self.advance(key, now, &mut device);
                }
            }
            if received == 0 {
                std::thread::sleep(std::time::Duration::from_millis(1));
            }
        }
    }
}

pub(crate) fn run(
    interface: Interface,
    device: impl Device,
    first: u32,
    count: usize,
    metrics: Arc<Metrics>,
    stop: &AtomicBool,
) {
    let mut engine = Engine {
        interface,
        first,
        tasks: vec![Task::default(); count],
        listeners: Vec::with_capacity(count),
        flows: HashMap::new(),
        empty: SocketSet::new(Vec::new()),
        metrics,
    };
    engine.initialize(count);
    engine.loop_packets(device, stop);
}

pub(crate) fn measure_allocations(first: u32, count: usize) {
    let tasks = vec![Task::default(); count];
    let mut listeners = Vec::with_capacity(count);
    for index in 0..count {
        listeners.push(Resident::new(Ipv4Addr::from(first + index as u32)));
    }
    std::hint::black_box((&tasks, &listeners));
    let rollup = std::fs::read_to_string("/proc/self/smaps_rollup").unwrap_or_default();
    let field = |name: &str| -> u64 {
        rollup
            .lines()
            .find_map(|line| line.strip_prefix(name))
            .and_then(|value| value.split_whitespace().next())
            .and_then(|value| value.parse::<u64>().ok())
            .unwrap_or(0)
            * 1024
    };
    println!(
        "{{\"count\":{count},\"task_bytes\":{},\"resident_bytes\":{},\"task_capacity\":{},\"listener_capacity\":{},\"rss_bytes\":{},\"pss_bytes\":{}}}",
        std::mem::size_of::<Task>(),
        std::mem::size_of::<Resident>(),
        tasks.capacity(),
        listeners.capacity(),
        field("Rss:"),
        field("Pss:")
    );
}

fn ipv4(frame: &[u8], medium: Medium) -> Option<Ipv4Packet<&[u8]>> {
    let bytes = match medium {
        Medium::Ip => frame,
        Medium::Ethernet => {
            let ethernet = EthernetFrame::new_checked(frame).ok()?;
            if ethernet.ethertype() != EthernetProtocol::Ipv4 {
                return None;
            }
            ethernet.payload()
        }
    };
    Ipv4Packet::new_checked(bytes).ok()
}

struct OnePacket<'a, T> {
    input: Option<&'a [u8]>,
    output: Option<T>,
    caps: DeviceCapabilities,
}

impl<'a, T> OnePacket<'a, T> {
    fn new(input: Option<&'a [u8]>, output: Option<T>, caps: DeviceCapabilities) -> Self {
        Self {
            input,
            output,
            caps,
        }
    }
}

struct Input<'a>(&'a [u8]);
struct Output<T>(T);

impl<T: TxToken> Device for OnePacket<'_, T> {
    type RxToken<'a>
        = Input<'a>
    where
        Self: 'a;
    type TxToken<'a>
        = Output<T>
    where
        Self: 'a;

    fn receive(&mut self, now: Instant) -> Option<(Input<'_>, Output<T>)> {
        Some((Input(self.input.take()?), self.transmit(now)?))
    }
    fn transmit(&mut self, _: Instant) -> Option<Output<T>> {
        self.output.take().map(Output)
    }
    fn capabilities(&self) -> DeviceCapabilities {
        self.caps.clone()
    }
}

impl RxToken for Input<'_> {
    fn consume<R, F: FnOnce(&[u8]) -> R>(self, f: F) -> R {
        f(self.0)
    }
}

impl<T: TxToken> TxToken for Output<T> {
    fn consume<R, F: FnOnce(&mut [u8]) -> R>(self, len: usize, f: F) -> R {
        self.0.consume(len, f)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn task_is_sixteen_bytes() {
        assert_eq!(std::mem::size_of::<Task>(), 16);
    }
    #[test]
    fn resident_socket_has_its_own_endpoint() {
        let ip = Ipv4Addr::new(10, 228, 225, 192);
        let resident = Resident::new(ip);
        let socket = resident.sockets.get::<Socket>(SocketHandle::default());
        assert!(socket.is_listening());
        assert_eq!(socket.listen_endpoint(), (ip, PORT).into());
    }
}
