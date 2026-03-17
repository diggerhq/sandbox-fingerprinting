# Modal Sandbox Fingerprinting Results

**Date:** 2026-02-19

## Executive Summary

Modal runs sandboxes inside **gVisor** (Google's userspace kernel) on **Microsoft Azure** (`eastus` region). The root filesystem is a **9p** mount (Plan 9 protocol — gVisor's filesystem passthrough) presenting **512 GiB** of storage. No real block devices exist. PID 1 is `dumb-init`, not systemd. The sandbox has **no outbound internet access** by default and no cloud metadata endpoint is reachable. CPU model is masked ("unknown") by gVisor, but CPU flags reveal **AMD EPYC** silicon underneath.

---

## Infrastructure Layer

| Component | Detail |
|-----------|--------|
| **Isolation** | **gVisor** (confirmed by kernel cmdline, dmesg, and env var) |
| **Host kernel** | Real host kernel hidden; gVisor presents fake `4.4.0` |
| **Host CPU** | **AMD EPYC** (confirmed by AMD-specific flags: `sse4a`, `misalignsse`, `topoext`, `perfctr_core`) |
| **Cloud provider** | **Microsoft Azure** (`MODAL_CLOUD_PROVIDER=CLOUD_PROVIDER_AZURE`) |
| **Region** | `eastus` |
| **Public IP** | Not accessible (no outbound internet) |

### Definitive gVisor Evidence

Three independent signals confirm gVisor:

1. **Kernel cmdline**: `BOOT_IMAGE=/vmlinuz-4.4.0-gvisor quiet`
2. **dmesg**: `[    0.000000] Starting gVisor...` followed by gVisor's signature joke boot messages
3. **Env var**: `MODAL_FUNCTION_RUNTIME=gvisor`

The fake kernel version `4.4.0` is gVisor's default — it does not reflect the actual host kernel. The dmesg output contains gVisor's famous Easter eggs:

```
[    0.000000] Starting gVisor...
[    0.568407] Accelerating teletypewriter to 9600 baud...
[    0.750225] Waiting for children...
[    1.215243] Segmenting fault lines...
[    1.236528] Preparing for the zombie uprising...
[    1.350380] Rewriting the kernel in Rust...
[    1.796549] Creating process schedule...
[    1.939503] Reticulating splines...
[    2.365016] Creating bureaucratic processes...
[    2.729406] Politicking the oom killer...
[    3.102576] Ready!
```

### How gVisor Differs from Firecracker (E2B/Sprites)

| Signal | Modal (gVisor) | E2B / Sprites (Firecracker) |
|--------|---------------|----------------------------|
| Isolation model | **Userspace kernel** (syscall interception) | **MicroVM** (hardware virtualization) |
| Block devices | **None** — 9p filesystem passthrough | `/dev/vda` (virtio block) |
| Kernel | Fake `4.4.0` (gVisor binary) | Real Linux kernel (6.1.x / 6.12.x) |
| ACPI/DMI/PCI | **None** (no hardware emulation) | ACPI tables present (FIRECK) |
| dmesg | Joke messages | Real boot sequence |
| /proc/cmdline | `vmlinuz-4.4.0-gvisor` | `pci=off virtio_mmio.device=...` |
| Init system | `dumb-init` | systemd / tini |

---

## Sandbox Specifications

| Resource | Value |
|----------|-------|
| **vCPUs** | 1 (default) |
| **RAM (visible)** | ~448 GiB (`MemTotal: 470001268 kB`) — **this is host memory leaking through gVisor** |
| **RAM (cgroup)** | No limit (`memory.limit_in_bytes = 9223372036854775807` = max int64) |
| **CPU (cgroup)** | No limit (`cpu.cfs_quota_us = -1`) |
| **Root filesystem** | **512 GiB** (9p mount) |
| **/dev/shm** | 16 GiB tmpfs |
| **Swap** | None |
| **Block devices** | None |
| **User** | `root` (uid=0) |

### Memory: Host Leak via gVisor

