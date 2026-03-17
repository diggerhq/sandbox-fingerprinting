# Sprites.dev (Fly.io) Sandbox Fingerprinting Results

**Date:** 2026-02-17

## Executive Summary

Sprites runs on **Firecracker microVMs** with a custom Fly.io kernel (`6.12.47-fly`) on Fly.io's own bare-metal infrastructure (IPv6 AS40509, IPv4 exits via CacheFly AS30081, Los Angeles). The architecture is a **container-in-microVM** hybrid: Firecracker boots a VM, then an overlay filesystem assembles the root from read-only system layers + a writable user layer, with **tini** as PID 1 (no systemd). Storage is backed by **JuiceFS** (S3-backed distributed FS) with a 100 GB checkpoint filesystem and 20 GB writable user disk.

---

## Infrastructure Layer

| Component | Detail |
|-----------|--------|
| **Hypervisor** | **Firecracker** (confirmed by kernel cmdline, MPTABLE OEM ID, and absence of PCI/ACPI/DMI) |
| **KVM backend** | Yes — `Hypervisor detected: KVM` |
| **Host CPU** | AMD EPYC (model masked by Firecracker) |
| **Hosting** | **Fly.io own infrastructure** — IPv6 from AS40509 (Fly.io), IPv4 exits via AS30081 (CacheFly), Los Angeles |
| **Public IPv4** | `216.246.104.93` (CacheFly transit) |
| **Public IPv6** | `2605:4c40:104:b71d:0:6737:442f:1` (Fly.io allocation) |

### Definitive Firecracker Evidence

Every signature lines up:

| Signal | Value | Why it proves Firecracker |
|--------|-------|--------------------------|
| `MPTABLE: OEM ID: FC` | **FC** | Firecracker's MP table signature |
| `pci=off` in cmdline | PCI disabled | Firecracker has no PCI bus |
| `acpi=off` in cmdline | ACPI disabled | Firecracker has no ACPI |
| `DMI not present or invalid` | No DMI/SMBIOS | Firecracker doesn't emulate DMI |
| `lspci` | Not available | No PCI devices exist |
| `/sys/firmware/acpi/tables/` | Doesn't exist | No ACPI tables |
| `virtio_mmio.device=4K@0xd0000000:5` | virtio-MMIO | Firecracker uses memory-mapped virtio (not PCI virtio) |
| `console=ttyS0` | Serial console | Firecracker's emulated serial |
| `reboot=k panic=1` | Standard FC params | Firecracker recommended kernel args |
| CPU model: `AMD EPYC` | Generic name | Firecracker masks the specific CPU model |

### Contrast with exe.dev (Cloud Hypervisor)

| Feature | Sprites (Firecracker) | exe.dev (Cloud Hypervisor) |
|---------|----------------------|---------------------------|
| PCI bus | **None** (`pci=off`) | 5 PCI devices |
| ACPI | **None** (`acpi=off`) | 4 ACPI tables (CLOUDH) |
| DMI/SMBIOS | **None** | `Cloud Hypervisor cloud-hypervisor` |
| Virtio transport | **MMIO** (memory-mapped) | **PCI** |
| Memory balloon | No | Yes |
| CPU model visible | No (masked as `AMD EPYC`) | Yes (`EPYC 9554P`) |

Firecracker is more minimal than Cloud Hypervisor — fewer features, smaller attack surface, faster boot.

---

## VM Specifications

| Resource | Value |
|----------|-------|
| **vCPUs** | 8 (no SMT — `threads per core: 1`) |
| **RAM** | 7.8 GiB (8,131,868 kB) — dedicated VM memory |
| **Cgroup memory** | `max` (no cgroup limit within the VM) |
| **Cgroup CPU** | `max 100000` (no CPU limit within the VM) |
| **Swap** | None |

Unlike Daytona (1 GiB cgroup-limited container), Sprites gives you a real VM with dedicated memory and no internal cgroup limits. Similar to exe.dev in this regard.

