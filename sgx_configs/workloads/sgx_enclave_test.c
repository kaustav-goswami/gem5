/*
 * sgx_enclave_test.c - a tiny workload that mimics the Intel SGX enclave
 * lifecycle against the gem5 SGX model (see readme-sgx.md).
 *
 * It does NOT use any real SGX cryptography (the model doesn't either). It
 * exercises the three modelled hardware primitives:
 *
 *   1. EENTER / EEXIT       -> m5_sgx_enter() / m5_sgx_exit()
 *   2. EPC (PRM) accesses    -> optional /dev/mem mapping of the EPC range
 *   3. AEX (async exit)      -> provoked by letting interrupts fire mid-enclave
 *
 * The m5 pseudo-ops are emitted directly as inline assembly using the gem5
 * "magic instruction" encoding (0x0F 0x04 <func16>), so this file is fully
 * self-contained and does NOT need to be linked against libm5.
 *
 * Build (inside the guest, or cross-compiled):
 *     make
 * Run (inside the booted guest):
 *     sudo ./sgx_enclave_test                 # lifecycle only
 *     sudo ./sgx_enclave_test 0x80000000      # also touch EPC via /dev/mem
 */

#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

/* gem5 x86 m5op encoding: 0F 04 <16-bit func code>. */
#define M5OP_SGX_ENTER 0x72
#define M5OP_SGX_EXIT 0x73

/* EENTER: transition the calling core into enclave mode for `enclave_id`.
 * The argument is passed in %rdi to match the gem5 m5op guest ABI. */
static inline void
m5_sgx_enter(uint64_t enclave_id)
{
    __asm__ __volatile__(".byte 0x0F, 0x04; .word %c[func]"
                         :
                         : "D"(enclave_id), [func] "i"(M5OP_SGX_ENTER)
                         : "memory");
}

/* EEXIT: graceful exit back to non-enclave execution. */
static inline void
m5_sgx_exit(void)
{
    __asm__ __volatile__(".byte 0x0F, 0x04; .word %c[func]"
                         :
                         : [func] "i"(M5OP_SGX_EXIT)
                         : "memory");
}

#define EPC_PAGE_SIZE 4096UL
#define EPC_WINDOW (256UL * 1024UL) /* 256 KiB touched inside the enclave */
#define ENCLAVE_ID 101

/*
 * The "secure" computation. In a real enclave this would run on EPC-backed
 * memory; here `buf` either points at a normal heap buffer or, when EPC mode is
 * enabled, at an mmap of the reserved EPC physical range (which makes the gem5
 * EPCM cold-miss / aliasing checks fire).
 */
static uint64_t
secure_compute(volatile uint8_t *buf, size_t len)
{
    uint64_t acc = 0;

    /* Write pass: dirty every page so EPCM write-permission checks run. */
    for (size_t i = 0; i < len; i++)
        buf[i] = (uint8_t)(i * 31 + 7);

    /* Read/reduce pass: a trivial "encryption-ish" mix. */
    for (size_t i = 0; i < len; i++)
        acc = (acc ^ buf[i]) * 1099511628211ULL + i;

    return acc;
}

static void *
map_epc(uint64_t epc_base, size_t len)
{
    int fd = open("/dev/mem", O_RDWR | O_SYNC);
    if (fd < 0) {
        perror("open(/dev/mem)");
        fprintf(stderr,
                "  -> Falling back to a normal heap buffer. To touch real EPC "
                "physical pages, run as root on a kernel built with "
                "CONFIG_STRICT_DEVMEM=n.\n");
        return NULL;
    }

    void *p = mmap(NULL, len, PROT_READ | PROT_WRITE, MAP_SHARED, fd,
                   (off_t)epc_base);
    close(fd);

    if (p == MAP_FAILED) {
        perror("mmap(/dev/mem @ EPC)");
        return NULL;
    }

    printf("  Mapped EPC: phys 0x%lx -> virt %p (%zu bytes)\n", epc_base, p,
           len);
    return p;
}

int
main(int argc, char **argv)
{
    uint64_t epc_base = 0;
    uint8_t *buf = NULL;
    int epc_mode = 0;
    size_t len = EPC_WINDOW;

    if (argc > 1) {
        epc_base = strtoull(argv[1], NULL, 0);
        epc_mode = 1;
    }

    printf("=== gem5 SGX enclave test ===\n");
    printf("enclave id      : %d\n", ENCLAVE_ID);
    printf("secure window   : %zu bytes (%zu pages)\n", len,
           len / EPC_PAGE_SIZE);

    if (epc_mode) {
        printf("EPC mode        : on, base = 0x%lx\n", epc_base);
        buf = map_epc(epc_base, len);
    } else {
        printf("EPC mode        : off (lifecycle + timing only)\n");
    }

    if (buf == NULL) {
        /* Page-aligned heap buffer so the access pattern still spans pages. */
        if (posix_memalign((void **)&buf, EPC_PAGE_SIZE, len) != 0) {
            perror("posix_memalign");
            return 1;
        }
    }

    struct timespec t0, t1;
    clock_gettime(CLOCK_MONOTONIC, &t0);

    /* ---- Enclave lifecycle ---- */
    printf("\n[EENTER] entering enclave mode...\n");
    m5_sgx_enter(ENCLAVE_ID);

    uint64_t result = secure_compute(buf, len);

    printf("[EEXIT]  leaving enclave mode (digest = 0x%016lx)\n", result);
    m5_sgx_exit();

    clock_gettime(CLOCK_MONOTONIC, &t1);

    double ms = (t1.tv_sec - t0.tv_sec) * 1e3 +
                (t1.tv_nsec - t0.tv_nsec) / 1e6;
    printf("\nenclave run wall-time: %.3f ms\n", ms);

    /*
     * A second, short enclave session. Any timer/IO interrupt that lands while
     * we are inside this enclave will be turned into an AEX by the model
     * (registers scrubbed + ~250-cycle stall). Sleeping briefly makes that
     * likely so the sgxStallCycles / AEX stats get exercised.
     */
    printf("\n[EENTER] second session (provoking AEX via interrupts)...\n");
    m5_sgx_enter(ENCLAVE_ID + 1);
    for (volatile int spin = 0; spin < 1000000; spin++) {
        /* burn cycles in-enclave so an interrupt is likely to hit here */
    }
    m5_sgx_exit();
    printf("[EEXIT]  second session done.\n");

    printf("\nSGX test complete. Check the gem5 stats for:\n");
    printf("  system.cpu*.sgxStallCycles / sgxStallEvents\n");
    printf("  system.cpu*.mmu.{itb,dtb}.sgxEpcmMisses / sgxPrmViolations\n");

    return 0;
}
