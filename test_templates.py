"""Test script for OpenSandbox template system.

Tests the full template lifecycle:
  1. List existing templates
  2. Build a custom template from a Dockerfile
  3. Create a sandbox from that custom template
  4. Verify the custom environment works
  5. Clean up (delete template + kill sandbox)

Measures latency at each step.

Usage:
  python delme/test_templates.py

Env vars (or edit defaults below):
  OPENSANDBOX_API_URL   default: https://app.opensandbox.ai
  OPENSANDBOX_API_KEY   default: (empty, for dev mode)
"""

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sdks", "python"))

from opensandbox import Sandbox
import httpx

API_URL = os.environ.get("OPENSANDBOX_API_URL", "https://app.opensandbox.ai")
API_KEY = os.environ.get("OPENSANDBOX_API_KEY", "")

CUSTOM_TEMPLATE_NAME = "test-custom-tmpl"

# Heavy Dockerfile to stress-test build times (~500MB+ image)
CUSTOM_DOCKERFILE = """\
FROM ubuntu:22.04

# Layer 1: Core build tools + compilers
RUN apt-get update && apt-get install -y --no-install-recommends \\
    build-essential gcc g++ make cmake \\
    curl wget ca-certificates gnupg \\
    jq git unzip zip \\
    && rm -rf /var/lib/apt/lists/*

# Layer 2: Python full + pip packages
RUN apt-get update && apt-get install -y --no-install-recommends \\
    python3 python3-pip python3-dev python3-venv \\
    && rm -rf /var/lib/apt/lists/*
RUN pip3 install --no-cache-dir \\
    numpy pandas scipy scikit-learn \\
    requests flask fastapi uvicorn \\
    pyyaml toml black ruff mypy

# Layer 3: Node.js 20 + npm packages
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \\
    && apt-get install -y nodejs \\
    && rm -rf /var/lib/apt/lists/*
RUN npm install -g typescript ts-node esbuild prettier eslint

# Layer 4: Rust toolchain
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y \\
    && . /root/.cargo/env \\
    && rustup component add clippy rustfmt

# Layer 5: Go 1.22
RUN curl -fsSL https://go.dev/dl/go1.22.5.linux-amd64.tar.gz | tar -C /usr/local -xzf -
ENV PATH="/usr/local/go/bin:/root/.cargo/bin:${PATH}"

# Layer 6: System libraries and tools
RUN apt-get update && apt-get install -y --no-install-recommends \\
    libssl-dev libffi-dev libpq-dev \\
    sqlite3 libsqlite3-dev \\
    redis-tools postgresql-client \\
    htop vim nano less tree \\
    net-tools iputils-ping dnsutils \\
    && rm -rf /var/lib/apt/lists/*

# Layer 7: Generate some bulk data to inflate image size
RUN dd if=/dev/urandom of=/opt/testdata_50mb.bin bs=1M count=50 \\
    && echo '{"ready": true, "stress": "heavy"}' > /opt/marker.json \\
    && python3 -c "import json; json.dump({f'key_{i}': f'value_{i}' for i in range(10000)}, open('/opt/big_config.json','w'))"

# Layer 8: Compile a small Rust binary to exercise the toolchain
RUN . /root/.cargo/env && mkdir -p /tmp/rusttest \\
    && echo 'fn main() { println!("rust works"); }' > /tmp/rusttest/main.rs \\
    && rustc /tmp/rusttest/main.rs -o /opt/rusttest \\
    && rm -rf /tmp/rusttest

# Layer 9: Compile a small Go binary
RUN mkdir -p /tmp/gotest \\
    && echo 'package main; import "fmt"; func main() { fmt.Println("go works") }' > /tmp/gotest/main.go \\
    && cd /tmp/gotest && go build -o /opt/gotest main.go \\
    && rm -rf /tmp/gotest
"""


def timer():
    """Return a callable that returns elapsed seconds since creation."""
    start = time.monotonic()
    return lambda: time.monotonic() - start


