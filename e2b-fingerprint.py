"""
E2B Sandbox Fingerprinting Script

Probes the environment inside an E2B sandbox to understand
the underlying platform, isolation method, and resource constraints.

Usage:
    export E2B_API_KEY=your-key
    pip install e2b
    python e2b-fingerprint.py
"""

from e2b import Sandbox


def run(sandbox, cmd: str, label: str) -> str:
    """Execute a command and print the result with a label."""
    try:
        result = sandbox.commands.run(cmd, timeout=30)
        output = result.stdout.strip() if result.stdout else "(no output)"
        if result.stderr and result.stderr.strip():
            output += f"\n[stderr]: {result.stderr.strip()}"
    except Exception as e:
        output = f"(error: {e})"
    print(f"\n{'=' * 60}")
    print(f"  {label}")
    print(f"  $ {cmd}")
    print(f"{'=' * 60}")
    print(output)
    return output


def fingerprint(sandbox):
    # --- OS & Kernel ---
    run(sandbox, "uname -a", "Kernel info")
    run(sandbox, "cat /proc/version", "Kernel version (proc)")
    run(sandbox, "cat /etc/os-release", "OS release")

    # --- Virtualization detection ---
    run(sandbox, "systemd-detect-virt 2>/dev/null || echo 'command not available'",
        "Virtualization type")
    run(sandbox, "grep -i hypervisor /proc/cpuinfo | head -1 || echo 'no hypervisor flag'",
        "Hypervisor from cpuinfo")
    run(sandbox, "cat /sys/class/dmi/id/sys_vendor 2>/dev/null || echo 'not available'",
        "DMI/BIOS vendor (VM indicator)")
    run(sandbox, "cat /sys/class/dmi/id/product_name 2>/dev/null || echo 'not available'",
        "DMI product name")
    run(sandbox, "ls -la /.dockerenv 2>/dev/null && echo 'DOCKER DETECTED' || echo 'No .dockerenv'",
        "Docker environment file")

    # --- Firecracker / microVM detection ---
    run(sandbox, "cat /proc/cmdline",
        "Kernel cmdline (Firecracker passes specific args)")
    run(sandbox, "lsblk 2>/dev/null || ls /sys/block/",
        "Block devices (virtio = VM, nvme = bare metal/cloud)")
    run(sandbox, "ls /sys/bus/virtio/devices/ 2>/dev/null || echo 'no virtio bus'",
        "Virtio devices")
    run(sandbox, "lspci 2>/dev/null || echo 'lspci not available'",
        "PCI devices (empty = microVM like Firecracker)")
    run(sandbox, "ls /sys/firmware/acpi/tables/ 2>/dev/null || echo 'no ACPI tables'",
        "ACPI tables (Firecracker has minimal ACPI)")
    run(sandbox, "ls /sys/firmware/devicetree/ 2>/dev/null || echo 'no device tree'",
        "Device tree")

    # --- CPU & Memory ---
    run(sandbox, "nproc", "CPU count")
    run(sandbox, "grep 'model name' /proc/cpuinfo | head -1",
        "CPU model")
    run(sandbox, "grep flags /proc/cpuinfo | head -1 | tr ' ' '\\n' | grep -E 'hypervisor|vmx|svm' || echo 'no VM-related flags'",
        "CPU flags (look for hypervisor flag)")
    run(sandbox, "free -h", "Memory")
    run(sandbox, "head -5 /proc/meminfo", "Memory info (detailed)")

    # --- cgroup ---
    run(sandbox, "cat /proc/1/cgroup 2>/dev/null | head -20 || echo 'not available'",
        "PID 1 cgroup")
    run(sandbox, "cat /sys/fs/cgroup/memory/memory.limit_in_bytes 2>/dev/null || cat /sys/fs/cgroup/memory.max 2>/dev/null || echo 'no cgroup memory limit'",
        "Cgroup memory limit")
    run(sandbox, "cat /sys/fs/cgroup/cpu/cpu.cfs_quota_us 2>/dev/null || cat /sys/fs/cgroup/cpu.max 2>/dev/null || echo 'no cgroup CPU limit'",
        "Cgroup CPU quota")

    # --- Filesystem ---
    run(sandbox, "df -hT", "Filesystem types and usage")
    run(sandbox, "lsblk -f 2>/dev/null || echo 'lsblk not available'",
        "Block device details")
    run(sandbox, "mount | grep ' / '", "Root filesystem mount")
    run(sandbox, "mount | head -30", "All mounts (summary)")

    # --- Boot / dmesg ---
    run(sandbox, "dmesg 2>/dev/null | head -80 || journalctl -k 2>/dev/null | head -80 || echo 'dmesg not available'",
        "Boot messages (first 80 lines — reveals hypervisor)")
    run(sandbox, "dmesg 2>/dev/null | grep -iE 'hypervisor|kvm|firecracker|qemu|xen|vmware|virtio|cloud-hypervisor' | head -20 || echo 'nothing found'",
        "Hypervisor in dmesg")

    # --- Network ---
    run(sandbox, "ip addr 2>/dev/null || ifconfig 2>/dev/null || echo 'no network tools'",
        "Network interfaces")
    run(sandbox, "cat /etc/resolv.conf", "DNS config")
    run(sandbox, "cat /etc/hosts", "Hosts file")
    run(sandbox, "ip route show default 2>/dev/null || echo 'no route tools'",
        "Default route")

    # --- Cloud provider / metadata ---
    run(sandbox, "curl -s --connect-timeout 2 http://169.254.169.254/ 2>/dev/null | head -20 || echo 'no metadata endpoint'",
        "Metadata endpoint (cloud provider detection)")
    run(sandbox, "curl -s --connect-timeout 2 -H 'Metadata-Flavor: Google' http://169.254.169.254/computeMetadata/v1/ 2>/dev/null | head -10 || echo 'not GCP'",
        "GCP metadata")
    run(sandbox, "curl -s --connect-timeout 2 http://169.254.169.254/latest/meta-data/ 2>/dev/null | head -10 || echo 'not AWS'",
        "AWS metadata (IMDSv1)")

    # --- Processes ---
    run(sandbox, "ps aux 2>/dev/null | head -30",
        "Running processes")
    run(sandbox, "ls -la /sbin/init 2>/dev/null; file /sbin/init 2>/dev/null || echo 'unknown init'",
        "Init system")
    run(sandbox, "systemctl list-units --type=service --state=running 2>/dev/null | head -20 || echo 'not systemd'",
        "Systemd units (if systemd)")

    # --- Disk ---
    run(sandbox, "cat /sys/block/vda/queue/scheduler 2>/dev/null || cat /sys/block/sda/queue/scheduler 2>/dev/null || echo 'unknown'",
        "Disk scheduler")
    run(sandbox, "cat /sys/fs/cgroup/io.max 2>/dev/null || echo 'no io limits'",
        "I/O cgroup limits")

    # --- E2B specific ---
    run(sandbox, "env | grep -iE 'e2b|E2B|sandbox' || echo 'no E2B env vars found'",
        "E2B environment variables")
    run(sandbox, "hostname", "Hostname")
    run(sandbox, "env | sort", "All environment variables")
    run(sandbox, "cat /etc/machine-id 2>/dev/null || echo 'no machine-id'",
        "Machine ID")

    # --- Network path / hosting ---
    run(sandbox, "traceroute -n -m 10 1.1.1.1 2>/dev/null | head -12 || echo 'traceroute not available'",
        "Traceroute (reveals network path / hosting)")
    run(sandbox, "curl -s --connect-timeout 5 ifconfig.me 2>/dev/null && echo || echo 'no external access'",
        "Public IP")
    run(sandbox, "curl -s --connect-timeout 5 https://ipinfo.io/json 2>/dev/null || echo 'no ipinfo access'",
        "IP info (ASN / provider)")

    # --- Storage perf ---
    run(sandbox, "dd if=/dev/zero of=/tmp/bench_write bs=1M count=1000 2>&1 | tail -1; rm -f /tmp/bench_write",
        "Sequential write throughput (1 GB)")
    run(sandbox, "sudo dd if=/dev/vda of=/dev/null bs=4k count=1000 iflag=direct 2>&1 | tail -1 || echo 'direct read not available'",
        "4K direct read (IOPS indicator)")

    print("\n" + "=" * 60)
    print("  Fingerprinting complete.")
    print("=" * 60)


def main():
    with Sandbox() as sandbox:
        print(f"Sandbox ID: {sandbox.sandbox_id}")
        fingerprint(sandbox)
    print("Sandbox cleaned up.")


if __name__ == "__main__":
    main()
