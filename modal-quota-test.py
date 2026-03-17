"""
Modal Storage Quota Test

Probes the actual storage limit inside a Modal sandbox by:
1. Trying fallocate (instant space reservation)
2. Trying sparse file creation (dd with seek)
3. Actually writing data in 5 GiB chunks until failure

Usage:
    python modal-quota-test.py
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
    print(f"\n--- {label} ---")
    print(f"  $ {cmd}")
    print(output)
    return output


def main():
    app = modal.App.lookup("quota-test", create_if_missing=True)
    print("Creating Modal sandbox...")
    sb = modal.Sandbox.create(app=app, timeout=600)
    print(f"Sandbox: {sb.object_id}\n")

    try:
        # Baseline
        run(sb, "df -hT /", "Baseline disk usage")
        run(sb, "df -hT /tmp", "Baseline /tmp usage")

        # --- Test 1: fallocate (instant, tests quota without writing data) ---
        for size in ["10G", "50G", "100G", "200G", "400G", "510G"]:
            result = run(sb,
                f"fallocate -l {size} /tmp/testfile_{size} 2>&1 && echo 'OK: allocated {size}' || echo 'FAILED at {size}'",
                f"fallocate {size}")
            run(sb, "df -h / | tail -1", f"Disk after fallocate {size}")
            if "FAILED" in result or "error" in result.lower():
                break
        run(sb, "rm -f /tmp/testfile_*", "Cleanup fallocate files")

        # --- Test 2: sparse file (tests apparent size limit) ---
        run(sb,
            "dd if=/dev/zero of=/tmp/sparse bs=1 count=0 seek=600G 2>&1 && ls -lh /tmp/sparse && du -h /tmp/sparse || echo 'FAILED'",
            "Sparse file 600G (apparent size, no real data)")
        run(sb, "rm -f /tmp/sparse", "Cleanup sparse")

        # --- Test 3: actual writes in 5 GiB chunks ---
        print("\n=== Actual write test (5 GiB chunks) ===")
        run(sb, "df -h / | tail -1", "Before writes")

        total = 0
        for i in range(1, 120):  # up to 600 GiB max
            total = i * 5
            result = run(sb,
                f"dd if=/dev/zero of=/tmp/fill_{i} bs=1M count=5120 2>&1 | tail -1",
                f"Write chunk {i} (total: {total} GiB)")
            df_result = run(sb, "df -h / | tail -1", f"Disk at {total} GiB written")
            if "error" in result.lower() or "No space" in result or "cannot" in result.lower():
                print(f"\n*** HIT LIMIT at ~{total} GiB ***")
                break

        # Final state
        run(sb, "df -hT /", "Final disk state")
        run(sb, "du -sh /tmp/", "Total written to /tmp")

        # Cleanup
        run(sb, "rm -f /tmp/fill_*", "Cleanup")
        run(sb, "df -hT /", "After cleanup")

    finally:
        sb.terminate()
        print("\nSandbox terminated.")


if __name__ == "__main__":
    main()
