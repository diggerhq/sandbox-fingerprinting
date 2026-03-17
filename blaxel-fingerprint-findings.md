# Blaxel Sandbox Fingerprinting Results

**Date:** 2026-02-17

## Executive Summary

Blaxel runs a **Unikraft unikernel inside a Firecracker microVM** on **AWS** (us-west-2, Oregon). This is the only platform of the five that uses a unikernel — the others all run standard Linux userlands. The guest OS is **Alpine Linux 3.23** with an **EROFS** (Enhanced Read-Only File System) base image mounted via overlay onto **ramfs** — meaning the entire filesystem lives in RAM with no persistent block storage. Default config: 2 vCPUs, 3.8 GiB RAM, ~1.9 GiB ramfs disk. PID 1 is a custom `/init unikraft /bin/metamorph-wrapper` chain. Formerly known as **Beamlit** (confirmed by internal hostname `us-west-2.prod.aws.beamlit.net`).

---

## Infrastructure Layer

| Component | Detail |
|-----------|--------|
| **Hypervisor** | **Firecracker** (confirmed by `MPTABLE: OEM ID: FC`, virtio-mmio, no PCI/ACPI/DMI) |
| **KVM backend** | Yes — `Hypervisor detected: KVM` |
| **Unikernel** | **Unikraft** (`unikraft` in kernel cmdline, `ukp_initrd` block device, `ukp-fuse` mount) |
| **Host CPU** | **Intel Xeon @ 2.90GHz** (Ice Lake — has AVX-512 VNNI, VBMI2, BITALG) |
| **Hosting** | **AWS us-west-2** (confirmed by `BL_RUN_INTERNAL_HOST=us-west-2.prod.aws.beamlit.net`) |
| **Region** | `us-pdx-1` (Portland, Oregon — maps to AWS us-west-2) |
| **AWS instance family** | Likely **c6i** or **m6i** (Ice Lake Xeon @ 2.9 GHz matches Xeon Platinum 8375C) |

### Definitive Firecracker Evidence

| Signal | Value | Why it proves Firecracker |
|--------|-------|--------------------------|
| `MPTABLE: OEM ID: FC` | **FC** | Firecracker's MP table signature |
| `DMI not present or invalid` | No DMI/SMBIOS | Firecracker doesn't emulate DMI |
| `virtio_mmio.device=4K@0xd0001000:5` | virtio-MMIO | Firecracker uses memory-mapped virtio |
| `console=ttyS0 reboot=k panic=1` | Standard FC args | Firecracker recommended kernel params |
| No PCI, no ACPI | — | Firecracker's minimal device model |
| No `lspci` output | — | No PCI bus exists |

### Definitive Unikraft Evidence

This is the novel finding. Blaxel layers Unikraft on top of Firecracker:

| Signal | Value | What it means |
|--------|-------|---------------|
| `unikraft` in kernel cmdline | Unikraft parameter | Unikraft framework is driving the boot |
| `vfs.fstab="initrd0:/:extract::ramfs=2:"` | Unikraft VFS config | Unikraft's custom filesystem table syntax |
| `ukp_initrd` block device | Unikraft Platform initrd | Contains the base filesystem image |
| `ukp_initrd.base=5100273664 ukp_initrd.len=213143552` | ~203 MiB initrd | The compressed base image size |
| `ukp-fuse on /uk/libukp type fuse` | Unikraft Platform FUSE | Unikraft's platform library mounted via FUSE |
| PID 1: `/init unikraft /bin/metamorph-wrapper` | Custom init chain | Unikraft init → metamorph wrapper → sandbox API |
| `env.vars=` syntax in cmdline | Unikraft env passing | Unikraft's mechanism for passing env vars via kernel cmdline |

### The Boot Chain

```
Firecracker VMM
  └── Linux kernel 6.5.13 (boots as Firecracker guest)
        └── /init (Unikraft init — NOT busybox/systemd)
              └── /bin/metamorph-wrapper (Blaxel's bridge layer)
                    └── /blaxel (working directory)
                          └── /usr/local/bin/sandbox-api (the sandbox process manager)
```

