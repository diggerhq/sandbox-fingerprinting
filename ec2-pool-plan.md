# EC2 Pool + EBS Volumes + ECR Image Sync Daemon

## Context

OpenSandbox currently runs on Fly.io or locally. We're building the production EC2 deployment with:
- A manually-managed pool of **t3.medium** instances (2 vCPUs, 4GB RAM, ~$30/month, 30GB gp3 root volume)
- **Per-sandbox EBS volumes** that follow the sandbox between running/idle instances (fast checkpoint restore — no S3 download)
- An **image sync daemon** that keeps all ECR template images cached on every worker (24h cycle + on-demand)
- Sandboxes get **2GB RAM, 2 CPUs** (~1GB overhead for OS/worker/Podman, ~1GB headroom)

The EC2 pool is **manually managed** (pre-launched, workers self-register via Redis heartbeat). The control plane discovers them through the existing Redis registry — no programmatic EC2 launch/terminate in the MVP.

---

## Implementation Plan (7 phases, 12 files)

### Phase 1: Foundation — Config, Migration, Podman Methods
*No runtime dependencies. Pure groundwork.*

**1a. Config additions** — `internal/config/config.go`
- Add fields to `Config` struct:
  ```
  EC2Region, EC2AvailabilityZone     (for EBS volume creation — same AZ as instances)
  EC2AccessKeyID, EC2SecretAccessKey  (reuse S3 keys if same account)
  EBSSandboxSizeGB (default 2)
  EBSVolumeType (default "gp3")
  EBSMountBase (default "/mnt/sandbox")
  ```
- Add env var loading in `Load()`:
  ```
  OPENSANDBOX_EC2_REGION, OPENSANDBOX_EC2_AZ
  OPENSANDBOX_EC2_ACCESS_KEY_ID, OPENSANDBOX_EC2_SECRET_ACCESS_KEY
  OPENSANDBOX_EBS_SANDBOX_SIZE_GB, OPENSANDBOX_EBS_VOLUME_TYPE
  OPENSANDBOX_EBS_MOUNT_BASE
  ```

**1b. Database migration** — `internal/db/migrations/005_ec2_ebs_pool.up.sql` (new file)
```sql
CREATE TABLE ec2_instances (
    instance_id       TEXT PRIMARY KEY,
    availability_zone TEXT NOT NULL,
    private_ip        TEXT,
    public_ip         TEXT,
    pool_type         TEXT NOT NULL DEFAULT 'idle',   -- 'running' or 'idle'
    active_sandbox_id TEXT,
    worker_id         TEXT,
    status            TEXT NOT NULL DEFAULT 'active',
    created_at        TIMESTAMPTZ DEFAULT now(),
    updated_at        TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE ebs_volumes (
    volume_id            TEXT PRIMARY KEY,
    sandbox_id           TEXT NOT NULL,
    availability_zone    TEXT NOT NULL,
    size_gb              INT NOT NULL DEFAULT 2,
    status               TEXT NOT NULL DEFAULT 'creating',
    attached_instance_id TEXT REFERENCES ec2_instances(instance_id),
    mount_path           TEXT,
    has_checkpoint       BOOLEAN DEFAULT false,
    created_at           TIMESTAMPTZ DEFAULT now(),
    updated_at           TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE sandbox_sessions ADD COLUMN IF NOT EXISTS ec2_instance_id TEXT;
ALTER TABLE sandbox_sessions ADD COLUMN IF NOT EXISTS ebs_volume_id TEXT;
```

**1c. DB accessor methods** — `internal/db/store.go`
- `UpsertEC2Instance(ctx, inst)` / `GetEC2Instance(ctx, instanceID)`
- `ListEC2Instances(ctx, poolType)` / `UpdateEC2Pool(ctx, instanceID, poolType, sandboxID)`
- `CreateEBSVolume(ctx, vol)` / `GetEBSVolumeBySandbox(ctx, sandboxID)`
- `AttachEBSVolume(ctx, volumeID, instanceID, mountPath)` / `DetachEBSVolume(ctx, volumeID)`
- `MarkEBSCheckpoint(ctx, volumeID)` / `ListEBSVolumesByInstance(ctx, instanceID)`
- `ListAllTemplates(ctx)` — returns all templates regardless of org (for image sync)