---

## Custom Kernel

| Property | Value |
|----------|-------|
| **Version** | `6.12.47-fly` |
| **Built by** | `support@fly.io` |
| **Compiler** | GCC 11.4.0 (Ubuntu 22.04 toolchain) |
| **Config** | `SMP PREEMPT_DYNAMIC` |
| **Features** | cgroup v2 only (`cgroup_no_v1=all`), no ACPI, no PCI |

The `-fly` suffix and `support@fly.io` builder confirm this is Fly.io's custom kernel optimized for Firecracker.

---

## Storage Architecture (Most Complex of the Three)

This is where Sprites really differs. The storage stack is layered and sophisticated:

### Block Devices

| Device | Size | RO? | Purpose |
|--------|------|-----|---------|
| `vda` | 144.2 MB | Read-only | SquashFS — contains `/.pilot/tini` (init binary) |
| `vdb` | 20 GB | Read-write | User data: `/tmp`, `/var/lib/docker`, `/.sprite/logs` |
| `vdc` | 4 KB | Read-only | Config overlay layer |
| `vdd` | 8 GB | Read-only | System image layer |
| `vde` | 8 GB | Read-only | System image layer |
| `vdf` | 8 GB | Read-only | System image layer |
| `vdg` | 268 KB | Read-only | Config/metadata layer |
| `loop0` | 100 GB | Read-only | Checkpoint filesystem |
| `nbd0-15` | 0 | — | Network block device slots (for checkpoint/restore) |

### Overlay Filesystem (Root `/`)

```
overlay on / type overlay (
    lowerdir=/mnt/languages-image:/system:/mnt/system-base,
    upperdir=/mnt/user-data/root-upper/upper,
    workdir=/mnt/user-data/root-upper/work
)
```

Root is a **3-layer overlay**:
1. `/mnt/system-base` — base Ubuntu 25.04 system (read-only, from vdd/vde/vdf)
2. `/system` — Fly.io system additions (read-only)
3. `/mnt/languages-image` — pre-installed language runtimes (read-only)
4. `upperdir` on vdb — user modifications (read-write)

This is analogous to Docker's layer model but at the VM level, with each layer as a separate virtio block device.

### JuiceFS (Distributed Storage)

```
SpriteFS on /.sprite/policy type fuse.juicefs (ro, 1.0P capacity)
```

**JuiceFS** is a POSIX-compatible distributed filesystem that stores data in object storage (S3) with metadata in a fast local store. The **1.0 PB** capacity indicates this is backed by S3-compatible object storage. This is the "durable external object storage" mentioned in their docs.

### Checkpoint System

```
/dev/loop0 on /.sprite/checkpoints/active type ext4 (ro, 100G)
```

The 100 GB loop device is the checkpoint/restore filesystem — used for snapshotting and restoring sprite state. The `nbd0-15` slots are likely for mounting checkpoint images from network storage during restore operations.

---

## Init System

| Property | Value |
|----------|-------|
| **PID 1** | `/.pilot/tini -- tail -f /dev/null` |
| **Init type** | **tini** (minimal init, no systemd) |
| **Source** | SquashFS on `vda` (144 MB, read-only) |
| **No systemd** | No systemctl, no journald, no login management |

This is a **container-in-VM** pattern:
1. Firecracker boots the kernel
2. Kernel mounts `vda` (squashfs) as initial root
3. `/.pilot/tini` starts as PID 1
4. Overlay root is assembled from multiple block devices
5. User shell (zsh) starts in the overlay

Much lighter than exe.dev's full systemd boot. Only 6 processes running at idle vs exe.dev's full service stack.

---

## Running Processes (Idle)

| PID | Process | User | Purpose |
|-----|---------|------|---------|
| 1 | `/.pilot/tini -- tail -f /dev/null` | sprite | Minimal init + keepalive |
| 2 | `zsh --login` | sprite | User shell |
| 3 | `tail -f /dev/null` | sprite | Keepalive process |

