#!/usr/bin/env bash
#
# Sprites.dev (Fly.io) Sandbox Fingerprinting Script
#
# Probes the environment inside a Sprites sandbox to understand
# the underlying platform, isolation method, and resource constraints.
#
# Usage: run inside your Sprites VM:
#   bash sprites-fingerprint.sh
#

set -euo pipefail

SEP="============================================================"

run() {
    local label="$1"
    local cmd="$2"
    echo ""
    echo "$SEP"
    echo "  $label"
    echo "  \$ $cmd"
    echo "$SEP"
    eval "$cmd" 2>&1 || echo "(command failed or no output)"
}

echo "$SEP"
echo "  Sprites.dev Fingerprinting — $(date -u)"
echo "$SEP"

# --- OS & Kernel ---
run "Kernel info" "uname -a"
run "Kernel version (proc)" "cat /proc/version"
run "OS release" "cat /etc/os-release"

# --- Virtualization detection ---
run "Virtualization type (systemd)" "systemd-detect-virt 2>/dev/null || echo 'command not available'"
run "Hypervisor from cpuinfo" "grep -i hypervisor /proc/cpuinfo | head -1 || echo 'no hypervisor flag'"
run "DMI/BIOS vendor (VM indicator)" "cat /sys/class/dmi/id/sys_vendor 2>/dev/null || echo 'not available'"
run "DMI product name" "cat /sys/class/dmi/id/product_name 2>/dev/null || echo 'not available'"
run "DMI board name" "cat /sys/class/dmi/id/board_name 2>/dev/null || echo 'not available'"
run "Docker environment file" "ls -la /.dockerenv 2>/dev/null && echo 'DOCKER DETECTED' || echo 'No .dockerenv'"

# --- Firecracker / microVM detection ---
run "Kernel cmdline (Firecracker passes specific args)" "cat /proc/cmdline"
run "Block devices (virtio = VM, nvme = bare metal/cloud)" "lsblk 2>/dev/null || ls /sys/block/"
run "Virtio devices" "ls /sys/bus/virtio/devices/ 2>/dev/null || echo 'no virtio bus'"
run "PCI devices (empty = microVM like Firecracker)" "lspci 2>/dev/null || echo 'lspci not available'"
run "ACPI tables (Firecracker has minimal ACPI)" "ls /sys/firmware/acpi/tables/ 2>/dev/null || echo 'no ACPI tables'"
run "Device tree (some microVMs use device tree instead of ACPI)" "ls /sys/firmware/devicetree/ 2>/dev/null || echo 'no device tree'"

# --- CPU & Memory ---
run "CPU count" "nproc"
run "CPU model" "grep 'model name' /proc/cpuinfo | head -1"
run "CPU flags (look for hypervisor flag)" "grep flags /proc/cpuinfo | head -1 | tr ' ' '\n' | grep -E 'hypervisor|vmx|svm' || echo 'no VM-related flags'"
run "Memory" "free -h"
run "Memory info (detailed)" "head -5 /proc/meminfo"

# --- cgroup (if containerized inside the VM) ---
run "PID 1 cgroup" "cat /proc/1/cgroup 2>/dev/null | head -20 || echo 'not available'"
run "Cgroup memory limit" \
    "cat /sys/fs/cgroup/memory/memory.limit_in_bytes 2>/dev/null || cat /sys/fs/cgroup/memory.max 2>/dev/null || echo 'no cgroup memory limit'"
run "Cgroup CPU quota" \
    "cat /sys/fs/cgroup/cpu/cpu.cfs_quota_us 2>/dev/null || cat /sys/fs/cgroup/cpu.max 2>/dev/null || echo 'no cgroup CPU limit'"

# --- Filesystem ---
run "Filesystem types and usage" "df -hT"
run "Block device details" "lsblk -f 2>/dev/null || echo 'lsblk not available'"
run "Root filesystem mount" "mount | grep ' / '"
run "All mounts (summary)" "mount | head -30"

# --- Boot / dmesg ---
run "Boot messages (first 80 lines — reveals hypervisor)" \
    "dmesg 2>/dev/null | head -80 || journalctl -k 2>/dev/null | head -80 || echo 'dmesg not available'"
