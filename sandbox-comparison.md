| | **E2B** | **Daytona** | **Modal** | **Blaxel** | **Sprites** | **exe.dev** |
|---|---|---|---|---|---|---|
| **Hosting Provider** | GCP (The Dalles, OR) | Hetzner bare-metal | Azure (eastus) | AWS us-west-2 | Fly.io (Los Angeles) | Latitude.sh bare-metal (Los Angeles) |
| **Host CPU** | Intel Xeon @ 2.60GHz | AMD EPYC 9254 24C/48T | AMD EPYC | Intel Xeon @ 2.90GHz (Ice Lake) | AMD EPYC | AMD EPYC 9554P 64C |
| **Isolation** | Firecracker microVM | Docker + Sysbox | gVisor (on Azure VM) | Firecracker + Unikraft | Firecracker microVM | Cloud Hypervisor VM |
| **Isolation Level** | Hardware (KVM) | Container (cgroup v2) | Kernel-level (syscall filter) | Hardware (KVM) + Unikernel | Hardware (KVM) | Hardware (KVM) |
| **vCPUs** | 2 | 1 | 1 | 2 | — | 2 |
| **RAM** | 482 MiB | 1 GiB | Host RAM leaks (~448 GiB visible) | 3.8 GiB | — | 7.2 GiB |
| **Disk Size** | 22.9 GiB | 3 GiB | 512 GiB | 1.9 GiB | 20 GiB + checkpoints | 18.6 GiB |
| **Disk Type** | ext4 on virtio-blk (`/dev/vda`) | Docker overlay on software RAID | 9p passthrough (no block device) | ramfs (RAM-only, no block device) | Multi-layer overlay (JuiceFS) | ext4 on virtio-blk (`/dev/vda`) |
| **Swap** | None | None | None | None | — | None |
| **Network** | Public IP (GCP) | Docker bridge (172.20.0.0/16) | No outbound internet | Public IP (AWS) | Public IPv4 + IPv6 | Public IP |
