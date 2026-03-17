"""
Modal Persistence Test

Tests whether data written to disk survives snapshot/restore and volume mounts.

Tests:
1. Filesystem snapshot: write files → snapshot → restore → verify
2. Volume persistence: write to mounted volume → terminate → remount → verify
3. Snapshot size: write large data → snapshot → measure overhead

Usage:
    python modal-persistence-test.py
"""

import time
import modal


def run(sb, cmd: str, label: str) -> str:
    try:
        proc = sb.exec("bash", "-c", cmd, timeout=60)
        stdout = proc.stdout.read()
        stderr = proc.stderr.read()
        output = stdout.strip() if stdout else "(no output)"
        if stderr and stderr.strip():
            output += f"\n[stderr]: {stderr.strip()}"
    except Exception as e:
        output = f"(error: {e})"
    print(f"  [{label}] {output}")
    return output


def test_filesystem_snapshot(app):
    """Test 1: Write files, snapshot, restore to new sandbox, verify."""
    print("\n" + "=" * 60)
    print("  TEST 1: Filesystem Snapshot + Restore")
    print("=" * 60)

    # Create sandbox and write test data
    print("\n--- Phase 1: Write data to sandbox ---")
    sb1 = modal.Sandbox.create(app=app, timeout=300)
    print(f"  Sandbox 1: {sb1.object_id}")

    run(sb1, "echo 'hello from snapshot test' > /tmp/test.txt", "Write text file")
    run(sb1, "mkdir -p /opt/mydata && echo '{\"key\": \"value\"}' > /opt/mydata/config.json", "Write JSON to /opt")
    run(sb1, "dd if=/dev/urandom of=/tmp/random_100mb bs=1M count=100 2>&1 | tail -1", "Write 100 MiB random data")
    run(sb1, "md5sum /tmp/random_100mb", "MD5 of random data (for verification)")
    run(sb1, "md5sum /tmp/test.txt /opt/mydata/config.json", "MD5 of text files")
    run(sb1, "df -h / | tail -1", "Disk usage before snapshot")

    md5_random = run(sb1, "md5sum /tmp/random_100mb | awk '{print $1}'", "Random file MD5")
    md5_text = run(sb1, "md5sum /tmp/test.txt | awk '{print $1}'", "Text file MD5")

    # Snapshot
    print("\n--- Phase 2: Create filesystem snapshot ---")
    t0 = time.time()
    snapshot_image = sb1.snapshot_filesystem()
    snap_time = time.time() - t0
    print(f"  Snapshot created in {snap_time:.2f}s")
    print(f"  Snapshot image: {snapshot_image.object_id}")

    sb1.terminate()
    print("  Sandbox 1 terminated.")

    # Restore
    print("\n--- Phase 3: Restore from snapshot ---")
    t0 = time.time()
    sb2 = modal.Sandbox.create(image=snapshot_image, app=app, timeout=300)
    restore_time = time.time() - t0
    print(f"  Sandbox 2: {sb2.object_id}")
    print(f"  Restored in {restore_time:.2f}s")

    # Verify
    print("\n--- Phase 4: Verify data integrity ---")
    run(sb2, "cat /tmp/test.txt", "Text file content")
    run(sb2, "cat /opt/mydata/config.json", "JSON file content")

    restored_md5_random = run(sb2, "md5sum /tmp/random_100mb | awk '{print $1}'", "Random file MD5 (restored)")
    restored_md5_text = run(sb2, "md5sum /tmp/test.txt | awk '{print $1}'", "Text file MD5 (restored)")

    run(sb2, "df -h / | tail -1", "Disk usage after restore")
    run(sb2, "ls -la /tmp/", "Contents of /tmp")
    run(sb2, "ls -la /opt/mydata/", "Contents of /opt/mydata")

    # Verify checksums
    random_match = md5_random.split("\n")[0] == restored_md5_random.split("\n")[0]
    text_match = md5_text.split("\n")[0] == restored_md5_text.split("\n")[0]
    print(f"\n  Random data integrity: {'PASS' if random_match else 'FAIL'}")
    print(f"  Text file integrity:   {'PASS' if text_match else 'FAIL'}")
    print(f"  Snapshot time:         {snap_time:.2f}s")
    print(f"  Restore time:          {restore_time:.2f}s")

    sb2.terminate()
    return snapshot_image