The 448 GiB `MemTotal` is **not** the sandbox's allocation — it's the host machine's RAM visible through gVisor's `/proc/meminfo` implementation. Unlike containers with LXCFS (Daytona has the same issue), gVisor doesn't virtualize meminfo to reflect per-sandbox limits. The cgroup memory limit is set to max int64 (effectively unlimited), suggesting Modal relies on other mechanisms for resource isolation or charges per-use.

The host with ~448 GiB RAM is consistent with Azure's **M-series** or **E-series** VMs (e.g., `Standard_E64s_v5` with 512 GiB).

### Cgroup Structure (v1)

Modal uses **cgroup v1** (not v2), with a custom `job` controller:

```
7:pids:/ta-01KHWAJCQD1NBBX9HSFDZXTCM2
6:memory:/ta-01KHWAJCQD1NBBX9HSFDZXTCM2
5:job:/ta-01KHWAJCQD1NBBX9HSFDZXTCM2
4:devices:/ta-01KHWAJCQD1NBBX9HSFDZXTCM2
3:cpuset:/ta-01KHWAJCQD1NBBX9HSFDZXTCM2
2:cpuacct:/ta-01KHWAJCQD1NBBX9HSFDZXTCM2
1:cpu:/ta-01KHWAJCQD1NBBX9HSFDZXTCM2
```

The `job` cgroup controller is non-standard — likely a custom gVisor/Modal addition for workload tracking. The `ta-` prefix in cgroup paths corresponds to `MODAL_TASK_ID`.

---

## Storage (9p — Unique Among All Platforms)

Modal is the **only** platform using 9p (Plan 9 filesystem protocol) for the root filesystem. This is gVisor's native way to provide filesystem access — the host's filesystem is presented to the sandbox over a file descriptor pair (`rfdno=4,wfdno=4`).

```
none  /                           9p     512G  800K  512G   1%  (rw, fscache)
none  /dev                        tmpfs  225G     0  225G   0%
none  /dev/shm                    tmpfs   16G     0   16G   0%
none  /sys/fs/cgroup              tmpfs  225G     0  225G   0%
none  /__modal/mounts             9p     512G  800K  512G   1%  (rw)
none  /etc/resolv.conf            9p      39G   12G   27G  30%  (ro)
none  /run/modal_daemon           9p     512G  800K  512G   1%  (rw)
none  /__modal/.debug_shell       9p      39G   12G   27G  30%  (ro)
none  /__modal/.task-startup      9p     512G  800K  512G   1%  (ro)
none  /__modal/.container-arguments 9p   512G  800K  512G   1%  (ro)
```

Key observations:
- **512 GiB** root filesystem — by far the largest of all platforms (E2B: 22.9G, exe.dev: 20G, Sprites: 20G, Daytona: 3G)
- `/etc/resolv.conf` is on a **separate 9p mount** (39G, 30% used = 12G) — this comes from the host's filesystem, not the sandbox image
- Multiple `/__modal/*` mounts for internal communication (daemon socket, debug shell, task startup, container arguments)
- Two mount cache modes: `fscache` (root, aggressive caching) vs `remote_revalidating` (internal mounts, always check host)

### Storage Quota Test (Confirmed)

**The 512 GiB is a real, hard-enforced limit.** Tested by writing 5 GiB chunks via `dd` until failure:

| Milestone | Observation |
|-----------|-------------|
| 0–215 GiB | Steady writes at 1.6–2.1 GB/s |
| ~215 GiB | Disk usage **drops ~64 GiB** (331G → 267G) — host-side reclamation of zero blocks |
| 215–375 GiB | Resumes writing, refills to 512G (100%) |
| ~375 GiB | Disk usage **drops again ~129 GiB** — same reclamation, write slows to 87 MB/s for one chunk |
| 375–465 GiB | Third fill cycle at 2.2 GB/s |
| ~470 GiB | Third drop (~37 GiB reclaimed), slow chunk (48s) |
| 470–512 GiB | Final fill to 100% |
| Chunk 103 (515 GiB total) | **Partial write**: only 2.0 GiB written (took 10s) |
| Chunk 104+ | **0 bytes written** — hard stop, no ENOSPC error from `dd` |
| Final state | `df`: 512G used, 272K free. `du -sh /tmp/`: 512G |
| After cleanup (`rm`) | Disk returns to 1.8M used — fully recoverable |