`metamorph-wrapper` is likely Blaxel's custom binary that:
1. Unpacks the EROFS initrd into the overlay filesystem
2. Sets up the ramfs upper layer
3. Starts the sandbox API server that handles `process.exec()` calls

---

## VM Specifications

| Resource | Value |
|----------|-------|
| **vCPUs** | 2 |
| **RAM** | **3.8 GiB** (4,027,672 kB) — requested 4096 MB, ~300 MB kernel overhead |
| **Disk** | **1.9 GiB ramfs** (no persistent block device!) |
| **Cgroup memory** | No limit (real VM) |
| **Cgroup CPU** | No limit (real VM) |
| **Swap** | None |

### RAM Comparison Across Platforms

| Platform | Default RAM | Type |
|----------|------------|------|
| E2B | 482 MiB | VM memory |
| Daytona | 1 GiB | cgroup limit |
| Blaxel | **3.8 GiB** | VM memory |
| exe.dev | 7.2 GiB | VM memory |
| Sprites | 7.8 GiB | VM memory |

---

## Kernel

| Property | Value |
|----------|-------|
| **Version** | `6.5.13` |
| **Built by** | `root@buildkitsandbox` (BuildKit CI — same pattern as exe.dev) |
| **Compiler** | GCC 14.2.0 (Alpine toolchain) |
| **Config** | `SMP PREEMPT_DYNAMIC` |
| **KASLR** | Not explicitly disabled (unlike E2B) |

The kernel is built with Alpine's GCC 14.2.0 inside a BuildKit container (`buildkitsandbox`). Version 6.5.x is between E2B's 6.1.x and exe.dev/Sprites' 6.12.x.

---

## Storage Architecture (Most Unique of All Five)

### The RAM-Only Filesystem

```
overlay on / type overlay (
    lowerdir=/mnt/erofs,         ← EROFS: compressed read-only base image
    upperdir=/mnt/tmp/upper,     ← ramfs: writable layer (in RAM!)
    workdir=/mnt/tmp/work        ← ramfs: overlay work directory
)
```

**There are no real block devices.** The entire filesystem lives in RAM:

- **Lower layer** (`/mnt/erofs`): EROFS (Enhanced Read-Only File System) — a highly compressed, read-only filesystem originally from Huawei, now mainline Linux. Used in Android and optimized container runtimes. Very fast decompression, minimal memory overhead.
- **Upper layer** (`/mnt/tmp/upper`): ramfs — all writes go to RAM. No persistence.
- **Source**: The `ukp_initrd` (~203 MiB compressed) contains the EROFS base image.

This explains:
- **The 25ms cold start**: No disk I/O needed — everything is already in memory
- **The 1.2 GB/s write speed**: Writing to RAM, not disk
- **The ~1.9 GiB total "disk" size**: Limited by available RAM, not a physical disk
- **No persistence**: When the sandbox dies, all data is gone

### Block Devices

| Device | Purpose |
|--------|---------|
| `loop0-loop7` | Loop device slots (available but unused) |
| `ukp_initrd` | **Unikraft platform initrd** — contains the EROFS base image |

No `vda`, `vdb`, or any virtio-blk devices. Only 2 virtio-mmio devices registered (likely virtio-net + virtio-rng or vsock).

### Storage Comparison

| Platform | Root FS | Persistent Disk | Write Speed | Why |
|----------|---------|----------------|-------------|-----|
| Daytona | Docker overlay | 3 GiB | N/A | Shared host disk |
| E2B | Single ext4 | 22.9 GiB | 1.1 GB/s | GCP local SSD |
| exe.dev | Single ext4 | 20 GiB | 476 MB/s | Latitude NVMe |
| Sprites | Multi-layer overlay | 20 GiB | 568 MB/s | Fly.io NVMe |
| **Blaxel** | **EROFS + ramfs overlay** | **None (RAM only)** | **1.2 GB/s** | **Writing to RAM** |