def test_volume_persistence(app):
    """Test 2: Write to a mounted volume, terminate, remount, verify."""
    print("\n" + "=" * 60)
    print("  TEST 2: Volume Persistence")
    print("=" * 60)

    vol_name = f"fingerprint-test-vol-{int(time.time())}"
    vol = modal.Volume.from_name(vol_name, create_if_missing=True)
    print(f"  Volume: {vol_name}")

    # Write data to volume
    print("\n--- Phase 1: Write data to volume ---")
    sb1 = modal.Sandbox.create(volumes={"/data": vol}, app=app, timeout=300)
    print(f"  Sandbox 1: {sb1.object_id}")

    run(sb1, "echo 'persistent data' > /data/persist.txt", "Write to volume")
    run(sb1, "dd if=/dev/urandom of=/data/random_50mb bs=1M count=50 2>&1 | tail -1", "Write 50 MiB to volume")
    md5_vol = run(sb1, "md5sum /data/random_50mb | awk '{print $1}'", "Volume file MD5")
    run(sb1, "ls -la /data/", "Volume contents")
    run(sb1, "df -hT /data", "Volume filesystem info")

    # Sync volume before terminating
    run(sb1, "sync", "Flush writes")
    sb1.terminate()
    sb1.wait(raise_on_termination=False)
    print("  Sandbox 1 terminated (waited for cleanup).")

    # Verify from client side before remounting
    print("\n--- Phase 1.5: Verify via client API ---")
    try:
        client_data = b""
        for chunk in vol.read_file("persist.txt"):
            client_data += chunk
        print(f"  [Client read persist.txt] {client_data.decode().strip()}")
    except Exception as e:
        print(f"  [Client read persist.txt] FAILED: {e}")

    try:
        entries = list(vol.listdir("/"))
        print(f"  [Client listdir /] {[e.path for e in entries]}")
    except Exception as e:
        print(f"  [Client listdir /] FAILED: {e}")

    # Remount in new sandbox
    print("\n--- Phase 2: Mount volume in new sandbox ---")
    sb2 = modal.Sandbox.create(volumes={"/data": vol}, app=app, timeout=300)
    print(f"  Sandbox 2: {sb2.object_id}")

    run(sb2, "ls -la /data/", "Volume contents after remount")
    run(sb2, "cat /data/persist.txt", "Read text from volume")
    restored_md5_vol = run(sb2, "md5sum /data/random_50mb | awk '{print $1}'", "Volume file MD5 (restored)")
    run(sb2, "df -hT /data", "Volume filesystem info")

    vol_match = md5_vol.split("\n")[0] == restored_md5_vol.split("\n")[0]
    print(f"\n  Volume data integrity: {'PASS' if vol_match else 'FAIL'}")

    sb2.terminate()

    # Cleanup volume
    try:
        modal.Volume.delete(vol_name)
        print(f"  Volume {vol_name} deleted.")
    except Exception as e:
        print(f"  Volume cleanup: {e}")


def test_snapshot_with_large_data(app):
    """Test 3: Write progressively larger data, snapshot each time, measure times."""
    print("\n" + "=" * 60)
    print("  TEST 3: Snapshot Overhead vs Data Size")
    print("=" * 60)

    sb = modal.Sandbox.create(app=app, timeout=600)
    print(f"  Sandbox: {sb.object_id}")

    sizes_mb = [0, 100, 500, 1000]
    results = []

    for size_mb in sizes_mb:
        if size_mb > 0:
            run(sb, f"dd if=/dev/urandom of=/tmp/data_{size_mb}mb bs=1M count={size_mb} 2>&1 | tail -1",
                f"Write {size_mb} MiB")

        run(sb, "du -sh /tmp/ 2>/dev/null", f"Total /tmp size")

        t0 = time.time()
        img = sb.snapshot_filesystem()
        snap_time = time.time() - t0
        results.append((size_mb, snap_time))
        print(f"  Snapshot at {size_mb} MiB: {snap_time:.2f}s  (image: {img.object_id})")

    sb.terminate()

    print("\n--- Summary ---")
    print(f"  {'Data (MiB)':<12} {'Snapshot Time (s)':<20}")
    print(f"  {'-'*12} {'-'*20}")
    for size_mb, snap_time in results:
        print(f"  {size_mb:<12} {snap_time:<20.2f}")


def main():
    app = modal.App.lookup("persistence-test", create_if_missing=True)

    test_filesystem_snapshot(app)
    test_volume_persistence(app)
    test_snapshot_with_large_data(app)

    print("\n" + "=" * 60)
    print("  All persistence tests complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()
