# Intel SGX Enclave Modeling in gem5

This document describes the changes that add a cycle-accurate **Intel SGX**
enclave model to gem5. The goal is to capture the microarchitectural timings
and execution bottlenecks of SGX (memory isolation, EPCM checks, enclave
transition penalties) for computer-architecture evaluation **without**
implementing any of the SGX cryptography.

The model implements three hardware primitives plus a software trigger
interface:

1. **PRM / EPC physical-memory boundary enforcement**
2. **The EPCM (Enclave Page Cache Map) metadata cache + miss/aliasing modeling**
3. **Asynchronous Enclave Exit (AEX) register scrubbing + pipeline stalls**
4. **`m5` pseudo-instructions** to drive the enclave lifecycle from a workload

> **Status:** All changes are source-only and lint-clean. They have **not**
> been compiled. Run a `scons` build to validate.

---

## Table of contents

- [Quick start](#quick-start)
- [Concept → implementation mapping](#concept--implementation-mapping)
- [New public APIs](#new-public-apis)
  - [Python configuration parameters](#python-configuration-parameters)
  - [C++ `System` accessors](#c-system-accessors)
  - [C++ `BaseISA` hooks](#c-baseisa-hooks)
  - [C++ `BaseCPU` method](#c-basecpu-method)
  - [Architectural MISCREGs](#architectural-miscregs)
  - [`m5ops` / pseudo-instructions](#m5ops--pseudo-instructions)
- [Statistics added](#statistics-added)
- [File-by-file change list](#file-by-file-change-list)
- [Runtime behavior](#runtime-behavior)
- [Deviations from the original plan](#deviations-from-the-original-plan)
- [Example workload](#example-workload)

---

## Quick start

1. **Enable SGX in your config** by setting the PRM/EPC physical range on the
   `System` object (defaults are `0`, i.e. disabled):

   ```python
   system.prm_start = 0x80000000
   system.prm_end   = 0x8C000000
   system.aex_trampoline_vector = 0  # optional: guest PC to jump to on AEX
   ```

2. **Annotate your workload** with the enclave lifecycle ops:

   ```c
   #include <gem5/m5ops.h>

   m5_sgx_enter(101);   // enter enclave mode, enclave id = 101
   /* ... secure computation ... */
   m5_sgx_exit();       // graceful EEXIT
   ```

3. **Run** as normal. SGX overhead shows up in the new stats
   (`sgxStallCycles`, `tlb.sgxEpcmMisses`, etc.).

If `prm_end <= prm_start` (the default), all SGX enforcement is bypassed and
there is zero change to baseline behavior.

---

## Concept → implementation mapping

| SGX primitive | Where it lives | What it does |
|---|---|---|
| PRM/EPC boundary | `X86ISA::TLB::sgxAccessCheck` (`src/arch/x86/tlb.cc`) | Faults on any access to the PRM range from outside enclave mode |
| EPCM metadata cache | `epcm_table` + `sgxAccessCheck` (`src/arch/x86/tlb.{hh,cc}`) | Models cold-miss DRAM penalty; detects VA remapping/aliasing |
| AEX (interrupt in enclave) | `ISA::handleEnclaveAsyncExit` (`src/arch/x86/isa.cc`) | Leaves enclave mode, scrubs registers, stalls, redirects PC |
| EENTER / EEXIT | `ISA::enclaveEnter` / `ISA::enclaveExit` (`src/arch/x86/isa.cc`) | Sets enclave MISCREGs, flushes TLBs, charges transition penalty |
| Software trigger | `m5_sgx_enter` / `m5_sgx_exit` pseudo-ops | Lets the workload signal lifecycle transitions |
| Latency accounting | `BaseCPU::stallPipeline` (`src/cpu/base.cc`) | Records modeled stall cycles into stats |

---

## New public APIs

### Python configuration parameters

Added to the base `System` SimObject (`src/sim/System.py`). All default to `0`.

| Param | Type | Default | Meaning |
|---|---|---|---|
| `prm_start` | `Addr` | `0` | Start of the Processor Reserved Memory (PRM) physical range |
| `prm_end` | `Addr` | `0` | End (exclusive) of the PRM range |
| `aex_trampoline_vector` | `Addr` | `0` | Guest PC the core jumps to on AEX (`0` = leave PC untouched) |

SGX enforcement is **enabled** only when `prm_end > prm_start`.

### C++ `System` accessors

Declared in `src/sim/system.hh`:

```cpp
Addr prmStart() const;
Addr prmEnd() const;
Addr aexTrampolineVector() const;
bool sgxEnabled() const;              // true iff prm_end > prm_start
bool isPrmAddr(Addr paddr) const;     // paddr in [prm_start, prm_end)
```

### C++ `BaseISA` hooks

ISA-agnostic virtual hooks (default no-op) declared in
`src/arch/generic/isa.hh`, overridden by `X86ISA::ISA`:

```cpp
// Called by the CPU just before delivering an interrupt/exception.
// If in enclave mode, performs an AEX. Returns true if an AEX occurred.
virtual bool handleEnclaveAsyncExit(ThreadContext *tc);

// Enter enclave mode for `enclave_id` (EENTER).
virtual void enclaveEnter(ThreadContext *tc, uint64_t enclave_id);

// Graceful exit from enclave mode (EEXIT).
virtual void enclaveExit(ThreadContext *tc);
```

The x86 implementations live in `src/arch/x86/isa.cc`.

### C++ `BaseCPU` method

Declared in `src/cpu/base.hh`, defined in `src/cpu/base.cc`:

```cpp
// Account a modeled pipeline stall of `cycles` cycles.
// Increments baseStats.sgxStallEvents and baseStats.sgxStallCycles.
void stallPipeline(Cycles cycles);
```

### Architectural MISCREGs

Added to the `misc_reg` enum in `src/arch/x86/regs/misc.hh` (before `NumRegs`):

| Reg | Meaning |
|---|---|
| `misc_reg::InEnclave` | Non-zero while the core executes in enclave mode |
| `misc_reg::ActiveEid` | Id of the currently executing enclave |

Access them via the standard `ThreadContext` interface:

```cpp
bool in = tc->readMiscRegNoEffect(misc_reg::InEnclave);
uint64_t eid = tc->readMiscRegNoEffect(misc_reg::ActiveEid);
tc->setMiscRegNoEffect(misc_reg::InEnclave, 1);
```

These are stored and checkpointed automatically by the x86 ISA's `regVal[]`
array (no serialization changes required).

### `m5ops` / pseudo-instructions

New opcodes in `include/gem5/asm/generic/m5ops.h`:

| Macro | Value |
|---|---|
| `M5OP_SGX_ENTER` | `0x72` |
| `M5OP_SGX_EXIT`  | `0x73` |

Guest-facing functions declared in `include/gem5/m5ops.h`:

```c
void m5_sgx_enter(uint64_t enclave_id);
void m5_sgx_exit(void);
```

Simulator-side handlers declared in `src/sim/pseudo_inst.hh`, implemented in
`src/sim/pseudo_inst.cc`:

```cpp
void m5SgxEnter(ThreadContext *tc, uint64_t enclave_id); // -> isa->enclaveEnter
void m5SgxExit(ThreadContext *tc);                       // -> isa->enclaveExit
```

The `M5OP_FOREACH` X-macro entries are added, which automatically generate:
- the x86 assembly stubs (`util/m5/src/abi/x86/m5op.S`), and
- the `util/m5` `DispatchTable` fields.

No manual edits to `util/m5` were needed.

---

## Statistics added

Per-TLB (`X86ISA::TLB`, e.g. `system.cpu.mmu.itb` / `dtb`):

| Stat | Meaning |
|---|---|
| `sgxPrmViolations` | Accesses to the PRM/EPC range from outside enclave mode |
| `sgxEpcmMisses` | EPCM metadata cache misses (cold EPC page references) |
| `sgxEpcmAliasFaults` | EPCM virtual-address remapping/aliasing faults |

Per-CPU (`BaseCPU::baseStats`):

| Stat | Meaning |
|---|---|
| `sgxStallCycles` | Cumulative modeled stall cycles (AEX + EEXIT + EPCM misses) |
| `sgxStallEvents` | Number of modeled stall events |

---

## File-by-file change list

### Memory / isolation
- **`src/arch/x86/regs/misc.hh`** — added `InEnclave`, `ActiveEid` MISCREGs.
- **`src/sim/System.py`** — added `prm_start`, `prm_end`,
  `aex_trampoline_vector` params.
- **`src/sim/system.hh`** — added `_prmStart`, `_prmEnd`,
  `_aexTrampolineVector` members and the `prmStart()`/`prmEnd()`/
  `aexTrampolineVector()`/`sgxEnabled()`/`isPrmAddr()` accessors.
- **`src/sim/system.cc`** — initialize the new members from params in the
  `System` constructor.

### EPCM + TLB checks
- **`src/arch/x86/tlb.hh`** — added the `EpcmEntry` struct, the
  `epcm_table` map, the `sgxAccessCheck()` declaration, and the three
  `sgx*` stat fields.
- **`src/arch/x86/tlb.cc`** — implemented `sgxAccessCheck()` (PRM boundary
  fault, EPCM cold-miss penalty via `stallPipeline`, aliasing/owner fault),
  registered the stats, and called `sgxAccessCheck()` from `TLB::translate`
  just before `finalizePhysical`. Added includes: `cpu/base.hh`,
  `sim/core.hh`, `sim/system.hh`.

### AEX + enclave lifecycle
- **`src/arch/generic/isa.hh`** — added the `handleEnclaveAsyncExit`,
  `enclaveEnter`, `enclaveExit` virtual hooks (default no-ops).
- **`src/arch/x86/isa.hh`** — declared the x86 overrides.
- **`src/arch/x86/isa.cc`** — implemented them: AEX (clear `InEnclave`, scrub
  GPRs + condition codes except `RSP`/`RBP`, `stallPipeline(Cycles(250))`,
  redirect to `aexTrampolineVector()`); EENTER (set MISCREGs, `flushAll()`);
  EEXIT (clear `InEnclave`, `stallPipeline(Cycles(120))`). Added
  `sim/system.hh` include.
- **`src/cpu/simple/base.cc`** — call `handleEnclaveAsyncExit(tc)` in
  `checkForInterrupts()` before delivering the interrupt.
- **`src/cpu/o3/cpu.cc`** — call `handleEnclaveAsyncExit()` in
  `processInterrupts()` before `trap()`.

### Latency accounting
- **`src/cpu/base.hh`** — declared `stallPipeline(Cycles)` and added the
  `sgxStallCycles` / `sgxStallEvents` stat fields.
- **`src/cpu/base.cc`** — defined `stallPipeline()` and registered the stats.

### Thread-context tracking (debug mirrors)
- **`src/cpu/simple/exec_context.hh`** — added `in_enclave_mode` /
  `active_enclave_id`.
- **`src/cpu/o3/thread_state.hh`** — added `in_enclave_mode` /
  `active_enclave_id`.

### Pseudo-instruction interface
- **`include/gem5/asm/generic/m5ops.h`** — `M5OP_SGX_ENTER`,
  `M5OP_SGX_EXIT`, and `M5OP_FOREACH` entries.
- **`include/gem5/m5ops.h`** — `m5_sgx_enter`, `m5_sgx_exit` declarations.
- **`src/sim/pseudo_inst.hh`** — `m5SgxEnter`/`m5SgxExit` declarations and
  `switch` cases in `pseudoInstWork`.
- **`src/sim/pseudo_inst.cc`** — `m5SgxEnter`/`m5SgxExit` implementations
  (delegate to the ISA hooks).

---

## Runtime behavior

### PRM / EPC enforcement
On every translation, once a physical address is resolved,
`TLB::sgxAccessCheck` runs. If the paddr is in the PRM range:
- **Not in enclave mode** → `PageFault` (`sgxPrmViolations++`). This is the
  host OS / other process being denied direct access to secure memory.
- **In enclave mode** → proceed to EPCM checks.

### EPCM checks
Keyed by EPC page number (`paddr >> 12`):
- **Cold miss** (no valid entry) → charge a modeled ~65 ns DRAM penalty via
  `cpu->stallPipeline(...)`, bind the page to the current enclave id and
  page-aligned VA, mark it valid (`sgxEpcmMisses++`).
- **Hit, VA or owner mismatch** → `PageFault` (`sgxEpcmAliasFaults++`). This
  detects host/hypervisor page-remapping (aliasing) attacks.
- **Hit, write to a non-writeable page** → `PageFault`.

### AEX (interrupt while in enclave)
When the CPU is about to deliver an interrupt/exception and the thread is in
enclave mode:
1. `InEnclave` is cleared.
2. GPRs (except `RSP`/`RBP`) and condition-code regs are scrubbed to `0`.
3. `stallPipeline(Cycles(250))` models the flush + scrub cost.
4. If `aex_trampoline_vector != 0`, the PC is redirected there.

> `RSP`/`RBP` are intentionally **not** scrubbed: SGX restores them to host
> values on exit, and clobbering them would break resumption of the
> interrupted context.

### EENTER / EEXIT (pseudo-ops)
- `m5_sgx_enter(id)` → `InEnclave = 1`, `ActiveEid = id`, `mmu->flushAll()`.
- `m5_sgx_exit()` → `InEnclave = 0`, `stallPipeline(Cycles(120))`.

---

## Deviations from the original plan

These were necessary to match the real gem5 APIs in this tree:

- **No `src/arch/x86/mmu.cc`** exists; x86 translation lives in `tlb.cc`, so
  the PRM check was folded into `TLB::translate`.
- **MISCREGs** use the `misc_reg::` enum, not legacy `MISCREG_*` macros.
- **ISA-agnostic hooks** (`handleEnclaveAsyncExit`, `enclaveEnter/Exit`) were
  added instead of putting x86-specific MISCREG logic directly into the
  generic CPU loops / `pseudo_inst.cc`. This keeps other ISAs compiling.
- **`EpcmMissFault` / `PageFaultException`** (which don't exist) were replaced
  with the real `X86ISA::PageFault` class plus a modeled `stallPipeline`
  penalty.
- **`tc->getITBPtr()/getDTBPtr()`** (don't exist) replaced with
  `tc->getMMUPtr()->flushAll()`.
- **`cpu->stallPipeline(...)`** was added to `BaseCPU` (the plan assumed it
  exists). It records modeled overhead into stats rather than inserting a
  literal timing bubble.
- **`i8259.cc` was not edited** — interrupt detection already funnels through
  the CPU interrupt loops, which is where the AEX hook now lives.
- **AEX register scrubbing** skips `RSP`/`RBP` (see above).

---

## Example workload

```c
#include <gem5/m5ops.h>

void run_secure_workload(void)
{
    /* set up shared buffers in the EPC-backed region ... */

    m5_sgx_enter(101);          /* core -> enclave mode (id 101)         */
    compute_collaborative_matrix();  /* EPC accesses now pass EPCM checks */
    m5_sgx_exit();              /* graceful EEXIT (+120-cycle penalty)   */
}
```

Build the workload against the gem5 `m5` library (`libm5`) so the
`m5_sgx_*` stubs resolve, and run it on an x86 system whose `prm_start` /
`prm_end` cover the physical pages backing the secure buffers.
