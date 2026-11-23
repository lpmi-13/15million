use std::net::Ipv4Addr;

// The article's scheduler context needs a program counter and two descriptors.
#[allow(dead_code)]
#[repr(C)]
struct Context {
    pc: u64,
    // TODO (step 5): Add fd_server and fd_client as i32 fields.
}

fn listener_address(_index: u32) -> Ipv4Addr {
    let base = u32::from(Ipv4Addr::new(10, 0, 0, 1));
    // TODO (step 5): Return the address for this 1-based listener index.
    Ipv4Addr::from(base)
}

fn main() {
    let bytes = std::mem::size_of::<Context>();
    assert_eq!(bytes, 16, "add both file descriptor fields");
    assert_eq!(listener_address(7_500_000), Ipv4Addr::new(10, 114, 112, 224));
    assert_eq!(listener_address(15_000_000), Ipv4Addr::new(10, 228, 225, 192));
    println!("context_bytes={bytes}");
    println!("all_contexts_bytes={}", bytes * 15_000_000);
    for index in [1, 7_500_000, 15_000_000] {
        println!("{index} -> {}", listener_address(index));
    }
}
