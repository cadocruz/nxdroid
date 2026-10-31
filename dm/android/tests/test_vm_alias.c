#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <unistd.h>

#ifndef MFD_CLOEXEC
#define MFD_CLOEXEC 0x0001U
#endif

#ifndef __NR_memfd_create
#if defined(__aarch64__)
#define __NR_memfd_create 279
#elif defined(__x86_64__)
#define __NR_memfd_create 319
#elif defined(SYS_memfd_create)
#define __NR_memfd_create SYS_memfd_create
#endif
#endif

static inline int dm_memfd_create(const char *name, unsigned int flags) {
#if defined(__NR_memfd_create)
    return (int)syscall(__NR_memfd_create, name, flags);
#elif defined(SYS_memfd_create)
    return (int)syscall(SYS_memfd_create, name, flags);
#else
    return memfd_create(name, flags);
#endif
}

static int g_as_fd = -1;
static uint8_t *g_as_base = NULL;
static size_t g_as_size = 0;

void *dm_guest_as_reserve(size_t reserve) {
    if (g_as_fd >= 0) {
        errno = EBUSY;
        return NULL;
    }
    int fd = dm_memfd_create("guest_as", MFD_CLOEXEC);
    if (fd < 0) return NULL;
    if (ftruncate(fd, (off_t)reserve) != 0) {
        close(fd);
        return NULL;
    }
    void *p = mmap(NULL, reserve, PROT_NONE, MAP_SHARED, fd, 0);
    if (p == MAP_FAILED) {
        close(fd);
        return NULL;
    }
    g_as_fd = fd;
    g_as_base = (uint8_t *)p;
    g_as_size = reserve;
    return p;
}

void dm_guest_as_release(void *as, size_t reserve) {
    if (as) munmap(as, reserve);
    if (g_as_fd >= 0) {
        close(g_as_fd);
        g_as_fd = -1;
    }
    g_as_base = NULL;
    g_as_size = 0;
}

void *dm_vm_alias(void *to, const void *from, size_t size) {
    if (g_as_fd < 0 || !g_as_base) {
        errno = ENOTSUP;
        return NULL;
    }
    uintptr_t f = (uintptr_t)from;
    uintptr_t b = (uintptr_t)g_as_base;
    if (f < b || f + size > b + g_as_size || f + size < f) {
        errno = EINVAL;
        return NULL;
    }
    off_t off = (off_t)(f - b);
    int flags = MAP_SHARED | (to ? MAP_FIXED : 0);
    void *p = mmap(to, size, PROT_READ | PROT_WRITE, flags, g_as_fd, off);
    if (p == MAP_FAILED) return NULL;
    return p;
}

int main(void) {
    const size_t AS_SIZE = 0x4000000; // 64 MiB
    const size_t PAGE_SIZE = 4096;

    // 1. Initial reservation
    void *as = dm_guest_as_reserve(AS_SIZE);
    assert(as != NULL);
    assert(((uintptr_t)as & (PAGE_SIZE - 1)) == 0);

    // Double reservation must fail with EBUSY
    void *as_dup = dm_guest_as_reserve(AS_SIZE);
    assert(as_dup == NULL);
    assert(errno == EBUSY);

    // 2. mprotect guest page to PROT_READ | PROT_WRITE
    uint8_t *guest_page = (uint8_t *)as + 0x10000;
    int rc = mprotect(guest_page, PAGE_SIZE, PROT_READ | PROT_WRITE);
    assert(rc == 0);

    // Write initial test value
    uint32_t *orig_ptr = (uint32_t *)guest_page;
    *orig_ptr = 0xdeadbeef;
    assert(*orig_ptr == 0xdeadbeef);

    // 3. Dynamic alias (to == NULL)
    void *alias1 = dm_vm_alias(NULL, guest_page, PAGE_SIZE);
    assert(alias1 != NULL);
    assert(alias1 != guest_page);
    uint32_t *alias1_ptr = (uint32_t *)alias1;
    assert(*alias1_ptr == 0xdeadbeef);

    // Write coherence: modify via alias1, check original
    *alias1_ptr = 0xcafebabe;
    assert(*orig_ptr == 0xcafebabe);

    // 4. Fixed alias (to != NULL)
    void *fixed_res = mmap(NULL, PAGE_SIZE, PROT_NONE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    assert(fixed_res != MAP_FAILED);

    void *alias2 = dm_vm_alias(fixed_res, guest_page, PAGE_SIZE);
    assert(alias2 == fixed_res);
    uint32_t *alias2_ptr = (uint32_t *)alias2;
    assert(*alias2_ptr == 0xcafebabe);

    // Write coherence: modify via alias2, check original and alias1
    *alias2_ptr = 0x12345678;
    assert(*orig_ptr == 0x12345678);
    assert(*alias1_ptr == 0x12345678);

    // Clean up alias mappings
    assert(munmap(alias1, PAGE_SIZE) == 0);
    assert(munmap(alias2, PAGE_SIZE) == 0);

    // 5. Independent page protections
    // Make original page read-only
    rc = mprotect(guest_page, PAGE_SIZE, PROT_READ);
    assert(rc == 0);

    // Create a new alias (mapped PROT_READ | PROT_WRITE)
    void *alias3 = dm_vm_alias(NULL, guest_page, PAGE_SIZE);
    assert(alias3 != NULL);
    uint32_t *alias3_ptr = (uint32_t *)alias3;

    // Writes through alias succeed even though original VMA is PROT_READ
    *alias3_ptr = 0xfeedface;
    assert(*orig_ptr == 0xfeedface);
    assert(munmap(alias3, PAGE_SIZE) == 0);

    // 6. Bounds checks
    // Beyond end of AS
    void *bad1 = dm_vm_alias(NULL, (uint8_t *)as + AS_SIZE, PAGE_SIZE);
    assert(bad1 == NULL);
    assert(errno == EINVAL);

    // Before start of AS
    void *bad2 = dm_vm_alias(NULL, (uint8_t *)as - PAGE_SIZE, PAGE_SIZE);
    assert(bad2 == NULL);
    assert(errno == EINVAL);

    // Straddles end of AS
    void *bad3 = dm_vm_alias(NULL, (uint8_t *)as + AS_SIZE - (PAGE_SIZE / 2), PAGE_SIZE);
    assert(bad3 == NULL);
    assert(errno == EINVAL);

    // 7. Release
    dm_guest_as_release(as, AS_SIZE);

    // Alias after release fails with ENOTSUP
    void *bad4 = dm_vm_alias(NULL, guest_page, PAGE_SIZE);
    assert(bad4 == NULL);
    assert(errno == ENOTSUP);

    // Re-reservation after release succeeds
    void *as2 = dm_guest_as_reserve(AS_SIZE);
    assert(as2 != NULL);
    dm_guest_as_release(as2, AS_SIZE);

    printf("ALL TESTS PASSED\n");
    return 0;
}
