/**
 * Cloudflare Sandbox Fingerprinting Script
 *
 * Deploys a Cloudflare Worker that creates a sandbox and probes the
 * environment to understand the underlying platform, isolation method,
 * and resource constraints.
 *
 * The Cloudflare Sandbox SDK requires a Worker + Durable Objects runtime.
 * This file is the Worker source — deploy it with wrangler.
 *
 * Prerequisites:
 *   1. Create project:
 *      npm create cloudflare@latest -- cf-fingerprint --template=cloudflare/sandbox-sdk/examples/minimal
 *   2. Replace src/index.ts with this file
 *   3. npm install
 *   4. npm run dev   (local, requires Docker)
 *      — OR —
 *      npx wrangler deploy   (deploy to Cloudflare)
 *   5. curl http://localhost:8787/fingerprint   (or deployed URL)
 *
 * wrangler.jsonc should have container + Durable Object bindings (the
 * template sets this up automatically).
 */

import { Sandbox, getSandbox } from "@cloudflare/sandbox";

export { Sandbox };

interface Env {
  Sandbox: DurableObjectNamespace<Sandbox>;
}

const SEP = "=".repeat(60);

const PROBES: Array<{ cmd: string; label: string }> = [
  // --- OS & Kernel ---
  { cmd: "uname -a", label: "Kernel info" },
  { cmd: "cat /proc/version", label: "Kernel version (proc)" },
  { cmd: "cat /etc/os-release", label: "OS release" },

  // --- Virtualization detection ---
  {
    cmd: "systemd-detect-virt 2>/dev/null || echo 'command not available'",
    label: "Virtualization type",
  },
  {
    cmd: "grep -i hypervisor /proc/cpuinfo | head -1 || echo 'no hypervisor flag'",
    label: "Hypervisor from cpuinfo",
  },
  {
    cmd: "cat /sys/class/dmi/id/sys_vendor 2>/dev/null || echo 'not available'",
    label: "DMI/BIOS vendor (VM indicator)",
  },
  {
    cmd: "cat /sys/class/dmi/id/product_name 2>/dev/null || echo 'not available'",
    label: "DMI product name",
  },
  {
    cmd: "cat /sys/class/dmi/id/board_name 2>/dev/null || echo 'not available'",
    label: "DMI board name",
  },
  {
    cmd: "ls -la /.dockerenv 2>/dev/null && echo 'DOCKER DETECTED' || echo 'No .dockerenv'",
    label: "Docker environment file",
  },

  // --- Firecracker / microVM / container detection ---
  { cmd: "cat /proc/cmdline 2>/dev/null || echo 'not available'", label: "Kernel cmdline" },
  {
    cmd: "lsblk 2>/dev/null || ls /sys/block/ 2>/dev/null || echo 'no block devices visible'",
    label: "Block devices",
  },
  {
    cmd: "ls /sys/bus/virtio/devices/ 2>/dev/null || echo 'no virtio bus'",
    label: "Virtio devices",
  },
  {
    cmd: "lspci 2>/dev/null || echo 'lspci not available'",
    label: "PCI devices",
  },
  {
    cmd: "ls /sys/firmware/acpi/tables/ 2>/dev/null || echo 'no ACPI tables'",
    label: "ACPI tables",
  },
  {
    cmd: "ls /sys/firmware/devicetree/ 2>/dev/null || echo 'no device tree'",
    label: "Device tree",
  },
  {
    cmd: "cat /sys/devices/virtual/dmi/id/bios_vendor 2>/dev/null || echo 'not available'",
    label: "BIOS vendor",
  },

  // --- CPU & Memory ---
  { cmd: "nproc", label: "CPU count" },
  { cmd: "grep 'model name' /proc/cpuinfo | head -1", label: "CPU model" },
  {
    cmd: "grep flags /proc/cpuinfo | head -1 | tr ' ' '\\n' | grep -E 'hypervisor|vmx|svm' || echo 'no VM-related flags'",
    label: "CPU flags (hypervisor flag)",
  },
  { cmd: "free -h", label: "Memory" },
  { cmd: "head -5 /proc/meminfo", label: "Memory info (detailed)" },

  // --- cgroup ---
  {
    cmd: "cat /proc/1/cgroup 2>/dev/null | head -20 || echo 'not available'",
    label: "PID 1 cgroup",
  },
  {
    cmd: "cat /sys/fs/cgroup/memory/memory.limit_in_bytes 2>/dev/null || cat /sys/fs/cgroup/memory.max 2>/dev/null || echo 'no cgroup memory limit'",
    label: "Cgroup memory limit",
  },
  {
    cmd: "cat /sys/fs/cgroup/cpu/cpu.cfs_quota_us 2>/dev/null || cat /sys/fs/cgroup/cpu.max 2>/dev/null || echo 'no cgroup CPU limit'",
    label: "Cgroup CPU quota",
  },

  // --- Filesystem ---
  { cmd: "df -hT", label: "Filesystem types and usage" },
  {
    cmd: "lsblk -f 2>/dev/null || echo 'lsblk not available'",
    label: "Block device details",
  },
  { cmd: "mount | grep ' / '", label: "Root filesystem mount" },
  { cmd: "mount | head -40", label: "All mounts (summary)" },
  { cmd: "cat /proc/mounts | head -40", label: "Proc mounts" },

  // --- Boot / dmesg ---
  {
    cmd: "dmesg 2>/dev/null | head -80 || journalctl -k 2>/dev/null | head -80 || echo 'dmesg not available'",
    label: "Boot messages (first 80 lines — reveals hypervisor)",
  },
  {
    cmd: "dmesg 2>/dev/null | grep -iE 'hypervisor|kvm|firecracker|qemu|xen|vmware|virtio|cloud-hypervisor|gvisor|kata' | head -20 || echo 'nothing found'",
    label: "Hypervisor in dmesg",
  },

  // --- Network ---
  {
    cmd: "ip addr 2>/dev/null || ifconfig 2>/dev/null || cat /proc/net/if_inet6 2>/dev/null || echo 'no network tools'",
    label: "Network interfaces",
  },
  { cmd: "cat /etc/resolv.conf", label: "DNS config" },
  { cmd: "cat /etc/hosts", label: "Hosts file" },
  {
    cmd: "ip route show default 2>/dev/null || echo 'no route tools'",
    label: "Default route",
  },

  // --- Cloud provider / metadata ---
  {
    cmd: "curl -s --connect-timeout 2 http://169.254.169.254/ 2>/dev/null | head -20 || echo 'no metadata endpoint'",
    label: "Metadata endpoint (cloud provider detection)",
  },
  {
    cmd: "curl -s --connect-timeout 2 -H 'Metadata-Flavor: Google' http://169.254.169.254/computeMetadata/v1/ 2>/dev/null | head -10 || echo 'not GCP'",
    label: "GCP metadata",
  },
  {
    cmd: "curl -s --connect-timeout 2 http://169.254.169.254/latest/meta-data/ 2>/dev/null | head -10 || echo 'not AWS'",
    label: "AWS metadata (IMDSv1)",
  },
  {
    cmd: "curl -s --connect-timeout 2 -H 'Metadata: true' 'http://169.254.169.254/metadata/instance?api-version=2021-02-01' 2>/dev/null | head -10 || echo 'not Azure'",
    label: "Azure metadata (IMDS)",
  },

  // --- Processes ---
  { cmd: "ps aux 2>/dev/null | head -30", label: "Running processes" },
  {
    cmd: "ls -la /sbin/init 2>/dev/null; file /sbin/init 2>/dev/null || echo 'unknown init'",
    label: "Init system",
  },
  {
    cmd: "cat /proc/1/cmdline 2>/dev/null | tr '\\0' ' ' || echo 'not available'",
    label: "PID 1 command",
  },
  {
    cmd: "systemctl list-units --type=service --state=running 2>/dev/null | head -20 || echo 'not systemd'",
    label: "Systemd units (if systemd)",
  },

  // --- Disk ---
  {
    cmd: "cat /sys/block/vda/queue/scheduler 2>/dev/null || cat /sys/block/sda/queue/scheduler 2>/dev/null || echo 'unknown'",
    label: "Disk scheduler",
  },
  {
    cmd: "cat /sys/fs/cgroup/io.max 2>/dev/null || echo 'no io limits'",
    label: "I/O cgroup limits",
  },

  // --- Cloudflare specific ---
  {
    cmd: "env | grep -iE 'cloudflare|CF_|WRANGLER|sandbox' || echo 'no Cloudflare env vars found'",
    label: "Cloudflare environment variables",
  },
  { cmd: "hostname", label: "Hostname" },
  { cmd: "env | sort", label: "All environment variables" },
  {
    cmd: "cat /etc/machine-id 2>/dev/null || echo 'no machine-id'",
    label: "Machine ID",
  },
  { cmd: "whoami && id", label: "Current user" },

  // --- Network path / hosting ---
  {
    cmd: "traceroute -n -m 10 1.1.1.1 2>/dev/null | head -12 || echo 'traceroute not available'",
    label: "Traceroute (reveals network path / hosting)",
  },
  {
    cmd: "curl -s --connect-timeout 5 ifconfig.me 2>/dev/null && echo || echo 'no external access'",
    label: "Public IP",
  },
  {
    cmd: "curl -s --connect-timeout 5 https://ipinfo.io/json 2>/dev/null || echo 'no ipinfo access'",
    label: "IP info (ASN / provider)",
  },

  // --- Reverse DNS ---
  {
    cmd: 'PUBLIC_IP=$(curl -s --connect-timeout 5 ifconfig.me 2>/dev/null); [ -n "$PUBLIC_IP" ] && dig +short -x $PUBLIC_IP 2>/dev/null || host $PUBLIC_IP 2>/dev/null || echo "no reverse DNS"',
    label: "Reverse DNS (hosting provider clue)",
  },

  // --- Storage perf ---
  {
    cmd: "dd if=/dev/zero of=/tmp/bench_write bs=1M count=1000 2>&1 | tail -1; rm -f /tmp/bench_write",
    label: "Sequential write throughput (1 GB)",
  },
  {
    cmd: "dd if=/dev/zero of=/tmp/bench_4k bs=4k count=10000 oflag=dsync 2>&1 | tail -1; rm -f /tmp/bench_4k",
    label: "4K sync write (IOPS indicator)",
  },

  // --- Distributed FS detection ---
  {
    cmd: "mount | grep -iE 'nfs|fuse|juicefs|gcsfuse|s3fs|ceph|lustre|overlay' || echo 'no distributed/overlay FS mounts'",
    label: "Distributed/overlay filesystem mounts",
  },
  {
    cmd: "cat /proc/filesystems 2>/dev/null | head -30",
    label: "Supported filesystems",
  },
];