**Only 3 processes at idle.** This is dramatically lighter than:
- exe.dev: ~9 services (systemd, shelley, dbus, cron, etc.)
- Daytona: ~5 processes (daemon, computer-use, REPL worker, etc.)

---

## Guest OS

| Property | Value |
|----------|-------|
| **OS** | Ubuntu 25.04 (Plucky Puffin) — bleeding edge |
| **Init** | tini (no systemd) |
| **User** | `sprite` |
| **Shell** | `/bin/zsh` |
| **Home** | `/home/sprite` |
| **Sprite tooling** | `/.sprite/bin/` (in PATH) |
| **Browser** | `/.sprite/bin/sprite-browser` |
| **Docker** | Available (`/var/lib/docker` mounted on vdb) |

---

## Network Configuration

| Property | Value |
|----------|-------|
| **Interface** | `spr0@if6` — veth pair (not raw virtio-net) |
| **VM IP** | `10.0.0.1/24` |
| **Gateway/DNS** | `10.0.0.2` |
| **IPv6** | `fdf::1/64` (ULA) |
| **DNS** | `10.0.0.2` + `fdf::2` (internal) |
| **Hostname** | `sprite` |
| **Metadata** | No 169.254.169.254 endpoint |

The `spr0@if6` interface name suggests there's a network namespace inside the VM — the Firecracker VM has a virtio-net device, but the user-visible network goes through an additional veth pair (container-in-VM pattern).

The `10.0.0.0/24` subnet is tiny (just the sprite + gateway) — each VM gets its own isolated /24.

### Hosting Confirmation

| Protocol | IP | ASN | Provider |
|----------|-----|------|----------|
| IPv6 | `2605:4c40:104:b71d:...` | AS40509 | **Fly.io** (own allocation) |
| IPv4 | `216.246.104.93` | AS30081 | **CacheFly** (transit/egress) |

Fly.io runs their own hardware in colocation facilities. The IPv6 `2605:4c40::/32` block is registered to Fly.io. IPv4 exits through CacheFly's network (transit provider).

---

## Storage Performance

| Test | Result |
|------|--------|
| Sequential write (1 GB, `/tmp`) | **568 MB/s** |
| 4K direct read | Not testable (root is overlay, not a block device) |

568 MB/s write is solid for a Firecracker VM writing to virtio-blk backed by NVMe. Comparable to exe.dev's warmed performance (476 MB/s) and much better than Daytona (container overlay).

---

## Packing Density Estimate

Hard to estimate without knowing the host CPU model (Firecracker masks it as generic `AMD EPYC`). But based on the VM specs:

Per VM: 8 vCPUs, 7.8 GiB RAM, 20 GB writable + ~24 GB read-only layers (shared across VMs via dedup)

| Assumption | Calculation | VMs per host |
|------------|------------|--------------|
| 512 GiB host RAM | 480 / 7.8 GiB | **~61** |
| CPU (64-core host, no overcommit) | 128 threads / 8 vCPUs | **16** |
| CPU (64-core host, 2x overcommit) | 256 / 8 vCPUs | **32** |

**Likely operating point: 20-40 VMs per host** — lowest density of the three due to 8 vCPUs per VM (vs 2 for exe.dev, 1 for Daytona). The read-only system layers (vda, vdc-vdg) can be shared across VMs, saving significant disk space.

Fly.io likely adjusts VM sizes dynamically — 8 vCPUs is probably the "up to" for this tier.

---

## Architecture Diagram

