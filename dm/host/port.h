// The host's platform primitives that have no POSIX spelling. The host calls these names; the Apple build gets them inline here over the libc and frameworks it already links,
// so no unit test needs another object, and the bionic build gets them from dm/android/port_android.c (over dm/android/compat/, which carries the Apple names there, and Linux).
// In dm/host and dm/gfx/nvn this is the only file that spells CommonCrypto, clonefile, the pthread QoS calls, GCD, the Mach VM and thread-policy calls, Mach-O sections and
// Darwin's signal-context layout (dm/tools/android_audit.py keeps it so); Mach time is still spelled where it is not a clock reading (the NVN profiling ticks that nvn_entry.S
// takes from mach_absolute_time in assembly, converted here by dm_ticks_ns), and compat's <mach/mach.h> answers the Mach calls whose semantics bionic has (vm_read_overwrite,
// task_info TASK_VM_INFO, thread_info THREAD_BASIC_INFO, the thread suspend / state / resume set).
#pragma once
#include <pthread.h>
#include <pthread/qos.h>   // qos_class_t and the QOS_CLASS_* values: Apple's header, or dm/android/compat's mapping of them to nice values
#include <stddef.h>
#include <stdint.h>
#include <sys/types.h>
#include <sys/ucontext.h>
#include <time.h>
#include <mach/mach.h>     // arm_thread_state64_t and the Mach calls both platforms answer (Apple's header, or compat's)

// ---- Clock, sleep, clone, digest, QoS ----
// Monotonic nanoseconds that do not advance while the device sleeps: the clock now_ns() (hle_os.c) and guest_ns() are built on, usable from a signal handler (no system
// call on either platform). Apple: CLOCK_UPTIME_RAW is mach_absolute_time() after the timebase conversion; bionic: CLOCK_MONOTONIC, the clock compat's mach_absolute_time reads.
#if defined(__APPLE__)
static inline uint64_t dm_clock_ns(void) { return clock_gettime_nsec_np(CLOCK_UPTIME_RAW); }
#else
static inline uint64_t dm_clock_ns(void) { struct timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts); return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec; }
#endif
// dm_sleep_until_ns: sleep until an absolute dm_clock_ns() time, at once when it has passed. Carries the platform's timer slack (hle_thread.c sleep_precise measures it on macOS).
// dm_ticks_ns: mach_absolute_time ticks (the NVN profiling thunks in nvn_entry.S take them in assembly) to nanoseconds; compat's mach_absolute_time already counts nanoseconds.
// dm_cond_timedwait_ns: pthread_cond_timedwait with a relative timeout (Apple's _relative_np; bionic's monotonic absolute wait).
// dm_thread_name: this thread's name for the debugger and the profiler (Apple's one-argument pthread_setname_np; Linux names are 15 characters, longer ones are cut).
// dm_clone_tree: clone a directory tree (or one file) to a path that does not exist yet: 0, or -1 with errno. Apple: an APFS copy-on-write clone (clonefile, nearly free, every
//   xattr included); bionic: a copy that is either whole or absent, like the clone (dm/android/compat/clonefile.c), which carries only user.* extended attributes.
// dm_xattr_*: an extended attribute of a path, not following a final symlink; the name is the Apple one (hle_fs.c's org.d2rmobile.guest-name, which existing saves carry) and
//   bionic puts it in the user. namespace, the one an app may set and the one the clone copies. dm_errno_noattr says whether an errno means "no such attribute" (ENOATTR / ENODATA).
// dm_fd_path: the path of an open regular file or directory (F_GETPATH; /proc/self/fd on Linux): 0, or -1.
// dm_sha256: SHA-256, one-shot or streaming (the shader program key hashes two sections, the capture several, the NRO table a module and its tail). The context holds the
//   platform's state (CommonCrypto's, or dm/android/compat/digest.c's behind the opaque bytes), sized and aligned for either; sizes above 4 GiB are fed in blocks.
// dm_qos: the calling thread's class (0 on success), what it last set, and a boost that holds thread t at least at class c until dm_qos_boost_end (ArbitrateLock lends the
//   waiter's class to the lock owner the way the Horizon kernel lends priority). Boosts compose: several waiters may lend to one owner, in any order of ending, and the owner's
//   own class may change meanwhile; the effective class is always the highest of its own and the active lends. Apple: the pthread QoS and override calls, which compose in
//   libpthread; bionic: per-thread nice values (compat's pthread/qos.h mapping), composed by port_android.c's lend table. dm_qos_thread_exit: the thread is leaving
//   (hle_thread.c thread_exit); bionic drops its lend entry there, Apple has nothing to drop (an override belongs to the pthread).
#if defined(__APPLE__)
#include <CommonCrypto/CommonDigest.h>
typedef union { CC_SHA256_CTX cc; uint64_t align[14]; } dm_sha256_t;
#else
typedef struct { uint64_t opaque[14]; } dm_sha256_t;
#endif
typedef void *dm_qos_boost_t;   // NULL = no boost in effect

