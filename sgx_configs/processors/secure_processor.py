# Copyright (c) 2026 The Regents of the University of California
# All rights reserved.
#
# SPDX-License-Identifier: BSD-3-Clause

"""
SGX-aware processor for the gem5 standard library.

The actual SGX micro-architectural model lives in the core/TLB C++ code
(``src/arch/x86/tlb.cc`` for the PRM/EPC + EPCM checks and
``src/arch/x86/isa.cc`` for EENTER/EEXIT/AEX). Every ``BaseCPU`` already carries
the ``stallPipeline`` accounting and the per-core MMU that performs the EPCM
checks, so a "secure" processor does not require a new SimObject - it simply has
to be a normal stdlib processor whose cores carry the SGX-enabled MMU.

``SecureProcessor`` is therefore a thin specialisation of the standard library
``SimpleProcessor`` that fixes the ISA to x86 (SGX is only modelled for x86) and
documents that the cores it produces participate in the enclave model.
"""

from gem5.components.processors.cpu_types import CPUTypes
from gem5.components.processors.simple_processor import SimpleProcessor
from gem5.isas import ISA


class SecureProcessor(SimpleProcessor):
    """An x86 processor whose cores participate in the SGX enclave model.

    :param cpu_type: The CPU model to use for every core. Defaults to the
                     timing simple CPU which is fast enough to boot Linux while
                     still exercising the modelled SGX stall penalties.
    :param num_cores: Number of cores in the processor.
    """

    def __init__(
        self,
        cpu_type: CPUTypes = CPUTypes.TIMING,
        num_cores: int = 2,
    ) -> None:
        if cpu_type == CPUTypes.KVM:
            # KVM executes natively on the host and bypasses the gem5 TLB
            # translation path, so the SGX PRM/EPC/EPCM checks would never
            # fire. Refuse it to avoid silently disabling the security model.
            raise Exception(
                "SecureProcessor cannot use the KVM CPU: the SGX model relies "
                "on gem5's software TLB translation, which KVM bypasses. Use "
                "TIMING, ATOMIC, MINOR or O3 instead."
            )

        super().__init__(
            cpu_type=cpu_type,
            num_cores=num_cores,
            isa=ISA.X86,
        )
        self._cpu_type = cpu_type

    def get_cpu_type(self) -> CPUTypes:
        """Returns the CPU type backing this secure processor."""
        return self._cpu_type
