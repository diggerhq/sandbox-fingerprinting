/**
 * Blaxel Sandbox Fingerprinting Script
 *
 * Probes the environment inside a Blaxel sandbox to understand
 * the underlying platform, isolation method, and resource constraints.
 *
 * Prerequisites:
 *   npm install @blaxel/core
 *   # Auth via one of:
 *   #   bl login            (CLI login — recommended for local dev)
 *   #   export BL_WORKSPACE=your-workspace BL_API_KEY=your-key
 *
 * Usage:
 *   npx tsx blaxel-fingerprint.ts
 */

import { SandboxInstance } from "@blaxel/core";

const SEP = "=".repeat(60);
let cmdIndex = 0;

async function run(
  sandbox: SandboxInstance,
  cmd: string,
  label: string
): Promise<string> {
  const name = `fp-${cmdIndex++}`;
  let output: string;
  try {
    const proc = await sandbox.process.exec({
      name,
      command: cmd,
      waitForCompletion: true,
    });
    // logs from waitForCompletion
    output = proc.logs?.trim() || "(no output)";
  } catch (e: any) {
    // fallback: try fetching logs separately
    try {
      const logs = await sandbox.process.logs(name, "all");
      output = typeof logs === "string" ? logs.trim() : JSON.stringify(logs);
      if (!output) output = `(error: ${e.message || e})`;
    } catch {
      output = `(error: ${e.message || e})`;
    }
  }
  console.log(`\n${SEP}`);
  console.log(`  ${label}`);
  console.log(`  $ ${cmd}`);
  console.log(SEP);
  console.log(output);
  return output;
}

async function fingerprint(sandbox: SandboxInstance) {
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
    "cat /sys/class/dmi/id/board_name 2>/dev/null || echo 'not available'",
    "DMI board name"
  );
  await run(
    sandbox,
    "ls -la /.dockerenv 2>/dev/null && echo 'DOCKER DETECTED' || echo 'No .dockerenv'",
    "Docker environment file"
  );

  // --- Firecracker / microVM / container detection ---
  await run(sandbox, "cat /proc/cmdline", "Kernel cmdline");
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
    "ACPI tables"
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
  await run(sandbox, "mount | head -40", "All mounts (summary)");

  // --- Boot / dmesg ---
  await run(
    sandbox,
    "dmesg 2>/dev/null | head -80 || journalctl -k 2>/dev/null | head -80 || echo 'dmesg not available'",
    "Boot messages (first 80 lines — reveals hypervisor)"
  );
  await run(
    sandbox,
    "dmesg 2>/dev/null | grep -iE 'hypervisor|kvm|firecracker|qemu|xen|vmware|virtio|cloud-hypervisor|gvisor|kata' | head -20 || echo 'nothing found'",
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
  await run(
    sandbox,
    "curl -s --connect-timeout 2 -H 'Metadata: true' 'http://169.254.169.254/metadata/instance?api-version=2021-02-01' 2>/dev/null | head -10 || echo 'not Azure'",
    "Azure metadata (IMDS)"
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

  // --- Blaxel specific ---
  await run(
    sandbox,
    "env | grep -iE 'blaxel|BL_|sandbox' || echo 'no Blaxel env vars found'",
    "Blaxel environment variables"
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

  // --- Reverse DNS on public IP ---
  await run(
    sandbox,
    "PUBLIC_IP=$(curl -s --connect-timeout 5 ifconfig.me 2>/dev/null); [ -n \"$PUBLIC_IP\" ] && dig +short -x $PUBLIC_IP 2>/dev/null || host $PUBLIC_IP 2>/dev/null || echo 'no reverse DNS'",
    "Reverse DNS (hosting provider clue)"
  );

  // --- Storage perf ---
  await run(
    sandbox,
    "dd if=/dev/zero of=/tmp/bench_write bs=1M count=1000 2>&1 | tail -1; rm -f /tmp/bench_write",
    "Sequential write throughput (1 GB)"
  );
  await run(
    sandbox,
    "ROOT_DEV=$(mount | grep ' / ' | awk '{print $1}'); [ -b \"$ROOT_DEV\" ] && sudo dd if=$ROOT_DEV of=/dev/null bs=4k count=1000 iflag=direct 2>&1 | tail -1 || echo 'direct read not available'",
    "4K direct read (IOPS indicator)"
  );

  console.log(`\n${SEP}`);
  console.log("  Fingerprinting complete.");
  console.log(SEP);
}

async function main() {
  console.log("Creating Blaxel sandbox...");
  const sandbox = await SandboxInstance.create({
    name: `fingerprint-${Date.now()}`,
    image: "blaxel/base-image:latest",
    memory: 4096,
  });
  console.log(`Sandbox: ${sandbox.metadata?.name}`);
  console.log(`Status: ${sandbox.status}`);

  try {
    await fingerprint(sandbox);
  } finally {
    try {
      await sandbox.delete();
      console.log("Sandbox cleaned up.");
    } catch (e: any) {
      console.error(`Cleanup warning: ${e.message || e}`);
    }
  }
}

main().catch(console.error);
