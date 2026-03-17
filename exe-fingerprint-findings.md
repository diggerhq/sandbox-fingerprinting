# exe.dev Sandbox Fingerprinting Results

**Date:** 2026-02-17

## Executive Summary

exe.dev runs **real virtual machines** using **Cloud Hypervisor** (not containers) on **Latitude.sh bare-metal servers** (Los Angeles, AS396356) with AMD EPYC 9554P CPUs. Each VM gets its own dedicated kernel (custom-built 6.12.67), 2 vCPUs, ~7.2 GiB RAM, and 18.6 GiB persistent disk. This is a fundamentally different (and stronger) isolation model than Daytona's Docker+Sysbox approach.

---

## Infrastructure Layer

| Component | Detail |
|-----------|--------|
| **Hypervisor** | **Cloud Hypervisor** (Intel/open-source, not Firecracker, not QEMU) |
| **KVM backend** | Yes — `Hypervisor detected: KVM` |
| **Host CPU** | AMD EPYC 9554P 64-Core (single-socket, Zen 4 Genoa) |
| **Hosting** | **Latitude.sh** bare metal (AS396356, Los Angeles, CA) |
| **Public IP** | `67.213.124.9` (Latitude.sh network) |
| **Cloud provider detection** | Metadata at `169.254.169.254` returns custom JSON: `{"name": "delta-compile", "source_ip": "10.42.2.67"}` — NOT AWS/GCP/Hetzner format |

### Hosting Provider Confirmation

