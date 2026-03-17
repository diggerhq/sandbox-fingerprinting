#!/usr/bin/env bash
#
# exe.dev Sandbox Fingerprinting Script
#
# Probes the environment inside an exe.dev VM to understand
# the underlying platform, isolation method, and resource constraints.
#
# Usage: ssh into your exe.dev VM, then run:
#   bash exe-fingerprint.sh
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
echo "  exe.dev Fingerprinting — $(date -u)"
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

# --- cgroup (if containerized) ---
run "PID 1 cgroup" "cat /proc/1/cgroup 2>/dev/null | head -20 || echo 'not available'"
run "Cgroup memory limit" \
    "cat /sys/fs/cgroup/memory/memory.limit_in_bytes 2>/dev/null || cat /sys/fs/cgroup/memory.max 2>/dev/null || echo 'no cgroup memory limit (likely a real VM)'"
run "Cgroup CPU quota" \
    "cat /sys/fs/cgroup/cpu/cpu.cfs_quota_us 2>/dev/null || cat /sys/fs/cgroup/cpu.max 2>/dev/null || echo 'no cgroup CPU limit (likely a real VM)'"

# --- Filesystem ---
run "Filesystem types and usage" "df -hT"
run "Block device details" "lsblk -f 2>/dev/null || echo 'lsblk not available'"
run "Root filesystem mount" "mount | grep ' / '"
run "All mounts (summary)" "mount | head -30"

# --- Boot / dmesg ---
run "Boot messages (first 80 lines — reveals hypervisor)" "dmesg 2>/dev/null | head -80 || journalctl -k 2>/dev/null | head -80 || echo 'dmesg not available'"
run "Hypervisor in dmesg" "dmesg 2>/dev/null | grep -iE 'hypervisor|kvm|firecracker|qemu|xen|vmware|virtio|cloud-hypervisor' | head -20 || echo 'nothing found'"

# --- Network ---
run "Network interfaces" "ip addr 2>/dev/null || ifconfig 2>/dev/null || echo 'no network tools'"
run "DNS config" "cat /etc/resolv.conf"
run "Hosts file" "cat /etc/hosts"
run "Default route" "ip route show default 2>/dev/null || route -n 2>/dev/null | head -5 || echo 'no route tools'"
run "Metadata endpoint (cloud provider detection)" \
    "curl -s --connect-timeout 2 http://169.254.169.254/ 2>/dev/null | head -20 || echo 'no metadata endpoint (not major cloud)'"
run "GCP metadata" \
    "curl -s --connect-timeout 2 -H 'Metadata-Flavor: Google' http://169.254.169.254/computeMetadata/v1/ 2>/dev/null | head -10 || echo 'not GCP'"
run "AWS metadata (IMDSv1)" \
    "curl -s --connect-timeout 2 http://169.254.169.254/latest/meta-data/ 2>/dev/null | head -10 || echo 'not AWS'"
run "Hetzner metadata" \
    "curl -s --connect-timeout 2 http://169.254.169.254/hetzner/v1/metadata 2>/dev/null | head -20 || echo 'not Hetzner'"

# --- Process namespace ---
run "Running processes" "ps aux 2>/dev/null | head -30"
run "Init system" "ls -la /sbin/init 2>/dev/null; file /sbin/init 2>/dev/null || echo 'unknown init'"
run "Systemd units (if systemd)" "systemctl list-units --type=service --state=running 2>/dev/null | head -20 || echo 'not systemd'"

# --- Disk performance hint ---
run "Disk scheduler (none = virtio-blk typical)" "cat /sys/block/vda/queue/scheduler 2>/dev/null || cat /sys/block/sda/queue/scheduler 2>/dev/null || echo 'unknown'"

# --- exe.dev specific ---
run "exe.dev environment variables" "env | grep -iE 'exe|EXE' || echo 'no exe.dev env vars found'"
run "Hostname" "hostname"
run "All environment variables" "env | sort"
run "SSH authorized keys" "cat ~/.ssh/authorized_keys 2>/dev/null | head -5 || echo 'no authorized_keys'"
run "Cloud-init data" "cat /run/cloud-init/instance-data.json 2>/dev/null | head -30 || ls /var/lib/cloud/ 2>/dev/null || echo 'no cloud-init'"
run "User data / startup script" "cat /var/lib/cloud/instance/user-data.txt 2>/dev/null | head -30 || echo 'no user-data'"

echo ""
echo "$SEP"
echo "  Fingerprinting complete."
echo "$SEP"
