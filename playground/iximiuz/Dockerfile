# syntax=docker/dockerfile:1
FROM rust:1.96.0-bookworm AS rust-build
WORKDIR /src/runtime
COPY runtime/Cargo.toml runtime/Cargo.lock runtime/rust-toolchain.toml ./
COPY runtime/src ./src
RUN cargo build --release --locked --no-default-features --features tun

FROM ghcr.io/iximiuz/labs/rootfs:ubuntu-24-04
USER root
ENV HOME=/root

RUN set -eu; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      ca-certificates curl gcc iproute2 iputils-ping jq make procps \
      python3 rustc strace sudo; \
    rm -rf /var/lib/apt/lists/*

COPY baseline /opt/15m-lab/baseline
COPY learning /opt/15m-lab/learning
COPY runtime /opt/15m-lab/runtime
COPY toolbox /opt/15m-lab/toolbox
COPY tasks /opt/15m-lab/tasks
COPY --from=rust-build /src/runtime/target/release/million-listeners /opt/15m-lab/bin/million-listeners
COPY playground/iximiuz/image/*.service /etc/systemd/system/
COPY playground/iximiuz/image/15m-lab.sudoers /etc/sudoers.d/15m-lab
COPY playground/iximiuz/image/runtime.env /etc/15m-lab/runtime.env

RUN set -eu; \
    make -C /opt/15m-lab/baseline; \
    rm -f /etc/sudoers.d/laborant; \
    gpasswd -d laborant sudo; \
    usermod -aG systemd-journal laborant; \
    chmod 0755 /opt/15m-lab/toolbox/*.sh /opt/15m-lab/toolbox/*.py \
      /opt/15m-lab/tasks/*.sh /opt/15m-lab/tasks/*.py /opt/15m-lab/bin/million-listeners; \
    chmod 0440 /etc/sudoers.d/15m-lab; \
    visudo -cf /etc/sudoers.d/15m-lab; \
    mkdir -p /var/lib/15m-lab/runs /etc/systemd/system/multi-user.target.wants; \
    ln -sf /etc/systemd/system/15m-status-bridge.service \
      /etc/systemd/system/multi-user.target.wants/15m-status-bridge.service; \
    ln -sf /etc/systemd/system/15m-client-route.service \
      /etc/systemd/system/multi-user.target.wants/15m-client-route.service; \
    if id laborant >/dev/null 2>&1; then \
      ln -sfn /opt/15m-lab /home/laborant/15m-lab; \
      chown -h laborant:laborant /home/laborant/15m-lab; \
      install -d -m 0755 -o laborant -g laborant /home/laborant/15m-work; \
      install -m 0644 -o laborant -g laborant /opt/15m-lab/learning/server.c /home/laborant/15m-work/server.c; \
      install -m 0644 -o laborant -g laborant /opt/15m-lab/learning/context.rs /home/laborant/15m-work/context.rs; \
    fi; \
    test -x /opt/15m-lab/bin/million-listeners; \
    test -x /opt/15m-lab/baseline/bin/port_exhaust; \
    test -x /opt/15m-lab/baseline/bin/server

USER laborant
ENV HOME=/home/laborant
