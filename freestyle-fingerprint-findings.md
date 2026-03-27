# Freestyle.sh VM Fingerprinting Results

**Date:** 2026-03-23

## Executive Summary

Freestyle.sh runs **Firecracker microVMs** on what appears to be **residential or small-office infrastructure** (Comcast Cable, Napa, California, AS7922). Each VM is a full KVM guest with **4 vCPUs, 7.8 GiB RAM, 15.6 GiB ext4 disk**. The kernel was custom-built by `jacob@jazlinux` (likely Freestyle founder Jacob Gerszten). The ACPI tables confirm **Firecracker** (`FIRECK` OEM ID) — the same VMM used by E2B and Sprites, but Freestyle's configuration is closest to E2B's (ACPI enabled, same table layout). The VM ships with **code-server, containerd, SSH, and ttyd** pre-installed — positioned as a full dev environment, not ephemeral code execution.

---

## Infrastructure Layer

| Component | Detail |
|-----------|--------|
| **Hypervisor** | **Firecracker** (confirmed by ACPI OEM ID `FIRECK`) |
| **KVM backend** | Yes — `Hypervisor detected: KVM` |
| **Host CPU** | **AMD EPYC** (model name stripped to just "AMD EPYC", has SVM flag) |
| **Hosting** | **Comcast Cable** residential/office (AS7922) |
| **Public IP** | `73.70.52.162` |
| **ASN** | AS7922 Comcast Cable Communications, LLC |
| **Location** | Napa, California |

### Definitive Firecracker Evidence

ACPI tables explicitly identify Firecracker, identical format to E2B:

```
ACPI: RSDP ... (v02 FIRECK)
ACPI: XSDT ... (v01 FIRECK FCMVXSDT ... FCAT 20240119)
ACPI: FACP ... (v06 FIRECK FCVMFADT ... FCAT 20240119)
ACPI: DSDT ... (v02 FIRECK FCVMDSDT ... FCAT 20240119)
ACPI: APIC ... (v06 FIRECK FCVMMADT ... FCAT 20240119)
```

`FCAT 20240119` — same Firecracker ACPI table build date as E2B, suggesting they use a similar or identical Firecracker version.

Other Firecracker signals:
- `pci=off` + `virtio_mmio.device` in kernel cmdline
- `DMI not present or invalid`
- `lspci` not available
- `reboot=k panic=1` standard FC args
- 2 virtio-mmio devices (vs E2B's 3, Sprites' 10)

### Unusual Hosting: Residential ISP

The public IP `73.70.52.162` resolves to **Comcast Cable** (AS7922) in **Napa, California**. This is highly unusual for a sandbox provider — every other provider uses datacenter hosting (GCP, AWS, Hetzner, Fly.io, Latitude.sh). This suggests Freestyle is either:
1. Running from a home/office server (early-stage startup)
2. Using a VPN/tunnel that exits through Comcast
3. NAT-ing through a residential connection

The `SSH_CONNECTION` shows internal IP `10.104.14.97` connecting to `172.16.0.2` — RFC 1918 private addressing, consistent with either approach.

---

## VM Specifications

| Resource | Value |
|----------|-------|
| **vCPUs** | 4 |
| **RAM** | **7.8 GiB** (8,156,744 kB) |
| **Disk** | 15.6 GiB, single ext4 on `/dev/vda` |
| **Cgroup memory** | No limit (real VM) |
| **Cgroup CPU** | No limit (real VM) |
| **Swap** | None |

Freestyle offers generous resources compared to most sandbox providers:
- More RAM than E2B (482 MiB), Daytona (1 GiB), or Blaxel (3.8 GiB)
- Comparable to exe.dev (7.2 GiB) and Sprites (7.8 GiB)
- 4 vCPUs — more than E2B (2), Daytona (1), exe.dev (2)
- Smaller disk than E2B (22.9 GiB) or exe.dev (18.6 GiB)

---

## Kernel

