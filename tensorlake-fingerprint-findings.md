# Tensorlake Sandbox Fingerprinting Findings

## Summary

Tensorlake (formerly Indexify) runs **Firecracker microVMs on AWS EC2** with a custom init system. Each sandbox gets a dedicated VM with its own kernel, virtio-blk storage, and direct internet access. The platform uses the classic Firecracker pattern with virtio-mmio devices and link-local TAP networking.

---

## Isolation Stack

| Layer | Technology |
|-------|-----------|
| **Hypervisor** | KVM |
| **VMM** | Firecracker (ACPI vendor: `FIRECK`, tables: `FCVMFADT`, `FCVMDSDT`, `FCVMMADT`) |
| **Guest Kernel** | Linux 6.1.155 (custom build, PREEMPT_DYNAMIC) |
| **Filesystem** | ext4 on virtio-blk (`/dev/vda`) |
| **Init** | Custom `/sbin/indexify-init` -> `indexify-daemon` |
| **Cloud** | AWS EC2 (us-east-1, Ashburn VA) |

## Kernel & OS

| Property | Value |
|----------|-------|
| Kernel | `6.1.155 #1 SMP PREEMPT_DYNAMIC Tue Nov 18 09:27:27 UTC 2025` |
| Built on | `root@0e0250f7f2f2` (container build) |
| Guest OS | Ubuntu 24.04 LTS (Noble Numbat) |
| Kernel cmdline | `reboot=k panic=1 pci=off console=ttyS0 net.ifnames=0 ip=169.254.0.21::169.254.0.22:255.255.255.252::eth0:off init=/sbin/indexify-init pci=off root=/dev/vda rw virtio_mmio.device=4K@0xc0001000:6 virtio_mmio.device=4K@0xc0002000:7 virtio_mmio.device=4K@0xc0003000:8` |
| KASLR | Disabled |
| Hostname | `indexify-vm` |

## CPU

| Property | Value |
|----------|-------|
| Model | Intel Xeon Processor (generic name, likely Sapphire Rapids) |
| Clock | 2.7 GHz (TSC detected) |
| vCPUs | 3 |
| Hypervisor flag | Present |
| Notable flags | AVX-512, AMX (amx_bf16, amx_tile, amx_int8), PKU |
| No cgroup CPU limit | CPU quota not set |

## Memory

| Property | Value |
|----------|-------|
| VM total | 6.6 GB (MemTotal: 6,954,836 kB) |
| Cgroup limit | None (no memory.max set) |
| Swap | None |
| Available at boot | ~6.5 GB |

## Storage

| Property | Value |
|----------|-------|
| Root disk | `/dev/vda` — ext4, 30 GB, 584 MB used |
| Binary disk | `/dev/vdb` — ext4, 64 MB, read-only, mounted at `/run/indexify-bin` |
| Virtio devices | 3 (virtio0=vda, virtio1=vdb, virtio2=net) |
| Device type | virtio-blk via virtio-mmio (classic Firecracker) |
| Disk scheduler | mq-deadline (default) |
| Seq write (1 GB) | **1.2 GB/s** |
| 4K sync write | **3.0 GB/s** (~730K IOPS — /tmp is tmpfs) |

## Network

| Property | Value |
|----------|-------|
| External access | **Yes** (public IP) |
| Public IP | 100.24.158.172 |
| Reverse DNS | `ec2-100-24-158-172.compute-1.amazonaws.com` |
| ASN | AS14618 Amazon.com, Inc. |
| Location | Ashburn, Virginia (us-east-1) |
| VM IP | 169.254.0.21/30 (link-local, Firecracker TAP) |
| Gateway | 169.254.0.22 |
| MAC | 02:fc:00:00:00:05 (`fc` = Firecracker prefix) |
| DNS | 10.2.0.2 (custom resolver) |
| Metadata | Custom endpoint at 169.254.169.254 returning `indexify/` (not AWS IMDS) |

## Platform Runtime

| Property | Value |
|----------|-------|
| PID 1 | `/run/indexify-bin/indexify-daemon --port 9500 --http-port 9501 --log-dir /var/log/indexify` |
| Init | `/sbin/indexify-init` (custom, not systemd) |
| Binary mount | `/dev/vdb` mounted read-only at `/run/indexify-bin` |
| Metadata | Custom MMDS at 169.254.169.254 serving `indexify/` path |

## Environment Variables

Minimal — no Tensorlake, Kubernetes, or platform-specific env vars exposed:

```
DNS_NAMESERVERS=10.2.0.2
HOME=/
PWD=/
SHLVL=1
TERM=linux
```

## Security

| Property | Value |
|----------|-------|
| User | root (uid=0, gid=0) |
| Seccomp | Disabled (0) |
| DMI | Not present (`DMI not present or invalid`) |
| .dockerenv | Not present |
| Cgroup limits | None (no CPU or memory limits set) |
| /proc | Read-write (not hardened) |
| /sys | Read-write |
| Transparent hugepages | `always [madvise] never` (madvise default) |

## Filesystem Details

### Mounts
```
/dev/vda on / type ext4 (rw,relatime)
devtmpfs on /dev type devtmpfs (rw,relatime,size=3474176k)
proc on /proc type proc (rw,relatime)
sysfs on /sys type sysfs (rw,relatime)
devpts on /dev/pts type devpts (rw,relatime)
tmpfs on /dev/shm type tmpfs (rw,relatime)
tmpfs on /tmp type tmpfs (rw,relatime)
tmpfs on /run type tmpfs (rw,relatime)
/dev/vdb on /run/indexify-bin type ext4 (ro,relatime)
```

### Supported Filesystems
ext2, ext3, ext4, squashfs, xfs, nfs, nfs4, overlay, autofs, pstore, selinuxfs

### /dev Devices
Full device tree including: console, cpu, hwrng, loop0-7, mem, null, port, ptp0, random, snapshot, sysgenid, tty0-63, urandom, vda, vdb, zero

## Key Fingerprinting Indicators

To detect a Tensorlake/Indexify environment from inside:

1. **Definitive**: `indexify-daemon` as PID 1 + `/run/indexify-bin` mount
2. **Definitive**: ACPI vendor `FIRECK` in dmesg (`ACPI: RSDP ... FIRECK`)
3. **Strong**: Hostname `indexify-vm`
4. **Strong**: `virtio_mmio.device` in kernel cmdline + `init=/sbin/indexify-init`
5. **Strong**: Custom metadata at 169.254.169.254 returning `indexify/`
6. **Strong**: MAC prefix `02:fc` (Firecracker)
7. **Moderate**: Link-local 169.254.0.x/30 networking (Firecracker TAP pattern)
8. **Moderate**: No DMI, no PCI, virtio-mmio only (Firecracker signature)

## Detection One-Liner

```bash
# Quick Tensorlake detection
pgrep -f indexify-daemon >/dev/null && echo "Tensorlake (Firecracker)" || echo "Not Tensorlake"
```

## Comparison Notes

Tensorlake has the **fastest disk I/O** of all tested providers:
- Sequential write: 1.2 GB/s (vs 192 MB/s Northflank, 500 MB/s E2B)
- 4K sync: 3.0 GB/s (tmpfs-backed /tmp, effectively RAM speed)
- Root disk (ext4/virtio-blk) will be slower but still fast (NVMe-backed EC2)

Also notable: full internet access, AMX instruction support (AI/ML acceleration), and no cgroup resource limits (you get the full VM allocation).