// ---- Process, thread and memory facts ----
// dm_section: the host's own data sections registered with DM_SECTION (swhle, swforce, swnvn): their bytes and length, NULL when empty. Apple: a __DATA section of the
//   executable (getsectiondata); ELF: the linker's __start_ / __stop_ symbols (the Android link keeps them with -z nostart-stop-gc).
// DM_SECTION / DM_ASM_*: the attribute that puts a table entry in such a section, and the spellings inline assembly needs for a symbol, its page and page offset and a hidden
//   directive (Mach-O: a leading underscore, @PAGE / @PAGEOFF, .private_extern; ELF: the bare name for adrp, as LLVM's assembler takes it, :lo12: for the offset, .hidden).
//   DM_ASM_FUNC / DM_ASM_END(sym) open and close a function written in inline assembly: on ELF its .type (a function, so a debugger, unwinder or symbolizer and the linker's
//   interposition treat it as code) and its .size; nothing on Mach-O, which has neither directive (the Apple assembly text is unchanged). For file-scope basic asm
//   only (__asm__("...") outside a function, as hle_bigstack.c and HLE_FORCE_BIG use it): inside an extended asm statement '%' starts an operand, and
//   "%function" would have to be written "%%function".
// dm_kslot_*: the guest's four thread slots (dm.h: K18, KTLS, KTLR, KGATE), which rewritten guest code reads and writes without a call (patch_nso.py emit_thread_base): new hands
//   out a key number (the loader writes key × 8 into each module's key page), get / set are this thread's slot (get is async-signal-safe and gives NULL on a thread that has no
//   slots). Apple: pthread keys, which the code finds at TPIDRRO_EL0 + 8 × key (Darwin's TSD array; loader.c tsd_check proves it). bionic: TPIDRRO_EL0 reads 0 in a Linux task
//   and bionic's thread pointer is TPIDR_EL0, so the slots are a per-thread table whose address set puts in the thread pointer's word TLS_SLOT_APP (DM_KSLOT_TP_OFF = 16 bytes),
//   the word bionic leaves to the app from Android 10 (API 29); a key is a table index (1..4, word 0 holds a tag). dm_kslot_guest_read reads key_off bytes into the table with the
//   instructions --target=android emits, for the loader's check. DM_KSLOT_TP_OFF is what a module's fixups.tsv must say (KSLOT_TP_OFF; absent = 0 = Apple's TSD).
// dm_uc_ss / dm_uc_ns: the integer and the SIMD registers of a signal's ucontext, as Apple's arm_thread_state64_t / arm_neon_state64_t (__x[29], __fp, __lr, __sp, __pc, __cpsr;
//   __v[32], __fpsr, __fpcr). Apple returns the context's own blocks; bionic overlays the state on uc_mcontext.regs (same order, pstate's low word is cpsr) and copies the fpsimd
//   block out of __reserved into tmp (NULL when the kernel left none). dm_uc_fault_write: whether a data abort was a write (the WnR bit, 6, of the ESR: Apple's __es.__esr;
//   Linux's esr record in __reserved, 0 when the kernel left none).
// dm_vm_region: the mapping that holds addr (start, length, PROT_* bits): 0, or -1 when nothing is mapped there (vm_region_64; /proc/self/maps on Linux).
// dm_guest_as_reserve / dm_guest_as_release: reserve and release the guest address space block. Apple: anonymous private mmap.
//   Linux/Android: memfd_create + MAP_SHARED so that dm_vm_alias can duplicate physical page mappings.
// dm_vm_alias: a second mapping of the same pages at to (NULL = anywhere): the pointer, or NULL with errno. Apple: vm_remap with copy = FALSE.
//   Linux/Android: mmap from the guest block's memfd with MAP_SHARED.
// dm_thread_rt_set / dm_thread_rt_live: the time-constraint (real-time) scheduling policy of this thread (Apple's THREAD_TIME_CONSTRAINT_POLICY: period and computation in ns;
//   bionic: not available to an app, SCHED_FIFO needs CAP_SYS_NICE, said once; live is then 0).
// dm_thread_sched: this thread's current priority, base priority and policy number as the platform counts them (Apple's THREAD_EXTENDED_INFO; Linux: nice, nice, sched policy).
// dm_task_power: the process's CPU time, its performance-core share of that time, its energy, its wakeups and its GPU time so far (Apple's TASK_POWER_INFO_V2, converted to ns and
//   nJ here); -1 where the platform has no reading (bionic: rusage gives the CPU time, the rest is not collected, said once).
// dm_cpu_perf_levels: how many performance levels the CPU has (Apple's hw.nperflevels; Linux: distinct cpuinfo_max_freq values), 1 when unknown.
// dm_proc_start_ns: when this process started, on the dm_clock_ns base (Apple: p_starttime from sysctl; Linux: /proc/self/stat starttime on CLOCK_BOOTTIME).
// dm_heap: a separate malloc zone for a guest allocator the host takes over (hle_uemalloc.c): Apple's malloc_create_zone; bionic's malloc, where usable sizes come from
//   malloc_usable_size (a zone of its own does not exist there: the bytes are counted by the caller as before).
// dm_sem: a counting semaphore with a timed wait (GCD's dispatch_semaphore on Apple); dm_after_ns: call fn(arg) on some other thread after ns nanoseconds (dispatch_after);
//   dm_on_sigterm: hand SIGTERM to fn("SIGTERM") on an ordinary thread (a GCD signal source; on Linux a sigaction handler that writes a self-pipe a waiting thread reads).
// dm_compress / dm_decompress: the NVN capture's chunk codec (nvn_capture.c, CAP_LZFSE): bytes written into dst, 0 when it did not fit or the codec is not available. Apple:
//   libcompression's LZFSE; bionic: no LZFSE in the tree, so compression fails (chunks are stored raw) and an LZFSE capture cannot be read there, said once with [RED].
//   DM_HAVE_COMPRESS says at compile time whether dm_compress can ever succeed (1 Apple, 0 bionic), so a caller skips the output buffer it would allocate for nothing.
#if defined(__APPLE__)
#define DM_SECTION(name) section("__DATA," name)
#define DM_ASM_SYM(name) "_" name
#define DM_ASM_HI(name) "_" name "@PAGE"
#define DM_ASM_LO(name) "_" name "@PAGEOFF"
#define DM_ASM_HIDDEN ".private_extern"
#define DM_ASM_FUNC(sym) ""
#define DM_ASM_END(sym) ""
#define DM_KSLOT_TP_OFF 0
#define DM_HAVE_COMPRESS 1
typedef arm_neon_state64_t dm_neon_t;
#else
#define DM_SECTION(name) section(name)
#define DM_ASM_SYM(name) name
#define DM_ASM_HI(name) name              // adrp takes the bare symbol in LLVM's AArch64 assembler (asm_elf.py spells the .S files the same way); :pg_hi21: is GNU-only
#define DM_ASM_LO(name) ":lo12:" name
#define DM_ASM_HIDDEN ".hidden"
#define DM_ASM_FUNC(sym) ".type " sym ", %function\n"
#define DM_ASM_END(sym) ".size " sym ", . - " sym "\n"
#define DM_KSLOT_TP_OFF 16                // bionic's TLS_SLOT_APP (2) × 8: patch_nso.py TLS_SLOT_APP
#define DM_HAVE_COMPRESS 0
typedef struct { __uint128_t __v[32]; uint32_t __fpsr, __fpcr; } dm_neon_t;
#endif
typedef struct { uint64_t cpu_ns, pcore_ns, energy_nj, wakeups_intr, wakeups_idle, gpu_ns; } dm_task_power_t;
typedef struct dm_heap dm_heap_t;
typedef struct dm_sem *dm_sem_t;

