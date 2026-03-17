# E2B Sandbox Fingerprinting Results

**Date:** 2026-02-17

## Executive Summary

E2B runs **Firecracker v1.10.1 microVMs** on **Google Cloud Platform** (The Dalles, Oregon, AS396982) using **`n1-standard-8` VMs with nested virtualization** (not bare metal — confirmed from [open-source infra repo](https://github.com/e2b-dev/infra)). Each sandbox is an L2 guest (GCP hypervisor → GCP VM → Firecracker → sandbox). Default config: 2 vCPUs, 482 MiB RAM, single 22.9 GiB ext4 disk. Orchestrated via **Nomad + Consul** (not Kubernetes). Uses 2MB **hugepages** (80% of host RAM) and **UFFD** for lazy snapshot resume.

---

## Infrastructure Layer

| Component | Detail |
|-----------|--------|
| **Hypervisor** | **Firecracker** (confirmed by ACPI OEM ID `FIRECK`) |
| **KVM backend** | Yes — `Hypervisor detected: KVM` |
| **Host CPU** | **Intel Xeon @ 2.60GHz** (likely Cascade Lake/Ice Lake, has AVX-512) |
| **Hosting** | **Google Cloud Platform** (confirmed) |
| **Public IP** | `136.109.171.234` |
| **Reverse DNS** | `234.171.109.136.bc.googleusercontent.com` (GCP signature) |
| **ASN** | AS396982 Google LLC |
| **Location** | The Dalles, Oregon (major Google datacenter) |

### Definitive Firecracker Evidence

E2B's Firecracker instance has ACPI tables (unlike Sprites which disables ACPI). The tables explicitly identify Firecracker:

```
ACPI: RSDP ... (v02 FIRECK)
ACPI: XSDT ... (v01 FIRECK FCMVXSDT ... FCAT 20240119)
ACPI: FACP ... (v06 FIRECK FCVMFADT ... FCAT 20240119)
ACPI: DSDT ... (v02 FIRECK FCVMDSDT ... FCAT 20240119)
ACPI: APIC ... (v06 FIRECK FCVMMADT ... FCAT 20240119)
```

`FIRECK` = Firecracker, `FCAT` = Firecracker ACPI Tables, `FCVM` prefix on all table names. Date `20240119` suggests this Firecracker build is from January 2024.

Other Firecracker signals:
- `pci=off` + `virtio_mmio.device` in kernel cmdline
- `DMI not present or invalid`
- `lspci` not available
- `reboot=k panic=1` standard FC args

### E2B vs Sprites: Two Firecracker Implementations

| Signal | E2B | Sprites |
|--------|-----|---------|
| ACPI | **Enabled** (5 FIRECK tables) | Disabled (`acpi=off`) |
| ACPI OEM ID | `FIRECK` | N/A |
| MPTABLE OEM ID | Not shown | `FC` |
| Kernel cmdline style | `clocksource=kvm-clock` first | `console=ttyS0` first |
| virtio-mmio devices | 3 | 10 |
| Host CPU | **Intel Xeon** (GCP) | **AMD EPYC** (Fly.io) |
| Host provider | **GCP** | **Fly.io bare metal** |

---

## VM Specifications

| Resource | Value |
|----------|-------|
| **vCPUs** | 2 |
| **RAM** | **482 MiB** (493,600 kB) — smallest of all four platforms |
| **Disk** | 22.9 GiB, single ext4 on `/dev/vda` |
| **Cgroup memory** | No limit (real VM) |
| **Cgroup CPU** | No limit (real VM) |
| **Swap** | None |

The 482 MiB RAM is dramatically less than the others:
- Daytona: 1 GiB (cgroup)
- exe.dev: 7.2 GiB
- Sprites: 7.8 GiB
- **E2B: 482 MiB** — optimized for short-lived code execution, not dev environments

---

## Kernel

| Property | Value |
|----------|-------|
| **Version** | `6.1.158` (oldest of all four) |
| **Built by** | `root@runnervmfxdz0` |
| **Compiler** | GCC 11.4.0 (Ubuntu 22.04 toolchain) |
| **Config** | `SMP PREEMPT_DYNAMIC` |
| **KASLR** | **Disabled** (noted in dmesg) |

The kernel is built on `runnervmfxdz0` — likely a CI runner. No custom suffix (unlike Fly.io's `-fly`). Version 6.1.x is the Debian 12 LTS kernel branch, suggesting they track Debian's kernel.

---

## Storage (Simplest of All Four)

```
vda   22.9G   ext4   /    (single disk, rw)
```

That's it. One disk, one filesystem, no overlay, no layers, no JuiceFS.

| Aspect | Daytona | exe.dev | Sprites | E2B |
|--------|---------|---------|---------|-----|
| Root FS | Docker overlay (30 layers) | Single ext4 | Multi-device overlay (7 VBDs) | **Single ext4** |
| Block devices | 0 (container) | 1 | 7+ | **1** |
| Distributed FS | None | None | JuiceFS (1 PB) | **None** |
| Checkpoints | Registry snapshots | None | loop0 + NBD | **None visible** |

### Storage Performance

| Test | E2B | exe.dev | Sprites |
|------|-----|---------|---------|
| Sequential write (1 GB) | **1.1 GB/s** | 476 MB/s | 568 MB/s |
| 4K direct read | 41.2 MB/s (~10K IOPS) | 59.9 MB/s (~14.6K IOPS) | N/A |

**E2B has the fastest sequential writes** at 1.1 GB/s — likely because GCP's persistent disks (or local SSDs) are faster than the bare-metal NVMe shared across many VMs at Latitude.sh/Fly.io. The IOPS are lower though (10K vs 14.6K on exe.dev).

Disk scheduler is `mq-deadline` (default Linux), not `none` like exe.dev and Sprites.

---

## Guest OS

| Property | Value |
|----------|-------|
| **OS** | Debian 12 (Bookworm) |
| **Init** | systemd (full boot) |
| **User** | `user` |
| **Shell** | `/bin/bash` |
| **Home** | `/home/user` |

---

## Network

| Property | Value |
|----------|-------|
| **Interface** | `eth0` (virtio-net via MMIO) |
| **VM IP** | `169.254.0.21/30` (link-local, /30 = only 4 IPs) |
| **Gateway** | `169.254.0.22` |
| **MAC** | `02:fc:00:00:00:05` (`fc` = Firecracker prefix) |
| **DNS** | `8.8.8.8` (Google DNS) |
| **Hostname** | `e2b.local` |
| **Events endpoint** | `192.0.2.1` (RFC 5737 test range, mapped in /etc/hosts) |

Key network details:
- `/30` subnet = point-to-point link (VM + gateway only) — maximum isolation
- `169.254.x.x` link-local addressing — no routable private IPs
- MAC prefix `02:fc` — Firecracker's signature
- `192.0.2.1` for E2B events uses RFC 5737 TEST-NET-1 range, routed internally via `/etc/hosts`

### Firecracker MMDS (Metadata Service)

The `169.254.169.254` endpoint returned:
```
No MMDS token provided. Use `X-metadata-token` header to specify the session token.
```

This is **Firecracker's built-in MicroVM Metadata Service (MMDS)**, not AWS/GCP IMDS. It requires a token (similar to AWS IMDSv2). E2B uses this for VM-to-host metadata communication.

---

## Running Processes

PID 1 is systemd (`/sbin/init → /lib/systemd/systemd`). The process list shows mostly kernel threads with `Feb11` start dates — the sandbox was created days ago and has been running (or restored from checkpoint) since then.

No visible E2B agent processes in the process list — their orchestration likely happens via the MMDS + external API rather than an in-VM agent.

---

## E2B Environment Variables

| Variable | Value | Purpose |
|----------|-------|---------|
| `E2B_SANDBOX` | `true` | Sandbox detection flag |
| `E2B_SANDBOX_ID` | `ighmj2e3lps5o73xlr8je` | Unique sandbox identifier |
| `E2B_TEMPLATE_ID` | `rki5dems9wqfm4r03t7g` | Template/image ID |
| `E2B_EVENTS_ADDRESS` | `http://192.0.2.1` | Internal events endpoint |

---

## Packing Density Estimate

With only 482 MiB RAM and 2 vCPUs per sandbox, E2B achieves much higher density than the others.

On a GCP `n2-highmem-64` (64 vCPUs, 512 GiB RAM) for example:

| Resource | Calculation | Sandboxes |
|----------|------------|-----------|
| RAM (no overcommit) | 500 GiB / 0.48 GiB | **~1,040** |
| RAM (2x overcommit) | 1000 GiB / 0.48 GiB | **~2,080** |
| CPU (no overcommit) | 64 vCPUs / 2 | **32** |
| CPU (2x overcommit) | 128 / 2 | **64** |

CPU is the bottleneck on GCP. **Likely 50-100 sandboxes per GCP VM** with moderate overcommit. Higher density than exe.dev/Sprites but lower than Daytona's containers.

---

## Architecture Diagram

```
Google Cloud Platform (The Dalles, Oregon)
├── GCP VM (Intel Xeon @ 2.60GHz, N2 or C2 family)
│   ├── Host Linux + KVM
│   │   ├── Firecracker VMM
│   │   │   ├── MicroVM: e2b.local (2 vCPU, 482 MiB)
│   │   │   │   ├── Kernel 6.1.158 (KASLR disabled)
│   │   │   │   ├── /dev/vda (22.9G ext4) — single root disk
│   │   │   │   ├── systemd (PID 1)
│   │   │   │   ├── Debian 12 Bookworm
│   │   │   │   ├── eth0: 169.254.0.21/30 (link-local)
│   │   │   │   ├── MMDS: 169.254.169.254 (token-based)
│   │   │   │   └── user: user, bash
│   │   │   ├── MicroVM: [another-sandbox] ...
│   │   │   └── (50-100 per GCP VM)
│   │   │
│   │   ├── Firecracker MMDS (metadata service)
│   │   └── E2B events (192.0.2.1)
│   │
│   └── GCP networking → AS396982 → internet
```

---

## Four-Way Comparison

| Aspect | Daytona | exe.dev | Sprites | E2B |
|--------|---------|---------|---------|-----|
| **Isolation** | Docker + Sysbox | Cloud Hypervisor | Firecracker | **Firecracker** |
| **Host provider** | Hetzner | Latitude.sh | Fly.io | **GCP** |
| **Host CPU** | AMD EPYC 9254 | AMD EPYC 9554P | AMD EPYC (masked) | **Intel Xeon** |
| **Location** | Unknown | Los Angeles | Los Angeles | **The Dalles, OR** |
| **Kernel** | Shared (6.8.0) | Custom (6.12.67) | Custom (6.12.47-fly) | **6.1.158** |
| **Init** | Daytona daemon | systemd | tini | **systemd** |
| **RAM** | 1 GiB (cgroup) | 7.2 GiB | 7.8 GiB | **482 MiB** |
| **CPU** | 1 core | 2 vCPUs | 8 vCPUs | **2 vCPUs** |
| **Disk** | 3 GiB overlay | 20 GiB ext4 | 20 GiB + layers | **22.9 GiB ext4** |
| **Root FS** | Docker overlay | Single disk | Multi-device overlay | **Single disk** |
| **Storage speed** | N/A | 476 MB/s | 568 MB/s | **1.1 GB/s** |
| **4K IOPS** | N/A | ~14.6K | N/A | **~10K** |
| **PCI** | N/A | 5 devices | None | **None** |
| **ACPI** | N/A | CLOUDH tables | None | **FIRECK tables** |
| **DMI** | N/A | Cloud Hypervisor | None | **None** |
| **Density** | ~500-800/host | ~50-80/host | ~20-40/host | **~50-100/GCP VM** |
| **OS** | Debian 13 | Ubuntu 24.04 | Ubuntu 25.04 | **Debian 12** |
| **Distributed FS** | None | None | JuiceFS | **None** |
| **Checkpoints** | Registry | None | loop0 + NBD | **None visible** |
| **AI agent** | SDK-driven | Shelley | None | **SDK-driven** |
| **Metadata** | Custom | Custom | None | **Firecracker MMDS** |
| **Network** | 172.20.0.0/16 | 10.42.0.0/16 | 10.0.0.0/24 | **169.254.0.0/30** |
| **Design goal** | Max density | Dev machine | Stateful + isolated | **Ephemeral execution** |

### Key Takeaway

E2B is the **most stripped-down, ephemeral-first** sandbox. Minimal RAM (482 MiB), minimal storage complexity (single disk), minimal network (/30 link-local), hosted on GCP for scale. It's optimized for **short-lived AI code execution** — spin up, run code, return results, kill. No bells and whistles.

**The spectrum refined:**
- **Daytona** → Max density, containers, fast cold start, tiny sandboxes
- **E2B** → Ephemeral microVMs, minimal resources, GCP scale, simple architecture
- **exe.dev** → "Real dev machine" VMs, full systemd, persistent, SSH-first
- **Sprites** → Most sophisticated: Firecracker + container layers + JuiceFS + checkpoints