**1d. Podman image management methods** — `internal/podman/container.go`
- Add after existing `ImageExists` (line 279):
  - `ListImages(ctx) ([]ImageInfo, error)` — `podman images --format json`
  - `RemoveImage(ctx, imageRef, force) error` — `podman rmi`
  - `ImageInfo` struct: ID, Names, Created, Size

---

### Phase 2: EBS Volume Manager
*AWS SDK wrapper for EBS lifecycle. Used by orchestrator and worker.*

**New file: `internal/compute/ebs.go`**

```go
type EBSManagerConfig struct {
    Region, AvailabilityZone, AccessKeyID, SecretAccessKey string
    DefaultSizeGB int
    VolumeType    string
}

type EBSManager struct { client *ec2.Client; cfg EBSManagerConfig }
```

Methods:
- `CreateVolume(ctx, sandboxID, sizeGB) (volumeID string, err)` — `ec2.CreateVolume` with tags `opensandbox:sandbox-id`
- `DeleteVolume(ctx, volumeID) error` — `ec2.DeleteVolume`
- `AttachVolume(ctx, volumeID, instanceID) (deviceName string, err)` — `ec2.AttachVolume`, auto-picks `/dev/xvd[f-p]`
- `DetachVolume(ctx, volumeID) error` — `ec2.DetachVolume`
- `WaitForState(ctx, volumeID, targetState) error` — polls `ec2.DescribeVolumes`
- `FindNextDevice(ctx, instanceID) (string, error)` — queries block device mappings

Dependencies: `aws-sdk-go-v2/service/ec2` (add to go.mod alongside existing aws-sdk-go-v2 usage)

---

### Phase 3: EBS Checkpoint Store + Modified Hibernate/Wake
*Replaces S3 round-trip with local EBS file I/O.*

**3a. New file: `internal/storage/ebs.go`**

```go
type EBSCheckpointStore struct { baseMountPath string }  // default "/mnt/sandbox"

func (s *EBSCheckpointStore) CheckpointPath(sandboxID string) string
    // → /mnt/sandbox/<sandboxID>/checkpoint.tar.zst

func (s *EBSCheckpointStore) Save(ctx, sandboxID, localPath) (int64, error)
    // Local file move/copy — no network

func (s *EBSCheckpointStore) Exists(sandboxID) bool
    // os.Stat check
```

**3b. Modified: `internal/sandbox/hibernate.go`**

