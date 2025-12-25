#!/usr/bin/env python3
"""
Run all tenants simultaneously for testing.

This script starts a separate server process for each tenant defined
in tenants.json. Useful for testing multi-tenant isolation.

Usage:
    python run_all_tenants.py
    python run_all_tenants.py --reload  # For development

Press Ctrl+C to stop all servers.
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def load_config(config_path: str = "tenants.json") -> dict:
    """Load tenant configuration."""
    with open(config_path, "r") as f:
        return json.load(f)


def run_all_tenants(config_path: str = "tenants.json", reload: bool = False):
    """Run all tenants in separate processes."""
    config = load_config(config_path)
    tenants = config.get("tenants", {})

    if not tenants:
        print("No tenants configured.")
        return

    processes = []
    python_exe = sys.executable

    print("\n" + "=" * 60)
    print("Starting all tenants...")
    print("=" * 60)

    for slug, tenant in tenants.items():
        port = tenant.get("port", 8006)
        name = tenant.get("name", slug)

        print(f"\nStarting: {name} ({slug}) on port {port}")

        cmd = [python_exe, "run_tenant.py", slug]
        if reload:
            cmd.append("--reload")

        # Start process
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        processes.append((slug, port, proc))

    print("\n" + "=" * 60)
    print("All tenants started!")
    print("=" * 60)

    for slug, port, _ in processes:
        print(f"  {slug}: http://localhost:{port}")

    print("\nPress Ctrl+C to stop all servers...")
    print("=" * 60 + "\n")

    def signal_handler(signum, frame):
        print("\n\nStopping all tenants...")
        for slug, port, proc in processes:
            print(f"  Stopping {slug}...")
            proc.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Wait for processes and print their output
    try:
        while True:
            for slug, port, proc in processes:
                # Check if process has output
                if proc.poll() is not None:
                    # Process has ended
                    output = proc.stdout.read()
                    if output:
                        print(f"[{slug}] {output}")
                    print(f"[{slug}] Process ended with code {proc.returncode}")
            time.sleep(0.5)
    except KeyboardInterrupt:
        signal_handler(None, None)


def main():
    parser = argparse.ArgumentParser(
        description="Run all tenants simultaneously"
    )
    parser.add_argument(
        "--config",
        "-c",
        default="tenants.json",
        help="Path to tenant configuration file",
    )
    parser.add_argument(
        "--reload",
        "-r",
        action="store_true",
        help="Enable auto-reload for development",
    )

    args = parser.parse_args()
    run_all_tenants(args.config, args.reload)


if __name__ == "__main__":
    main()