```
Fly.io Bare Metal (AMD EPYC, colocation, LA)
├── Host OS (Fly.io custom)
│   ├── Firecracker VMM (KVM backend)
│   │   ├── MicroVM: sprite (8 vCPU, 7.8 GiB)
│   │   │   ├── Custom kernel 6.12.47-fly
│   │   │   ├── vda (squashfs, 144M) → /.pilot/tini (PID 1)
│   │   │   ├── vdb (ext4, 20G) → user data, Docker, tmp
│   │   │   ├── vdc-vdg (RO layers) → system image layers
│   │   │   ├── loop0 (ext4, 100G) → checkpoint storage
│   │   │   ├── Overlay root: system-base + system + languages + user
│   │   │   ├── Ubuntu 25.04 (no systemd, tini init)
│   │   │   ├── spr0 veth → 10.0.0.1/24
│   │   │   └── user: sprite, zsh
│   │   ├── MicroVM: [another-sprite] ...
│   │   └── (20-40 per host)
│   │
│   ├── JuiceFS → S3 object storage (1 PB, checkpoints + policy)
│   ├── NBD server (checkpoint image serving)
│   └── Network: Fly.io backbone (AS40509) + CacheFly transit (AS30081)
```

---

## Three-Way Comparison: Daytona vs exe.dev vs Sprites

| Aspect | Daytona | exe.dev | Sprites (Fly.io) |
|--------|---------|---------|-------------------|
| **Isolation** | Docker + Sysbox | Cloud Hypervisor (KVM) | **Firecracker (KVM)** |
| **Kernel** | Shared host | Dedicated (6.12.67, custom) | **Dedicated (6.12.47-fly)** |
| **Init** | Daytona daemon | systemd (full) | **tini (minimal)** |
| **Memory** | 1 GiB (cgroup) | 7.2 GiB (VM) | **7.8 GiB (VM)** |
| **CPU** | 1 core | 2 vCPUs | **8 vCPUs** |
| **Disk** | 3 GiB overlay | 20 GiB ext4 | **20 GiB ext4 + 100 GiB checkpoint** |
| **Root FS** | Docker overlay | Single ext4 | **Multi-layer overlay (container-in-VM)** |
| **OS** | Debian 13 | Ubuntu 24.04 | **Ubuntu 25.04** |
| **PCI** | N/A (container) | 5 devices | **None (pci=off)** |
| **ACPI** | N/A | 4 tables | **None (acpi=off)** |
| **DMI** | N/A | Cloud Hypervisor | **None** |
| **Processes at idle** | ~5 | ~9 | **3** |
| **Docker inside** | Via Sysbox | Nested KVM | **Yes (vdb mounts /var/lib/docker)** |
| **Density** | ~500-800/host | ~50-80/host | **~20-40/host** |
| **Distributed FS** | None | None | **JuiceFS (1 PB, S3-backed)** |
| **Checkpoint/restore** | Snapshots via registry | Not visible | **Native (loop0 + NBD)** |
| **Host CPU** | EPYC 9254 (visible) | EPYC 9554P (visible) | **EPYC (masked by Firecracker)** |
| **Hosting** | Hetzner (inferred) | Latitude.sh (confirmed) | **Fly.io own infra (confirmed)** |
| **Location** | Unknown | Los Angeles | **Los Angeles** |
| **Write speed** | N/A | 476 MB/s | **568 MB/s** |
| **AI agent** | SDK-driven | Shelley (systemd svc) | **None built-in** |
| **Access** | SDK API | SSH | **SSH + REST API** |
| **Security model** | Namespace + cgroup | Hardware virt | **Hardware virt (most minimal)** |

### Key Takeaway

Sprites is the **most technically sophisticated** of the three — Firecracker microVMs give the smallest attack surface, the multi-layer overlay root is elegant (share base images across VMs, only the user delta is writable), and JuiceFS + checkpoint/NBD provides industrial-grade state management. The trade-off is lowest density (~20-40/host due to 8 vCPUs each) and no systemd (lighter, but less "real machine" feel than exe.dev).

**The spectrum:**
- **Daytona** → Maximum density, minimum isolation (containers)
- **exe.dev** → "Real VM" experience, full systemd, balanced (Cloud Hypervisor)
- **Sprites** → Maximum isolation + sophistication, minimal init, container-in-VM (Firecracker)
