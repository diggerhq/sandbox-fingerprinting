/**
 * Northflank Job Fingerprinting Script
 *
 * Creates a Northflank manual job that runs fingerprinting probes inside
 * a container, waits for completion, retrieves the logs, then cleans up.
 *
 * Northflank uses Kata Containers (Cloud Hypervisor / QEMU / Firecracker)
 * or gVisor for isolation, running on Kubernetes with containerd.
 *
 * Prerequisites:
 *   npm install @northflank/js-client
 *   export NORTHFLANK_API_TOKEN=your-token
 *   export NORTHFLANK_PROJECT_ID=your-project-id
 *
 * Usage:
 *   npx tsx northflank-fingerprint.ts
 */

import {
  ApiClient,
  ApiClientInMemoryContextProvider,
} from "@northflank/js-client";

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
  {
    cmd: "cat /proc/cmdline 2>/dev/null || echo 'not available'",
    label: "Kernel cmdline",
  },
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

  // --- Kata / gVisor specific ---
  {
    cmd: "uname -r | grep -i gvisor && echo 'GVISOR DETECTED' || echo 'not gVisor kernel'",
    label: "gVisor kernel detection",
  },
  {
    cmd: "dmesg 2>/dev/null | grep -i 'Cloud Hypervisor' | head -5 || echo 'no Cloud Hypervisor in dmesg'",
    label: "Cloud Hypervisor in dmesg",
  },
  {
    cmd: "cat /proc/version 2>/dev/null | grep -iE 'kata|dragonball' || echo 'no kata markers in kernel version'",
    label: "Kata kernel markers",
  },
  {
    cmd: "ls /sys/bus/virtio/devices/ 2>/dev/null && cat /sys/bus/virtio/devices/*/device 2>/dev/null || echo 'no virtio device IDs'",
    label: "Virtio device IDs (Kata uses virtiofs)",
  },
  {
    cmd: "mount | grep -i virtiofs || echo 'no virtiofs mounts'",
    label: "Virtiofs mounts (Kata indicator)",
  },
  {
    cmd: "cat /proc/self/status | grep -i seccomp || echo 'no seccomp info'",
    label: "Seccomp status",
  },

  // --- CPU & Memory ---
  { cmd: "nproc", label: "CPU count" },
  { cmd: "grep 'model name' /proc/cpuinfo | head -1", label: "CPU model" },
  {
    cmd: "grep flags /proc/cpuinfo | head -1 | tr ' ' '\\n' | grep -E 'hypervisor|vmx|svm' || echo 'no VM-related flags'",
    label: "CPU flags (hypervisor flag)",
  },
  { cmd: "free -h 2>/dev/null || cat /proc/meminfo | head -5", label: "Memory" },
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

  // --- Northflank / Kubernetes specific ---
  {
    cmd: "env | grep -iE 'northflank|NORTHFLANK|NF_' | sort || echo 'no Northflank env vars found'",
    label: "Northflank environment variables",
  },
  {
    cmd: "env | grep -iE 'KUBERNETES|K8S|KUBE' | sort || echo 'no Kubernetes env vars'",
    label: "Kubernetes environment variables",
  },
  {
    cmd: "cat /var/run/secrets/kubernetes.io/serviceaccount/namespace 2>/dev/null || echo 'no k8s namespace'",
    label: "Kubernetes namespace",
  },
  {
    cmd: "cat /var/run/secrets/kubernetes.io/serviceaccount/token 2>/dev/null | head -c 50 && echo '...(truncated)' || echo 'no k8s service account token'",
    label: "Kubernetes service account token (truncated)",
  },
  {
    cmd: "ls /var/run/secrets/ 2>/dev/null || echo 'no secrets dir'",
    label: "Secrets directory",
  },
  {
    cmd: "cat /proc/self/attr/current 2>/dev/null || echo 'no LSM label'",
    label: "LSM security label (AppArmor/SELinux)",
  },
  { cmd: "hostname", label: "Hostname" },
  { cmd: "env | sort", label: "All environment variables" },
  {
    cmd: "cat /etc/machine-id 2>/dev/null || echo 'no machine-id'",
    label: "Machine ID",
  },
  { cmd: "whoami && id", label: "Current user" },

  // --- Runtime class detection ---
  {
    cmd: "cat /proc/self/mountinfo 2>/dev/null | grep -iE 'kata|virtiofs|overlay' | head -10 || echo 'no kata/virtiofs in mountinfo'",
    label: "Runtime class hints in mountinfo",
  },
  {
    cmd: "cat /sys/kernel/mm/transparent_hugepage/enabled 2>/dev/null || echo 'not available'",
    label: "Transparent hugepages (differs in microVMs)",
  },
  {
    cmd: "ls /dev/ | head -40",
    label: "Device nodes (reveals virtio/vhost devices)",
  },

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
    cmd: 'PUBLIC_IP=$(curl -s --connect-timeout 5 ifconfig.me 2>/dev/null); [ -n "$PUBLIC_IP" ] && (dig +short -x $PUBLIC_IP 2>/dev/null || host $PUBLIC_IP 2>/dev/null || echo "no reverse DNS tools") || echo "no public IP"',
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