def make_client() -> httpx.AsyncClient:
    base = API_URL.rstrip("/")
    api_base = base if base.endswith("/api") else f"{base}/api"
    headers = {}
    if API_KEY:
        headers["X-API-Key"] = API_KEY
    return httpx.AsyncClient(base_url=api_base, headers=headers, timeout=30.0)


async def test_list_templates(client: httpx.AsyncClient):
    """List all available templates and print them."""
    print("\n=== 1. List Templates ===")
    elapsed = timer()

    resp = await client.get("/templates")
    resp.raise_for_status()
    templates = resp.json()

    print(f"  Found {len(templates)} templates ({elapsed():.3f}s)")
    for t in templates:
        # API returns DBTemplate: id, name, tag, imageRef, isPublic
        tid = t.get("id") or t.get("templateID", "?")
        name = t.get("name", "?")
        tag = t.get("tag", "latest")
        public = t.get("isPublic", False)
        image = t.get("imageRef", "")
        print(f"    - {name}:{tag}  (id={tid[:8]}..  public={public}  image={image})")
    return templates


async def test_build_template(client: httpx.AsyncClient):
    """Build a custom template from a Dockerfile."""
    print("\n=== 2. Build Custom Template ===")
    print(f"  Name: {CUSTOM_TEMPLATE_NAME}")
    print(f"  Dockerfile:\n    {CUSTOM_DOCKERFILE.strip().replace(chr(10), chr(10) + '    ')}")

    elapsed = timer()
    try:
        resp = await client.post(
            "/templates",
            json={"name": CUSTOM_TEMPLATE_NAME, "dockerfile": CUSTOM_DOCKERFILE},
            timeout=300.0,
        )
        resp.raise_for_status()
        data = resp.json()
        print(f"  Built successfully ({elapsed():.3f}s)")
        tid = data.get("id") or data.get("templateID", "?")
        print(f"    id={tid}  name={data.get('name')}  tag={data.get('tag')}")
        print(f"    imageRef={data.get('imageRef', 'n/a')}")
        return data
    except asyncio.TimeoutError:
        print(f"  TIMEOUT after {elapsed():.1f}s - build took too long")
        return None
    except httpx.HTTPStatusError as e:
        print(f"  FAILED ({elapsed():.3f}s): {e.response.status_code} {e.response.text[:300]}")
        return None


async def test_create_sandbox_default(template: str = "base"):
    """Create a sandbox from a default template to establish a baseline."""
    print(f"\n=== 3. Create Sandbox (default: {template}) ===")
    elapsed = timer()

    try:
        sb = await Sandbox.create(
            template=template,
            timeout=120,
            api_key=API_KEY,
            api_url=API_URL,
        )
        create_time = elapsed()
        print(f"  Created {sb.sandbox_id} ({create_time:.3f}s)")

        # Quick smoke test
        result = await sb.commands.run("echo ok")
        print(f"  Smoke test: exit={result.exit_code} stdout={result.stdout.strip()}")

        await sb.kill()
        await sb.close()
        print(f"  Killed ({elapsed():.3f}s total)")
        return create_time
    except Exception as e:
        print(f"  FAILED ({elapsed():.3f}s): {e}")
        return None


