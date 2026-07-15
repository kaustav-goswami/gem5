# Copyright (c) 2026 The Regents of the University of California
# All rights reserved.
#
# SPDX-License-Identifier: BSD-3-Clause

"""
SGX-aware cache hierarchy for the gem5 standard library.

The SGX EPCM checks and PRM enforcement happen inside each core's MMU/TLB
(``src/arch/x86/tlb.cc``), i.e. *before* a request ever reaches the cache
hierarchy. As a result no cache-level changes are required to model SGX: a
standard private-L1 / shared-L2 hierarchy with table-walker caches already
routes every translated access through the SGX-enabled TLB.

``SecureCacheHierarchy`` is a thin specialisation of the standard library
``PrivateL1SharedL2WalkCacheHierarchy`` with cache sizes chosen to resemble a
small client SGX part. It exists so the secure machine is assembled entirely
from clearly-named "secure" components.
"""

from gem5.components.cachehierarchies.classic.private_l1_shared_l2_walk_cache_hierarchy import (
    PrivateL1SharedL2WalkCacheHierarchy,
)


class SecureCacheHierarchy(PrivateL1SharedL2WalkCacheHierarchy):
    """Private L1 + shared L2 hierarchy used by the SGX secure board.

    :param l1d_size: Size of each per-core L1 data cache.
    :param l1i_size: Size of each per-core L1 instruction cache.
    :param l2_size: Size of the shared L2 cache.
    """

    def __init__(
        self,
        l1d_size: str = "32KiB",
        l1i_size: str = "32KiB",
        l2_size: str = "2MiB",
    ) -> None:
        super().__init__(
            l1d_size=l1d_size,
            l1i_size=l1i_size,
            l2_size=l2_size,
        )
