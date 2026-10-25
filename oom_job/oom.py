#!/usr/bin/env python3
"""The failing job. Allocates ALLOC_MB under a cgroup limit; logs its own RSS.

Under --memory=128m this is OOM-killed (exit 137, OOMKilled=true) partway through.
Under a raised limit it reaches WORK_COMPLETE. The last log line is the evidence.
"""
import os
import sys
import time

ALLOC_MB = int(os.environ.get("ALLOC_MB", "512"))
CHUNK_MB = 16
SLEEP = float(os.environ.get("SLEEP", "0.2"))


def read(path: str) -> str:
    try:
        with open(path) as fh:
            return fh.read().strip()
    except OSError:
        return "?"


def rss_mb() -> int:
    # statm field 2 is resident pages
    pages = int(read("/proc/self/statm").split()[1])
    return pages * 4096 // (1024 * 1024)


def cgroup_limit() -> str:
    return read("/sys/fs/cgroup/memory.max")


def main() -> int:
    print(
        f"worker start alloc={ALLOC_MB}MiB cgroup_limit={cgroup_limit()}",
        flush=True,
    )
    held = []
    for mb in range(CHUNK_MB, ALLOC_MB + 1, CHUNK_MB):
        held.append(bytearray(CHUNK_MB * 1024 * 1024))
        print(f"rss={rss_mb()}MiB allocated={mb}MiB", flush=True)
        time.sleep(SLEEP)
    print(f"WORK_COMPLETE allocated={ALLOC_MB}MiB", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
