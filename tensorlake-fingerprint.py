"""
Tensorlake Sandbox Fingerprinting Script

Probes the environment inside a Tensorlake sandbox to understand
the underlying platform, isolation method, and resource constraints.

Prerequisites:
    pip install tensorlake
    tl login   (authenticates via browser)

Usage:
    python tensorlake-fingerprint.py
"""

from tensorlake.sandbox import SandboxClient

SEP = "=" * 60

PROBES = [
    # --- OS & Kernel ---
    ("Kernel info", "uname -a"),
    ("Kernel version (proc)", "cat /proc/version"),
    ("OS release", "cat /etc/os-release"),

    # --- Virtualization detection ---
    ("Virtualization type", "systemd-detect-virt 2>/dev/null || echo 'command not available'"),
    ("Hypervisor from cpuinfo", "grep -i hypervisor /proc/cpuinfo | head -1 || echo 'no hypervisor flag'"),
    ("DMI/BIOS vendor (VM indicator)", "cat /sys/class/dmi/id/sys_vendor 2>/dev/null || echo 'not available'"),
    ("DMI product name", "cat /sys/class/dmi/id/product_name 2>/dev/null || echo 'not available'"),
    ("DMI board name", "cat /sys/class/dmi/id/board_name 2>/dev/null || echo 'not available'"),
    ("Docker environment file", "ls -la /.dockerenv 2>/dev/null && echo 'DOCKER DETECTED' || echo 'No .dockerenv'"),

    # --- Firecracker / microVM / container detection ---
    ("Kernel cmdline", "cat /proc/cmdline 2>/dev/null || echo 'not available'"),
    ("Block devices", "lsblk 2>/dev/null || ls /sys/block/ 2>/dev/null || echo 'no block devices visible'"),
    ("Virtio devices", "ls /sys/bus/virtio/devices/ 2>/dev/null || echo 'no virtio bus'"),
    ("PCI devices", "lspci 2>/dev/null || echo 'lspci not available'"),
    ("ACPI tables", "ls /sys/firmware/acpi/tables/ 2>/dev/null || echo 'no ACPI tables'"),
    ("Device tree", "ls /sys/firmware/devicetree/ 2>/dev/null || echo 'no device tree'"),
    ("BIOS vendor", "cat /sys/devices/virtual/dmi/id/bios_vendor 2>/dev/null || echo 'not available'"),

    # --- Kata / gVisor / Firecracker specific ---
    ("gVisor kernel detection", "uname -r | grep -i gvisor && echo 'GVISOR DETECTED' || echo 'not gVisor kernel'"),
    ("Cloud Hypervisor in dmesg", "dmesg 2>/dev/null | grep -i 'Cloud Hypervisor' | head -5 || echo 'no Cloud Hypervisor in dmesg'"),
    ("Kata kernel markers", "cat /proc/version 2>/dev/null | grep -iE 'kata|dragonball' || echo 'no kata markers in kernel version'"),
    ("Virtiofs mounts (Kata indicator)", "mount | grep -i virtiofs || echo 'no virtiofs mounts'"),
    ("Firecracker in dmesg", "dmesg 2>/dev/null | grep -iE 'firecracker|fc_' | head -5 || echo 'no Firecracker in dmesg'"),
    ("Seccomp status", "cat /proc/self/status | grep -i seccomp || echo 'no seccomp info'"),

    # --- CPU & Memory ---
    ("CPU count", "nproc"),
    ("CPU model", "grep 'model name' /proc/cpuinfo | head -1"),
    ("CPU flags (hypervisor flag)", "grep flags /proc/cpuinfo | head -1 | tr ' ' '\\n' | grep -E 'hypervisor|vmx|svm' || echo 'no VM-related flags'"),
    ("Memory", "free -h 2>/dev/null || cat /proc/meminfo | head -5"),
    ("Memory info (detailed)", "head -5 /proc/meminfo"),

    # --- cgroup ---
    ("PID 1 cgroup", "cat /proc/1/cgroup 2>/dev/null | head -20 || echo 'not available'"),
    ("Cgroup memory limit", "cat /sys/fs/cgroup/memory/memory.limit_in_bytes 2>/dev/null || cat /sys/fs/cgroup/memory.max 2>/dev/null || echo 'no cgroup memory limit'"),
    ("Cgroup CPU quota", "cat /sys/fs/cgroup/cpu/cpu.cfs_quota_us 2>/dev/null || cat /sys/fs/cgroup/cpu.max 2>/dev/null || echo 'no cgroup CPU limit'"),

    # --- Filesystem ---
    ("Filesystem types and usage", "df -hT"),
    ("Block device details", "lsblk -f 2>/dev/null || echo 'lsblk not available'"),
    ("Root filesystem mount", "mount | grep ' / '"),
    ("All mounts (summary)", "mount | head -40"),
    ("Proc mounts", "cat /proc/mounts | head -40"),

    # --- Boot / dmesg ---
    ("Boot messages (first 80 lines)", "dmesg 2>/dev/null | head -80 || journalctl -k 2>/dev/null | head -80 || echo 'dmesg not available'"),
    ("Hypervisor in dmesg", "dmesg 2>/dev/null | grep -iE 'hypervisor|kvm|firecracker|qemu|xen|vmware|virtio|cloud-hypervisor|gvisor|kata' | head -20 || echo 'nothing found'"),

    # --- Network ---
    ("Network interfaces", "ip addr 2>/dev/null || ifconfig 2>/dev/null || cat /proc/net/if_inet6 2>/dev/null || echo 'no network tools'"),
    ("DNS config", "cat /etc/resolv.conf"),
    ("Hosts file", "cat /etc/hosts"),
    ("Default route", "ip route show default 2>/dev/null || echo 'no route tools'"),

    # --- Cloud provider / metadata ---
    ("Metadata endpoint (cloud provider detection)", "curl -s --connect-timeout 2 http://169.254.169.254/ 2>/dev/null | head -20 || echo 'no metadata endpoint'"),
    ("GCP metadata", "curl -s --connect-timeout 2 -H 'Metadata-Flavor: Google' http://169.254.169.254/computeMetadata/v1/ 2>/dev/null | head -10 || echo 'not GCP'"),
    ("AWS metadata (IMDSv1)", "curl -s --connect-timeout 2 http://169.254.169.254/latest/meta-data/ 2>/dev/null | head -10 || echo 'not AWS'"),
    ("Azure metadata (IMDS)", "curl -s --connect-timeout 2 -H 'Metadata: true' 'http://169.254.169.254/metadata/instance?api-version=2021-02-01' 2>/dev/null | head -10 || echo 'not Azure'"),

    # --- Processes ---
    ("Running processes", "ps aux 2>/dev/null | head -30"),
    ("Init system", "ls -la /sbin/init 2>/dev/null; file /sbin/init 2>/dev/null || echo 'unknown init'"),
    ("PID 1 command", "cat /proc/1/cmdline 2>/dev/null | tr '\\0' ' ' || echo 'not available'"),
    ("Systemd units (if systemd)", "systemctl list-units --type=service --state=running 2>/dev/null | head -20 || echo 'not systemd'"),

    # --- Disk ---
    ("Disk scheduler", "cat /sys/block/vda/queue/scheduler 2>/dev/null || cat /sys/block/sda/queue/scheduler 2>/dev/null || echo 'unknown'"),
    ("I/O cgroup limits", "cat /sys/fs/cgroup/io.max 2>/dev/null || echo 'no io limits'"),

    # --- Tensorlake specific ---
    ("Tensorlake environment variables", "env | grep -iE 'tensorlake|TENSORLAKE|TL_|SANDBOX' | sort || echo 'no Tensorlake env vars found'"),
    ("Kubernetes environment variables", "env | grep -iE 'KUBERNETES|K8S|KUBE' | sort || echo 'no Kubernetes env vars'"),
    ("Hostname", "hostname"),
    ("All environment variables", "env | sort"),
    ("Machine ID", "cat /etc/machine-id 2>/dev/null || echo 'no machine-id'"),
    ("Current user", "whoami && id"),

    # --- Runtime class detection ---
    ("Runtime class hints in mountinfo", "cat /proc/self/mountinfo 2>/dev/null | grep -iE 'kata|virtiofs|overlay|firecracker' | head -10 || echo 'no runtime hints in mountinfo'"),
    ("Transparent hugepages (differs in microVMs)", "cat /sys/kernel/mm/transparent_hugepage/enabled 2>/dev/null || echo 'not available'"),
    ("Device nodes (reveals virtio/vhost devices)", "ls /dev/ | head -40"),

    # --- Network path / hosting ---
    ("Traceroute (reveals network path)", "traceroute -n -m 10 1.1.1.1 2>/dev/null | head -12 || echo 'traceroute not available'"),
    ("Public IP", "curl -s --connect-timeout 5 ifconfig.me 2>/dev/null && echo || echo 'no external access'"),
    ("IP info (ASN / provider)", "curl -s --connect-timeout 5 https://ipinfo.io/json 2>/dev/null || echo 'no ipinfo access'"),

    # --- Reverse DNS ---
    ("Reverse DNS (hosting provider clue)", 'PUBLIC_IP=$(curl -s --connect-timeout 5 ifconfig.me 2>/dev/null); [ -n "$PUBLIC_IP" ] && (dig +short -x $PUBLIC_IP 2>/dev/null || host $PUBLIC_IP 2>/dev/null || echo "no reverse DNS tools") || echo "no public IP"'),

    # --- Storage perf (tmpfs — /tmp) ---
    ("Sequential write /tmp (1 GB, tmpfs)", "dd if=/dev/zero of=/tmp/bench_write bs=1M count=1000 2>&1 | tail -1; rm -f /tmp/bench_write"),
    ("4K sync write /tmp (tmpfs)", "dd if=/dev/zero of=/tmp/bench_4k bs=4k count=10000 oflag=dsync 2>&1 | tail -1; rm -f /tmp/bench_4k"),

    # --- Storage perf (real disk — /dev/vda ext4) ---
    ("Sequential write / (1 GB, real disk)", "dd if=/dev/zero of=/bench_write bs=1M count=1000 2>&1 | tail -1; rm -f /bench_write"),
    ("4K sync write / (real disk)", "dd if=/dev/zero of=/bench_4k bs=4k count=10000 oflag=dsync 2>&1 | tail -1; rm -f /bench_4k"),
    ("4K random read (real disk)", "dd if=/dev/vda of=/dev/null bs=4k count=10000 iflag=direct 2>&1 | tail -1"),

    # --- Distributed FS detection ---
    ("Distributed/overlay filesystem mounts", "mount | grep -iE 'nfs|fuse|juicefs|gcsfuse|s3fs|ceph|lustre|overlay' || echo 'no distributed/overlay FS mounts'"),
    ("Supported filesystems", "cat /proc/filesystems 2>/dev/null | head -30"),
]


