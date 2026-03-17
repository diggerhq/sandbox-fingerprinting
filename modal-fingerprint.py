"""
Modal Sandbox Fingerprinting Script

Probes the environment inside a Modal sandbox to understand
the underlying platform, isolation method, and resource constraints.

Usage:
    pip install modal
    modal setup          # one-time auth
    python modal-fingerprint.py
"""

import modal


def run(sb, cmd: str, label: str) -> str:
    """Execute a command and print the result with a label."""
    try:
        proc = sb.exec("bash", "-c", cmd, timeout=30)
        stdout = proc.stdout.read()
        stderr = proc.stderr.read()
        output = stdout.strip() if stdout else "(no output)"
        if stderr and stderr.strip():
            output += f"\n[stderr]: {stderr.strip()}"
    except Exception as e:
        output = f"(error: {e})"
    print(f"\n{'=' * 60}")
    print(f"  {label}")
    print(f"  $ {cmd}")
    print(f"{'=' * 60}")
    print(output)
    return output


def fingerprint(sb):
    # --- OS & Kernel ---
    run(sb, "uname -a", "Kernel info")
    run(sb, "cat /proc/version", "Kernel version (proc)")
    run(sb, "cat /etc/os-release", "OS release")

    # --- Virtualization detection ---
    run(sb, "systemd-detect-virt 2>/dev/null || echo 'command not available'",
        "Virtualization type")
    run(sb, "grep -i hypervisor /proc/cpuinfo | head -1 || echo 'no hypervisor flag'",
        "Hypervisor from cpuinfo")
    run(sb, "cat /sys/class/dmi/id/sys_vendor 2>/dev/null || echo 'not available'",
        "DMI/BIOS vendor (VM indicator)")
    run(sb, "cat /sys/class/dmi/id/product_name 2>/dev/null || echo 'not available'",
        "DMI product name")
    run(sb, "ls -la /.dockerenv 2>/dev/null && echo 'DOCKER DETECTED' || echo 'No .dockerenv'",
        "Docker environment file")

    # --- Firecracker / microVM / gVisor detection ---
    run(sb, "cat /proc/cmdline 2>/dev/null || echo 'not available'",
        "Kernel cmdline (Firecracker passes specific args)")
    run(sb, "lsblk 2>/dev/null || ls /sys/block/ 2>/dev/null || echo 'no block devices visible'",
        "Block devices (virtio = VM, nvme = bare metal/cloud)")
    run(sb, "ls /sys/bus/virtio/devices/ 2>/dev/null || echo 'no virtio bus'",
        "Virtio devices")
    run(sb, "lspci 2>/dev/null || echo 'lspci not available'",
        "PCI devices (empty = microVM like Firecracker)")
    run(sb, "ls /sys/firmware/acpi/tables/ 2>/dev/null || echo 'no ACPI tables'",
        "ACPI tables")
    run(sb, "dmesg 2>/dev/null | grep -i gvisor | head -5 || echo 'no gVisor in dmesg'",
        "gVisor detection (dmesg)")
    run(sb, "cat /sys/devices/virtual/dmi/id/bios_vendor 2>/dev/null || echo 'not available'",
        "BIOS vendor")

    # --- CPU & Memory ---
    run(sb, "nproc", "CPU count")
    run(sb, "grep 'model name' /proc/cpuinfo | head -1",
        "CPU model")
    run(sb, "grep flags /proc/cpuinfo | head -1 | tr ' ' '\\n' | grep -E 'hypervisor|vmx|svm' || echo 'no VM-related flags'",
        "CPU flags (look for hypervisor flag)")
    run(sb, "free -h", "Memory")
    run(sb, "head -5 /proc/meminfo", "Memory info (detailed)")

    # --- cgroup ---
    run(sb, "cat /proc/1/cgroup 2>/dev/null | head -20 || echo 'not available'",
        "PID 1 cgroup")
    run(sb, "cat /sys/fs/cgroup/memory/memory.limit_in_bytes 2>/dev/null || "
        "cat /sys/fs/cgroup/memory.max 2>/dev/null || echo 'no cgroup memory limit'",
        "Cgroup memory limit")
    run(sb, "cat /sys/fs/cgroup/cpu/cpu.cfs_quota_us 2>/dev/null || "
        "cat /sys/fs/cgroup/cpu.max 2>/dev/null || echo 'no cgroup CPU limit'",
        "Cgroup CPU quota")

    # --- Filesystem ---
    run(sb, "df -hT", "Filesystem types and usage")
    run(sb, "lsblk -f 2>/dev/null || echo 'lsblk not available'",
        "Block device details")
    run(sb, "mount | grep ' / '", "Root filesystem mount")
    run(sb, "mount | head -40", "All mounts (summary)")
    run(sb, "cat /proc/mounts | head -40", "Proc mounts")

    # --- Boot / dmesg ---
    run(sb, "dmesg 2>/dev/null | head -80 || journalctl -k 2>/dev/null | head -80 || echo 'dmesg not available'",
        "Boot messages (first 80 lines — reveals hypervisor)")
    run(sb, "dmesg 2>/dev/null | grep -iE 'hypervisor|kvm|firecracker|qemu|xen|vmware|virtio|cloud-hypervisor|gvisor' | head -20 || echo 'nothing found'",
        "Hypervisor in dmesg")

    # --- Network ---
    run(sb, "ip addr 2>/dev/null || ifconfig 2>/dev/null || cat /proc/net/if_inet6 2>/dev/null || echo 'no network tools'",
        "Network interfaces")
    run(sb, "cat /etc/resolv.conf", "DNS config")
    run(sb, "cat /etc/hosts", "Hosts file")
    run(sb, "ip route show default 2>/dev/null || echo 'no route tools'",
        "Default route")

    # --- Cloud provider / metadata ---
    run(sb, "curl -s --connect-timeout 2 http://169.254.169.254/ 2>/dev/null | head -20 || echo 'no metadata endpoint'",
        "Metadata endpoint (cloud provider detection)")
    run(sb, "curl -s --connect-timeout 2 -H 'Metadata-Flavor: Google' http://169.254.169.254/computeMetadata/v1/ 2>/dev/null | head -10 || echo 'not GCP'",
        "GCP metadata")
    run(sb, "curl -s --connect-timeout 2 http://169.254.169.254/latest/meta-data/ 2>/dev/null | head -10 || echo 'not AWS'",
        "AWS metadata (IMDSv1)")
    run(sb, "TOKEN=$(curl -s --connect-timeout 2 -X PUT -H 'X-aws-ec2-metadata-token-ttl-seconds: 21600' http://169.254.169.254/latest/api/token 2>/dev/null) && "
        "curl -s --connect-timeout 2 -H \"X-aws-ec2-metadata-token: $TOKEN\" http://169.254.169.254/latest/meta-data/ 2>/dev/null | head -10 || echo 'not AWS IMDSv2'",
        "AWS metadata (IMDSv2)")

    # --- Processes ---
    run(sb, "ps aux 2>/dev/null | head -30",
        "Running processes")
    run(sb, "ls -la /sbin/init 2>/dev/null; file /sbin/init 2>/dev/null || echo 'unknown init'",
        "Init system")
    run(sb, "cat /proc/1/cmdline 2>/dev/null | tr '\\0' ' ' || echo 'not available'",
        "PID 1 command")

    # --- Disk ---
    run(sb, "cat /sys/block/vda/queue/scheduler 2>/dev/null || "
        "cat /sys/block/sda/queue/scheduler 2>/dev/null || echo 'unknown'",
        "Disk scheduler")
    run(sb, "cat /sys/fs/cgroup/io.max 2>/dev/null || echo 'no io limits'",
        "I/O cgroup limits")

    # --- Modal specific ---
    run(sb, "env | grep -iE 'modal|MODAL' || echo 'no MODAL env vars found'",
        "Modal environment variables")
    run(sb, "hostname", "Hostname")
    run(sb, "env | sort", "All environment variables")
    run(sb, "cat /etc/machine-id 2>/dev/null || echo 'no machine-id'",
        "Machine ID")
    run(sb, "whoami && id", "Current user")

    # --- Network path / hosting ---
    run(sb, "traceroute -n -m 10 1.1.1.1 2>/dev/null || echo 'traceroute not available'",
        "Traceroute (reveals network path / hosting)")
    run(sb, "curl -s --connect-timeout 5 ifconfig.me 2>/dev/null && echo || echo 'no external access'",
        "Public IP")
    run(sb, "curl -s --connect-timeout 5 https://ipinfo.io/json 2>/dev/null || echo 'no ipinfo access'",
        "IP info (ASN / provider)")

    # --- Storage perf ---
    run(sb, "dd if=/dev/zero of=/tmp/bench_write bs=1M count=1000 2>&1 | tail -1; rm -f /tmp/bench_write",
        "Sequential write throughput (1 GB)")
    run(sb, "dd if=/dev/zero of=/tmp/bench_4k bs=4k count=10000 oflag=dsync 2>&1 | tail -1; rm -f /tmp/bench_4k",
        "4K sync write (IOPS indicator)")

    # --- NFS / distributed FS detection ---
    run(sb, "mount | grep -iE 'nfs|fuse|juicefs|gcsfuse|s3fs|ceph|lustre' || echo 'no distributed FS mounts'",
        "Distributed filesystem mounts")
    run(sb, "cat /proc/filesystems 2>/dev/null | head -30",
        "Supported filesystems")

    print("\n" + "=" * 60)
    print("  Fingerprinting complete.")
    print("=" * 60)


def main():
    app = modal.App.lookup("fingerprint-sandbox", create_if_missing=True)

    print("Creating Modal sandbox...")
    sb = modal.Sandbox.create(app=app, timeout=300)
    print(f"Sandbox created: {sb.object_id}")

    try:
        fingerprint(sb)
    finally:
        sb.terminate()
        print("Sandbox terminated.")


if __name__ == "__main__":
    main()