---

## Guest OS

| Property | Value |
|----------|-------|
| **OS** | Alpine Linux 3.23.3 (lightest of all five) |
| **Init** | Custom Unikraft init chain (no systemd, no tini, no busybox init) |
| **User** | `root` |
| **Shell** | `/bin/sh` (busybox) |
| **Home** | `/blaxel` |
| **Node.js** | 22.22.0 |
| **Yarn** | 1.22.22 |
| **libc** | musl (Alpine — not glibc) |

Alpine Linux is the smallest base OS of all five platforms. Combined with EROFS compression, this minimizes the initrd size (~203 MiB).

---

## Network

| Property | Value |
|----------|-------|
| **Interface** | `eth0` (virtio-net via MMIO) |
| **VM IP** | `172.16.19.9/30` (private, /30 = point-to-point) |
| **Gateway/DNS** | `172.16.19.10` |
| **MAC** | `12:b0:ac:10:13:09` (no Firecracker `02:fc` prefix — custom) |
| **DNS** | `172.16.19.10` (gateway is DNS) |
| **Hostname** | `(none)` |
| **Public IP** | Not directly accessible (egress goes through proxy) |
| **Metadata** | No 169.254.169.254 endpoint (blocked or not routed) |

### Network Path (Traceroute to 1.1.1.1)

```
1  172.16.19.10      0.082 ms    ← Firecracker gateway
2  10.110.1.77       1.038 ms    ← AWS VPC internal
3  244.5.2.103       9.291 ms    ← AWS backbone (240.0.0.0/4 = AWS internal)
4  240.4.228.4       2.480 ms    ← AWS backbone
5  242.1.39.239      3.214 ms    ← AWS backbone
6  240.2.140.12      7.357 ms    ← AWS backbone
7  242.6.125.131     6.892 ms    ← AWS backbone
8  99.83.95.34       7.632 ms    ← AWS Global Accelerator
9  99.83.95.33      10.813 ms    ← AWS Global Accelerator
10 172.68.172.7      7.800 ms    ← Cloudflare (1.1.1.1 is Cloudflare)
```

The `240.x.x.x`, `242.x.x.x`, and `244.x.x.x` addresses are **AWS internal backbone addresses** — these are not publicly routable and are only visible from within AWS's network. `99.83.95.x` is AWS Global Accelerator. This definitively confirms **AWS us-west-2**.

---

## Running Processes

| PID | Process | Purpose |
|-----|---------|---------|
| 1 | `/init unikraft /bin/metamorph-wrapper /blaxel /usr/local/bin/sandbox-api` | Unikraft init → metamorph → sandbox API |
| 2+ | Kernel threads only | No other userspace processes |

**Only 1 userspace process at idle.** The lightest of all five platforms:

| Platform | Userspace Processes at Idle |
|----------|----|
| **Blaxel** | **1** |
| Sprites | 3 |
| Daytona | ~5 |
| E2B | ~5 (systemd + services) |
| exe.dev | ~9 |

---

## Blaxel Environment Variables

| Variable | Value | Purpose |
|----------|-------|---------|
| `BL_GENERATION` | `mk3` | Infrastructure generation (explains "Mark 3" in their docs) |
| `BL_TYPE` | `sandbox` | Workload type |
| `BL_REGION` | `us-pdx-1` | Portland, Oregon → AWS us-west-2 |
| `BL_RUN_INTERNAL_HOST` | `us-west-2.prod.aws.beamlit.net` | **Confirms AWS + former "Beamlit" name** |
| `BL_ENV` | `prod` | Production environment |
| `BL_CLOUD` | `true` | Cloud deployment flag |
| `BL_S_CUSTOMER_ID` | `cus_TzzwsWYnyMHLTP` | **Stripe customer ID** (billing via Stripe) |
| `BL_WORKSPACE_ID` | `YNRKPA` | Internal workspace identifier |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `https://otlp.blaxel.ai` | OpenTelemetry traces/metrics endpoint |

