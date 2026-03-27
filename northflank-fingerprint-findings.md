# Northflank Sandbox Fingerprinting Findings

## Summary

Northflank runs **Kata Containers with Cloud Hypervisor (CLH) on KVM** for workload isolation. Each job gets a dedicated microVM with its own kernel, using **virtiofs** for the root filesystem and **pmem** (persistent memory) for the guest OS image. The container runs inside the microVM with cgroup-based resource limits.

---

## Isolation Stack

| Layer | Technology |
|-------|-----------|
| **Hypervisor** | KVM |
| **VMM** | Cloud Hypervisor (`DMI: Cloud Hypervisor cloud-hypervisor, BIOS 0`) |
| **Container Runtime** | Kata Containers (`systemd.unit=kata-containers.target` in kernel cmdline) |
| **Filesystem** | virtiofs (`kataShared on / type virtiofs`) |
| **Guest Kernel** | Linux 6.12.60 (custom build, no "kata" in version string) |
| **Orchestration** | Kubernetes (containerd) |

## Kernel & OS

| Property | Value |
|----------|-------|
| Kernel | `6.12.60 #1 SMP Thu Dec 4 16:27:11 UTC 2025` |
| Built on | `@36bd407da5d3` (container build hash) |
| Compiler | gcc 11.4.0 (Ubuntu 22.04) |
| Guest OS | Ubuntu 22.04.5 LTS (Jammy Jellyfish) |
| Boot source | `root=/dev/pmem0p1` (DAX-backed persistent memory) |
| Kernel cmdline | `root=/dev/pmem0p1 rootflags=dax,data=ordered,errors=remount-ro ro rootfstype=ext4 panic=1 no_timer_check noreplace-smp quiet systemd.unit=kata-containers.target systemd.mask=systemd-networkd.service systemd.mask=systemd-networkd.socket agent.drop_cache_type=3 systemd.unified_cgroup_hierarchy=1 agent.hotplug_timeout=8` |

## CPU

| Property | Value |
|----------|-------|
| Model | Intel Xeon Platinum 8581C @ 2.10GHz |
| nproc | 3 (VM sees 32 cores, cgroup limits to plan) |
| CPU quota | `20000 100000` (0.2 vCPU via cgroup) |
| `NF_CPU_RESOURCES` | 0.2 |
| Hypervisor flag | Present |
| Notable flags | AVX-512, TSX (HLE/RTM) |

## Memory

| Property | Value |
|----------|-------|
| VM total | ~3 GB (MemTotal: 3,080,172 kB) |
| Cgroup limit | 512 MB (`memory.max = 512000000`) |
| `NF_RAM_RESOURCES` | 512 |
| Swap | None |
| Available at boot | ~2.8 GB |

## Storage

| Property | Value |
|----------|-------|
| Root FS | virtiofs (`kataShared`), 338G total, 281G used, 58G avail |
| Guest OS disk | pmem0 (254M, ext4 with DAX) |
| Block devices | Only pmem0 (no vda/sda) |
| Ephemeral storage | 2048 MB (`NF_EPHEMERAL_STORAGE`) |
| Seq write (1GB) | 65.8 MB/s |
| 4K sync write | 1.8 MB/s (~432 IOPS) |

## Network

| Property | Value |
|----------|-------|
| External access | **None** (no public IP, curl fails) |
| Pod IP | 10.28.11.194 |
| K8s DNS | 10.22.0.10 |
| DNS search | `ns-cgd4q4y59xgj.svc.cluster.local svc.cluster.local cluster.local` |
| Network tools | None (no `ip`, `ifconfig`, `traceroute`) |
| Metadata endpoint | Not accessible (169.254.169.254 blocked) |

## Platform Runtime