Add two new methods alongside existing S3 methods (don't modify existing ones):

- `HibernateToEBS(ctx, sandboxID, ebsStore)` — checkpoint directly to EBS mount path, no upload
- `WakeFromEBS(ctx, sandboxID, ebsStore, timeout)` — restore from local EBS path, no download

Both reuse existing `trimBeforeCheckpoint()`, `podman.CheckpointContainer()`, `podman.RestoreContainer()`.

**3c. Worker EBS mount utility** — new file: `internal/worker/ebs_mount.go`

- `MountEBSVolume(device, mountPath) error` — `mkfs.ext4` if needed, then `mount`
- `UnmountEBSVolume(mountPath) error` — `umount`
- `MountAttachedVolumes(basePath) error` — discovers attached non-root block devices via `lsblk`, mounts each

Called at worker startup and after EBS attach operations.

---

### Phase 4: Image Sync Daemon
*Background goroutine in the worker process. 24h full sync + on-demand pull.*

**New file: `internal/worker/image_sync.go`**

```go
type ImageSyncDaemon struct {
    podman    *podman.Client
    ecrConfig *ecr.Config
    store     *db.Store          // PG — for listing templates
    interval  time.Duration      // 24h
    pruneAge  time.Duration      // 24h
}
```

**`Start()` goroutine loop:**
1. Run `fullSync()` immediately on startup
2. Refresh ECR auth every 10h (tokens expire 12h)
3. Run `fullSync()` every 24h

**`fullSync()` steps:**
1. `refreshECRAuth()` — `ecr.GetAuthToken()` → `podman.LoginRegistry()`
2. `store.ListAllTemplates(ctx)` — get all template imageRefs from PG
3. For each template: `podman.ImageExists()` → if missing, `podman.PullImage()`
4. Build set of referenced images
5. `pruneImages()` — `podman.ListImages()`, filter to ECR images not in referenced set and older than `pruneAge`, call `podman.RemoveImage()`

**`EnsureImage(ctx, imageRef) error`:**
- Called synchronously before sandbox creation
- If image exists locally, returns nil immediately
- Otherwise pulls from ECR (blocking)

**Integration point:** `cmd/worker/main.go` — start daemon after the existing pre-pull goroutine (line 185):
```go
if ecrCfg != nil && ecrCfg.IsConfigured() && store != nil {
    syncDaemon := worker.NewImageSyncDaemon(...)
    syncDaemon.Start()
    defer syncDaemon.Stop()
}
```

---

### Phase 5: Orchestrator
*Runs on the control plane. Ties EBS + DB + worker registry together.*

**New file: `internal/compute/orchestrator.go`**

```go
type Orchestrator struct {
    ebs   *EBSManager
    store *db.Store
    az    string
}
```

**`ProvisionSandbox(ctx, sandboxID, workerID, instanceID, sizeGB) (volumeID, mountPath, error)`:**
1. `ebs.CreateVolume(ctx, sandboxID, sizeGB)`
2. `ebs.WaitForState(ctx, volumeID, "available")`
3. `ebs.AttachVolume(ctx, volumeID, instanceID)`
4. `ebs.WaitForState(ctx, volumeID, "in-use")`
5. Worker mounts volume (via gRPC call)
6. Update DB: `store.CreateEBSVolume()`, `store.AttachEBSVolume()`, `store.UpdateEC2Pool(instanceID, "running", sandboxID)`

**`ReleaseSandbox(ctx, sandboxID) error`:**
Called after hibernate — detaches EBS, frees instance back to idle pool:
1. `store.GetEBSVolumeBySandbox(ctx, sandboxID)`
2. Worker unmounts volume
3. `ebs.DetachVolume(ctx, volumeID)`
4. `ebs.WaitForState(ctx, volumeID, "available")`
5. `store.DetachEBSVolume(ctx, volumeID)`
6. `store.UpdateEC2Pool(instanceID, "idle", nil)`

**`PrepareSandboxWake(ctx, sandboxID, instanceID) (mountPath, error)`:**
Called before wake — reattaches EBS to a (potentially different) instance:
1. `store.GetEBSVolumeBySandbox(ctx, sandboxID)`
2. `ebs.AttachVolume(ctx, volumeID, instanceID)`
3. `ebs.WaitForState(ctx, volumeID, "in-use")`
4. Worker mounts volume
5. `store.AttachEBSVolume(ctx, volumeID, instanceID, mountPath)`
6. `store.UpdateEC2Pool(instanceID, "running", sandboxID)`

**`DestroySandbox(ctx, sandboxID) error`:**
Full cleanup — detach + delete EBS, free instance:
1. Detach volume (if attached)
2. `ebs.DeleteVolume(ctx, volumeID)`
3. `store.DeleteEBSVolumeRecord(ctx, volumeID)`
4. `store.UpdateEC2Pool(instanceID, "idle", nil)`

---

### Phase 6: Control Plane + Router Integration

**6a. Modified sandbox creation** — `internal/api/sandbox.go`

In `createSandboxRemote()`, when orchestrator is configured:
1. Pick worker via existing `workerRegistry.GetLeastLoadedWorker()`
2. Look up which EC2 instance that worker is on: `store.GetEC2InstanceByWorker(workerID)`
3. `orchestrator.ProvisionSandbox(ctx, sandboxID, workerID, instanceID, sizeGB)`
4. Tell worker to mount the EBS volume (new gRPC RPC)
5. Dispatch existing `grpcClient.CreateSandbox()` — unchanged
6. Record `ec2_instance_id` and `ebs_volume_id` in `sandbox_sessions`

**6b. Modified sandbox router** — `internal/sandbox/router.go`

Add `EBSStore *storage.EBSCheckpointStore` to `RouterConfig`.

In `onTimeout()`: if `ebsStore != nil`, call `manager.HibernateToEBS()` instead of S3.
In `doWake()`: if `ebsStore != nil` and checkpoint exists on EBS, call `manager.WakeFromEBS()`.

Falls back to existing S3 path if EBS is not configured.

**6c. New gRPC RPCs** — `proto/worker/worker.proto`

Add:
```protobuf
rpc MountVolume(MountVolumeRequest) returns (MountVolumeResponse);
rpc UnmountVolume(UnmountVolumeRequest) returns (UnmountVolumeResponse);
```

Implemented in `internal/worker/grpc_server.go` — calls `ebs_mount.MountEBSVolume()` / `UnmountEBSVolume()`.

---

### Phase 7: AMI + Deployment

**7a. Packer template** — new file: `deploy/ec2/packer.pkr.hcl`
- Source: Ubuntu 24.04 AMI
- Runs existing `setup-instance.sh`
- Pre-pulls default images (ubuntu, python, node) into AMI
- Creates `/mnt/sandbox/` directory
- 30GB gp3 root volume
- Output: AMI ID for launching workers

**7b. Updated worker.env** — `deploy/ec2/worker.env.example`
- Add `OPENSANDBOX_EC2_REGION`, `OPENSANDBOX_EC2_AZ`
- Add `OPENSANDBOX_EBS_*` vars
- Add `OPENSANDBOX_ECR_REGISTRY`, `OPENSANDBOX_ECR_REPOSITORY`

**7c. Instance self-registration**
- User-data script writes instance metadata (instance-id, AZ, private IP) to `/etc/opensandbox/instance.json`
- Worker reads this at startup and includes it in Redis heartbeat

---

## File Summary

| File | Action | Description |
|------|--------|-------------|
| `internal/config/config.go` | Modify | Add EC2/EBS env vars |
| `internal/db/migrations/005_ec2_ebs_pool.up.sql` | New | ec2_instances + ebs_volumes tables |
| `internal/db/store.go` | Modify | Add EC2/EBS/template DB methods |
| `internal/podman/container.go` | Modify | Add ListImages, RemoveImage |
| `internal/compute/ebs.go` | New | EBS volume lifecycle (AWS SDK) |
| `internal/storage/ebs.go` | New | EBS checkpoint store (local I/O) |
| `internal/sandbox/hibernate.go` | Modify | Add HibernateToEBS, WakeFromEBS |
| `internal/worker/image_sync.go` | New | ECR image sync daemon |
| `internal/worker/ebs_mount.go` | New | EBS mount/unmount/format utilities |
| `internal/compute/orchestrator.go` | New | EBS provisioning + instance pool coordination |
| `internal/api/sandbox.go` | Modify | Integrate orchestrator into sandbox creation |
| `internal/sandbox/router.go` | Modify | Prefer EBS checkpoint over S3 |
| `cmd/worker/main.go` | Modify | Start image sync daemon, mount EBS on startup |
| `proto/worker/worker.proto` | Modify | Add MountVolume/UnmountVolume RPCs |
| `deploy/ec2/packer.pkr.hcl` | New | AMI baking template |
| `deploy/ec2/worker.env.example` | Modify | Add EC2/EBS config vars |

## Implementation Order

```
Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5 → Phase 6 → Phase 7
config     EBS mgr   checkpoint  img sync   orchestr   integrate  deploy
migration  (AWS SDK)  hibernate   daemon     (ties it   (API +     (AMI)
podman               wake        (ECR pull)  together)  router)
DB methods
```

Phases 2, 3, 4 are independent of each other once Phase 1 is done — can be built in parallel.

## Verification

1. **Phase 1**: `CGO_ENABLED=1 go build ./...` compiles. Migration runs via `make run-pg`.
2. **Phase 2**: Unit test EBS manager against localstack or AWS sandbox account.
3. **Phase 3**: Test `HibernateToEBS` / `WakeFromEBS` locally by writing checkpoint to a temp dir.
4. **Phase 4**: Start worker with ECR config, verify daemon pulls templates and prunes old images.
5. **Phase 5**: Integration test: provision sandbox → get volume ID → attach → mount → verify.
6. **Phase 6**: End-to-end: `POST /api/sandboxes` → sandbox created on EC2 with EBS → hibernate → wake from EBS.
7. **Phase 7**: Bake AMI with Packer, launch instance, verify worker self-registers.

## Key Constraints

- **Same-AZ**: All EBS volumes and EC2 instances must be in the same AZ. Cross-AZ attach fails.
- **No auto-scaling**: Fixed pool, manually launched. Add scaling later.
- **Single region**: One AZ for MVP. Multi-region is a future concern.
- **30GB root volume budget**: ~5GB OS, ~25GB for image cache. Pruning keeps it bounded.
- **EBS attach latency**: 5-15 seconds per attach. Adds to cold-start but eliminates S3 download (30s+).
