"""
Daytona Sandbox Fingerprinting Script

Probes the environment inside a Daytona sandbox to understand
the underlying platform, isolation method, and resource constraints.
"""

from daytona import Daytona


def run(sandbox, cmd: str, label: str) -> str:
    """Execute a command and print the result with a label."""
    try:
        result = sandbox.process.exec(cmd)
        output = result.result.strip() if result.result else "(no output)"
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
    run(sandbox, "ls -la /.dockerenv 2>/dev/null && echo 'DOCKER DETECTED' || echo 'No .dockerenv'",
        "Docker environment file")
    run(sandbox, "cat /proc/1/cgroup 2>/dev/null | head -20",
        "PID 1 cgroup (reveals container runtime)")
    run(sandbox, "cat /proc/1/mountinfo 2>/dev/null | head -20",
        "PID 1 mount info")

    # --- CPU & Memory ---
    run(sandbox, "nproc", "CPU count")
    run(sandbox, "cat /proc/cpuinfo | grep 'model name' | head -1",
        "CPU model (VM vs bare metal)")
    run(sandbox, "free -h", "Memory")
    run(sandbox, "cat /sys/fs/cgroup/memory/memory.limit_in_bytes 2>/dev/null || "
        "cat /sys/fs/cgroup/memory.max 2>/dev/null || echo 'cgroup info unavailable'",
        "Cgroup memory limit")
    run(sandbox, "cat /sys/fs/cgroup/cpu/cpu.cfs_quota_us 2>/dev/null || "
        "cat /sys/fs/cgroup/cpu.max 2>/dev/null || echo 'cgroup info unavailable'",
        "Cgroup CPU quota")

    # --- Filesystem ---
    run(sandbox, "df -hT", "Filesystem types and usage")
    run(sandbox, "mount | grep overlay", "Overlay mounts (Docker indicator)")
    run(sandbox, "ls /", "Root filesystem layout")

    # --- Network ---
    run(sandbox, "ip addr 2>/dev/null || ifconfig 2>/dev/null || echo 'no network tools'",
        "Network interfaces")
    run(sandbox, "cat /etc/resolv.conf", "DNS config (reveals orchestrator)")
    run(sandbox, "cat /etc/hosts", "Hosts file")

    # --- Boot / dmesg ---
    run(sandbox, "dmesg 2>/dev/null | head -50 || echo 'dmesg not available (container)'",
        "Boot messages (VMs show boot sequence, containers usually denied)")

    # --- Process namespace ---
    run(sandbox, "ps aux 2>/dev/null | head -20 || ls /proc/*/cmdline 2>/dev/null | wc -l",
        "Running processes")

    # --- Daytona-specific ---
    run(sandbox, "env | grep -i daytona || echo 'no DAYTONA env vars found'",
        "Daytona environment variables")
    run(sandbox, "env | sort", "All environment variables")

    print("\n" + "=" * 60)
    print("  Fingerprinting complete.")
    print("=" * 60)


def main():
    daytona = Daytona()
    sandbox = daytona.create()
    try:
        fingerprint(sandbox)
    finally:
        daytona.delete(sandbox)


if __name__ == "__main__":
    main()
