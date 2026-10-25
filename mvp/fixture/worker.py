import os
import time

target_mib = int(os.environ.get("TARGET_MIB", "192"))
blocks = []
while len(blocks) * 8 < target_mib:
    block = bytearray(8 * 1024 * 1024)
    for offset in range(0, len(block), 4096):
        block[offset] = 1
    blocks.append(block)
    print(f"allocated_mib={len(blocks) * 8}", flush=True)
    time.sleep(0.1)
print("RESULT: completed memory workload", flush=True)

