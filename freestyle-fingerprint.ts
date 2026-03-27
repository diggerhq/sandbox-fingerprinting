/**
 * Freestyle.sh VM Fingerprinting Script
 *
 * Probes the environment inside a Freestyle VM to understand
 * the underlying platform, isolation method, and resource constraints.
 *
 * Prerequisites:
 *   npm install freestyle-sandboxes
 *   export FREESTYLE_API_KEY=your-key  (from https://dash.freestyle.sh)
 *
 * Usage:
 *   npx tsx freestyle-fingerprint.ts
 */

import { freestyle } from "freestyle-sandboxes";

const SEP = "=".repeat(60);

async function run(
  vm: any,
  cmd: string,
  label: string
): Promise<string> {
  let output: string;
  try {
    const result = await vm.exec(cmd);
    const stdout = result.stdout?.trim?.() ?? "";
    const stderr = result.stderr?.trim?.() ?? "";
    output = stdout || "(no output)";
    if (stderr) output += `\n[stderr]: ${stderr}`;
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

async function fingerprint(vm: any) {
  // --- OS & Kernel ---
  await run(vm, "uname -a", "Kernel info");
  await run(vm, "cat /proc/version", "Kernel version (proc)");
  await run(vm, "cat /etc/os-release", "OS release");

  // --- Virtualization detection ---
  await run(
    vm,
    "systemd-detect-virt 2>/dev/null || echo 'command not available'",
    "Virtualization type"
  );
  await run(
    vm,
    "grep -i hypervisor /proc/cpuinfo | head -1 || echo 'no hypervisor flag'",
    "Hypervisor from cpuinfo"
  );
  await run(
    vm,
    "cat /sys/class/dmi/id/sys_vendor 2>/dev/null || echo 'not available'",
    "DMI/BIOS vendor (VM indicator)"
  );
  await run(
    vm,
    "cat /sys/class/dmi/id/product_name 2>/dev/null || echo 'not available'",
    "DMI product name"
  );
  await run(
    vm,
    "cat /sys/class/dmi/id/board_name 2>/dev/null || echo 'not available'",
    "DMI board name"
  );
  await run(
    vm,
    "ls -la /.dockerenv 2>/dev/null && echo 'DOCKER DETECTED' || echo 'No .dockerenv'",
    "Docker environment file"
  );

  // --- Firecracker / microVM / container detection ---
  await run(vm, "cat /proc/cmdline", "Kernel cmdline");
  await run(
    vm,
    "lsblk 2>/dev/null || ls /sys/block/",
    "Block devices (virtio = VM, nvme = bare metal/cloud)"
  );
  await run(
    vm,
    "ls /sys/bus/virtio/devices/ 2>/dev/null || echo 'no virtio bus'",
    "Virtio devices"
  );
  await run(
    vm,
    "lspci 2>/dev/null || echo 'lspci not available'",
    "PCI devices (empty = microVM like Firecracker)"
  );
  await run(
    vm,
    "ls /sys/firmware/acpi/tables/ 2>/dev/null || echo 'no ACPI tables'",
    "ACPI tables"
  );
  await run(
    vm,
    "ls /sys/firmware/devicetree/ 2>/dev/null || echo 'no device tree'",
    "Device tree"
  );

  // --- CPU & Memory ---
  await run(vm, "nproc", "CPU count");
  await run(
    vm,
    "grep 'model name' /proc/cpuinfo | head -1",
    "CPU model"
  );
  await run(
    vm,
    "grep flags /proc/cpuinfo | head -1 | tr ' ' '\\n' | grep -E 'hypervisor|vmx|svm' || echo 'no VM-related flags'",
    "CPU flags (look for hypervisor flag)"
  );
  await run(vm, "free -h", "Memory");
  await run(vm, "head -5 /proc/meminfo", "Memory info (detailed)");

  // --- cgroup ---
  await run(
    vm,
    "cat /proc/1/cgroup 2>/dev/null | head -20 || echo 'not available'",
    "PID 1 cgroup"
  );
  await run(
    vm,
    "cat /sys/fs/cgroup/memory/memory.limit_in_bytes 2>/dev/null || cat /sys/fs/cgroup/memory.max 2>/dev/null || echo 'no cgroup memory limit'",
    "Cgroup memory limit"
  );
  await run(
    vm,
    "cat /sys/fs/cgroup/cpu/cpu.cfs_quota_us 2>/dev/null || cat /sys/fs/cgroup/cpu.max 2>/dev/null || echo 'no cgroup CPU limit'",
    "Cgroup CPU quota"
  );

  // --- Filesystem ---
  await run(vm, "df -hT", "Filesystem types and usage");
  await run(
    vm,
    "lsblk -f 2>/dev/null || echo 'lsblk not available'",
    "Block device details"
  );
  await run(vm, "mount | grep ' / '", "Root filesystem mount");
  await run(vm, "mount | head -40", "All mounts (summary)");

  // --- Boot / dmesg ---
  await run(
    vm,
    "dmesg 2>/dev/null | head -80 || journalctl -k 2>/dev/null | head -80 || echo 'dmesg not available'",
    "Boot messages (first 80 lines — reveals hypervisor)"
  );
  await run(
    vm,
    "dmesg 2>/dev/null | grep -iE 'hypervisor|kvm|firecracker|qemu|xen|vmware|virtio|cloud-hypervisor|gvisor|kata' | head -20 || echo 'nothing found'",
    "Hypervisor in dmesg"
  );

  // --- Network ---
  await run(
    vm,
    "ip addr 2>/dev/null || ifconfig 2>/dev/null || echo 'no network tools'",
    "Network interfaces"
  );
  await run(vm, "cat /etc/resolv.conf", "DNS config");
  await run(vm, "cat /etc/hosts", "Hosts file");
  await run(
    vm,
    "ip route show default 2>/dev/null || echo 'no route tools'",
    "Default route"
  );

  // --- Cloud provider / metadata ---
  await run(
    vm,
    "curl -s --connect-timeout 2 http://169.254.169.254/ 2>/dev/null | head -20 || echo 'no metadata endpoint'",
    "Metadata endpoint (cloud provider detection)"
  );
  await run(
    vm,
    "curl -s --connect-timeout 2 -H 'Metadata-Flavor: Google' http://169.254.169.254/computeMetadata/v1/ 2>/dev/null | head -10 || echo 'not GCP'",
    "GCP metadata"
  );
  await run(
    vm,
    "curl -s --connect-timeout 2 http://169.254.169.254/latest/meta-data/ 2>/dev/null | head -10 || echo 'not AWS'",
    "AWS metadata (IMDSv1)"
  );
  await run(
    vm,
    "curl -s --connect-timeout 2 -H 'Metadata: true' 'http://169.254.169.254/metadata/instance?api-version=2021-02-01' 2>/dev/null | head -10 || echo 'not Azure'",
    "Azure metadata (IMDS)"
  );

  // --- Processes ---
  await run(vm, "ps aux 2>/dev/null | head -30", "Running processes");
  await run(
    vm,
    "ls -la /sbin/init 2>/dev/null; file /sbin/init 2>/dev/null || echo 'unknown init'",
    "Init system"
  );
  await run(
    vm,
    "systemctl list-units --type=service --state=running 2>/dev/null | head -20 || echo 'not systemd'",
    "Systemd units (if systemd)"
  );
  await run(
    vm,
    "cat /proc/1/cmdline 2>/dev/null | tr '\\0' ' ' || echo 'not available'",
    "PID 1 command"
  );

  // --- Disk ---
  await run(
    vm,
    "cat /sys/block/vda/queue/scheduler 2>/dev/null || cat /sys/block/sda/queue/scheduler 2>/dev/null || echo 'unknown'",
    "Disk scheduler"
  );
  await run(
    vm,
    "cat /sys/fs/cgroup/io.max 2>/dev/null || echo 'no io limits'",
    "I/O cgroup limits"
  );

  // --- Freestyle specific ---
  await run(
    vm,
    "env | grep -iE 'freestyle|FREESTYLE|sandbox' || echo 'no Freestyle env vars found'",
    "Freestyle environment variables"
  );
  await run(vm, "hostname", "Hostname");
  await run(vm, "env | sort", "All environment variables");
  await run(
    vm,
    "cat /etc/machine-id 2>/dev/null || echo 'no machine-id'",
    "Machine ID"
  );
  await run(vm, "whoami && id", "Current user");

  // --- Network path / hosting ---
  await run(
    vm,
    "traceroute -n -m 10 1.1.1.1 2>/dev/null | head -12 || echo 'traceroute not available'",
    "Traceroute (reveals network path / hosting)"
  );
  await run(
    vm,
    "curl -s --connect-timeout 5 ifconfig.me 2>/dev/null && echo || echo 'no external access'",
    "Public IP"
  );
  await run(
    vm,
    "curl -s --connect-timeout 5 https://ipinfo.io/json 2>/dev/null || echo 'no ipinfo access'",
    "IP info (ASN / provider)"
  );

  // --- Reverse DNS on public IP ---
  await run(
    vm,
    "PUBLIC_IP=$(curl -s --connect-timeout 5 ifconfig.me 2>/dev/null); [ -n \"$PUBLIC_IP\" ] && dig +short -x $PUBLIC_IP 2>/dev/null || host $PUBLIC_IP 2>/dev/null || echo 'no reverse DNS'",
    "Reverse DNS (hosting provider clue)"
  );

  // --- Storage perf ---
  await run(
    vm,
    "dd if=/dev/zero of=/tmp/bench_write bs=1M count=1000 2>&1 | tail -1; rm -f /tmp/bench_write",
    "Sequential write throughput (1 GB)"
  );
  await run(
    vm,
    "ROOT_DEV=$(mount | grep ' / ' | awk '{print $1}'); [ -b \"$ROOT_DEV\" ] && sudo dd if=$ROOT_DEV of=/dev/null bs=4k count=1000 iflag=direct 2>&1 | tail -1 || echo 'direct read not available'",
    "4K direct read (IOPS indicator)"
  );

  // --- Distributed FS detection ---
  await run(
    vm,
    "mount | grep -iE 'nfs|fuse|juicefs|gcsfuse|s3fs|ceph|lustre' || echo 'no distributed FS mounts'",
    "Distributed filesystem mounts"
  );
  await run(
    vm,
    "cat /proc/filesystems 2>/dev/null | head -30",
    "Supported filesystems"
  );

  console.log(`\n${SEP}`);
  console.log("  Fingerprinting complete.");
  console.log(SEP);
}

async function main() {
  console.log("Creating Freestyle VM...");
  const { vm, vmId } = await freestyle.vms.create();
  console.log(`VM created: ${vmId}`);

  try {
    await fingerprint(vm);
  } finally {
    try {
      await vm.stop();
      console.log("VM stopped.");
    } catch (e: any) {
      console.error(`Cleanup warning: ${e.message || e}`);
    }
  }
}

main().catch(console.error);