### The Beamlit Connection

Blaxel was formerly **Beamlit**. The internal hostname `us-west-2.prod.aws.beamlit.net` hasn't been updated to the new brand. The `BL_` prefix in all env vars also stands for "BeamLit" (or now "BLaxel").

---

## Packing Density Estimate

With 2 vCPUs and 3.8 GiB RAM per sandbox (at 4096 MB tier), on an AWS `m6i.metal` (128 vCPUs, 512 GiB RAM):

| Resource | Calculation | Sandboxes |
|----------|------------|-----------|
| RAM (no overcommit) | 480 GiB / 3.8 GiB | **~126** |
| RAM (2x overcommit) | 960 GiB / 3.8 GiB | **~252** |
| CPU (no overcommit) | 128 vCPUs / 2 | **64** |
| CPU (2x overcommit) | 256 / 2 | **128** |

With the smallest tier (0.5 vCPU / 2 GiB):

| Resource | Calculation | Sandboxes |
|----------|------------|-----------|
| RAM (no overcommit) | 480 GiB / 2 GiB | **~240** |
| CPU (no overcommit) | 128 / 0.5 | **256** |

**Likely operating point: 60-130 sandboxes per host** depending on tier. The RAM-only filesystem means no disk I/O contention — density is purely RAM + CPU bound. The Unikraft init adds minimal overhead (~45 MiB used at idle from 3.8 GiB).

If they use `.metal` instances (bare-metal AWS), they avoid the nested virtualization overhead that E2B has. The Ice Lake Xeon @ 2.9 GHz and the full AVX-512 feature set suggest bare metal or at minimum a dedicated host.

---

## Architecture Diagram

```
AWS us-west-2 (Portland, Oregon)
├── EC2 Instance (Intel Ice Lake Xeon @ 2.90GHz, likely m6i.metal or c6i.metal)
│   ├── Host Linux + KVM
│   │   ├── Firecracker VMM
│   │   │   ├── MicroVM: sandbox (2 vCPU, 3.8 GiB)
│   │   │   │   ├── Kernel 6.5.13 (Alpine GCC 14.2, BuildKit-built)
│   │   │   │   ├── Unikraft init chain
│   │   │   │   │   ├── /init (Unikraft bootstrap)
│   │   │   │   │   ├── /bin/metamorph-wrapper (Blaxel bridge)
│   │   │   │   │   └── /usr/local/bin/sandbox-api (process manager)
│   │   │   │   ├── ukp_initrd (203 MiB EROFS image)
│   │   │   │   ├── Overlay root: EROFS (RO) + ramfs (RW)
│   │   │   │   ├── Alpine Linux 3.23 (musl, busybox)
│   │   │   │   ├── eth0: 172.16.19.x/30
│   │   │   │   └── No persistent storage
│   │   │   ├── MicroVM: [another-sandbox] ...
│   │   │   └── (60-130 per host)
│   │   │
│   │   ├── ukp-fuse (Unikraft Platform library)
│   │   └── Firecracker MMDS / networking
│   │
│   └── AWS networking → AWS backbone (240/242/244.x.x.x) → internet
│
├── OpenTelemetry → otlp.blaxel.ai
└── Internal API → us-west-2.prod.aws.beamlit.net
```

---

## Five-Way Comparison

