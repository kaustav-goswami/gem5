# SGX-aware gem5 standard-library configuration package.
#
# This package builds an Intel-SGX-like full-system x86 machine on top of the
# gem5 standard library. It provides "secure" variants of the standard library
# components (board, processor, memory and cache hierarchy) that are wired up to
# the SGX enclave model documented in ``readme-sgx.md`` (PRM/EPC physical-memory
# isolation, the EPCM metadata cache, and Asynchronous Enclave Exit handling).