| Property | Value |
|----------|-------|
| PID 1 | `/.platform-runtime/bin/env-injector` (Northflank's custom init) |
| Runtime dirs | `/.platform-runtime/bin`, `/.platform-runtime/cache`, `/.northflank-runtime/bin` (all tmpfs) |
| Region | `us-east1` (GCP) |
| Plan | `nf-compute-20` |
| Object type | `job` |
| Namespace | `ns-cgd4q4y59xgj` |

## Northflank Environment Variables

```
NF_CPU_RESOURCES=0.2
NF_DISCOVERY_SERVICE=fingerprint-...-headless
NF_ENV_SIDECAR_QUIT_ENDPOINT=http://127.0.0.1:15020/quitquitquit
NF_EPHEMERAL_STORAGE=2048
NF_EXTERNAL_DOCKER_IMAGE=library/ubuntu:22.04
NF_EXTERNAL_DOCKER_PRIVATE=false
NF_EXTERNAL_DOCKER_PROVIDER=dockerhub
NF_NAMESPACE=ns-cgd4q4y59xgj
NF_OBJECT_ID=fingerprint-...
NF_OBJECT_TYPE=job
NF_PLAN_ID=nf-compute-20
NF_POD_ID=<uuid>
NF_POD_IP=10.28.11.194
NF_POD_NAME=fingerprint-...-2vgrq
NF_PROJECT_ID=testingsandboxes
NF_RAM_RESOURCES=512
NF_REGION=us-east1
NF_RESOURCE_ID=fingerprint-...
```

## Security

| Property | Value |
|----------|-------|
| User | root (uid=0, gid=0) |
| Seccomp | Disabled (0) |
| LSM label | `kernel` (no AppArmor/SELinux enforcement) |
| .dockerenv | Not present |
| K8s service account | No token accessible |
| K8s secrets dir | Not accessible |
| /proc hardening | `/proc/bus`, `/proc/fs`, `/proc/irq`, `/proc/sys` mounted read-only; `/proc/interrupts`, `/proc/keys`, `/proc/timer_list` masked with tmpfs |
| Cloud metadata | Blocked (169.254.169.254 not reachable) |

## Filesystem Details

### Mounts
```
kataShared on / type virtiofs (rw,relatime)
proc on /proc type proc (rw,nosuid,nodev,noexec,relatime)
tmpfs on /dev type tmpfs (rw,nosuid,size=65536k)
sysfs on /sys type sysfs (ro,nosuid,nodev,noexec,relatime)
cgroup2 on /sys/fs/cgroup type cgroup2 (ro,nosuid,nodev,noexec)
tmpfs on /.platform-runtime/cache type tmpfs (rw,relatime,size=1015796k)
tmpfs on /.platform-runtime/bin type tmpfs (rw,relatime,size=1015796k)
tmpfs on /.northflank-runtime/bin type tmpfs (rw,relatime,size=1015796k)
kataShared on /etc/hosts type virtiofs (rw,relatime)
kataShared on /etc/hostname type virtiofs (rw,relatime)
kataShared on /etc/resolv.conf type virtiofs (rw,relatime)
kataShared on /dev/termination-log type virtiofs (rw,relatime)
```

### Supported Filesystems
ext2, ext3, ext4, xfs, erofs, virtiofs, 9p, overlay, fuse, fusectl, bpf, cgroup, cgroup2, selinuxfs

### /dev Devices
Minimal: fd, full, mqueue, null, ptmx, pts, random, shm, stderr, stdin, stdout, termination-log, tty, urandom, zero. No block devices exposed.

## Virtio Devices

6 virtio devices (virtio0-5) with device IDs: 0x0001, 0x0004, 0x001b, 0x0013, 0x0005, 0x001a

## Key Fingerprinting Indicators

To detect a Northflank environment from inside:

1. **Definitive**: `kataShared` in mount output + `NF_*` env vars
2. **Strong**: `virtiofs` root mount + `kata-containers.target` in `/proc/cmdline`
3. **Strong**: `Cloud Hypervisor` in dmesg DMI string
4. **Strong**: `/.platform-runtime/bin/env-injector` as PID 1
5. **Strong**: `/.northflank-runtime/` directory exists
6. **Moderate**: pmem0 block device (Kata's persistent memory boot)
7. **Moderate**: `hypervisor` CPU flag + no vda/sda + no public network
8. **Weak**: K8s env vars + `ns-*` namespace pattern

## Detection One-Liner

```bash
# Quick Northflank detection
env | grep -q '^NF_' && mount | grep -q 'kataShared' && echo "Northflank (Kata+CLH)" || echo "Not Northflank"
```
