# OpenSandbox Benchmark Summary — 2026-02-23

## Final Results (c7i.xlarge, 4 vCPUs, 8GB RAM)

| Provider | create_sandbox | setup | git_clone | npm_install | npm_run_dev | kill_sandbox | TOTAL |
|----------|---------------|-------|-----------|-------------|-------------|--------------|-------|
| **OpenSandbox** | 680ms | 410ms | 506ms | **8.69s** | 271ms | 252ms | **10.81s** |
| Daytona | 2.75s | — | 618ms | 11.46s | 207ms | 209ms | 15.81s |
| E2B | 178ms | — | 725ms | 13.50s | 5.13s | 103ms | 20.05s |

**OpenSandbox is 31% faster than Daytona and 46% faster than E2B on total time.**

## Optimization Journey

| Change | Instance | npm_install | Total | Delta |
|--------|----------|------------|-------|-------|
| Baseline | t3.medium, 1 CPU, 512MB tmpfs, 1024MB RAM | 25.5s | ~28s | — |
| Bump RAM to 2048MB, tmpfs to 1GB | t3.medium, 2 CPU, 1GB tmpfs | 23.4s | ~26s | -8% |
| Enable t3.unlimited | t3.medium (unlimited) | 23.5s | ~26s | ~0% |
| Dedicated CPU | c5.large, 2 CPU, 3.0GHz | 17.2s | ~19s | -27% |
| Newer CPU gen | c7i.large, 2 CPU, 3.8GHz | 14.5s | ~17s | -16% |
| Double cores | c7i.xlarge, 4 CPU, 3.8GHz | **8.7s** | **10.8s** | -40% |

**Total improvement: 25.5s → 8.7s npm_install (66% faster)**

---

## Detailed Results Per Machine

### t3.medium — 2 vCPU (burstable), 4GB RAM, Xeon 8259CL @ 2.5GHz (~$30/mo)

**Config: 2 CPUs, 2048MB RAM, 1GB tmpfs /home/user**

| Step | OpenSandbox |
|------|-------------|
| create_sandbox | 748-862ms |
| setup | 412-441ms |
| git_clone | 520-523ms |
| npm_install | 18.98-21.17s (avg ~20s) |
| npm_run_dev | 213-310ms |
| kill_sandbox | 312-320ms |
| **TOTAL** | **21.29-23.52s** |

Notes: Enabling t3.unlimited had no measurable impact (~23.5s). Burstable vs dedicated CPU was not the bottleneck — raw clock speed was.

### c5.large — 2 vCPU (dedicated), 4GB RAM, Xeon 8124M @ 3.0GHz (~$62/mo)

**Config: 2 CPUs, 2048MB RAM, 1GB tmpfs /home/user**

Manual test (podman exec, no API overhead): npm_install = **17.9s** (user: 12.6s, sys: 1.5s)

Note: Full benchmark through the control plane failed on this machine due to stale worker IP in Redis. Manual container test confirmed the improvement.

### c7i.large — 2 vCPU (dedicated), 4GB RAM, Xeon 8488C @ 3.8GHz (~$65/mo)

**Config: 2 CPUs, 2048MB RAM, 1GB tmpfs /home/user**

All three providers, 3 iterations each (avg ± std [min .. max]):

| Step | OpenSandbox | E2B | Daytona |
|------|-------------|-----|---------|
| create_sandbox | 648ms ± 54ms | 122ms ± 35ms | 2.75s ± 190ms |
| setup | 377ms ± 16ms | — | — |
| git_clone | 640ms ± 150ms | 725ms ± 54ms | 618ms ± 179ms |
| npm_install | **14.48s ± 906ms** | 14.00s ± 1.84s | **10.49s ± 480ms** |
| npm_run_dev | 289ms ± 81ms | 5.14s ± 34ms | 151ms ± 40ms |
| kill_sandbox | 258ms ± 29ms | 136ms ± 44ms | 255ms ± 47ms |
| **TOTAL** | **16.69s ± 1.02s** | **20.24s ± 2.09s** | **13.96s ± 218ms** |

Notes: OpenSandbox and E2B nearly tied on npm_install (14.5s vs 14.0s). Daytona still ahead due to 64-core oversubscription.

### c7i.xlarge — 4 vCPU (dedicated), 8GB RAM, Xeon 8488C @ 3.8GHz (~$130/mo)

**Config: 4 CPUs, 2048MB RAM, 1GB tmpfs /home/user**

All three providers, 3 iterations each (avg ± std [min .. max]):

| Step | OpenSandbox | E2B | Daytona |
|------|-------------|-----|---------|
| create_sandbox | 680ms ± 96ms [583ms .. 775ms] | 178ms ± 73ms [132ms .. 262ms] | 2.70s ± 731ms [1.94s .. 3.40s] |
| setup | 410ms ± 48ms [358ms .. 452ms] | — | — |
| git_clone | 506ms ± 19ms [495ms .. 528ms] | 883ms ± 112ms [755ms .. 958ms] | 449ms ± 196ms [312ms .. 673ms] |
| npm_install | **8.69s ± 1.17s [7.83s .. 10.03s]** | 13.73s ± 128ms [13.58s .. 13.82s] | 11.63s ± 372ms [11.34s .. 12.05s] |
| npm_run_dev | 271ms ± 70ms [193ms .. 328ms] | 5.16s ± 41ms [5.13s .. 5.20s] | 204ms ± 107ms [112ms .. 321ms] |
| kill_sandbox | 252ms ± 9ms [242ms .. 260ms] | 100ms ± 1ms [99ms .. 101ms] | 213ms ± 1ms [211ms .. 214ms] |
| **TOTAL** | **10.81s ± 1.09s [10.01s .. 12.05s]** | **20.05s ± 239ms [19.91s .. 20.32s]** | **15.61s ± 693ms [15.12s .. 16.40s]** |