| Aspect | Daytona | exe.dev | Sprites | E2B | **Blaxel** |
|--------|---------|---------|---------|-----|------------|
| **Isolation** | Docker + Sysbox | Cloud Hypervisor | Firecracker | Firecracker | **Firecracker + Unikraft** |
| **Host provider** | Hetzner | Latitude.sh | Fly.io | GCP | **AWS** |
| **Host CPU** | AMD EPYC 9254 | AMD EPYC 9554P | AMD EPYC (masked) | Intel Xeon 2.6GHz | **Intel Xeon 2.9GHz (Ice Lake)** |
| **Location** | Unknown | Los Angeles | Los Angeles | The Dalles, OR | **Portland, OR (us-west-2)** |
| **Kernel** | Shared (6.8.0) | Custom (6.12.67) | Custom (6.12.47-fly) | 6.1.158 | **6.5.13 (Alpine/BuildKit)** |
| **Init** | Daytona daemon | custom → systemd | tini | systemd | **Unikraft → metamorph** |
| **RAM** | 1 GiB (cgroup) | 7.2 GiB | 7.8 GiB | 482 MiB | **3.8 GiB** |
| **CPU** | 1 core | 2 vCPUs | 8 vCPUs | 2 vCPUs | **2 vCPUs** |
| **Disk** | 3 GiB overlay | 20 GiB ext4 | 20 GiB + layers | 22.9 GiB ext4 | **1.9 GiB ramfs (no disk!)** |
| **Root FS** | Docker overlay | Single disk | Multi-device overlay | Single disk | **EROFS + ramfs overlay** |
| **Base image format** | Docker layers | ext4 | SquashFS + ext4 layers | ext4 | **EROFS (compressed RO)** |
| **Storage speed** | N/A | 476 MB/s | 568 MB/s | 1.1 GB/s | **1.2 GB/s (RAM)** |
| **Persistent storage** | Yes (overlay) | Yes (ext4) | Yes (ext4 + JuiceFS) | Yes (ext4) | **No (ramfs = volatile)** |
| **PCI** | N/A | 5 devices | None | None | **None** |
| **ACPI** | N/A | CLOUDH tables | None | FIRECK tables | **None** |
| **DMI** | N/A | Cloud Hypervisor | None | None | **None** |
| **Processes at idle** | ~5 | ~9 | 3 | ~5 | **1** |
| **OS** | Debian 13 | Ubuntu 24.04 | Ubuntu 25.04 | Debian 12 | **Alpine 3.23** |
| **libc** | glibc | glibc | glibc | glibc | **musl** |
| **Distributed FS** | None | None | JuiceFS | None | **None** |
| **Checkpoints** | Registry | None | loop0 + NBD | UFFD snapshots | **None visible** |
| **Density** | ~500-800/host | ~50-80/host | ~20-40/host | ~50-100/GCP VM | **~60-130/host** |
| **Network** | 172.20.0.0/16 | 10.42.0.0/16 | 10.0.0.0/24 | 169.254.0.0/30 | **172.16.x.x/30** |
| **Metadata svc** | Custom | Custom | None | Firecracker MMDS | **None accessible** |
| **Unikernel** | No | No | No | No | **Yes (Unikraft)** |
| **Design goal** | Max density | Dev machine | Stateful + isolated | Ephemeral execution | **Ultra-fast boot, ephemeral** |

---

## Key Takeaway

Blaxel is the **most architecturally novel** of all five platforms. While the others all run standard Linux userlands (systemd, tini, or daemon-based), Blaxel layers **Unikraft** (a unikernel framework) on top of Firecracker. The EROFS + ramfs overlay means the entire filesystem lives in RAM — no disk I/O, no persistence, but blazing fast.

This explains their 25ms cold start claim: with EROFS pre-loaded into memory and Unikraft's minimal init chain, there's almost nothing to boot. The trade-off is zero persistence — everything is ephemeral.

**The spectrum refined:**
- **Daytona** → Max density, containers, fast cold start, tiny sandboxes
- **E2B** → Ephemeral microVMs, minimal resources, GCP scale, simple architecture
- **Blaxel** → **Unikernel + Firecracker, RAM-only FS, ultra-fast boot, zero persistence**
- **exe.dev** → "Real dev machine" VMs, full systemd, persistent, SSH-first
- **Sprites** → Most sophisticated: Firecracker + container layers + JuiceFS + checkpoints

Blaxel sits between E2B and Daytona on the density/ephemeral axis, but with the most exotic technology stack (Unikraft + EROFS). It's optimized for **stateless, short-lived AI code execution** where boot latency matters more than persistence.
