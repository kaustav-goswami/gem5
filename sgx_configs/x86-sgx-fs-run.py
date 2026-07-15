# Copyright (c) 2026 The Regents of the University of California
# All rights reserved.
#
# SPDX-License-Identifier: BSD-3-Clause

"""
Full-system SGX boot for x86 using the gem5 standard library.

This script assembles an Intel-SGX-like machine entirely from the "secure"
standard-library components in ``sgx_configs`` and boots an Ubuntu disk image
with a locally-built Linux kernel. The SGX hardware model (PRM/EPC isolation,
EPCM metadata cache, and Asynchronous Enclave Exit) is armed by the
``X86SecureBoard``.

Usage
-----

```
./build/X86/gem5.opt sgx_configs/x86-sgx-fs-run.py
```

Optional arguments::

    --cpu {timing,atomic,o3}   CPU model for the cores (default: timing)
    --cores N                  Number of cores (default: 2)
    --epc-base ADDR            EPC physical base address (default: 0x80000000)
    --epc-size SIZE            EPC size, e.g. 128MiB (default: 128MiB)
    --aex-vector ADDR          AEX trampoline guest PC (default: 0 / untouched)
    --kernel PATH              Override the kernel image path
    --disk PATH                Override the disk image path

After the OS reaches the login prompt, build and run the SGX test program
(see ``sgx_configs/workloads/``) inside the guest to exercise the enclave
lifecycle.
"""

import argparse
import os
import sys

# Make the ``sgx_configs`` package importable regardless of the cwd gem5 is
# launched from. The repo root is the parent of this file's directory.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from gem5.components.processors.cpu_types import CPUTypes
from gem5.resources.resource import (
    DiskImageResource,
    KernelResource,
)
from gem5.simulate.simulator import Simulator

from sgx_configs.boards.x86_secure_board import X86SecureBoard
from sgx_configs.cachehierarchies.secure_cache_hierarchy import (
    SecureCacheHierarchy,
)
from sgx_configs.memory.secure_memory import SecureMemory
from sgx_configs.processors.secure_processor import SecureProcessor

# Full-system resources requested for this machine.
DEFAULT_KERNEL = "/home/kaustavg/kernel/x86/linux-6.9.9/vmlinux"
DEFAULT_DISK = (
    "/home/kaustavg/projects/kg-resources-2/src/shared-memcached/"
    "x86-disk-image-24-04/x86-ubuntu"
)

_CPU_TYPE_MAP = {
    "timing": CPUTypes.TIMING,
    "atomic": CPUTypes.ATOMIC,
    "o3": CPUTypes.O3,
    "minor": CPUTypes.MINOR,
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="SGX-enabled x86 full-system boot."
    )
    parser.add_argument(
        "--cpu",
        choices=list(_CPU_TYPE_MAP.keys()),
        default="timing",
        help="CPU model for the secure processor cores.",
    )
    parser.add_argument(
        "--cores", type=int, default=2, help="Number of cores."
    )
    parser.add_argument(
        "--mem-size", default="3GiB", help="Total DRAM size (max 3GiB)."
    )
    parser.add_argument(
        "--epc-base",
        type=lambda x: int(x, 0),
        default=0x80000000,
        help="EPC physical base address (default 0x80000000).",
    )
    parser.add_argument(
        "--epc-size", default="128MiB", help="EPC size (default 128MiB)."
    )
    parser.add_argument(
        "--aex-vector",
        type=lambda x: int(x, 0),
        default=0,
        help="AEX trampoline guest PC (0 = leave PC untouched).",
    )
    parser.add_argument(
        "--kernel", default=DEFAULT_KERNEL, help="Path to the kernel image."
    )
    parser.add_argument(
        "--disk", default=DEFAULT_DISK, help="Path to the disk image."
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # --- Secure standard-library components ---------------------------------
    memory = SecureMemory(
        size=args.mem_size,
        epc_base=args.epc_base,
        epc_size=args.epc_size,
    )

    processor = SecureProcessor(
        cpu_type=_CPU_TYPE_MAP[args.cpu],
        num_cores=args.cores,
    )

    cache_hierarchy = SecureCacheHierarchy()

    # --- SGX-aware board ----------------------------------------------------
    board = X86SecureBoard(
        clk_freq="3GHz",
        processor=processor,
        memory=memory,
        cache_hierarchy=cache_hierarchy,
        aex_trampoline_vector=args.aex_vector,
    )

    prm_start, prm_end = board.get_epc_range()
    print(
        "[SGX] PRM/EPC armed: "
        f"[{hex(prm_start)}, {hex(prm_end)}) "
        f"({(prm_end - prm_start) >> 20} MiB), "
        f"AEX vector = {hex(args.aex_vector)}"
    )

    # --- Full-system workload (local kernel + Ubuntu disk image) ------------
    board.set_kernel_disk_workload(
        kernel=KernelResource(local_path=args.kernel),
        disk_image=DiskImageResource(
            local_path=args.disk,
            root_partition="1",
        ),
    )

    simulator = Simulator(board=board)

    print(
        "[SGX] Booting Linux... "
        "(serial console in m5out/board.pc.com_1.device)"
    )
    simulator.run()
    print(
        f"[SGX] Exiting @ tick {simulator.get_current_tick()} "
        f"cause: {simulator.get_last_exit_event_cause()}"
    )


if __name__ == "__m5_main__":
    main()