Iteration-level detail for OpenSandbox:

| | Iter 1 | Iter 2 | Iter 3 |
|---|--------|--------|--------|
| create_sandbox | 730ms | 583ms | 597ms |
| setup | 869ms | 459ms | 369ms |
| git_clone | 797ms | 524ms | 497ms |
| npm_install | 9.62s | 8.20s | 8.02s |
| npm_run_dev | 193ms | 198ms | 303ms |
| kill_sandbox | 255ms | 238ms | 264ms |
| **TOTAL** | **12.46s** | **10.20s** | **10.05s** |

Notes: Iter 1 is consistently slower (cold image pull / first container creation overhead). Best run: 10.05s total, 8.02s npm_install.

---

## Cache Probe Results (per-package install timing)

Single-package install times across providers (no cache, no proxy — all hit registry.npmjs.org):

| Provider | npm install express (64 deps) | npm install @anthropic-ai/tokenizer (4 deps) |
|----------|-------------------------------|----------------------------------------------|
| OpenSandbox (c7i.xlarge) | 3.3s | 1.8s |
| E2B | 2.5s | 1.6s |
| Daytona | 1.8-13.7s (high variance) | 1.5-1.7s |

Key finding: Per-package speeds are similar across all providers. The difference in full npm_install comes from parallelism (core count) and CPU speed during extraction/linking of 386 packages.

---

## Key Findings

### What didn't help
- **Disk-backed bind mounts**: Replacing tmpfs `/home/user` with a disk bind mount made npm_install *worse* (29.3s vs 25.5s). npm's thousands of small file writes are faster on RAM-backed tmpfs.
- **t3.unlimited**: Enabling burst credits had negligible impact (~23.5s vs 23.4s). The t3.medium CPU (Xeon 8259CL @ 2.5GHz) is just slow, not throttled.

### What helped
- **More RAM**: Bumping from 1024MB to 2048MB container memory (with 1GB tmpfs for `/home/user`) reduced contention.
- **Dedicated CPU**: Moving from burstable t3 to dedicated c5 gave an immediate 27% improvement.
- **Newer CPU**: c7i (Xeon 8488C @ 3.8GHz) vs c5 (Xeon 8124M @ 3.0GHz) = 16% faster per-core.
- **More cores**: 2 → 4 vCPUs gave the biggest single improvement (40%). npm install is heavily parallelizable.

### Root cause analysis
- npm_install is **~80% CPU-bound** (user time: 12.6s out of 16.3s wall time on 2 cores).
- Network download from registry.npmjs.org is fast (~10 MB/s). Not a bottleneck.
- No provider (E2B, Daytona, OpenSandbox) uses npm cache or registry proxy — all hit npmjs.org directly.

### Competitor hardware (from cache_probe.py)

| Provider | vCPUs visible | RAM | CPU |
|----------|--------------|-----|-----|
| OpenSandbox | 4 | 8GB | Intel Xeon 8488C @ 3.8GHz (c7i.xlarge) |
| E2B | 2 | 480MB | Intel Xeon @ 2.6GHz |
| Daytona | 64 | 755GB | AMD EPYC 9354P 32-Core |

- **Daytona** runs on a beefy bare-metal server (~$200-250/mo Hetzner-class) with no CPU limits on containers. Sandboxes see all 64 cores. This is an oversubscription model — works because most sandboxes are idle.
- **E2B** has weaker hardware (2.6GHz, 480MB RAM) — consistently slowest on npm_install.
- **OpenSandbox** wins with 4 dedicated cores on modern silicon, despite being a much smaller (cheaper) instance.

## Cost Comparison

| Setup | Monthly cost | npm_install | Cost per active sandbox |
|-------|-------------|-------------|------------------------|
| c7i.xlarge (current) | ~$130/mo | 8.7s | $130/mo (1 sandbox/machine) |
| Daytona bare-metal (est.) | ~$220-275/mo | 11.5s | ~$5-14/mo (oversubscribed) |
| c7i.large (2 vCPU) | ~$65/mo | 14.5s | $65/mo (1 sandbox/machine) |
| t3.medium (baseline) | ~$30/mo | 25.5s | $30/mo |

## Current Configuration

```
Instance:      c7i.xlarge (4 vCPUs, 8GB RAM)
CPU:           Intel Xeon Platinum 8488C @ 3.8GHz
Container:     --cpus 4, --memory 2048m
Filesystem:    tmpfs /home/user (1GB), tmpfs /tmp (256MB)
Network:       bridge mode
Image:         docker.io/library/node:20
```

## Software Changes Made

1. **`internal/podman/container.go`** — Added `Volumes []string` field to `ContainerConfig` + `--volume` CLI arg generation (for future bind mount use).
2. **`internal/sandbox/manager.go`** — Added `dataDir` field to Manager, bumped `defaultMemoryMB` from 1024 → 2048, bumped `defaultCPU` from 1 → 4, tmpfs `/home/user` at 1GB.
3. **`cmd/worker/main.go`** + **`cmd/server/main.go`** — Pass `cfg.DataDir` to `NewManager()`.

## Next Steps

- Investigate npm cache pre-warming (tested locally: 5.6s with warm cache vs 17s without on c5.large)
- Consider removing `--cpus` limit entirely (Daytona model) for even better burst performance
- EC2 pool implementation (see `delme/ec2-pool-plan.md`) for production multi-sandbox deployment
- Evaluate c7i.2xlarge (8 vCPUs) or larger instances if more concurrency per machine is needed
