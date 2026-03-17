# OpenSandbox Infrastructure Options Summary

**Date:** 2026-02-19
**Context:** Architecture options for sandbox hosting, based on competitive fingerprinting of Modal, E2B, Daytona, Sprites, and exe.dev.

---

## Competitive Landscape (What Others Do)

| Platform | Isolation | Cloud | Storage/Sandbox | Resume Time | Density |
|----------|-----------|-------|----------------|-------------|---------|
| **Modal** | gVisor (userspace kernel) | Azure eastus | 512 GiB (9p, thin-provisioned) | 0.11s (snapshot) | ~200-500/VM |
| **E2B** | Firecracker (microVM) | GCP | 22.9 GiB (ext4 block) | N/A | ~50-100/VM |
| **Sprites** | Firecracker + JuiceFS | Fly.io bare metal | 20 GiB + 1 PB distributed | N/A | ~20-40/host |
| **exe.dev** | Cloud Hypervisor (full VM) | Latitude.sh bare metal | 20 GiB (ext4 block) | N/A | ~50-80/host |
| **Daytona** | Docker + Sysbox | Hetzner bare metal | 3 GiB (overlay) | <90ms (registry) | ~500-800/host |

### Key finding from Modal fingerprinting:
- 512 GiB is a **real hard limit per sandbox** (confirmed by writing 512G)
- Each sandbox gets an **independent quota** (tested with 2 concurrent sandboxes)
- gVisor + 9p enables thin provisioning: 512G promised, ~700K used at start
- Filesystem snapshots: **4.7s to snapshot, 0.11s to restore** (diff-based)
- Volume persistence works (requires `sb.wait()` after terminate)
- No outbound internet by default
- 34K IOPS (best of all platforms) via 9p + host page cache

---

## Architecture Options for OpenSandbox

### Option A: Dense Packing (Many Sandboxes per Large VM)

The Modal/Daytona approach — pack 100-200 sandboxes on each large VM using Podman + overlayfs.

```
Large VM (L80s_v3: 80 vCPU, 640 GiB, 19.2 TB NVMe)
├── Podman + overlayfs on XFS (pquota for per-sandbox limits)
├── 100-160 sandboxes per host
├── Shared base image (stored once)
├── Thin-provisioned 512G quota per sandbox
└── Sub-second cold start (container launch)
```

**Pros:**
- Sub-second cold start
- Efficient resource sharing (CPU, RAM, disk)
- Matches what competitors do
- Highest density

**Cons:**
- Complex ops: cgroup tuning, quota management, noisy neighbor mitigation
- Container isolation weaker than VM isolation
- Capacity planning required (always-on VMs)
- Pay for full VMs even at low utilization

**Cost (3-worker cluster, 480 sandboxes):**

| Component | Monthly |
|-----------|---------|
| 3x L80s_v3 | $15,243 |
| Azure NetApp Files 4 TiB | $1,204 |
| **Total** | **$16,447** |
| **Per sandbox** | **~$34** |

With 1-year reserved instances: ~$21/sandbox. With 3-year: ~$14/sandbox.

**Alternative (cheaper VMs without local NVMe):**

| Component | Monthly |
|-----------|---------|
| 3x E96as_v5 | $11,880 |
| 3x Premium SSD v2 (4 TiB) | $1,125 |
| Azure NetApp Files 4 TiB | $1,204 |
| **Total** | **$14,209** |
| **Per sandbox (576 capacity)** | **~$25** |

---

### Option B: 1 VM per Sandbox (Small Instances + EBS)

Each sandbox runs on its own small EC2 instance with a dedicated EBS volume.

```
t3.small (2 vCPU, 2 GiB RAM)
├── EBS gp3 (20 GiB, expandable to TBs)
├── 1 Podman container per instance
├── Hibernate: stop instance, EBS persists
└── Resume: start instance, Podman starts container
```

**Pros:**
- Perfect VM-level isolation
- Simple — no container orchestration, no quota management
- Elastic — scale to zero, pay only for active sandboxes
- Spot instances for 60-90% savings
- Per-sandbox EBS expandable on demand
- No noisy neighbors