| Property | Value |
|----------|-------|
| **Version** | `6.1.155` |
| **Built by** | `jacob@jazlinux` (personal build) |
| **Compiler** | GCC 14.2.0 (Ubuntu 24.10/25.04 toolchain) |
| **Config** | `SMP PREEMPT_DYNAMIC` |
| **KASLR** | **Disabled** |

The kernel is built on `jazlinux` by `jacob` — clearly a personal development machine, not a CI runner. The GCC 14.2.0 compiler is from a very recent Ubuntu (24.10+). Version 6.1.x matches the Debian LTS kernel branch (same as E2B's 6.1.158).

---

## Storage

```
vda   15.6G   ext4   /    (single disk, rw)
```

Simple single-disk layout, identical architecture to E2B. No overlay filesystem, no distributed FS, no layers.

### Storage Performance

| Test | Freestyle | E2B | exe.dev | Sprites |
|------|-----------|-----|---------|---------|
| Sequential write (1 GB) | **60 MB/s** | 1.1 GB/s | 476 MB/s | 568 MB/s |
| 4K direct read | 46.4 MB/s (~11.3K IOPS) | 41.2 MB/s (~10K IOPS) | 59.9 MB/s (~14.6K IOPS) | N/A |

**Freestyle has the slowest sequential writes by far** at 60 MB/s — 18x slower than E2B, 8x slower than exe.dev. This is consistent with residential-grade storage (consumer NVMe or HDD) rather than datacenter SSDs. The 4K random read performance is reasonable though (~11.3K IOPS), suggesting the underlying storage is SSD but bandwidth-constrained.

---

## Guest OS

| Property | Value |
|----------|-------|
| **OS** | Debian 13 (Trixie) |
| **Init** | systemd (full boot) |
| **User** | `root` |
| **Shell** | `/bin/bash` |
| **Home** | `/root` |

Notably runs as **root** — most other sandboxes use unprivileged users (e2b: `user`, daytona: `daytona`).

---

## Pre-installed Services

Freestyle ships a rich dev environment with these systemd services running:

| Service | Purpose |
|---------|---------|
| `code-server` | VS Code in the browser |
| `containerd` | Container runtime (can run containers inside the VM) |
| `ssh` | OpenSSH server |
| `ttyd` | Terminal over HTTP (web terminal) |
| `systemd-networkd` | Network management |
| `systemd-timesyncd` | NTP time sync |

This is significantly more than other sandboxes:
- **E2B**: No visible agent processes
- **Sprites**: tini init, minimal services
- **exe.dev**: systemd but fewer services
- **Freestyle**: Full dev environment with IDE, container runtime, SSH, web terminal

---

## Network

| Property | Value |
|----------|-------|
| **Interface** | Not visible (`ip` command not installed) |
| **VM IP** | `172.16.0.2` (from SSH_CONNECTION) |
| **Gateway/Host** | `10.104.14.97` (from SSH_CONNECTION) |
| **DNS** | `8.8.8.8`, `8.8.4.4`, `1.1.1.1` (Google + Cloudflare) |
| **Hostname** | `tu23nvsa5l6y5zo4bewl` (random ID) |
| **Metadata** | Firecracker MMDS at `169.254.169.254` (token-based) |

Key observations:
- No `ip` or `ifconfig` installed — network tools stripped
- `172.16.0.0/12` private range used for VM networking
- SSH connection from `10.104.14.97` — the Freestyle host/orchestrator
- Uses Firecracker MMDS (same as E2B) for metadata
- `/etc/hosts` contains two entries: a snapshot hostname (`pp7m7s9xfo2o35f0mno5`) and current VM ID — suggests the VM was created from a snapshot

### Snapshot Evidence

The `/etc/hosts` file contains:
```
127.0.1.1    pp7m7s9xfo2o35f0mno5
127.0.1.1    tu23nvsa5l6y5zo4bewl
```

Two hostnames mapped to `127.0.1.1` — the first is likely the base snapshot, the second is the current VM. This confirms Freestyle uses **Firecracker snapshots** for fast VM creation (similar to E2B's approach).

---

## Environment Variables

Minimal environment — no Freestyle-specific variables. Only notable variable is `FS_CMD` which contains the command being executed (set by the exec API).

| Variable | Value | Purpose |
|----------|-------|---------|
| `FS_CMD` | (current command) | Freestyle exec wrapper |
| `SSH_CONNECTION` | `10.104.14.97 → 172.16.0.2` | Host-to-VM SSH tunnel |

---

## Architecture Diagram

```
Comcast Cable (Napa, California, AS7922)
├── Host Server (AMD EPYC)
│   ├── Host Linux + KVM
│   │   ├── Firecracker VMM
│   │   │   ├── MicroVM: tu23nvsa5l6y5zo4bewl (4 vCPU, 7.8 GiB)
│   │   │   │   ├── Kernel 6.1.155 (custom, jacob@jazlinux)
│   │   │   │   ├── /dev/vda (15.6G ext4)
│   │   │   │   ├── systemd (PID 1)
│   │   │   │   ├── Debian 13 Trixie
│   │   │   │   ├── code-server + containerd + SSH + ttyd
│   │   │   │   ├── VM IP: 172.16.0.2
│   │   │   │   ├── MMDS: 169.254.169.254
│   │   │   │   └── user: root
│   │   │   ├── MicroVM: [another-vm] ...
│   │   │   └── (estimated ~10-20 per host)
│   │   │
│   │   ├── Firecracker MMDS (metadata service)
│   │   └── Orchestrator (10.104.14.97, SSH-based exec)
│   │
│   └── Comcast NAT → AS7922 → internet
```

---

## Comparison with Other Firecracker Sandboxes

| Signal | E2B | Sprites | Freestyle |
|--------|-----|---------|-----------|
| ACPI | Enabled (FIRECK) | Disabled (`acpi=off`) | **Enabled (FIRECK)** |
| ACPI build date | `20240119` | N/A | **`20240119` (same!)** |
| Kernel cmdline | `clocksource=kvm-clock` first | `console=ttyS0` first | **`console=ttyS0` first** |
| virtio-mmio devices | 3 | 10 | **2** |
| Host CPU | Intel Xeon (GCP) | AMD EPYC (Fly.io) | **AMD EPYC** |
| Host provider | GCP | Fly.io | **Comcast (residential)** |
| Kernel builder | `root@runnervmfxdz0` | Custom | **`jacob@jazlinux`** |
| vCPUs | 2 | 8 | **4** |
| RAM | 482 MiB | 7.8 GiB | **7.8 GiB** |
| Pre-installed services | Minimal | Minimal | **Rich (IDE, containers, SSH)** |
| Root access | No (`user`) | No | **Yes (`root`)** |

### Key Takeaway

Freestyle is **Firecracker + full dev environment**. Same hypervisor and ACPI tables as E2B (potentially sharing upstream Firecracker builds), but positioned very differently: generous resources (4 vCPU, 7.8 GiB RAM), root access, code-server IDE, containerd, SSH — it's a "real machine" in a microVM. The residential Comcast hosting and personal kernel build (`jacob@jazlinux`) suggest an early-stage startup running from co-located or home infrastructure. Storage performance (60 MB/s sequential write) is the weakest of all tested sandboxes, consistent with non-datacenter hardware or bandwidth constraints.

**The spectrum updated:**
- **Daytona** → Max density, containers, fast cold start, tiny sandboxes
- **E2B** → Ephemeral microVMs, minimal resources, GCP scale
- **Freestyle** → Full dev-environment Firecracker VMs, generous resources, early-stage infra
- **exe.dev** → "Real dev machine" VMs, Cloud Hypervisor, persistent
- **Sprites** → Most sophisticated: Firecracker + container layers + JuiceFS + checkpoints