**Key findings:**

1. **Hard 512 GiB per-sandbox limit** — not shared, not virtual. Each sandbox gets its own 512G quota.
2. **Host-side zero-block reclamation** — the host (or gVisor's gofer process) detects zero-filled blocks and reclaims them, causing periodic disk usage drops. This is why we could write ~512 GiB of real data despite seeing the disk "fill up" multiple times mid-test. Since we were writing `/dev/zero`, the host could sparse-optimize the older files.
3. **No `ENOSPC` errno** — `dd` doesn't get a proper "No space left on device" error. It just writes 0 bytes silently. The `fallocate` test does get a proper error: `fallocate: fallocate failed: No space left on device`.
4. **Write throughput degrades near capacity** — drops from 2+ GB/s to 87–278 MB/s when the disk is 99-100% full and the host is reclaiming blocks.
5. **Sparse files work but report incorrectly** — `dd seek=600G` creates a 600G sparse file, but gVisor's `du` reports 600G (apparent size) instead of 0 (actual blocks). This is a gVisor quirk.
6. **`fallocate` enforces quota correctly** — allocating 10+50+100+200=360G succeeded, then 400G more failed (would exceed 512G).

### Disk Isolation Test (Confirmed Independent)

Tested by creating two sandboxes concurrently and writing data in one while monitoring the other:

| Test | Result |
|------|--------|
| Baseline | Both sandboxes: 512G total, 708K used |
| Write ~42 GiB in A | A: 42G used. **B: unchanged at 716K** |
| File visibility | B cannot see A's files (`cat` → "No such file or directory") |
| Write in both simultaneously | A: 84G used, B: 44G used — **no interference** |
| Same host? | **Yes** — identical MemTotal (1007 GiB), different cgroup IDs |

**Conclusion: each sandbox gets its own independent 512 GiB quota.** Sandboxes on the same physical host have completely isolated filesystems — no shared disk, no contention, no cross-visibility. The 9p filesystem gives each sandbox its own CoW directory tree on the host.

Also revealed a **different host class** than the fingerprint run: MemTotal = 1007 GiB (~1 TiB) vs 448 GiB previously. Modal uses heterogeneous Azure VMs — likely scaling across multiple SKUs (E64s for smaller workloads, M-series for denser packing).

### Storage Comparison

| Aspect | Modal | E2B | exe.dev | Sprites | Daytona |
|--------|-------|-----|---------|---------|---------|
| Root FS type | **9p** | ext4 | ext4 | overlay | Docker overlay |
| Capacity | **512 GiB (hard limit)** | 22.9 GiB | 20 GiB | 20 GiB + layers | 3 GiB |
| Block devices | **None** | 1 (vda) | 1 (sda) | 7+ (vbd) | 0 (container) |
| Distributed FS | **None** | None | None | JuiceFS | None |
| FS protocol | **Plan 9** | Block I/O | Block I/O | Block I/O | OverlayFS |
| Zero-block optimization | **Yes (host-side)** | No | No | No | No |

### Storage Performance

| Test | Modal | E2B | exe.dev | Sprites |
|------|-------|-----|---------|---------|
| Sequential write (1 GB) | **1.1 GB/s** | 1.1 GB/s | 476 MB/s | 568 MB/s |
| Sustained write (bulk) | **1.6–2.4 GB/s** | N/A | N/A | N/A |
| 4K sync write | **136 MB/s (~34K IOPS)** | 41.2 MB/s (~10K IOPS) | 59.9 MB/s (~14.6K IOPS) | N/A |

Modal has **the highest 4K IOPS** by a wide margin (34K vs 14.6K on exe.dev). This makes sense — 9p operations go through gVisor's VFS layer and the host's page cache without hitting a real block device. Sustained bulk writes are even faster (2.0–2.4 GB/s) than the initial 1 GB benchmark, likely due to host page cache warming up.

---

## Guest OS

| Property | Value |
|----------|-------|
| **OS** | Debian 12 (Bookworm) |
| **Init** | `dumb-init` (PID 1: `/bin/dumb-init -- sleep 172800`) |
| **User** | `root` (uid=0, gid=0) |
| **Shell** | `/bin/bash` |
| **Python** | 3.13.3 |
| **Hostname** | `modal` |

The `sleep 172800` argument = 48 hours, which is the sandbox's maximum lifetime / keep-alive timeout.

---

## Network

| Property | Value |
|----------|-------|
| **External access** | **None** (curl to ifconfig.me, ipinfo.io both failed) |
| **DNS resolver** | `172.21.0.1` (internal Modal resolver) + `1.1.1.1` + `8.8.8.8` |
| **Network tools** | `ip`, `ifconfig` not available |
| **Metadata endpoint** | Not reachable (169.254.169.254 blocked for both GCP and AWS) |

Key findings:
- **No outbound internet by default** — this is a significant difference from E2B, exe.dev, and Sprites which all have internet access. Modal sandboxes are network-isolated by default (outbound can be enabled via `Sandbox.create(..., allow_outbound=True)`)
- DNS points to `172.21.0.1` — an internal Modal resolver on a private subnet, likely running on the host or a sidecar
- The `/etc/resolv.conf` is auto-generated by Modal and mounted read-only

---

## Modal Environment Variables

| Variable | Value | Purpose |
|----------|-------|---------|
| `MODAL_SANDBOX_ID` | `sb-E61GDBUMtgCcLt0hTp4bAH` | Unique sandbox identifier |
| `MODAL_TASK_ID` | `ta-01KHWAJCQD1NBBX9HSFDZXTCM2` | Task/cgroup identifier |
| `MODAL_IMAGE_ID` | `im-R5Wufnqy0S6jjwIcH8Q8fV` | Container image hash |
| `MODAL_FUNCTION_RUNTIME` | `gvisor` | Isolation runtime |
| `MODAL_CLOUD_PROVIDER` | `CLOUD_PROVIDER_AZURE` | Underlying cloud |
| `MODAL_REGION` | `eastus` | Azure region |
| `MODAL_CONTAINER_ARGUMENTS_PATH` | `/__modal/.container-arguments/data.bin` | Binary config blob |

Also notable:
- `PYTHONHASHSEED=0` — deterministic Python hashing (reproducibility)
- `UV_BREAK_SYSTEM_PACKAGES=1` — allows uv/pip to install into system Python
- `OMP_NUM_THREADS=1`, `MKL_NUM_THREADS=1`, `OPENBLAS_NUM_THREADS=1`, `BLIS_NUM_THREADS=1` — all math libraries pinned to 1 thread (prevents oversubscription on shared hosts)

---

## Persistence & Snapshots

### Filesystem Snapshots — PASS

Modal supports `snapshot_filesystem()` which creates a diff-based image of the sandbox's current state. Tested with 100 MiB of random data + text files:

| Metric | Value |
|--------|-------|
| **Snapshot time** | **4.66s** (100 MiB of modified data) |
| **Restore time** | **0.11s** (near-instant) |
| **Data integrity** | All MD5 checksums match (PASS) |
| **Files preserved** | /tmp/*, /opt/*, all directories |

Snapshot overhead scales sub-linearly with data size (diff-based, only modified files stored):

| Data Written | Snapshot Time |
|-------------|---------------|
| 0 MiB | 0.59s |
| 100 MiB | 3.40s |
| 500 MiB | 4.45s |
| 1000 MiB | 9.25s |

Snapshots are **incremental/diff-based** — only changes from the base image are captured. 500 MiB (4.45s) was only ~1s slower than 100 MiB (3.40s). Restore uses the same infrastructure as Modal's cold-start optimization, explaining the 0.11s restore time.

A `.__modal_markerViHfIX` file appears in /tmp after restore — Modal's internal snapshot marker.

### Volume Persistence — PASS

Mounted a `modal.Volume` at `/data`, wrote 50 MiB of random data + text file, terminated sandbox, remounted in a new sandbox. **Data persisted with matching MD5 checksums.**

Critical requirement: **must call `sb.wait(raise_on_termination=False)` after `sb.terminate()`** — without it, writes are lost because the volume isn't flushed before teardown. Initial test without `wait()` resulted in empty volume.

Client-side API also confirmed persistence before remounting:
- `vol.read_file("persist.txt")` → `"persistent data"`
- `vol.listdir("/")` → `['random_50mb', 'persist.txt']`

Volume details:
- Volumes mount at `/__modal/volumes` internally, mapped to the user-specified path (`/data`)
- Volume filesystem: 9p, **382 GiB** capacity (different from root's 512 GiB)
- Volume shows 0 bytes used in `df` even after writing 50 MiB (lazy accounting or write-back cache)
- Volumes persist across sandbox lifetimes and can be deleted via `modal.Volume.objects.delete()`

---

## Supported Filesystems

```
nodev    proc
nodev    cgroup
nodev    sysfs
nodev    tmpfs
nodev    mqueue
nodev    devpts
nodev    devtmpfs
nodev    erofs
nodev    fuse
nodev    9p
nodev    overlay
```

Only `nodev` filesystems — no real block device filesystems (ext4, xfs, etc.). This confirms there are no block devices. The `erofs` (Enhanced Read-Only File System) support suggests gVisor may use it for image layers internally. `fuse` and `overlay` are available but unused in this sandbox.

---

## Architecture Diagram

```
Microsoft Azure (eastus)
├── Azure VM (AMD EPYC, ~448 GiB RAM, likely E64s_v5 or similar)
│   ├── Host Linux (real kernel, unknown version)
│   │   ├── gVisor (runsc) — userspace kernel
│   │   │   ├── Sandbox: modal (1 vCPU, no memory limit)
│   │   │   │   ├── Fake kernel 4.4.0 (gVisor's syscall layer)
│   │   │   │   ├── / (9p, 512G hard limit) — host FS passthrough
│   │   │   │   ├── /dev/shm (tmpfs, 16G)
│   │   │   │   ├── dumb-init (PID 1) → sleep 172800
│   │   │   │   ├── Debian 12, Python 3.13.3
│   │   │   │   ├── No network interfaces visible
│   │   │   │   ├── DNS: 172.21.0.1 (Modal internal)
│   │   │   │   ├── /__modal/* (9p mounts for internal comms)
│   │   │   │   └── user: root
│   │   │   ├── Sandbox: [another-sandbox] ...
│   │   │   └── (density: high — gVisor overhead is ~15-30 MB/sandbox)
│   │   │
│   │   ├── Modal daemon (/run/modal_daemon via 9p)
│   │   └── Internal DNS resolver (172.21.0.1)
│   │
│   └── Azure networking (no outbound by default)
```

---

## Packing Density Estimate

gVisor's per-sandbox overhead is very low (~15-30 MB for the gVisor kernel + sentry process). With no memory cgroup limits visible, Modal likely manages density at the orchestration layer rather than per-sandbox cgroups.

On an Azure `Standard_E64s_v5` (64 vCPUs, 512 GiB RAM):

| Strategy | Sandboxes per VM |
|----------|-----------------|
| 1 vCPU, 512 MiB assumed per sandbox | ~900 (memory-bound) |
| 1 vCPU, no overcommit (CPU-bound) | 64 |
| 2:1 CPU overcommit | 128 |
| Idle packing (~50 MB overhead each) | ~10,000 |

With gVisor's low overhead and no visible memory limits, Modal likely achieves **very high density** — potentially 200-500+ sandboxes per VM for typical AI code execution workloads.

---

## Six-Way Comparison

| Aspect | Daytona | exe.dev | Sprites | E2B | Modal | Blaxel |
|--------|---------|---------|---------|-----|-------|--------|
| **Isolation** | Docker + Sysbox | Cloud Hypervisor | Firecracker | Firecracker | **gVisor** | TBD |
| **Host provider** | Hetzner | Latitude.sh | Fly.io | GCP | **Azure** | TBD |
| **Host CPU** | AMD EPYC 9254 | AMD EPYC 9554P | AMD EPYC (masked) | Intel Xeon | **AMD EPYC (masked)** | TBD |
| **Region** | Unknown | Los Angeles | Los Angeles | The Dalles, OR | **eastus** | TBD |
| **Kernel** | Shared (6.8.0) | Custom (6.12.67) | Custom (6.12.47-fly) | 6.1.158 | **Fake 4.4.0 (gVisor)** | TBD |
| **Init** | Daytona daemon | systemd | tini | systemd | **dumb-init** | TBD |
| **RAM** | 1 GiB (cgroup) | 7.2 GiB | 7.8 GiB | 482 MiB | **Unlimited (no cgroup)** | TBD |
| **CPU** | 1 core | 2 vCPUs | 8 vCPUs | 2 vCPUs | **1 vCPU** | TBD |
| **Disk** | 3 GiB overlay | 20 GiB ext4 | 20 GiB + layers | 22.9 GiB ext4 | **512 GiB (9p)** | TBD |
| **Root FS** | Docker overlay | Single disk | Multi-device overlay | Single disk | **9p passthrough** | TBD |
| **Seq write** | N/A | 476 MB/s | 568 MB/s | 1.1 GB/s | **1.1 GB/s** | TBD |
| **4K IOPS** | N/A | ~14.6K | N/A | ~10K | **~34K** | TBD |
| **Internet** | Yes | Yes | Yes | Yes | **No (default)** | TBD |
| **Density** | ~500-800/host | ~50-80/host | ~20-40/host | ~50-100/VM | **~200-500+/VM** | TBD |
| **OS** | Debian 13 | Ubuntu 24.04 | Ubuntu 25.04 | Debian 12 | **Debian 12** | TBD |
| **Design goal** | Max density | Dev machine | Stateful + isolated | Ephemeral execution | **Serverless compute** | TBD |

---

## Key Takeaways

1. **gVisor is unique** — Modal is the only platform in this comparison using gVisor. Everyone else uses either Firecracker (E2B, Sprites), Cloud Hypervisor (exe.dev), or Docker+Sysbox (Daytona). gVisor provides strong isolation through syscall interception without hardware virtualization overhead.

2. **512 GiB storage** — The largest storage allocation by far, but it's a 9p virtual filesystem (likely backed by the host's disk with copy-on-write at the host layer), not a dedicated block device. The 800K used at startup suggests thin provisioning.

3. **No internet by default** — Modal is the only platform that blocks outbound network access by default. This is a deliberate security choice for sandboxed code execution.

4. **Azure, not AWS/GCP** — Surprising given that most sandbox platforms use AWS or GCP. Modal runs on Azure `eastus`, with AMD EPYC CPUs.

5. **Best 4K IOPS** — 34K IOPS, more than 2x the next closest (exe.dev at 14.6K). The 9p + gVisor VFS + host page cache combination is very fast for small writes.

6. **No visible resource limits** — Memory and CPU cgroup limits are effectively unlimited. Modal likely enforces limits at the orchestration/billing layer or via gVisor's own resource controls rather than Linux cgroups.

7. **The spectrum refined:**
   - **Daytona** → Max density, containers, fast cold start, tiny sandboxes (3 GiB)
   - **E2B** → Ephemeral microVMs, minimal resources, GCP scale
   - **Modal** → gVisor on Azure, largest storage, no internet, serverless-first
   - **exe.dev** → "Real dev machine" VMs, full systemd, persistent, SSH-first
   - **Sprites** → Most sophisticated: Firecracker + container layers + JuiceFS + checkpoints
