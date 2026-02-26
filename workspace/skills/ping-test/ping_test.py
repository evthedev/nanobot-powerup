#!/usr/bin/env python3
"""Ping a host 3 times and report latency."""

import subprocess
import re
import sys

host = sys.argv[1] if len(sys.argv) > 1 else "google.com"

result = subprocess.run(
    ["ping", "-c", "3", host],
    capture_output=True,
    text=True
)

print(result.stdout)

if result.returncode != 0:
    print(f"Ping failed: {result.stderr}", file=sys.stderr)
    sys.exit(1)

# Parse latency summary
match = re.search(r"round-trip min/avg/max/stddev = ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+) ms", result.stdout)
if match:
    min_ms, avg_ms, max_ms, stddev_ms = match.groups()
    print(f"\n📡 Ping Summary for {host}:")
    print(f"  Min:    {min_ms} ms")
    print(f"  Avg:    {avg_ms} ms")
    print(f"  Max:    {max_ms} ms")
    print(f"  Stddev: {stddev_ms} ms")
else:
    print(f"\n📡 Ping to {host} completed.")
