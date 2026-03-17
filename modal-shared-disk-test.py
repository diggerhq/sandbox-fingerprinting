"""
Modal Shared Disk Test

Determines whether multiple sandboxes share the same underlying
disk quota or each get independent 512 GiB allocations.

Tests:
1. Create 2 sandboxes, write 100G in one, check df in both
2. Check if files from sandbox 1 are visible in sandbox 2
3. Write in both simultaneously, see if they compete for space

Usage:
    python modal-shared-disk-test.py
"""

import modal


def run(sb, cmd: str, label: str) -> str:
    try:
        proc = sb.exec("bash", "-c", cmd, timeout=120)
        stdout = proc.stdout.read()
        stderr = proc.stderr.read()
        output = stdout.strip() if stdout else "(no output)"
        if stderr and stderr.strip():
            output += f"\n[stderr]: {stderr.strip()}"
    except Exception as e:
        output = f"(error: {e})"
    print(f"  [{label}] {output}")
    return output


def main():
    app = modal.App.lookup("shared-disk-test", create_if_missing=True)

    print("Creating two sandboxes concurrently...")
    sb1 = modal.Sandbox.create(app=app, timeout=600)
    sb2 = modal.Sandbox.create(app=app, timeout=600)
    print(f"  Sandbox A: {sb1.object_id}")
    print(f"  Sandbox B: {sb2.object_id}")

    # --- Test 1: Baseline ---
    print("\n" + "=" * 60)
    print("  TEST 1: Baseline disk usage")
    print("=" * 60)
    run(sb1, "df -h / | tail -1", "A: baseline")
    run(sb2, "df -h / | tail -1", "B: baseline")

    # --- Test 2: Write 100G in A, check B ---
    print("\n" + "=" * 60)
    print("  TEST 2: Write 100 GiB in A, check if B is affected")
    print("=" * 60)
    run(sb1, "dd if=/dev/urandom of=/tmp/bigfile bs=1M count=102400 2>&1 | tail -1",
        "A: writing 100 GiB (urandom, incompressible)")
    run(sb1, "df -h / | tail -1", "A: after 100G write")
    run(sb2, "df -h / | tail -1", "B: after A wrote 100G")

    # --- Test 3: Check file isolation ---
    print("\n" + "=" * 60)
    print("  TEST 3: File isolation — can B see A's files?")
    print("=" * 60)
    run(sb1, "echo 'from sandbox A' > /tmp/sandbox_a_file.txt", "A: write marker")
    run(sb2, "cat /tmp/sandbox_a_file.txt 2>&1", "B: try to read A's file")
    run(sb2, "ls /tmp/", "B: list /tmp")
    run(sb1, "ls /tmp/", "A: list /tmp")

    # --- Test 4: Write in both, check for contention ---
    print("\n" + "=" * 60)
    print("  TEST 4: Write 50 GiB in B while A has 100 GiB")
    print("=" * 60)
    run(sb2, "dd if=/dev/urandom of=/tmp/bigfile_b bs=1M count=51200 2>&1 | tail -1",
        "B: writing 50 GiB")
    run(sb1, "df -h / | tail -1", "A: after B wrote 50G")
    run(sb2, "df -h / | tail -1", "B: after B wrote 50G")

    # --- Test 5: Check host identity ---
    print("\n" + "=" * 60)
    print("  TEST 5: Are they on the same host?")
    print("=" * 60)
    run(sb1, "cat /proc/cpuinfo | grep 'model name' | head -1", "A: CPU")
    run(sb2, "cat /proc/cpuinfo | grep 'model name' | head -1", "B: CPU")
    run(sb1, "head -1 /proc/meminfo", "A: MemTotal (host leak)")
    run(sb2, "head -1 /proc/meminfo", "B: MemTotal (host leak)")
    run(sb1, "cat /proc/1/cgroup | head -3", "A: cgroup ID")
    run(sb2, "cat /proc/1/cgroup | head -3", "B: cgroup ID")

    # --- Summary ---
    print("\n" + "=" * 60)
    print("  SUMMARY")
    print("=" * 60)
    a_df = run(sb1, "df -h / | tail -1", "A: final")
    b_df = run(sb2, "df -h / | tail -1", "B: final")

    sb1.terminate()
    sb2.terminate()
    print("\nBoth sandboxes terminated.")


if __name__ == "__main__":
    main()
