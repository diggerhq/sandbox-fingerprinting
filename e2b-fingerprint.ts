/**
 * E2B Sandbox Fingerprinting Script
 *
 * Probes the environment inside an E2B sandbox to understand
 * the underlying platform, isolation method, and resource constraints.
 *
 * Usage:
 *   export E2B_API_KEY=your-key
 *   npx tsx e2b-fingerprint.ts
 */

import { Sandbox } from "e2b";

const SEP = "=".repeat(60);

async function run(
  sandbox: Sandbox,
  cmd: string,
  label: string
): Promise<string> {
  let output: string;
  try {
    const result = await sandbox.commands.run(cmd, { timeout: 30 });
    output = result.stdout?.trim() || "(no output)";
    if (result.stderr?.trim()) {
      output += `\n[stderr]: ${result.stderr.trim()}`;
    }
  } catch (e: any) {
    output = `(error: ${e.message || e})`;
  }
  console.log(`\n${SEP}`);
  console.log(`  ${label}`);
  console.log(`  $ ${cmd}`);
  console.log(SEP);
  console.log(output);
  return output;
}

async function fingerprint(sandbox: Sandbox) {
  // --- OS & Kernel ---
  await run(sandbox, "uname -a", "Kernel info");
  await run(sandbox, "cat /proc/version", "Kernel version (proc)");
  await run(sandbox, "cat /etc/os-release", "OS release");

  // --- Virtualization detection ---
  await run(
    sandbox,
    "systemd-detect-virt 2>/dev/null || echo 'command not available'",
    "Virtualization type"
  );
  await run(
    sandbox,
    "grep -i hypervisor /proc/cpuinfo | head -1 || echo 'no hypervisor flag'",
    "Hypervisor from cpuinfo"
  );
  await run(
    sandbox,
    "cat /sys/class/dmi/id/sys_vendor 2>/dev/null || echo 'not available'",
    "DMI/BIOS vendor (VM indicator)"
  );
  await run(
    sandbox,
    "cat /sys/class/dmi/id/product_name 2>/dev/null || echo 'not available'",
    "DMI product name"
  );
  await run(
    sandbox,
    "ls -la /.dockerenv 2>/dev/null && echo 'DOCKER DETECTED' || echo 'No .dockerenv'",
    "Docker environment file"
  );

  // --- Firecracker / microVM detection ---
  await run(
    sandbox,
    "cat /proc/cmdline",
    "Kernel cmdline (Firecracker passes specific args)"
  );
  await run(
    sandbox,
    "lsblk 2>/dev/null || ls /sys/block/",
    "Block devices (virtio = VM, nvme = bare metal/cloud)"
  );
  await run(
    sandbox,
    "ls /sys/bus/virtio/devices/ 2>/dev/null || echo 'no virtio bus'",
    "Virtio devices"
  );
  await run(
    sandbox,
    "lspci 2>/dev/null || echo 'lspci not available'",
    "PCI devices (empty = microVM like Firecracker)"
  );
  await run(
    sandbox,
    "ls /sys/firmware/acpi/tables/ 2>/dev/null || echo 'no ACPI tables'",
    "ACPI tables (Firecracker has minimal ACPI)"
  );
  await run(
    sandbox,
    "ls /sys/firmware/devicetree/ 2>/dev/null || echo 'no device tree'",
    "Device tree"
  );

  // --- CPU & Memory ---
  await run(sandbox, "nproc", "CPU count");
  await run(
    sandbox,
    "grep 'model name' /proc/cpuinfo | head -1",
    "CPU model"
  );
  await run(
    sandbox,
    "grep flags /proc/cpuinfo | head -1 | tr ' ' '\\n' | grep -E 'hypervisor|vmx|svm' || echo 'no VM-related flags'",
    "CPU flags (look for hypervisor flag)"
  );
  await run(sandbox, "free -h", "Memory");
  await run(sandbox, "head -5 /proc/meminfo", "Memory info (detailed)");

  // --- cgroup ---
  await run(
    sandbox,
    "cat /proc/1/cgroup 2>/dev/null | head -20 || echo 'not available'",
    "PID 1 cgroup"
  );
  await run(
    sandbox,
    "cat /sys/fs/cgroup/memory/memory.limit_in_bytes 2>/dev/null || cat /sys/fs/cgroup/memory.max 2>/dev/null || echo 'no cgroup memory limit'",
    "Cgroup memory limit"
  );
  await run(
    sandbox,
    "cat /sys/fs/cgroup/cpu/cpu.cfs_quota_us 2>/dev/null || cat /sys/fs/cgroup/cpu.max 2>/dev/null || echo 'no cgroup CPU limit'",
    "Cgroup CPU quota"
  );

  // --- Filesystem ---
  await run(sandbox, "df -hT", "Filesystem types and usage");
  await run(
    sandbox,
    "lsblk -f 2>/dev/null || echo 'lsblk not available'",
    "Block device details"
  );
  await run(sandbox, "mount | grep ' / '", "Root filesystem mount");
  await run(sandbox, "mount | head -30", "All mounts (summary)");

  // --- Boot / dmesg ---
  await run(
    sandbox,
    "dmesg 2>/dev/null | head -80 || journalctl -k 2>/dev/null | head -80 || echo 'dmesg not available'",
    "Boot messages (first 80 lines — reveals hypervisor)"
  );
  await run(
    sandbox,
    "dmesg 2>/dev/null | grep -iE 'hypervisor|kvm|firecracker|qemu|xen|vmware|virtio|cloud-hypervisor' | head -20 || echo 'nothing found'",
    "Hypervisor in dmesg"
  );

  // --- Network ---
  await run(
    sandbox,
    "ip addr 2>/dev/null || ifconfig 2>/dev/null || echo 'no network tools'",
    "Network interfaces"
  );
  await run(sandbox, "cat /etc/resolv.conf", "DNS config");
  await run(sandbox, "cat /etc/hosts", "Hosts file");
  await run(
    sandbox,
    "ip route show default 2>/dev/null || echo 'no route tools'",
    "Default route"
  );

  // --- Cloud provider / metadata ---
  await run(
    sandbox,
    "curl -s --connect-timeout 2 http://169.254.169.254/ 2>/dev/null | head -20 || echo 'no metadata endpoint'",
    "Metadata endpoint (cloud provider detection)"
  );
  await run(
    sandbox,
    "curl -s --connect-timeout 2 -H 'Metadata-Flavor: Google' http://169.254.169.254/computeMetadata/v1/ 2>/dev/null | head -10 || echo 'not GCP'",
    "GCP metadata"
  );
  await run(
    sandbox,
    "curl -s --connect-timeout 2 http://169.254.169.254/latest/meta-data/ 2>/dev/null | head -10 || echo 'not AWS'",
    "AWS metadata (IMDSv1)"
  );

  // --- Processes ---
  await run(sandbox, "ps aux 2>/dev/null | head -30", "Running processes");
  await run(
    sandbox,
    "ls -la /sbin/init 2>/dev/null; file /sbin/init 2>/dev/null || echo 'unknown init'",
    "Init system"
  );
  await run(
    sandbox,
    "systemctl list-units --type=service --state=running 2>/dev/null | head -20 || echo 'not systemd'",
    "Systemd units (if systemd)"
  );

  // --- Disk ---
  await run(
    sandbox,
    "cat /sys/block/vda/queue/scheduler 2>/dev/null || cat /sys/block/sda/queue/scheduler 2>/dev/null || echo 'unknown'",
    "Disk scheduler"
  );
  await run(
    sandbox,
    "cat /sys/fs/cgroup/io.max 2>/dev/null || echo 'no io limits'",
    "I/O cgroup limits"
  );

  // --- E2B specific ---
  await run(
    sandbox,
    "env | grep -iE 'e2b|E2B|sandbox' || echo 'no E2B env vars found'",
    "E2B environment variables"
  );
  await run(sandbox, "hostname", "Hostname");
  await run(sandbox, "env | sort", "All environment variables");
  await run(
    sandbox,
    "cat /etc/machine-id 2>/dev/null || echo 'no machine-id'",
    "Machine ID"
  );

  // --- Network path / hosting ---
  await run(
    sandbox,
    "traceroute -n -m 10 1.1.1.1 2>/dev/null | head -12 || echo 'traceroute not available'",
    "Traceroute (reveals network path / hosting)"
  );
  await run(
    sandbox,
    "curl -s --connect-timeout 5 ifconfig.me 2>/dev/null && echo || echo 'no external access'",
    "Public IP"
  );
  await run(
    sandbox,
    "curl -s --connect-timeout 5 https://ipinfo.io/json 2>/dev/null || echo 'no ipinfo access'",
    "IP info (ASN / provider)"
  );

  // --- Storage perf ---
  await run(
    sandbox,
    "dd if=/dev/zero of=/tmp/bench_write bs=1M count=1000 2>&1 | tail -1; rm -f /tmp/bench_write",
    "Sequential write throughput (1 GB)"
  );
  await run(
    sandbox,
    "sudo dd if=/dev/vda of=/dev/null bs=4k count=1000 iflag=direct 2>&1 | tail -1 || echo 'direct read not available'",
    "4K direct read (IOPS indicator)"
  );

  console.log(`\n${SEP}`);
  console.log("  Fingerprinting complete.");
  console.log(SEP);
}

async function main() {
  const sandbox = await Sandbox.create();
  console.log(`Sandbox ID: ${sandbox.sandboxId}`);
  try {
    await fingerprint(sandbox);
  } finally {
    await sandbox.kill();
    console.log("Sandbox cleaned up.");
  }
}

main().catch(console.error);