Confirmed via `traceroute` and `ipinfo.io`:
- **Public IP:** `67.213.124.9`
- **ASN:** AS396356 (Latitude.sh)
- **Location:** Los Angeles, California
- **Provider:** [Latitude.sh](https://latitude.sh) (formerly Maxihost) — API-driven bare-metal cloud

```
Hop 1: 10.42.0.1      (exe.dev gateway)
Hop 2: 67.213.124.8   (Latitude.sh edge)
Hop 3-4: 10.10.102.x  (Latitude.sh internal backbone)
Hop 5: 206.53.172.7   (peering)
Hop 6: 141.101.72.x   (Cloudflare edge)
Hop 7: 1.1.1.1        (destination)
```

### Evidence for Cloud Hypervisor

Definitive — directly in `dmesg`:
```
DMI: Cloud Hypervisor cloud-hypervisor, BIOS 0
ACPI: RSDP 0x00000000000A0000 000024 (v02 CLOUDH)
ACPI: XSDT ... (v01 CLOUDH CHXSDT ...)
ACPI: FACP ... (v06 CLOUDH CHFACP ...)
ACPI: DSDT ... (v06 CLOUDH CHDSDT ...)
```

All ACPI tables have the `CLOUDH` OEM ID — the signature of [Cloud Hypervisor](https://github.com/cloud-hypervisor/cloud-hypervisor).

### Why Cloud Hypervisor, not Firecracker?

| Signal | Firecracker | Cloud Hypervisor | exe.dev result |
|--------|------------|-----------------|----------------|
| PCI bus | None (no `lspci`) | Minimal PCI with virtio | **5 PCI devices present** |
| ACPI tables | None or 1 | 4-5 tables (CLOUDH OEM) | **4 ACPI tables (CLOUDH)** |
| DMI/SMBIOS | None | `Cloud Hypervisor` | **`Cloud Hypervisor cloud-hypervisor`** |
| Memory balloon | No | Yes (virtio-balloon) | **virtio balloon present** |
| Console | serial | `hvc0` (virtio-console) | **`console=hvc0`** |

Cloud Hypervisor is a Rust-based VMM (like Firecracker) but supports more features: PCI, ACPI, memory ballooning, virtio-fs, live migration. It's the VMM behind Azure's confidential computing and was originally forked from Firecracker's codebase.

---

## VM Specifications

| Resource | Value |
|----------|-------|
| **vCPUs** | 2 (no SMT — `threads per core: 1`) |
| **RAM** | 7.2 GiB (7,576,044 kB) — dedicated, not cgroup-limited |
| **Disk** | 18.6 GiB virtio-blk (`/dev/vda`), ext4, no partitions |
| **Swap** | None |
| **Cgroup limits** | None — it's a real VM, not a container |

Unlike Daytona (where `free` lies about memory), exe.dev VMs show their **actual dedicated memory** — 7.2 GiB is what you really have.

---

## Custom Kernel

| Property | Value |
|----------|-------|
| **Version** | `6.12.67` (very recent mainline) |
| **Built by** | `root@buildkitsandbox` — compiled using Docker BuildKit |
| **Compiler** | GCC 13.3.0 (Ubuntu 24.04 toolchain) |
| **Config** | SMP, PREEMPT not set, custom for Cloud Hypervisor |
| **Boot args** | `console=hvc0 root=/dev/vda init=/exe.dev/bin/exe-init rw` |

They compile their own kernel via BuildKit — this is a modern CI approach. The kernel is purpose-built for Cloud Hypervisor (virtio drivers, KVM paravirt, minimal hardware support).

### Custom Init Chain

```
Cloud Hypervisor boots kernel
  → /exe.dev/bin/exe-init (custom init, sets up VM)
    → /sbin/init (systemd)
      → normal Ubuntu 24.04 userspace
```

The `/exe.dev/bin/exe-init` binary is their custom first-stage init that configures the VM before handing off to systemd. This is analogous to how Firecracker uses a custom init in some deployments.

---

## Guest OS

| Property | Value |
|----------|-------|
| **OS** | Ubuntu 24.04.3 LTS (Noble Numbat) |
| **Init** | systemd (via custom exe-init wrapper) |
| **User** | `exedev` (uid 1000) |
| **Shell** | `/bin/bash` |
| **Home** | `/home/exedev` |
| **exe.dev binaries** | `/exe.dev/bin/` (in PATH) |

---

## Virtio Devices (PCI Bus)

| PCI Address | Device | Purpose |
|-------------|--------|---------|
| `00:00.0` | Intel Host Bridge (0x0d57) | PCI root |
| `00:01.0` | Red Hat Virtio 1.0 console | Serial/terminal (`hvc0`) |
| `00:02.0` | Red Hat Virtio 1.0 block device | Root disk (`/dev/vda`) |
| `00:03.0` | Red Hat Virtio 1.0 network device | `eth0` |
| `00:04.0` | Red Hat Virtio 1.0 RNG | Entropy source |
| `00:05.0` | Red Hat Virtio 1.0 memory balloon | Dynamic memory management |

The memory balloon device is notable — it allows the host to reclaim unused memory from VMs dynamically, improving density.

---

## Running Services

| Service | Purpose |
|---------|---------|
| `systemd` (PID 1) | Full init system with journald |
| `cron.service` | Scheduled tasks |
| `dbus.service` | System message bus |
| `polkit.service` | Authorization manager |
| **`shelley.service`** | exe.dev's AI agent ("Shelley") |
| `systemd-journald` | Log management |
| `systemd-logind` | User session management |
| `systemd-timesyncd` | NTP time sync |
| `user@1000.service` | User session for `exedev` |

This is a full systemd-based Linux system, not a stripped-down container. The `shelley.service` is their built-in AI coding agent.

---

## Network Configuration

| Property | Value |
|----------|-------|
| **Subnet** | `10.42.0.0/16` |
| **VM IP** | `10.42.2.67` |
| **Gateway** | `10.42.0.1` (also the SSH jump host) |
| **DNS** | `1.1.1.1` (Cloudflare only) |
| **Hostname** | `delta-compile` |
| **Domain** | `delta-compile.exe.xyz` (internal domain) |
| **Interface** | `eth0` — virtio-net (not veth) |
| **SSH from** | `10.42.0.1:36820` → `10.42.2.67:22` |

Key differences from Daytona:
- Real virtio NIC (not a veth pair in a network namespace)
- SSH connections are proxied through the gateway at `10.42.0.1`
- Internal domain is `*.exe.xyz`
- IP is configured via kernel cmdline (`ip=` parameter), not DHCP

### Network Kernel Boot Param (decoded)

```
ip=10.42.2.67:10.42.0.1:10.42.0.1:255.255.0.0:delta-compile:eth0:none:1.1.1.1:8.8.8.8:ntp.ubuntu.com
```

Format: `ip=<client>:<server>:<gateway>:<netmask>:<hostname>:<device>:<autoconf>:<dns0>:<dns1>:<ntp>`

Network is configured at kernel boot time — no DHCP, no cloud-init. This is fast.

---

## Nested Virtualization

```
kvm_amd: Nested Virtualization enabled
kvm_amd: Nested Paging enabled
```

exe.dev VMs support **nested virtualization** — you can run KVM/QEMU/Docker inside the VM. This is enabled by the AMD EPYC's hardware nested page table support and Cloud Hypervisor exposing it to the guest.

---

## Custom Metadata Service

The `169.254.169.254` endpoint returns a custom (non-cloud-provider) response:

```json
{
  "name": "delta-compile",
  "source_ip": "10.42.2.67"
}
```

This is exe.dev's own metadata service running on the host/gateway, not AWS/GCP/Hetzner IMDS. Minimal by design.

---

## Packing Density Estimate

Host specs (inferred from AMD EPYC 9554P):
- 64 cores / 128 threads
- Likely 512 GiB or 1 TB RAM (common configs for this CPU)
- NVMe storage array

Per VM: 2 vCPUs, 7.2 GiB RAM, 18.6 GiB disk

| Assumption | Calculation | VMs per host |
|------------|------------|--------------|
| 512 GiB host RAM | 480 usable / 7.2 GiB | **~66** |
| 1 TB host RAM | 960 usable / 7.2 GiB | **~133** |
| CPU-bound (no overcommit) | 128 threads / 2 vCPUs | **64** |
| CPU-bound (2x overcommit) | 128 x 2 / 2 vCPUs | **128** |
| Disk (4 TB NVMe) | 4000 / 18.6 GiB | **~215** |

**Likely operating point: 50-80 VMs per host** — much lower density than Daytona (~500-800 containers) but with significantly stronger isolation.

With memory ballooning (virtio-balloon is present), idle VMs could have memory reclaimed, pushing density higher during off-peak.

---

## Architecture Diagram

```
Bare Metal Server (AMD EPYC 9554P, 64c/128t, ~512 GiB+ RAM)
├── Host OS (likely minimal Linux)
│   ├── Cloud Hypervisor VMM (Rust-based, KVM backend)
│   │   ├── VM: delta-compile (2 vCPU, 7.2 GiB, 18.6 GiB disk)
│   │   │   ├── Custom kernel 6.12.67 (built via BuildKit)
│   │   │   ├── /exe.dev/bin/exe-init → systemd
│   │   │   ├── Ubuntu 24.04.3 LTS
│   │   │   ├── shelley.service (AI agent)
│   │   │   ├── Docker available (nested virt enabled)
│   │   │   └── user: exedev, SSH access
│   │   ├── VM: [another-sandbox] ...
│   │   ├── VM: [another-sandbox] ...
│   │   └── (50-80 per host)
│   │
│   ├── Gateway / SSH proxy (10.42.0.1)
│   ├── Custom metadata service (169.254.169.254)
│   └── Internal network (10.42.0.0/16, virtio-net)
│
└── NVMe storage (virtio-blk to VMs)
```

---

## Daytona vs exe.dev Comparison

| Aspect | Daytona | exe.dev |
|--------|---------|---------|
| **Isolation** | Docker container + Sysbox | **Cloud Hypervisor VM (KVM)** |
| **Kernel** | Shared host kernel (6.8.0) | **Dedicated per-VM kernel (6.12.67, custom-built)** |
| **Init** | Daytona daemon (PID 1) | **systemd (full Linux boot)** |
| **Memory** | 1 GiB (cgroup limit, `free` lies) | **7.2 GiB (real, dedicated)** |
| **CPU** | 1 core (cgroup quota) | **2 vCPUs (dedicated)** |
| **Disk** | 3 GiB overlay | **18.6 GiB persistent ext4** |
| **Cold start** | <90ms (container) | Sub-second (VM boot) |
| **Docker inside** | Via Sysbox (rootless) | **Native (nested KVM)** |
| **Density** | ~500-800 per host | **~50-80 per host** |
| **Host CPU** | AMD EPYC 9254 (24c, Hetzner) | **AMD EPYC 9554P (64c)** |
| **Network** | Docker bridge (veth) | **virtio-net (real NIC)** |
| **OS** | Debian 13 Trixie | **Ubuntu 24.04 LTS** |
| **Memory balloon** | N/A (container) | **Yes (dynamic reclaim)** |
| **AI agent** | SDK-driven (external) | **Built-in (`shelley.service`)** |
| **Access model** | SDK API calls | **SSH** |
| **Guest image** | OCI/Docker image | **Full VM disk image** |
| **Kernel cmdline** | N/A | **Static IP, NTP, custom init** |
| **Security model** | Namespace + cgroup | **Hardware virtualization (VT-x/AMD-V)** |

### Key Takeaway

exe.dev chose **security and capability over density**. Each sandbox is a proper VM with its own kernel, full systemd, nested virtualization, and 7x more RAM than Daytona. The trade-off is ~10x lower density per host. This positions exe.dev as a "real dev machine in the cloud" vs Daytona's "lightweight code execution sandbox."

---

## Storage Performance & Pricing

### Disk Size

The advertised 25 GB is the **maximum expandable** size. The default allocation is **~20 GB** (18.6 GiB). Additional disk costs **$0.08/GB/month**, and the disk is **fixed-size** — it does NOT grow dynamically.

Confirmed by writing 10 GB, filling the disk, and observing `lsblk` unchanged at 18.6G.

### Write Throughput Benchmarks

| Test | Size | Speed | Notes |
|------|------|-------|-------|
| 1st sequential write | 10 GB | 124 MB/s | Cold — first-time block allocation overhead |
| 2nd write (disk nearly full) | 4 GB | 1.7 GB/s | **Misleading** — fit in 7.2 GiB page cache, never flushed to disk |
| 3rd write (warmed blocks) | 10 GB | 476 MB/s | **Real sustained throughput** |

**Real sustained sequential write: ~476 MB/s.** This is reasonable for shared NVMe behind virtio-blk with 50-80 VMs per host. Raw NVMe would be 3-5 GB/s, so each VM gets roughly 1/8th of the drive's bandwidth under contention.

### Pricing Model

| Resource | Cost |
|----------|------|
| Base disk (~20 GB) | Included in subscription |
| Additional disk | $0.08/GB/month |
| Data transfer | $0.07/GB/month |

The data transfer charge explains why they route all traffic through the gateway at `10.42.0.1` — that's their metering point for egress billing.
