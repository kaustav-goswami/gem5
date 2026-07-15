# Copyright (c) 2026 The Regents of the University of California
# All rights reserved.
#
# SPDX-License-Identifier: BSD-3-Clause

"""
``X86SecureBoard`` - an SGX-aware full-system x86 board.

This board extends the standard library :class:`X86Board` and turns on the gem5
Intel-SGX model documented in ``readme-sgx.md``. Concretely it:

1. Programs the ``System`` parameters that arm the SGX hardware model:
   ``prm_start`` / ``prm_end`` (the Processor Reserved Memory range that holds
   the Enclave Page Cache) and ``aex_trampoline_vector`` (the guest PC the core
   jumps to on an Asynchronous Enclave Exit).

2. Reserves the EPC physical range from the guest OS via a ``memmap=`` kernel
   argument. This is essential: once SGX is armed, *any* access to the PRM range
   from outside enclave mode faults, so the Linux kernel must never hand those
   physical pages out as ordinary memory.

The board is otherwise a normal x86 FS board and boots an unmodified Linux
kernel + disk image.
"""

from typing import List

from m5.util import (
    fatal,
    warn,
)

from gem5.components.boards.kernel_disk_workload import KernelDiskWorkload
from gem5.components.boards.x86_board import X86Board
from gem5.components.cachehierarchies.abstract_cache_hierarchy import (
    AbstractCacheHierarchy,
)
from gem5.components.memory.abstract_memory_system import AbstractMemorySystem
from gem5.components.processors.abstract_processor import AbstractProcessor
from gem5.utils.override import overrides


class X86SecureBoard(X86Board):
    """A full-system x86 board with the SGX enclave model enabled.

    :param clk_freq: System clock frequency (e.g. ``"3GHz"``).
    :param processor: The (secure) processor to use.
    :param memory: The (secure) memory system. If it exposes
                   ``get_epc_range()`` the EPC geometry is taken from it.
    :param cache_hierarchy: The (secure) cache hierarchy.
    :param prm_start: Override for the PRM/EPC base physical address. If left at
                      ``None`` the value is taken from ``memory.get_epc_range()``.
    :param prm_end: Override for the (exclusive) PRM/EPC end physical address.
    :param aex_trampoline_vector: Guest PC to redirect to on an Asynchronous
                                  Enclave Exit. ``0`` leaves the PC untouched.
    :param reserve_epc_from_os: When ``True`` (default) a ``memmap=`` kernel arg
                                is appended so Linux does not allocate the EPC.
    """

    def __init__(
        self,
        clk_freq: str,
        processor: AbstractProcessor,
        memory: AbstractMemorySystem,
        cache_hierarchy: AbstractCacheHierarchy,
        prm_start: int = None,
        prm_end: int = None,
        aex_trampoline_vector: int = 0,
        reserve_epc_from_os: bool = True,
    ) -> None:
        super().__init__(
            clk_freq=clk_freq,
            processor=processor,
            memory=memory,
            cache_hierarchy=cache_hierarchy,
        )

        # Resolve the EPC geometry: explicit overrides win, otherwise ask the
        # memory system where it placed the EPC.
        if prm_start is None or prm_end is None:
            if hasattr(memory, "get_epc_range"):
                mem_start, mem_end = memory.get_epc_range()
                prm_start = mem_start if prm_start is None else prm_start
                prm_end = mem_end if prm_end is None else prm_end
            else:
                fatal(
                    "X86SecureBoard could not determine the EPC range. Either "
                    "pass prm_start/prm_end explicitly or use a memory system "
                    "that implements get_epc_range() (e.g. SecureMemory)."
                )

        if prm_end <= prm_start:
            fatal(
                f"Invalid EPC range: prm_end ({hex(prm_end)}) must be greater "
                f"than prm_start ({hex(prm_start)})."
            )

        self._prm_start = prm_start
        self._prm_end = prm_end
        self._aex_trampoline_vector = aex_trampoline_vector
        self._reserve_epc_from_os = reserve_epc_from_os

        # These are parameters on the base ``System`` SimObject (added by the
        # SGX fork). The board *is* a System, so we set them directly. Once
        # ``prm_end > prm_start`` the C++ TLB starts enforcing PRM/EPC/EPCM.
        self.prm_start = prm_start
        self.prm_end = prm_end
        self.aex_trampoline_vector = aex_trampoline_vector

    def get_epc_range(self):
        """Returns the armed ``(prm_start, prm_end)`` EPC range."""
        return (self._prm_start, self._prm_end)

    @overrides(KernelDiskWorkload)
    def get_default_kernel_args(self) -> List[str]:
        args = super().get_default_kernel_args()

        if self._reserve_epc_from_os:
            # ``memmap=<size>$<base>`` marks the region as reserved ("type 2"),
            # so the Linux kernel will not allocate EPC pages as normal memory.
            # Using this avoids spurious PRM-violation faults during boot.
            epc_size = self._prm_end - self._prm_start
            args.append(f"memmap=0x{epc_size:x}$0x{self._prm_start:x}")

        return args