**Cons:**
- Slow cold start: 30-60s (EC2 boot)
- Slow resume from hibernate: 30-60s
- AWS API limits become bottleneck at >50K instances
- EBS costs for hibernated sandboxes ($1.60/mo per 20 GiB)

**Cost (500 active + 4,500 hibernated):**

| Component | Monthly |
|-----------|---------|
| 500x t3.small spot (active) | $2,200 |
| 500x EBS 20 GiB (active) | $800 |
| 4,500x EBS 20 GiB (hibernated) | $7,200 |
| **Total** | **$10,200** |
| **Per active sandbox** | **~$6** |
| **Per hibernated sandbox** | **$1.60 (storage only)** |

---

### Option C: Worker Pool + Detached EBS (Recommended for v1)

Keep a fleet of EC2 instances always running as a worker pool. Sandbox state lives on detachable EBS volumes. Resume = attach EBS to idle worker.

```
Worker Pool (auto-scaling group of t3.small spot instances)
├── 50-600 workers (scales with demand)
├── Each worker: pre-baked AMI with Podman + OpenSandbox agent
├── Workers are stateless — sandbox state is on EBS
│
Detached EBS Volumes (hibernated sandboxes)
├── 20 GiB gp3 per sandbox (expandable)
├── Contains: Podman overlay, user files, optional CRIU checkpoint
├── Costs $1.60/month when detached
│
Resume Flow:
  1. Pick idle worker in same AZ as EBS volume    (~instant)
  2. Attach EBS to worker                         (~5-10s)
  3. Mount + podman restore                       (~1-5s)
  4. Total:                                       ~10-15s
```

**Pros:**
- Eliminates EC2 boot time (workers already running)
- 10-15s resume (vs 30-60s with stop/start)
- Workers are reusable — serve many sandboxes over time
- Stable worker IPs (easier networking)
- Spot interruption only kills active sandbox, EBS is safe
- Simple auto-scaling

**Cons:**
- EBS volumes are AZ-locked (need workers per AZ)
- Worker pool has idle cost (~$219/month for 50 idle workers)
- 10-15s resume still not sub-second

**Cost (500 active + 4,500 hibernated):**

| Component | Monthly |
|-----------|---------|
| Worker pool (avg 600, spot) | $2,640 |
| EBS active (500x 20 GiB) | $800 |
| EBS hibernated (4,500x 20 GiB) | $7,200 |
| **Total** | **$10,640** |
| **Per active sandbox** | **~$6.50** |
| **Per hibernated sandbox** | **$1.60** |

---

### Option D: Tiered Resume Architecture (Maximum Performance)

Combine multiple strategies for different resume speed requirements. Sub-second for hot sandboxes, seconds for warm, minutes for cold.

```
┌─────────────────────────────────────────────────────┐
│                                                      │
│  HOT    podman pause/unpause           ~10ms         │
│         Container frozen in RAM on same worker       │
│         Last active: < 15 min                        │
│                                                      │
│  WARM   CRIU lazy restore (userfaultfd) ~200-800ms   │
│         Checkpoint on shared FS (EFS)                │
│         Pages fault in on-demand                     │
│         Last active: < 24 hrs                        │
│                                                      │
│  COLD   EBS attach + podman start       ~10-15s      │
│         Detached EBS on idle worker                  │
│         Last active: < 30 days                       │
│                                                      │
│  FROZEN EBS snapshot → create volume    ~30-60s      │
│         Volume deleted, snapshot kept                │
│         Last active: > 30 days                       │
│                                                      │
└─────────────────────────────────────────────────────┘
```

**Per-tier costs:**

| Tier | Resume Time | Cost/Sandbox/Month | What Pays |
|------|-------------|-------------------|-----------|
| Hot | ~10ms | ~$2 | RAM on worker |
| Warm | ~200-800ms | ~$0.50 | EFS checkpoint storage |
| Cold | ~10-15s | ~$1.60 | Detached EBS volume |
| Frozen | ~30-60s | ~$1.00 | EBS snapshot |

**At scale (5,000 sandboxes, mixed tiers):**

