"""
Sprites.dev (Fly.io) Sandbox Fingerprinting Script

Probes the environment inside a Sprites sandbox to understand
the underlying platform, isolation method, and resource constraints.

Usage:
    export SPRITES_TOKEN=your-token
    python sprites-fingerprint.py [sprite-name]
"""

import os
import sys

from sprites import SpritesClient


SPRITE_NAME = sys.argv[1] if len(sys.argv) > 1 else "fingerprint-probe"


def run(sprite, cmd: str, label: str) -> str:
    """Execute a command and print the result with a label."""
    try:
        result = sprite.run("bash", "-c", cmd, capture_output=True, timeout=30)
        output = result.stdout.decode().strip() if result.stdout else "(no output)"
    except Exception as e:
        output = f"(error: {e})"
    print(f"\n{'=' * 60}")
    print(f"  {label}")
    print(f"  $ {cmd}")
    print(f"{'=' * 60}")
    print(output)
    return output


def fingerprint(sprite):
    # --- OS & Kernel ---
    run(sprite, "uname -a", "Kernel info")
    run(sprite, "cat /proc/version", "Kernel version (proc)")
    run(sprite, "cat /etc/os-release", "OS release")

    # --- Virtualization detection ---
    run(sprite, "systemd-detect-virt 2>/dev/null || echo 'command not available'",
        "Virtualization type")
    run(sprite, "grep -i hypervisor /proc/cpuinfo | head -1 || echo 'no hypervisor flag'",
        "Hypervisor from cpuinfo")
    run(sprite, "cat /sys/class/dmi/id/sys_vendor 2>/dev/null || echo 'not available'",
        "DMI/BIOS vendor (VM indicator)")
    run(sprite, "cat /sys/class/dmi/id/product_name 2>/dev/null || echo 'not available'",
        "DMI product name")
    run(sprite, "ls -la /.dockerenv 2>/dev/null && echo 'DOCKER DETECTED' || echo 'No .dockerenv'",
        "Docker environment file")

    # --- Firecracker / microVM detection ---
    run(sprite, "cat /proc/cmdline",
        "Kernel cmdline (Firecracker passes specific args)")
    run(sprite, "lsblk 2>/dev/null || ls /sys/block/",
        "Block devices (virtio = VM, nvme = bare metal/cloud)")
    run(sprite, "ls /sys/bus/virtio/devices/ 2>/dev/null || echo 'no virtio bus'",
        "Virtio devices")
    run(sprite, "lspci 2>/dev/null || echo 'lspci not available'",
        "PCI devices (empty = microVM like Firecracker)")
    run(sprite, "ls /sys/firmware/acpi/tables/ 2>/dev/null || echo 'no ACPI tables'",
        "ACPI tables (Firecracker has minimal ACPI)")

    # --- CPU & Memory ---
    run(sprite, "nproc", "CPU count")
    run(sprite, "grep 'model name' /proc/cpuinfo | head -1",
        "CPU model")
    run(sprite, "grep flags /proc/cpuinfo | head -1 | tr ' ' '\\n' | grep -E 'hypervisor|vmx|svm' || echo 'no VM-related flags'",
        "CPU flags (look for hypervisor flag)")
    run(sprite, "free -h", "Memory")
    run(sprite, "head -5 /proc/meminfo", "Memory info (detailed)")

    # --- cgroup ---
    run(sprite, "cat /proc/1/cgroup 2>/dev/null | head -20",
        "PID 1 cgroup")
    run(sprite, "cat /sys/fs/cgroup/memory/memory.limit_in_bytes 2>/dev/null || cat /sys/fs/cgroup/memory.max 2>/dev/null || echo 'no cgroup memory limit'",
        "Cgroup memory limit")
    run(sprite, "cat /sys/fs/cgroup/cpu/cpu.cfs_quota_us 2>/dev/null || cat /sys/fs/cgroup/cpu.max 2>/dev/null || echo 'no cgroup CPU limit'",
        "Cgroup CPU quota")

    # --- Filesystem ---
    run(sprite, "df -hT", "Filesystem types and usage")
    run(sprite, "lsblk -f 2>/dev/null || echo 'lsblk not available'",
        "Block device details")
    run(sprite, "mount | grep ' / '", "Root filesystem mount")
    run(sprite, "mount | head -30", "All mounts (summary)")

    # --- Boot / dmesg ---
    run(sprite, "dmesg 2>/dev/null | head -80 || journalctl -k 2>/dev/null | head -80 || echo 'dmesg not available'",
        "Boot messages (first 80 lines — reveals hypervisor)")
    run(sprite, "dmesg 2>/dev/null | grep -iE 'hypervisor|kvm|firecracker|qemu|xen|vmware|virtio|cloud-hypervisor' | head -20 || echo 'nothing found'",
        "Hypervisor in dmesg")

    # --- Network ---
    run(sprite, "ip addr 2>/dev/null || ifconfig 2>/dev/null || echo 'no network tools'",
        "Network interfaces")
    run(sprite, "cat /etc/resolv.conf", "DNS config")
    run(sprite, "cat /etc/hosts", "Hosts file")
    run(sprite, "ip route show default 2>/dev/null || echo 'no route tools'",
        "Default route")

    # --- Cloud provider / metadata ---
    run(sprite, "curl -s --connect-timeout 2 http://169.254.169.254/ 2>/dev/null | head -20 || echo 'no metadata endpoint'",
        "Metadata endpoint (cloud provider detection)")
    run(sprite, "curl -s --connect-timeout 2 -H 'Metadata-Flavor: Google' http://169.254.169.254/computeMetadata/v1/ 2>/dev/null | head -10 || echo 'not GCP'",
        "GCP metadata")
    run(sprite, "curl -s --connect-timeout 2 http://169.254.169.254/latest/meta-data/ 2>/dev/null | head -10 || echo 'not AWS'",
        "AWS metadata (IMDSv1)")

    # --- Processes ---
    run(sprite, "ps aux 2>/dev/null | head -30",
        "Running processes")
    run(sprite, "ls -la /sbin/init 2>/dev/null; file /sbin/init 2>/dev/null || echo 'unknown init'",
        "Init system")

    # --- Storage performance ---
    run(sprite, "cat /sys/block/vda/queue/scheduler 2>/dev/null || cat /sys/block/sda/queue/scheduler 2>/dev/null || echo 'unknown'",
        "Disk scheduler")

    # --- Fly.io / Sprites specific ---
    run(sprite, "env | grep -iE 'fly|sprite|FLY|SPRITE' || echo 'no Fly/Sprites env vars found'",
        "Fly.io / Sprites environment variables")
    run(sprite, "hostname", "Hostname")
    run(sprite, "env | sort", "All environment variables")
    run(sprite, "cat /etc/machine-id 2>/dev/null || echo 'no machine-id'",
        "Machine ID")

    # --- Network path ---
    run(sprite, "traceroute -n 1.1.1.1 2>/dev/null | head -10 || echo 'traceroute not available'",
        "Traceroute (reveals network path / hosting)")
    run(sprite, "curl -s ifconfig.me 2>/dev/null && echo || echo 'no external access'",
        "Public IP")
    run(sprite, "curl -s https://ipinfo.io/json 2>/dev/null || echo 'no ipinfo access'",
        "IP info (ASN / provider)")

    # --- Disk perf quick test ---
    run(sprite, "dd if=/dev/zero of=/tmp/bench_write bs=1M count=1000 2>&1 | tail -1; rm -f /tmp/bench_write",
        "Sequential write throughput (1 GB)")
    run(sprite, "sudo dd if=$(mount | grep ' / ' | awk '{print $1}') of=/dev/null bs=4k count=1000 iflag=direct 2>&1 | tail -1",
        "4K direct read (IOPS indicator)")

    print("\n" + "=" * 60)
    print("  Fingerprinting complete.")
    print("=" * 60)


def main():
    token = os.environ.get("SPRITES_TOKEN")
    if not token:
        print("Error: SPRITES_TOKEN environment variable not set")
        sys.exit(1)

    client = SpritesClient(token=token)

    # Create sprite if it doesn't exist
    created = False
    try:
        client.create_sprite(SPRITE_NAME)
        created = True
        print(f"Created sprite: {SPRITE_NAME}")
    except Exception:
        print(f"Using existing sprite: {SPRITE_NAME}")

    sprite = client.sprite(SPRITE_NAME)

    try:
        fingerprint(sprite)
    finally:
        if created:
            try:
                client.delete_sprite(SPRITE_NAME)
                print(f"\nCleaned up sprite: {SPRITE_NAME}")
            except Exception as e:
                print(f"\nFailed to cleanup sprite: {e}")


if __name__ == "__main__":
    main()
