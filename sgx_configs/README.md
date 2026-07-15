# `sgx_configs` — an SGX-aware machine built on the gem5 standard library

This directory contains a full-system x86 machine, assembled entirely from
gem5 standard-library components, that turns on the Intel-SGX model described in
[`../readme-sgx.md`](../readme-sgx.md). It boots an unmodified Ubuntu disk image
with a locally-built Linux kernel and exposes the enclave lifecycle to a guest
workload via the `m5_sgx_*` pseudo-instructions.

> The SGX model itself (PRM/EPC isolation, the EPCM metadata cache, and
> Asynchronous Enclave Exit) already lives in the gem5 C++ tree. **No gem5
> rebuild is required** to use these configs — they only *configure* and
> *exercise* that model.

## Layout

```
sgx_configs/
├── boards/
│   └── x86_secure_board.py        # X86SecureBoard  (arms PRM/EPC + reserves EPC from the OS)
├── cachehierarchies/
│   └── secure_cache_hierarchy.py  # SecureCacheHierarchy (private L1 + shared L2 + walk caches)
├── memory/
│   └── secure_memory.py           # SecureMemory (DDR4 + EPC geometry / get_epc_range())
├── processors/
│   └── secure_processor.py        # SecureProcessor (x86 cores carrying the SGX TLB)
├── workloads/
│   ├── sgx_enclave_test.c         # SGX-mimicking guest test program
│   └── Makefile
└── x86-sgx-fs-run.py              # full-system boot script
```

### How the pieces map to SGX

| SGX concept | Component | What it does here |
|---|---|---|
| PRM / EPC DRAM carve-out | `SecureMemory` | Places the EPC inside DRAM and reports `get_epc_range()` |
| Arming the hardware | `X86SecureBoard` | Sets `System.prm_start/prm_end/aex_trampoline_vector` |
| Keeping the OS out of the EPC | `X86SecureBoard` | Adds a `memmap=` kernel arg reserving the EPC range |
| EPCM checks / PRM faults | per-core MMU/TLB | Already in `src/arch/x86/tlb.cc`, carried by every core |
| EENTER / EEXIT / AEX | `m5_sgx_enter/exit` + CPU | Driven by `sgx_enclave_test.c` |

## Running

From the gem5 repo root:

```bash
./build/X86/gem5.opt sgx_configs/x86-sgx-fs-run.py
```

Useful options:

```bash
./build/X86/gem5.opt sgx_configs/x86-sgx-fs-run.py \
    --cpu timing \           # timing | atomic | o3 | minor
    --cores 2 \
    --epc-base 0x80000000 \  # EPC physical base
    --epc-size 128MiB \      # EPC size
    --aex-vector 0           # guest PC to jump to on AEX (0 = leave untouched)
```

Defaults boot:

* **kernel:** `/home/kaustavg/kernel/x86/linux-6.9.9/vmlinux`
* **disk:** `/home/kaustavg/projects/kg-resources-2/src/shared-memcached/x86-disk-image-24-04/x86-ubuntu`

The serial console is written to `m5out/board.pc.com_1.device`. On start-up the
script prints the armed EPC range, e.g.:

```
[SGX] PRM/EPC armed: [0x80000000, 0x88000000) (128 MiB), AEX vector = 0x0
[SGX] Booting Linux...
```

## The test workload

`workloads/sgx_enclave_test.c` mimics the SGX enclave constructs. It emits the
gem5 `m5_sgx_enter` / `m5_sgx_exit` pseudo-ops directly as inline assembly
(encoding `0F 04 <func16>`), so it is self-contained and does **not** need to be
linked against `libm5`.

It performs two enclave sessions:

1. **EENTER → secure compute → EEXIT** over a 256 KiB window.
2. A second enclave session that spins so a timer/IO interrupt is likely to
   land mid-enclave, provoking an **AEX** (register scrub + modelled stall).

Optionally pass the EPC base address to make the secure computation touch the
real EPC physical pages (via `/dev/mem`), which exercises the EPCM
cold-miss / aliasing path:

```bash
# inside the booted guest
make                          # builds a static binary
sudo ./sgx_enclave_test                 # lifecycle + timing only
sudo ./sgx_enclave_test 0x80000000      # also touch EPC via /dev/mem
```

> Touching real EPC pages via `/dev/mem` requires root and a guest kernel built
> with `CONFIG_STRICT_DEVMEM=n`. Without it, the program transparently falls
> back to a page-aligned heap buffer and still exercises the enclave lifecycle.

### Getting the binary into the guest

The disk image is large and already provisioned, so the simplest options are:

* build `sgx_enclave_test` on the host (`make` in `workloads/`) and copy it into
  the disk image / a shared folder, or
* build it inside the guest after boot (the `.c` file is self-contained).

## Inspecting the results

After a run, the SGX statistics appear in `m5out/stats.txt`:

```
system.cpu*.sgxStallCycles          # modelled AEX + EEXIT + EPCM-miss stalls
system.cpu*.sgxStallEvents
system.cpu*.mmu.itb.sgxEpcmMisses   # EPC cold-miss events
system.cpu*.mmu.dtb.sgxEpcmMisses
system.cpu*.mmu.dtb.sgxPrmViolations
system.cpu*.mmu.dtb.sgxEpcmAliasFaults
```