run "Hypervisor in dmesg" \
    "dmesg 2>/dev/null | grep -iE 'hypervisor|kvm|firecracker|qemu|xen|vmware|virtio|cloud-hypervisor' | head -20 || echo 'nothing found'"

# --- Network ---
run "Network interfaces" "ip addr 2>/dev/null || ifconfig 2>/dev/null || echo 'no network tools'"
run "DNS config" "cat /etc/resolv.conf"
run "Hosts file" "cat /etc/hosts"
run "Default route" "ip route show default 2>/dev/null || route -n 2>/dev/null | head -5 || echo 'no route tools'"

# --- Cloud provider / metadata ---
run "Metadata endpoint (cloud provider detection)" \
    "curl -s --connect-timeout 2 http://169.254.169.254/ 2>/dev/null | head -20 || echo 'no metadata endpoint'"
run "Fly.io internal metadata" \
    "curl -s --connect-timeout 2 http://169.254.169.254/metadata/v1 2>/dev/null | head -20 || echo 'no Fly metadata'"
run "GCP metadata" \
    "curl -s --connect-timeout 2 -H 'Metadata-Flavor: Google' http://169.254.169.254/computeMetadata/v1/ 2>/dev/null | head -10 || echo 'not GCP'"
run "AWS metadata (IMDSv1)" \
    "curl -s --connect-timeout 2 http://169.254.169.254/latest/meta-data/ 2>/dev/null | head -10 || echo 'not AWS'"

# --- Fly.io specific ---
run "Fly.io app metadata" \
    "curl -s --connect-timeout 2 http://_api.internal:4280/ 2>/dev/null | head -20 || echo 'no Fly internal API'"
run "Fly.io DNS (internal)" \
    "dig +short _apps.internal 2>/dev/null || nslookup _apps.internal 2>/dev/null || echo 'no Fly internal DNS'"

# --- Processes ---
run "Running processes" "ps aux 2>/dev/null | head -30"
run "Init system" "ls -la /sbin/init 2>/dev/null; file /sbin/init 2>/dev/null || echo 'unknown init'"
run "Systemd units (if systemd)" \
    "systemctl list-units --type=service --state=running 2>/dev/null | head -20 || echo 'not systemd'"

# --- Disk ---
run "Disk scheduler (none = virtio-blk typical)" \
    "cat /sys/block/vda/queue/scheduler 2>/dev/null || cat /sys/block/sda/queue/scheduler 2>/dev/null || echo 'unknown'"
run "I/O cgroup limits" "cat /sys/fs/cgroup/io.max 2>/dev/null || echo 'no io limits'"

# --- Fly.io / Sprites env ---
run "Fly.io / Sprites environment variables" \
    "env | grep -iE 'fly|sprite|FLY|SPRITE' || echo 'no Fly/Sprites env vars found'"
run "Hostname" "hostname"
run "All environment variables" "env | sort"
run "Machine ID" "cat /etc/machine-id 2>/dev/null || echo 'no machine-id'"

# --- Network path / hosting ---
run "Traceroute (reveals network path / hosting)" \
    "traceroute -n -m 10 1.1.1.1 2>/dev/null | head -12 || echo 'traceroute not available'"
run "Public IP" "curl -s --connect-timeout 5 ifconfig.me 2>/dev/null && echo || echo 'no external access'"
run "IP info (ASN / provider)" \
    "curl -s --connect-timeout 5 https://ipinfo.io/json 2>/dev/null || echo 'no ipinfo access'"

# --- Storage perf ---
run "Sequential write throughput (1 GB)" \
    "dd if=/dev/zero of=/tmp/bench_write bs=1M count=1000 2>&1 | tail -1; rm -f /tmp/bench_write"
run "4K direct read (IOPS indicator)" \
    "sudo dd if=\$(mount | grep ' / ' | awk '{print \$1}') of=/dev/null bs=4k count=1000 iflag=direct 2>&1 | tail -1 || echo 'direct read not available'"

echo ""
echo "$SEP"
echo "  Fingerprinting complete."
echo "$SEP"