def run_probe(sandbox, label, cmd):
    """Run a single probe command and return formatted output."""
    try:
        result = sandbox.run("bash", ["-c", cmd])
        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        output = stdout or "(no output)"
        if stderr:
            output += f"\n[stderr]: {stderr}"
    except Exception as e:
        output = f"(error: {e})"

    block = f"\n{SEP}\n  {label}\n  $ {cmd}\n{SEP}\n{output}"
    print(block)
    return output


def main():
    print("Creating Tensorlake sandbox...")
    client = SandboxClient()
    sandbox = client.create_and_connect(
        cpus=3.0,
        memory_mb=7000,
        timeout_secs=600,
        allow_internet_access=True,
    )
    sandbox_id = sandbox.sandbox_id
    print(f"Sandbox created: {sandbox_id}")

    try:
        print(f"\n{SEP}")
        print("  Tensorlake Sandbox Fingerprinting")
        print(SEP)

        for label, cmd in PROBES:
            run_probe(sandbox, label, cmd)

        print(f"\n{SEP}")
        print("  Fingerprinting complete.")
        print(SEP)
    finally:
        try:
            client.delete(sandbox_id)
            print("Sandbox deleted.")
        except Exception as e:
            print(f"Cleanup warning: {e}")


if __name__ == "__main__":
    main()