async function runProbe(
  sandbox: Sandbox,
  cmd: string,
  label: string
): Promise<string> {
  let output: string;
  try {
    const result = await sandbox.exec(`bash -c ${JSON.stringify(cmd)}`);
    const stdout = result.stdout?.trim() ?? "";
    const stderr = result.stderr?.trim() ?? "";
    output = stdout || "(no output)";
    if (stderr) output += `\n[stderr]: ${stderr}`;
  } catch (e: any) {
    output = `(error: ${e.message || e})`;
  }
  return `\n${SEP}\n  ${label}\n  $ ${cmd}\n${SEP}\n${output}`;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    const sessionId = url.searchParams.get("session") || `fp-${Date.now()}`;
    const sandbox = getSandbox(env.Sandbox, sessionId);

    // Quick location-only endpoint — single exec, no ipinfo
    if (url.pathname === "/location") {
      const result = await sandbox.exec("bash -c \"echo $CLOUDFLARE_LOCATION $CLOUDFLARE_REGION $CLOUDFLARE_COUNTRY_A2 $CLOUDFLARE_NODE_ID\"");
      const loc = result.stdout?.trim() ?? "unknown";
      return new Response(`${sessionId}: ${loc}\n`, {
        headers: { "Content-Type": "text/plain; charset=utf-8" },
      });
    }

    if (url.pathname !== "/fingerprint") {
      return new Response(
        "Cloudflare Sandbox Fingerprinting\n\nGET /fingerprint — run all probes\nGET /location — quick placement check (use ?session=NAME to force new placement)\n",
        { status: 200 }
      );
    }

    const lines: string[] = [
      `Cloudflare Sandbox Fingerprinting (session: ${sessionId})`,
      `${"=".repeat(60)}`,
      "",
    ];

    for (const probe of PROBES) {
      const result = await runProbe(sandbox, probe.cmd, probe.label);
      lines.push(result);
    }

    lines.push(`\n${SEP}`);
    lines.push("  Fingerprinting complete.");
    lines.push(SEP);

    return new Response(lines.join("\n"), {
      headers: { "Content-Type": "text/plain; charset=utf-8" },
    });
  },
};