/** Build a single shell script from all probes */
function buildFingerprintScript(): string {
  const lines = [
    "#!/bin/bash",
    "set +e", // don't exit on errors
    `echo "${SEP}"`,
    `echo "  Northflank Job Fingerprinting"`,
    `echo "${SEP}"`,
    "",
  ];

  for (const probe of PROBES) {
    // Escape single quotes in cmd for safe embedding in heredoc-style script
    const escapedCmd = probe.cmd.replace(/'/g, "'\\''");
    lines.push(`echo ""`);
    lines.push(`echo "${SEP}"`);
    lines.push(`echo "  ${probe.label}"`);
    lines.push(`echo "  \\$ ${escapedCmd}"`);
    lines.push(`echo "${SEP}"`);
    lines.push(`( ${probe.cmd} ) 2>&1 || true`);
  }

  lines.push(`echo ""`);
  lines.push(`echo "${SEP}"`);
  lines.push(`echo "  Fingerprinting complete."`);
  lines.push(`echo "${SEP}"`);

  return lines.join("\n");
}

async function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function main() {
  const token = process.env.NORTHFLANK_API_TOKEN;
  const projectId = process.env.NORTHFLANK_PROJECT_ID;

  if (!token) {
    console.error("Error: NORTHFLANK_API_TOKEN environment variable is required.");
    console.error("Get one from: Northflank Dashboard > Account Settings > API > Tokens");
    process.exit(1);
  }
  if (!projectId) {
    console.error("Error: NORTHFLANK_PROJECT_ID environment variable is required.");
    console.error("Find it in your Northflank project settings.");
    process.exit(1);
  }

  const contextProvider = new ApiClientInMemoryContextProvider();
  await contextProvider.addContext({ name: "default", token });
  const api = new ApiClient(contextProvider);

  const jobName = `fingerprint-${Date.now()}`;
  const script = buildFingerprintScript();
  const b64Script = Buffer.from(script).toString("base64");

  console.log("Creating Northflank fingerprinting job...");
  console.log(`[DEBUG] Script size: ${script.length} chars, base64: ${b64Script.length} chars`);

  // Create a manual job with ubuntu:22.04 that runs the fingerprint script
  // We base64-encode the script to avoid quoting/length issues in the API
  let jobId: string;
  try {
    const createResult = await api.create.job.manual({
      parameters: { projectId },
      data: {
        name: jobName,
        billing: {
          deploymentPlan: "nf-compute-200-4", // 2 dedicated vCPU, 4 GB RAM
        },
        backoffLimit: 0,
        activeDeadlineSeconds: 600, // 10 minute timeout
        runOnSourceChange: "never",
        deployment: {
          external: {
            imagePath: "ubuntu:22.04",
          },
          docker: {
            configType: "customCommand",
            customCommand: `bash -c "echo ${b64Script} | base64 -d | bash"`,
          },
          storage: {
            ephemeralStorage: { storageSize: 2048 },
          },
        },
      },
    });
    jobId = createResult.data?.id ?? jobName;
    console.log(`Job created: ${jobId} (${jobName})`);
  } catch (e: any) {
    console.error("Failed to create job:", e.message || e);
    process.exit(1);
  }

  // Trigger the job run
  console.log("Starting job run...");
  let runId: string;
  try {
    const runResult = await api.start.job.run({
      parameters: { projectId, jobId },
      data: {},
    });
    runId = runResult.data?.id;
    console.log(`Run started: ${runId}`);
  } catch (e: any) {
    console.error("Failed to start job run:", e.message || e);
    console.log("Cleaning up job...");
    await api.delete.job({ parameters: { projectId, jobId } }).catch(() => {});
    process.exit(1);
  }

  // Poll for completion
  console.log("Waiting for job to complete...");
  const maxWaitMs = 10 * 60 * 1000; // 10 minutes
  const pollIntervalMs = 5000;
  const startTime = Date.now();

  while (Date.now() - startTime < maxWaitMs) {
    try {
      const runsResult = await api.get.job.runs({
        parameters: { projectId, jobId },
      });
      const runs = runsResult.data?.runs ?? [];
      const thisRun = runs.find((r: any) => r.id === runId);
      if (thisRun) {
        const status = thisRun.status?.toUpperCase?.() ?? "";
        if (status === "SUCCESS" || thisRun.concluded) {
          console.log(`Job completed with status: ${status}`);
          break;
        }
        if (status === "FAILED" || status === "ERROR") {
          console.log(`Job failed with status: ${status}`);
          break;
        }
        const elapsed = Math.round((Date.now() - startTime) / 1000);
        process.stdout.write(`\r  Status: ${status || "PENDING"} (${elapsed}s elapsed)`);
      }
    } catch (e: any) {
      // Transient API errors — keep polling
    }
    await sleep(pollIntervalMs);
  }
  console.log("");

  // Retrieve logs — try SDK first, then fall back to REST API
  console.log("Retrieving logs...\n");
  let logsFound = false;

  // Retrieve logs via REST API (paginated, max 1000 lines per request)
  const allLogs: string[] = [];
  let cursor: string | undefined;
  const maxPages = 10;

  for (let page = 0; page < maxPages; page++) {
    try {
      const params = new URLSearchParams({
        runId,
        direction: "forward",
        lineLimit: "1000",
      });
      if (cursor) params.set("cursor", cursor);

      const url = `https://api.northflank.com/v1/projects/${projectId}/jobs/${jobId}/logs?${params}`;
      const res = await fetch(url, {
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
      });
      const body = await res.json() as any;

      if (res.status !== 200) {
        console.error("[DEBUG] REST logs error:", res.status, JSON.stringify(body).slice(0, 300));
        break;
      }

      // Extract log entries from response
      const entries =
        body?.data?.logs ?? body?.logs ?? (Array.isArray(body?.data) ? body.data : []);

      if (page === 0 && entries.length === 0) {
        // Debug: show raw shape so we can diagnose
        console.log("[DEBUG] REST body keys:", Object.keys(body ?? {}));
        if (body?.data) console.log("[DEBUG] .data keys:", Object.keys(body.data));
        console.log("[DEBUG] Raw (first 500):", JSON.stringify(body).slice(0, 500));
      }

      for (const entry of entries) {
        const line =
          typeof entry === "string"
            ? entry
            : entry.log ?? entry.message ?? JSON.stringify(entry);
        allLogs.push(line);
      }

      // Check for pagination cursor
      const nextCursor = body?.pagination?.cursor ?? body?.cursor;
      if (!nextCursor || entries.length < 1000) break;
      cursor = nextCursor;
    } catch (e: any) {
      console.error("REST logs error:", e.message || e);
      break;
    }
  }

  if (allLogs.length > 0) {
    for (const line of allLogs) {
      console.log(line);
    }
  } else {
    console.log("No logs retrieved. Check the Northflank dashboard for job output.");
  }

  // Cleanup — delete the job
  console.log("\nCleaning up — deleting job...");
  try {
    await api.delete.job({ parameters: { projectId, jobId } });
    console.log("Job deleted.");
  } catch (e: any) {
    console.error(`Cleanup warning: ${e.message || e}`);
    console.log(`You may need to manually delete job "${jobName}" from the dashboard.`);
  }
}

main().catch(console.error);
