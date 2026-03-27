| | **E2B** | **Daytona** | **Modal** | **Blaxel** | **Sprites** | **exe.dev** | **Freestyle** | **Cloudflare** |
|---|---|---|---|---|---|---|---|---|
| **Hosting Provider** | GCP (The Dalles, OR) | Hetzner bare-metal | Azure (eastus) | AWS us-west-2 | Fly.io (Los Angeles) | Latitude.sh bare-metal (Los Angeles) | Comcast/residential (Napa, CA) | Cloudflare own (geo-distributed, tested: Mumbai) |
| **Host CPU** | Intel Xeon @ 2.60GHz | AMD EPYC 9254 24C/48T | AMD EPYC | Intel Xeon @ 2.90GHz (Ice Lake) | AMD EPYC | AMD EPYC 9554P 64C | AMD EPYC | AMD EPYC (AVX-512) |
| **Isolation** | Firecracker microVM | Docker + Sysbox | gVisor (on Azure VM) | Firecracker + Unikraft | Firecracker microVM | Cloud Hypervisor VM | Firecracker microVM | Firecracker microVM + OCI container |
| **Isolation Level** | Hardware (KVM) | Container (cgroup v2) | Kernel-level (syscall filter) | Hardware (KVM) + Unikernel | Hardware (KVM) | Hardware (KVM) | Hardware (KVM) | Hardware (KVM) + container overlay |
| **vCPUs** | 2 | 1 | 1 | 2 | — | 2 | 4 | 1 |
| **RAM** | 482 MiB | 1 GiB | Host RAM leaks (~448 GiB visible) | 3.8 GiB | — | 7.2 GiB | 7.8 GiB | 466 MiB |
| **Disk Size** | 22.9 GiB | 3 GiB | 512 GiB | 1.9 GiB | 20 GiB + checkpoints | 18.6 GiB | 15.6 GiB | 2 GiB (root) + 2.3 GiB (4 disks total) |
| **Disk Type** | ext4 on virtio-blk (`/dev/vda`) | Docker overlay on software RAID | 9p passthrough (no block device) | ramfs (RAM-only, no block device) | Multi-layer overlay (JuiceFS) | ext4 on virtio-blk (`/dev/vda`) | ext4 on virtio-blk (`/dev/vda`) | ext4 on virtio-blk (`/dev/vdc`) + OCI overlay |
| **Swap** | None | None | None | None | — | None | None | None |
| **Network** | Public IP (GCP) | Docker bridge (172.20.0.0/16) | No outbound internet | Public IP (AWS) | Public IPv4 + IPv6 | Public IP | Public IP (Comcast NAT) | Cloudflare anycast (IPv6-first) |