| Tier | Count | Monthly Cost |
|------|-------|-------------|
| Hot | 200 | $400 |
| Warm | 800 | $400 |
| Cold | 2,000 | $3,200 |
| Frozen | 2,000 | $2,000 |
| Worker pool (300 avg) | 300 | $1,320 |
| Shared FS (EFS 500 GiB) | 1 | $150 |
| **Total** | **5,000** | **$7,470** |
| **Blended per sandbox** | | **$1.49** |

**Sub-second resume via CRIU lazy pages:**
- CRIU checkpoints the container's memory + process state to shared filesystem
- On restore, process resumes immediately — memory pages fault in on-demand via userfaultfd
- Process starts in ~200-500ms, fully warm within seconds
- Same technique AWS Lambda uses for Firecracker snapshots

---

## Comparison Matrix

| | Option A: Dense | Option B: 1-per-VM | Option C: Worker Pool | Option D: Tiered |
|---|---|---|---|---|
| **Resume time** | <1s | 30-60s | 10-15s | 10ms - 60s |
| **Isolation** | Container | Full VM | Full VM | Full VM |
| **Complexity** | High | Low | Medium | High |
| **Cost/sandbox (active)** | $14-34 | $6 | $6.50 | $1.49 (blended) |
| **Cost at zero load** | Full VM cost | $0 | Pool idle cost | Pool idle cost |
| **Max scale** | Millions | ~50K | ~50K | ~50K (AWS), millions (bare metal) |
| **Cold start (new)** | <1s | 60-90s | 60-90s (or instant from warm pool) | 60-90s |
| **Storage/sandbox** | 512G thin | 20G real (expandable) | 20G real (expandable) | 20G real (expandable) |
| **Best for** | High density, ephemeral | Dev environments | Dev environments | Mixed workloads |

---

## Scaling Path

| Stage | Sandboxes | Architecture | Infrastructure |
|-------|-----------|-------------|---------------|
| **Launch** (month 1-6) | 0-5,000 | Option C (worker pool + EBS) | AWS, t3.small spot |
| **Growth** (month 6-12) | 5,000-50,000 | Option D (tiered) | AWS, multi-region |
| **Scale** (year 2) | 50,000-200,000 | Hybrid: dense hot + 1-per-VM cold | AWS + bare metal |
| **Massive** (year 3+) | 200,000-1M+ | Dense packing on bare metal | Hetzner/OVH ($300/host vs $5K on AWS) |

---

## AWS Quota Reality

| Account Stage | Max Instances | Timeline |
|---------------|--------------|----------|
| New account | 50-500 | Day 1 |
| 3-6 months, $5K+/mo spend | 2,500-5,000 | Auto/request |
| Enterprise support + TAM | 10,000-50,000 | 1 week |
| Strategic contract | 100,000+ | Negotiated |
| **Practical ceiling for 1-per-VM** | **~50,000-100,000** | Multi-region |

Beyond 50K-100K instances, the EC2/EBS control plane (API rate limits, volume management, networking) becomes the bottleneck — not AWS willingness to sell compute.

---

## Recommendation

**Start with Option C (Worker Pool + Detached EBS) for launch.**

Reasons:
1. **Simple** — EC2 + EBS + Podman, no exotic infrastructure
2. **Cheap** — $6.50/active sandbox, $1.60/hibernated, scales to zero
3. **Strong isolation** — full VM per sandbox (selling point vs competitors)
4. **Fast enough** — 10-15s resume is acceptable for dev environments
5. **Expandable** — per-sandbox EBS grows from 20 GiB to TBs on demand
6. **Spot-friendly** — 60-90% cost savings, EBS survives interruptions
7. **Migration path** — add CRIU/tiered resume later without re-architecting

When 10-15s resume becomes a competitive disadvantage, layer on CRIU lazy restore (Option D warm tier) for sub-second resume of recently active sandboxes. This is additive — no need to rebuild.

When you outgrow AWS (~50K sandboxes), transition the hot tier to dense packing on bare metal (Hetzner at $300/host = 7x cheaper than AWS). The cold/frozen tiers can stay on AWS EBS/snapshots.
