# Copyright (c) 2026 The Regents of the University of California
# All rights reserved.
#
# SPDX-License-Identifier: BSD-3-Clause

"""
SGX-aware memory system for the gem5 standard library.

In real Intel SGX hardware a contiguous slice of DRAM - the Processor Reserved
Memory (PRM) - is carved out and the Enclave Page Cache (EPC) lives inside it.
The PRM is normal DRAM electrically; what makes it "secure" is that the
memory-controller / core only allows accesses to it while a core executes in
enclave mode (this is exactly what the gem5 SGX model enforces in the TLB via
``System::isPrmAddr`` + the EPCM checks).

Because the PRM is backed by the same DRAM as the rest of the system, the
``SecureMemory`` here is a regular channeled DDR4 memory that *additionally*
records where the EPC should be placed. The board reads :meth:`get_epc_range`
to program the ``prm_start`` / ``prm_end`` ``System`` parameters and to reserve
the region from the guest OS, keeping the EPC geometry in a single place.
"""

from typing import (
    Optional,
    Tuple,
)

from m5.util.convert import toMemorySize

from gem5.components.memory.dram_interfaces.ddr4 import DDR4_2400_8x8
from gem5.components.memory.memory import ChanneledMemory

# Default EPC geometry. 0x80000000 == 2GiB; a 128MiB EPC mirrors the largest
# EPC commonly exposed by client SGX parts. Both values sit comfortably inside a
# 3GiB DRAM and below the 0xC0000000 I/O hole used by the x86 board.
DEFAULT_EPC_BASE = 0x80000000
DEFAULT_EPC_SIZE = "128MiB"


class SecureMemory(ChanneledMemory):
    """A dual-channel DDR4 memory that reserves an EPC region for SGX.

    :param size: Total DRAM size. Must be large enough to contain the EPC and
                 stay within the x86 board's 3GiB limit.
    :param epc_base: Physical base address of the Enclave Page Cache.
    :param epc_size: Size of the Enclave Page Cache (e.g. ``"128MiB"``).
    """

    def __init__(
        self,
        size: str = "3GiB",
        epc_base: int = DEFAULT_EPC_BASE,
        epc_size: str = DEFAULT_EPC_SIZE,
    ) -> None:
        super().__init__(
            dram_interface_class=DDR4_2400_8x8,
            num_channels=2,
            interleaving_size=64,
            size=size,
        )

        self._epc_base = epc_base
        self._epc_size = toMemorySize(epc_size)

        epc_end = self._epc_base + self._epc_size
        if epc_end > toMemorySize(size):
            raise Exception(
                f"The EPC range [{hex(self._epc_base)}, {hex(epc_end)}) does "
                f"not fit inside the {size} of DRAM. Lower the EPC base/size "
                "or grow the memory."
            )

    def get_epc_range(self) -> Tuple[int, int]:
        """Returns the ``(prm_start, prm_end)`` physical range for the EPC.

        ``prm_end`` is exclusive, matching the convention used by the C++ SGX
        model (``System::isPrmAddr`` tests ``[prm_start, prm_end)``).
        """
        return (self._epc_base, self._epc_base + self._epc_size)

    def get_epc_size(self) -> int:
        """Returns the EPC size in bytes."""
        return self._epc_size
