mod worker;

use smoltcp::iface::{Config, Interface};
use smoltcp::phy::{Medium, TunTapInterface};
use smoltcp::time::Instant;
use smoltcp::wire::{EthernetAddress, HardwareAddress, IpCidr};
use std::error::Error;
use std::io::{Read, Write};
use std::net::Ipv4Addr;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::UnixListener;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, AtomicU64, AtomicUsize, Ordering};
use std::time::Instant as Clock;

static STOP: AtomicBool = AtomicBool::new(false);

extern "C" fn stop_signal(_: libc::c_int) {
    STOP.store(true, Ordering::Relaxed);
}

#[derive(Clone)]
struct Options {
    first: Ipv4Addr,
    count: usize,
    backend: String,
    device: String,
    status_socket: PathBuf,
    measure_only: bool,
}

impl Options {
    fn parse() -> Result<Self, Box<dyn Error>> {
        let mut options = Self {
            first: Ipv4Addr::new(10, 0, 0, 1),
            count: 15_000_000,
            backend: "tun".into(),
            device: "smolbench".into(),
            status_socket: "/run/15m-lab/status.sock".into(),
            measure_only: false,
        };
        let mut args = std::env::args().skip(1);
        while let Some(flag) = args.next() {
            if flag == "--measure-only" {
                options.measure_only = true;
                continue;
            }
            let value = args.next().ok_or(format!("missing value for {flag}"))?;
            match flag.as_str() {
                "--base" => options.first = value.parse()?,
                "--count" => options.count = value.parse()?,
                "--backend" => options.backend = value,
                "--device" => options.device = value,
                "--status-socket" => options.status_socket = value.into(),
                _ => return Err(format!("unknown option: {flag}").into()),
            }
        }
        if options.count == 0 || options.count > 15_000_000 {
            return Err("count must be between 1 and 15000000".into());
        }
        let start = u32::from(options.first);
        let end = start
            .checked_add(u32::try_from(options.count - 1)?)
            .ok_or("IPv4 address overflow")?;
        if (start >> 24) != 10 || (end >> 24) != 10 {
            return Err("all listener addresses must stay inside private 10/8".into());
        }
        match options.backend.as_str() {
            "tun" if cfg!(feature = "tun") => {}
            "tap" if cfg!(feature = "tap") => {}
            _ => return Err("backend was not compiled into this binary".into()),
        }
        Ok(options)
    }

    fn last(&self) -> Ipv4Addr {
        Ipv4Addr::from(u32::from(self.first) + (self.count - 1) as u32)
    }
}

pub(crate) struct Metrics {
    initialized: AtomicUsize,
    accepted: AtomicU64,
    ready: AtomicBool,
    started: Clock,
    startup_ms: AtomicU64,
}

fn start_status(options: &Options, metrics: Arc<Metrics>) -> Result<(), Box<dyn Error>> {
    let path = options.status_socket.clone();
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    if path.exists() {
        if !std::fs::symlink_metadata(&path)?.file_type().is_socket() {
            return Err(format!("status path is not a socket: {}", path.display()).into());
        }
        std::fs::remove_file(&path)?;
    }
    let listener = UnixListener::bind(&path)?;
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o666))?;
    listener.set_nonblocking(true)?;
    let options = options.clone();
    std::thread::spawn(move || {
        while !STOP.load(Ordering::Relaxed) {
            match listener.accept() {
                Ok((mut stream, _)) => {
                    let _ = stream.set_read_timeout(Some(std::time::Duration::from_millis(200)));
                    let _ = stream.set_write_timeout(Some(std::time::Duration::from_millis(200)));
                    let mut request = [0u8; 16];
                    let _ = stream.read(&mut request);
                    let response = format!(
                        "{{\"pid\":{},\"backend\":\"{}\",\"base\":\"{}\",\"last\":\"{}\",\"port\":8080,\"requested\":{},\"initialized\":{},\"ready\":{},\"accepted\":{},\"startup_ms\":{},\"task_bytes\":{},\"listener_bytes\":{}}}\n",
                        std::process::id(),
                        options.backend,
                        options.first,
                        options.last(),
                        options.count,
                        metrics.initialized.load(Ordering::Acquire),
                        metrics.ready.load(Ordering::Acquire),
                        metrics.accepted.load(Ordering::Relaxed),
                        metrics.startup_ms.load(Ordering::Acquire),
                        std::mem::size_of::<worker::Task>(),
                        std::mem::size_of::<worker::Resident>(),
                    );
                    let _ = stream.write_all(response.as_bytes());
                }
                Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                    std::thread::sleep(std::time::Duration::from_millis(50));
                }
                Err(_) => break,
            }
        }
        let _ = std::fs::remove_file(path);
    });
    Ok(())
}

fn run() -> Result<(), Box<dyn Error>> {
    let options = Options::parse()?;
    if options.measure_only {
        worker::measure_allocations(u32::from(options.first), options.count);
        return Ok(());
    }
    let medium = match options.backend.as_str() {
        "tun" => Medium::Ip,
        "tap" => Medium::Ethernet,
        _ => unreachable!(),
    };
    let mut device = TunTapInterface::new(&options.device, medium)?;
    let hardware = match medium {
        Medium::Ip => HardwareAddress::Ip,
        Medium::Ethernet => HardwareAddress::Ethernet(EthernetAddress([0x02, 0, 0, 0, 0, 1])),
    };
    let mut config = Config::new(hardware);
    config.random_seed = 0x1530_0001;
    let mut interface = Interface::new(config, &mut device, Instant::now());
    let local: Ipv4Addr = if medium == Medium::Ip {
        "192.0.2.1"
    } else {
        "198.51.100.2"
    }
    .parse()?;
    interface.update_ip_addrs(|addresses| {
        addresses.push(IpCidr::new(local.into(), 24)).unwrap();
        addresses
            .push(IpCidr::new(options.first.into(), 32))
            .unwrap();
    });
    interface.routes_mut().add_default_ipv4_route(local)?;
    interface.set_any_ip(true);

    unsafe {
        libc::signal(
            libc::SIGTERM,
            stop_signal as *const () as libc::sighandler_t,
        );
        libc::signal(libc::SIGINT, stop_signal as *const () as libc::sighandler_t);
    }
    let metrics = Arc::new(Metrics {
        initialized: AtomicUsize::new(0),
        accepted: AtomicU64::new(0),
        ready: AtomicBool::new(false),
        started: Clock::now(),
        startup_ms: AtomicU64::new(0),
    });
    start_status(&options, Arc::clone(&metrics))?;
    worker::run(
        interface,
        device,
        u32::from(options.first),
        options.count,
        metrics,
        &STOP,
    );
    Ok(())
}

fn main() {
    if let Err(error) = run() {
        eprintln!("million-listeners: {error}");
        std::process::exit(1);
    }
}

use std::os::unix::fs::FileTypeExt;