async def test_create_sandbox_custom():
    """Create a sandbox from the custom template and verify it."""
    print(f"\n=== 4. Create Sandbox (custom: {CUSTOM_TEMPLATE_NAME}) ===")
    elapsed = timer()

    try:
        sb = await Sandbox.create(
            template=CUSTOM_TEMPLATE_NAME,
            timeout=120,
            api_key=API_KEY,
            api_url=API_URL,
        )
        create_time = elapsed()
        print(f"  Created {sb.sandbox_id} ({create_time:.3f}s)")

        # Verify all toolchains from the heavy image
        print("\n  --- Verify custom environment ---")

        checks = [
            ("jq",      "jq --version"),
            ("curl",    "curl --version | head -1"),
            ("gcc",     "gcc --version | head -1"),
            ("python3", "python3 --version"),
            ("node",    "node --version"),
            ("npm",     "npm --version"),
            ("tsc",     "tsc --version"),
            ("rustc",   ". /root/.cargo/env && rustc --version"),
            ("cargo",   ". /root/.cargo/env && cargo --version"),
            ("go",      "go version"),
            ("git",     "git --version"),
            ("sqlite3", "sqlite3 --version | head -1"),
        ]
        for label, cmd in checks:
            result = await sb.commands.run(cmd)
            status = result.stdout.strip() if result.exit_code == 0 else f"MISSING (exit {result.exit_code})"
            print(f"    {label:10s} {status}")

        # Check baked-in artifacts
        print("\n  --- Verify baked-in files ---")
        result = await sb.commands.run("cat /opt/marker.json")
        print(f"    marker.json:  {result.stdout.strip()}")

        result = await sb.commands.run("du -sh /opt/testdata_50mb.bin")
        print(f"    testdata:     {result.stdout.strip()}")

        result = await sb.commands.run("python3 -c \"import json; d=json.load(open('/opt/big_config.json')); print(f'{len(d)} keys')\"")
        print(f"    big_config:   {result.stdout.strip()}")

        result = await sb.commands.run("/opt/rusttest")
        print(f"    rust binary:  {result.stdout.strip()}")

        result = await sb.commands.run("/opt/gotest")
        print(f"    go binary:    {result.stdout.strip()}")

        # Quick pip / npm check
        print("\n  --- Verify pip/npm packages ---")
        result = await sb.commands.run("python3 -c 'import numpy; import pandas; import flask; print(f\"numpy={numpy.__version__} pandas={pandas.__version__} flask={flask.__version__}\")'")
        print(f"    pip pkgs:     {result.stdout.strip()}")

        result = await sb.commands.run("npx esbuild --version")
        print(f"    esbuild:      {result.stdout.strip()}")

        await sb.kill()
        await sb.close()
        print(f"\n  Total (create + verify + kill): {elapsed():.3f}s")
        return create_time
    except Exception as e:
        print(f"  FAILED ({elapsed():.3f}s): {e}")
        return None


async def test_delete_template(client: httpx.AsyncClient):
    """Delete the custom template."""
    print(f"\n=== 5. Delete Custom Template ===")
    elapsed = timer()

    try:
        resp = await client.delete(f"/templates/{CUSTOM_TEMPLATE_NAME}")
        resp.raise_for_status()
        print(f"  Deleted '{CUSTOM_TEMPLATE_NAME}' ({elapsed():.3f}s)")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            print(f"  Already gone (404) ({elapsed():.3f}s)")
        elif e.response.status_code == 204:
            print(f"  Deleted '{CUSTOM_TEMPLATE_NAME}' ({elapsed():.3f}s)")
        else:
            print(f"  FAILED: {e.response.status_code} {e.response.text[:200]}")


async def main():
    print("=" * 60)
    print("OpenSandbox Template Test")
    print("=" * 60)
    print(f"  API URL: {API_URL}")
    print(f"  API Key: {'***' + API_KEY[-8:] if len(API_KEY) > 8 else '(none/dev)'}")

    client = make_client()
    total_elapsed = timer()

    # 1. List existing templates
    await test_list_templates(client)

    # 2. Build custom template (the slow part)
    build_result = await test_build_template(client)

    # 3. Baseline: create sandbox from default template
    default_time = await test_create_sandbox_default("base")

    # 4. Create sandbox from custom template
    custom_time = None
    if build_result:
        custom_time = await test_create_sandbox_custom()
    else:
        print("\n=== 4. SKIPPED (custom template build failed) ===")

    # 5. Cleanup
    await test_delete_template(client)

    # 6. List again to confirm deletion
    await test_list_templates(client)

    await client.aclose()

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  Total time:              {total_elapsed():.3f}s")
    if default_time:
        print(f"  Default sandbox create:  {default_time:.3f}s")
    if custom_time:
        print(f"  Custom sandbox create:   {custom_time:.3f}s")
    if default_time and custom_time:
        delta = custom_time - default_time
        print(f"  Custom overhead:         {delta:+.3f}s")
    print()


if __name__ == "__main__":
    asyncio.run(main())