#if defined(__APPLE__)
#include <CommonCrypto/CommonDigest.h>
#include <compression.h>
__asm__(".linker_option \"-lcompression\"");   // libcompression links itself: the host, the iOS app and the tests that compile nvn_capture.c need no link flag
#include <dispatch/dispatch.h>
#include <mach-o/getsect.h>
#include <mach-o/ldsyms.h>
#include <mach/mach_time.h>
#include <mach/thread_policy.h>
#include <malloc/malloc.h>
#include <signal.h>
#include <sys/clonefile.h>
#include <sys/fcntl.h>
#include <sys/mman.h>
#include <sys/sysctl.h>
#include <sys/xattr.h>
#include <errno.h>
#include <string.h>
static inline uint64_t dm_ticks_ns(uint64_t ticks) { static mach_timebase_info_data_t tb; if (!tb.denom) mach_timebase_info(&tb); return ticks * tb.numer / tb.denom; }
static inline void dm_sleep_until_ns(uint64_t deadline_ns) {
    static mach_timebase_info_data_t tb; if (!tb.denom) mach_timebase_info(&tb);
    uint64_t now = dm_clock_ns(); if (deadline_ns <= now) return;
    mach_wait_until(mach_absolute_time() + (deadline_ns - now) * tb.denom / tb.numer);
}
static inline int dm_cond_timedwait_ns(pthread_cond_t *cv, pthread_mutex_t *mu, uint64_t rel_ns) {
    struct timespec ts = {(time_t)(rel_ns / 1000000000u), (long)(rel_ns % 1000000000u)}; return pthread_cond_timedwait_relative_np(cv, mu, &ts);
}
static inline int dm_thread_name(const char *name) { return pthread_setname_np(name); }
static inline int dm_clone_tree(const char *src, const char *dst) { return clonefile(src, dst, 0); }
static inline ssize_t dm_xattr_get(const char *path, const char *name, void *buf, size_t n) { return getxattr(path, name, buf, n, 0, XATTR_NOFOLLOW); }
static inline int dm_xattr_set(const char *path, const char *name, const void *v, size_t n) { return setxattr(path, name, v, n, 0, XATTR_NOFOLLOW); }
static inline int dm_xattr_remove(const char *path, const char *name) { return removexattr(path, name, XATTR_NOFOLLOW); }
static inline int dm_errno_noattr(int e) { return e == ENOATTR; }
static inline int dm_fd_path(int fd, char *out, size_t n) { char p[MAXPATHLEN]; if (fcntl(fd, F_GETPATH, p) || !p[0]) return -1; strlcpy(out, p, n); return 0; }
static inline void dm_sha256_init(dm_sha256_t *c) { CC_SHA256_Init(&c->cc); }
static inline void dm_sha256_update(dm_sha256_t *c, const void *data, size_t n) {   // CC_LONG is 32 bits: in blocks, so a size past 4 GiB is not truncated
    for (const uint8_t *p = data; n; ) { size_t k = n > (1u << 30) ? (1u << 30) : n; CC_SHA256_Update(&c->cc, p, (CC_LONG)k); p += k; n -= k; }
}
static inline void dm_sha256_final(dm_sha256_t *c, uint8_t out[32]) { CC_SHA256_Final(out, &c->cc); }
static inline void dm_sha256(const void *data, size_t n, uint8_t out[32]) { dm_sha256_t c; dm_sha256_init(&c); dm_sha256_update(&c, data, n); dm_sha256_final(&c, out); }
static inline int dm_qos_set_self(qos_class_t c) { return pthread_set_qos_class_self_np(c, 0); }
static inline qos_class_t dm_qos_self(void) { qos_class_t c = QOS_CLASS_UNSPECIFIED; int rp = 0; pthread_get_qos_class_np(pthread_self(), &c, &rp); return c; }
static inline dm_qos_boost_t dm_qos_boost_start(pthread_t t, qos_class_t c) { return (dm_qos_boost_t)pthread_override_qos_class_start_np(t, c, 0); }
static inline void dm_qos_boost_end(dm_qos_boost_t b) { if (b) pthread_override_qos_class_end_np((pthread_override_t)b); }
static inline void dm_qos_thread_exit(void) {}
static inline int dm_kslot_new(pthread_key_t *k) { return pthread_key_create(k, NULL); }
static inline void *dm_kslot_get(pthread_key_t k) { return pthread_getspecific(k); }
static inline int dm_kslot_set(pthread_key_t k, const void *v) { return pthread_setspecific(k, v); }
static inline const void *dm_section(const char *name, unsigned long *size) { return getsectiondata(&_mh_execute_header, "__DATA", name, size); }
static inline arm_thread_state64_t *dm_uc_ss(ucontext_t *uc) { return &uc->uc_mcontext->__ss; }
static inline const dm_neon_t *dm_uc_ns(ucontext_t *uc, dm_neon_t *tmp) { (void)tmp; return &uc->uc_mcontext->__ns; }
static inline int dm_uc_fault_write(ucontext_t *uc) { return (int)((uc->uc_mcontext->__es.__esr >> 6) & 1); }
static inline int dm_vm_region(uintptr_t addr, uintptr_t *start, size_t *len, int *prot) {
    vm_address_t at = (vm_address_t)addr; vm_size_t sz = 0; vm_region_basic_info_data_64_t info; mach_msg_type_number_t cnt = VM_REGION_BASIC_INFO_COUNT_64; mach_port_t obj = MACH_PORT_NULL;
    if (vm_region_64(mach_task_self(), &at, &sz, VM_REGION_BASIC_INFO_64, (vm_region_info_t)&info, &cnt, &obj) != KERN_SUCCESS || at > addr) return -1;
    *start = at; *len = sz; *prot = (info.protection & VM_PROT_READ ? PROT_READ : 0) | (info.protection & VM_PROT_WRITE ? PROT_WRITE : 0) | (info.protection & VM_PROT_EXECUTE ? PROT_EXEC : 0);
    return 0;
}
static inline void *dm_guest_as_reserve(size_t reserve) {
    void *p = mmap(NULL, reserve, PROT_NONE, MAP_PRIVATE | MAP_ANON, -1, 0);
    return p == MAP_FAILED ? NULL : p;
}
static inline void dm_guest_as_release(void *as, size_t reserve) {
    if (as) munmap(as, reserve);
}
static inline void *dm_vm_alias(void *to, const void *from, size_t size) {
    vm_address_t a = (vm_address_t)to; vm_prot_t cur = 0, max = 0;
    kern_return_t kr = vm_remap(mach_task_self(), &a, size, 0, to ? VM_FLAGS_FIXED | VM_FLAGS_OVERWRITE : VM_FLAGS_ANYWHERE, mach_task_self(), (vm_address_t)from, FALSE, &cur, &max, VM_INHERIT_NONE);
    if (kr != KERN_SUCCESS || (to && a != (vm_address_t)to)) { errno = kr == KERN_INVALID_ARGUMENT ? EINVAL : kr == KERN_NO_SPACE ? ENOMEM : EIO; return NULL; }
    return (void *)a;
}
static inline int dm_thread_rt_set(uint64_t period_ns, uint64_t comp_ns) {
    static mach_timebase_info_data_t tb; if (!tb.denom) mach_timebase_info(&tb);
    thread_time_constraint_policy_data_t p = {.period = (uint32_t)(period_ns * tb.denom / tb.numer), .computation = (uint32_t)(comp_ns * tb.denom / tb.numer), .constraint = (uint32_t)(period_ns * tb.denom / tb.numer), .preemptible = 1};
    return thread_policy_set(pthread_mach_thread_np(pthread_self()), THREAD_TIME_CONSTRAINT_POLICY, (thread_policy_t)&p, THREAD_TIME_CONSTRAINT_POLICY_COUNT) == KERN_SUCCESS ? 0 : -1;
}
static inline int dm_thread_rt_live(void) {
    thread_time_constraint_policy_data_t tp; mach_msg_type_number_t tc = THREAD_TIME_CONSTRAINT_POLICY_COUNT; boolean_t def = 0;
    return thread_policy_get(pthread_mach_thread_np(pthread_self()), THREAD_TIME_CONSTRAINT_POLICY, (thread_policy_t)&tp, &tc, &def) == KERN_SUCCESS && !def;   // def = 1: never set / revoked
}
static inline int dm_thread_sched(int *cur, int *base, int *policy) {
    thread_extended_info_data_t xi; mach_msg_type_number_t xc = THREAD_EXTENDED_INFO_COUNT;
    if (thread_info(pthread_mach_thread_np(pthread_self()), THREAD_EXTENDED_INFO, (thread_info_t)&xi, &xc) != KERN_SUCCESS) return -1;
    *cur = xi.pth_curpri; *base = xi.pth_priority; *policy = xi.pth_policy; return 0;
}
static inline int dm_task_power(dm_task_power_t *out) {
    task_power_info_v2_data_t pw; mach_msg_type_number_t n = TASK_POWER_INFO_V2_COUNT;
    if (task_info(mach_task_self(), TASK_POWER_INFO_V2, (task_info_t)&pw, &n) != KERN_SUCCESS) return -1;
    out->cpu_ns = dm_ticks_ns(pw.cpu_energy.total_user + pw.cpu_energy.total_system); out->pcore_ns = dm_ticks_ns(pw.task_ptime);
#if defined(__arm64__)
    out->energy_nj = pw.task_energy;
#else
    out->energy_nj = 0;
#endif
    out->wakeups_intr = pw.cpu_energy.task_interrupt_wakeups; out->wakeups_idle = pw.cpu_energy.task_platform_idle_wakeups; out->gpu_ns = pw.gpu_energy.task_gpu_utilisation;
    return 0;
}
static inline int dm_cpu_perf_levels(void) { int levels = 0; size_t n = sizeof levels; return sysctlbyname("hw.nperflevels", &levels, &n, 0, 0) || levels < 1 ? 1 : levels; }
static inline uint64_t dm_proc_start_ns(void) {   // p_starttime (wall clock) moved onto the monotonic base; the current time when the kernel does not answer
    struct kinfo_proc kp; size_t n = sizeof kp; int mib[4] = {CTL_KERN, KERN_PROC, KERN_PROC_PID, getpid()};
    uint64_t mono = dm_clock_ns(); struct timeval tv; gettimeofday(&tv, NULL);
    if (sysctl(mib, 4, &kp, &n, NULL, 0) || !n) return mono;
    int64_t age = (int64_t)(tv.tv_sec - kp.kp_proc.p_starttime.tv_sec) * 1000000000ll + (tv.tv_usec - kp.kp_proc.p_starttime.tv_usec) * 1000ll;
    return age > 0 ? mono - (uint64_t)age : mono;
}
static inline dm_heap_t *dm_heap_new(const char *name) { malloc_zone_t *z = malloc_create_zone(0, 0); if (z && name) malloc_set_zone_name(z, name); return (dm_heap_t *)z; }
static inline void *dm_heap_malloc(dm_heap_t *h, size_t n) { return malloc_zone_malloc((malloc_zone_t *)h, n); }
static inline void *dm_heap_memalign(dm_heap_t *h, size_t align, size_t n) { return malloc_zone_memalign((malloc_zone_t *)h, align, n); }
static inline void *dm_heap_realloc(dm_heap_t *h, void *p, size_t n) { return malloc_zone_realloc((malloc_zone_t *)h, p, n); }
static inline void dm_heap_free(dm_heap_t *h, void *p) { malloc_zone_free((malloc_zone_t *)h, p); }
static inline size_t dm_heap_size(dm_heap_t *h, const void *p) { (void)h; return malloc_size(p); }
static inline size_t dm_heap_good_size(size_t n) { return malloc_good_size(n); }
static inline dm_sem_t dm_sem_new(long value) { return (dm_sem_t)dispatch_semaphore_create(value); }
static inline void dm_sem_signal(dm_sem_t s) { dispatch_semaphore_signal((dispatch_semaphore_t)s); }
static inline int dm_sem_wait(dm_sem_t s, int64_t timeout_ns) {   // 0 = taken, -1 = timed out; timeout_ns < 0 waits forever
    return dispatch_semaphore_wait((dispatch_semaphore_t)s, timeout_ns < 0 ? DISPATCH_TIME_FOREVER : dispatch_time(DISPATCH_TIME_NOW, timeout_ns)) ? -1 : 0;
}
static inline void dm_sem_free(dm_sem_t s) { dispatch_release((dispatch_semaphore_t)s); }
static inline void dm_after_ns(uint64_t ns, void (*fn)(void *), void *arg) {
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)ns), dispatch_get_global_queue(QOS_CLASS_USER_INTERACTIVE, 0), ^{ fn(arg); });
}
static inline void dm_on_sigterm(void (*fn)(const char *)) {
    signal(SIGTERM, SIG_IGN);   // not the default action: the signal source hands it to an ordinary thread
    static dispatch_source_t src;
    src = dispatch_source_create(DISPATCH_SOURCE_TYPE_SIGNAL, SIGTERM, 0, dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0));
    dispatch_source_set_event_handler(src, ^{ fn("SIGTERM"); });
    dispatch_resume(src);
}
static inline size_t dm_compress(void *dst, size_t cap, const void *src, size_t n) { return compression_encode_buffer(dst, cap, src, n, NULL, COMPRESSION_LZFSE); }
static inline size_t dm_decompress(void *dst, size_t cap, const void *src, size_t n) { return compression_decode_buffer(dst, cap, src, n, NULL, COMPRESSION_LZFSE); }
#else
uint64_t dm_ticks_ns(uint64_t ticks);   // dm/android/port_android.c
void dm_sleep_until_ns(uint64_t deadline_ns);
int dm_cond_timedwait_ns(pthread_cond_t *cv, pthread_mutex_t *mu, uint64_t rel_ns);
int dm_thread_name(const char *name);
int dm_clone_tree(const char *src, const char *dst);
ssize_t dm_xattr_get(const char *path, const char *name, void *buf, size_t n);
int dm_xattr_set(const char *path, const char *name, const void *v, size_t n);
int dm_xattr_remove(const char *path, const char *name);
int dm_errno_noattr(int e);
int dm_fd_path(int fd, char *out, size_t n);
void dm_sha256_init(dm_sha256_t *c);
void dm_sha256_update(dm_sha256_t *c, const void *data, size_t n);
void dm_sha256_final(dm_sha256_t *c, uint8_t out[32]);
void dm_sha256(const void *data, size_t n, uint8_t out[32]);
int dm_qos_set_self(qos_class_t c);
qos_class_t dm_qos_self(void);
dm_qos_boost_t dm_qos_boost_start(pthread_t t, qos_class_t c);
void dm_qos_boost_end(dm_qos_boost_t b);
void dm_qos_thread_exit(void);
int dm_kslot_new(pthread_key_t *k);
void *dm_kslot_get(pthread_key_t k);
int dm_kslot_set(pthread_key_t k, const void *v);
uint64_t dm_kslot_guest_read(uint64_t key_off);
const void *dm_section(const char *name, unsigned long *size);
arm_thread_state64_t *dm_uc_ss(ucontext_t *uc);
const dm_neon_t *dm_uc_ns(ucontext_t *uc, dm_neon_t *tmp);
int dm_uc_fault_write(ucontext_t *uc);
int dm_vm_region(uintptr_t addr, uintptr_t *start, size_t *len, int *prot);
void *dm_guest_as_reserve(size_t reserve);
void dm_guest_as_release(void *as, size_t reserve);
void *dm_vm_alias(void *to, const void *from, size_t size);
int dm_thread_rt_set(uint64_t period_ns, uint64_t comp_ns);
int dm_thread_rt_live(void);
int dm_thread_sched(int *cur, int *base, int *policy);
int dm_task_power(dm_task_power_t *out);
int dm_cpu_perf_levels(void);
uint64_t dm_proc_start_ns(void);
dm_heap_t *dm_heap_new(const char *name);
void *dm_heap_malloc(dm_heap_t *h, size_t n);
void *dm_heap_memalign(dm_heap_t *h, size_t align, size_t n);
void *dm_heap_realloc(dm_heap_t *h, void *p, size_t n);
void dm_heap_free(dm_heap_t *h, void *p);
size_t dm_heap_size(dm_heap_t *h, const void *p);
static inline size_t dm_heap_good_size(size_t n) { return n; }
dm_sem_t dm_sem_new(long value);
void dm_sem_signal(dm_sem_t s);
int dm_sem_wait(dm_sem_t s, int64_t timeout_ns);
void dm_sem_free(dm_sem_t s);
void dm_after_ns(uint64_t ns, void (*fn)(void *), void *arg);
void dm_on_sigterm(void (*fn)(const char *));
size_t dm_compress(void *dst, size_t cap, const void *src, size_t n);
size_t dm_decompress(void *dst, size_t cap, const void *src, size_t n);
#endif
