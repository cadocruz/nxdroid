// dm/host/port.h on bionic: the platform primitives the host names there, over dm/android/compat/ (which carries the Apple spellings: clonefile, CC_SHA256, the QoS class
// values and their nice mapping) and POSIX. Built only into the Android host (dm/android/CMakeLists.txt ANDROID_SRCS); the Apple build has these inline in port.h.
#include "compat/include/dm_android_compat.h"   // clonefile (dm/android/compat/clonefile.c); force-included by the CMake build as well
#include "../host/port.h"
#include "../host/dm.h"                         // LOG
#include <CommonCrypto/CommonDigest.h>         // dm/android/compat/digest.c
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <malloc.h>
#include <sched.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/xattr.h>
#include <android/api-level.h>          // android_get_device_api_level (a function from API 29, the build's floor)
#include <unistd.h>

_Static_assert(sizeof(CC_SHA256_CTX) <= sizeof(dm_sha256_t), "dm_sha256_t must hold compat's CC_SHA256_CTX");
_Static_assert(_Alignof(CC_SHA256_CTX) <= _Alignof(dm_sha256_t), "dm_sha256_t must align compat's CC_SHA256_CTX");
_Static_assert(DM_KSLOT_TP_OFF == 2 * 8, "the slot table is in bionic's TLS_SLOT_APP (2), where patch_nso.py --target=android looks");

// port.h's dm_clock_ns() is CLOCK_MONOTONIC here, so the deadline is an absolute CLOCK_MONOTONIC time
void dm_sleep_until_ns(uint64_t deadline_ns) {
    struct timespec ts = {(time_t)(deadline_ns / 1000000000ull), (long)(deadline_ns % 1000000000ull)};
    while (clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &ts, NULL) == EINTR) {}
}

int dm_clone_tree(const char *src, const char *dst) { return clonefile(src, dst, 0); }

static CC_SHA256_CTX *cc(dm_sha256_t *c) { return (CC_SHA256_CTX *)c->opaque; }
void dm_sha256_init(dm_sha256_t *c) { CC_SHA256_Init(cc(c)); }
void dm_sha256_update(dm_sha256_t *c, const void *data, size_t n) {   // CC_LONG is 32 bits: in blocks, so a size past 4 GiB is not truncated
    for (const uint8_t *p = data; n; ) { size_t k = n > (1u << 30) ? (1u << 30) : n; CC_SHA256_Update(cc(c), p, (CC_LONG)k); p += k; n -= k; }
}
void dm_sha256_final(dm_sha256_t *c, uint8_t out[32]) { CC_SHA256_Final(out, cc(c)); }
void dm_sha256(const void *data, size_t n, uint8_t out[32]) { dm_sha256_t c; dm_sha256_init(&c); dm_sha256_update(&c, data, n); dm_sha256_final(&c, out); }

// ---- QoS: classes are nice values (compat's pthread/qos.h mapping), and a boost is a lend of the waiter's class to the lock owner ----
// Linux has no priority inheritance for nice values and no override object like Apple's, so the lends are composed here: a table of the threads that currently hold at least
// one lend, with the thread's own class as the base, the active lends per class rank, and the nice the kernel has (applied). The target nice is the lowest of the base and the
// highest lended class the limit has not refused; whenever a lend starts or ends or the owner sets its own class, the target is compared with the applied nice and one
// setpriority brings them together. A thread without lends has no entry: its nice is its base. Everything, the setpriority included, happens under one mutex, so a lend that
// starts while the owner is changing its class sees the class the owner ends up with (ArbitrateLock already holds the host's G there; the lends in flight are the blocked
// waiters, so the table stays small).
// The limit (RLIMIT_NICE; not measured on an Android app process, to measure on the S23 Ultra) refuses a nice below it with EACCES. A lend it refuses is recorded and its
// class marked denied for that owner, so it no longer counts in the target (the owner's own class, or a lower lend the limit allows, is applied instead); the mark goes when
// the last lend of that class ends. A thread's own class is reported (dm_qos_self) only when its setpriority was accepted, or when a lend in force already holds the thread at
// that nice or lower; a refused class is said once and not reported (hle_thread.c compares classes to decide a lend).
// The contract of a handle: it names (tid, rank, slot, generation). A lend takes one of LEND_BITS slots of its rank and the next value of one 16-bit counter shared by the
// whole table, so an end whose generation is not the slot's current one (a second end of the same lend, after the slot was taken again by any thread, in any entry) does
// nothing, until the counter wraps: 65,536 lends after a stale handle was kept, it can match again. Past LEND_BITS concurrent lends of one class to one owner, a lend is counted
// (more[rank]) instead of slotted: it holds the owner just the same, its handle carries slot 0xff, and only its end is not instance-checked (a second end of such a lend would
// release a sibling's). The host's one caller, hle_thread.c's ArbitrateLock, ends each lend exactly once, so both limits are theoretical there.
// An entry is keyed by the kernel thread id. A thread that leaves through hle_thread.c's thread_exit calls dm_qos_thread_exit, which drops its entry (the lends in flight end
// into nothing); a thread that dies any other way leaves its entry until its lends end, and a new thread given the same tid meanwhile has its own class folded into that entry
// (its set is recorded as the base; it is applied when the stale lends end).
_Static_assert(sizeof(uintptr_t) >= 8, "the lend handle packs tid (32 bits), generation (16), rank (8) and slot (8) into a pointer: the Android host is arm64-v8a (LP64)");
enum { LEND_RANKS = 5, LEND_SLOTS = 256, LEND_BITS = 32, LEND_MORE = 0xff };
static const qos_class_t k_rank_class[LEND_RANKS] = {QOS_CLASS_BACKGROUND, QOS_CLASS_UTILITY, QOS_CLASS_DEFAULT, QOS_CLASS_USER_INITIATED, QOS_CLASS_USER_INTERACTIVE};
typedef struct {
    pid_t tid; int base, applied;   // the thread's own nice, and the nice the kernel has (set here, or read when the entry was made)
    uint32_t lend[LEND_RANKS]; uint16_t more[LEND_RANKS]; uint8_t denied;   // lend[k]: one bit per slotted lend of rank k; denied: ranks the limit refused for this thread
    uint16_t gen[LEND_RANKS][LEND_BITS];
} lend_t;
static lend_t g_lend[LEND_SLOTS];
static pthread_mutex_t g_lend_mu = PTHREAD_MUTEX_INITIALIZER;
static uint16_t g_gen;                   // one counter for every slot of the table (under g_lend_mu)
static int g_lend_denied, g_self_denied, g_lend_full;   // under g_lend_mu
static __thread qos_class_t g_qos_self = QOS_CLASS_UNSPECIFIED;   // the class this thread last set with success

static int rank_of(qos_class_t c) { for (int k = 0; k < LEND_RANKS; k++) if (k_rank_class[k] == c) return k; return -1; }
static int rank_active(const lend_t *e, int k) { return e->lend[k] || e->more[k]; }
static int top_rank(const lend_t *e) { for (int k = LEND_RANKS - 1; k >= 0; k--) if (rank_active(e, k) && !(e->denied & 1u << k)) return k; return -1; }
static int target_nice(const lend_t *e) { int k = top_rank(e); if (k < 0) return e->base; int v = dm_qos_nice_(k_rank_class[k]); return v < e->base ? v : e->base; }
static lend_t *lend_find(pid_t tid) { for (int i = 0; i < LEND_SLOTS; i++) if (g_lend[i].tid == tid) return &g_lend[i]; return NULL; }
static lend_t *lend_alloc(pid_t tid, int nice) {
    for (int i = 0; i < LEND_SLOTS; i++) if (!g_lend[i].tid) { lend_t *e = &g_lend[i]; memset(e->lend, 0, sizeof e->lend); memset(e->more, 0, sizeof e->more); e->denied = 0; e->tid = tid; e->base = e->applied = nice; return e; }
    return NULL;   // gen[][] is kept across uses of an entry: a stale handle from an earlier owner of the entry still misses
}
static int lend_has(const lend_t *e) { for (int k = 0; k < LEND_RANKS; k++) if (rank_active(e, k)) return 1; return 0; }
// Put the entry's target nice in force when it is not already: 0, or -1 with errno (EACCES is the limit above, said once per kind; ESRCH when the thread is gone: nothing to do then)
static int apply_target(lend_t *e, int lend) {
    int want = target_nice(e);
    if (want == e->applied) return 0;
    if (!setpriority(PRIO_PROCESS, (id_t)e->tid, want)) { e->applied = want; return 0; }
    if (errno != EACCES) return -1;
    if (lend) { if (!g_lend_denied++) LOG("QoS lend: setpriority(%d) for thread %d failed with EACCES (RLIMIT_NICE): a higher class cannot be lent to a lock owner in this process; waiters wait at the owner's own class", want, (int)e->tid); }
    else if (!g_self_denied++) LOG("QoS: setpriority(%d) for thread %d's own class failed with EACCES (RLIMIT_NICE): classes above the limit are not applied in this process", want, (int)e->tid);
    return -1;
}
static dm_qos_boost_t handle(pid_t tid, int rank, int slot, unsigned gen) {
    return (dm_qos_boost_t)(uintptr_t)((uint64_t)(uint32_t)tid << 32 | (uint64_t)(gen & 0xffff) << 16 | (uint64_t)(unsigned)(rank + 1) << 8 | (uint64_t)(unsigned)slot);
}

int dm_qos_set_self(qos_class_t c) {
    if (rank_of(c) < 0) return -1;
    pid_t tid = gettid(); int want = dm_qos_nice_(c), r;
    pthread_mutex_lock(&g_lend_mu);
    lend_t *e = lend_find(tid);
    if (!e) {   // no lend: the thread's nice is its class
        r = setpriority(PRIO_PROCESS, (id_t)tid, want);
        if (r && errno == EACCES && !g_self_denied++) LOG("QoS: setpriority(%d) for thread %d's own class failed with EACCES (RLIMIT_NICE): classes above the limit are not applied in this process", want, (int)tid);
    } else {
        int old = e->base; e->base = want;
        r = apply_target(e, 0);
        if (r && target_nice(e) != want) { e->denied |= 1u << top_rank(e); r = apply_target(e, 0); }   // the lend on top is what the limit refuses: mark it, the own class may still pass
        if (r) e->base = old;   // refused: the base stays what the kernel has
    }
    if (!r) g_qos_self = c;
    pthread_mutex_unlock(&g_lend_mu);
    return r;
}
qos_class_t dm_qos_self(void) { return g_qos_self; }
void dm_qos_thread_exit(void) {
    pid_t tid = gettid();
    pthread_mutex_lock(&g_lend_mu);
    lend_t *e = lend_find(tid); if (e) e->tid = 0;   // the lends in flight end into nothing; the tid may be reused at once
    pthread_mutex_unlock(&g_lend_mu);
}

dm_qos_boost_t dm_qos_boost_start(pthread_t t, qos_class_t c) {
    int rank = rank_of(c); if (rank < 0) return NULL;   // QOS_CLASS_UNSPECIFIED lends nothing
    pid_t tid = pthread_gettid_np(t); if (tid <= 0) return NULL;
    pthread_mutex_lock(&g_lend_mu);
    lend_t *e = lend_find(tid);
    if (!e) {   // no lend yet: its nice is its base
        errno = 0; int cur = getpriority(PRIO_PROCESS, (id_t)tid);
        if (cur == -1 && errno) { pthread_mutex_unlock(&g_lend_mu); return NULL; }   // the thread is gone
        e = lend_alloc(tid, cur);
        if (!e) { if (!g_lend_full++) LOG("[RED] QoS lend: more than %d threads hold lends at once; this waiter lends nothing", LEND_SLOTS); pthread_mutex_unlock(&g_lend_mu); return NULL; }
    }
    int slot; unsigned gen = 0;
    uint32_t free_bits = ~e->lend[rank];
    if (free_bits) { slot = __builtin_ctz(free_bits); e->lend[rank] |= 1u << slot; gen = e->gen[rank][slot] = ++g_gen; }
    else { slot = LEND_MORE; e->more[rank]++; }   // every slot of this class is taken: counted, not instance-checked (see the contract above)
    if (apply_target(e, 1) && top_rank(e) == rank) e->denied |= 1u << rank;   // this lend is what the limit refuses: it no longer counts, the owner keeps what it has
    pthread_mutex_unlock(&g_lend_mu);
    return handle(tid, rank, slot, gen);
}
void dm_qos_boost_end(dm_qos_boost_t b) {
    if (!b) return;
    uint64_t h = (uintptr_t)b; pid_t tid = (pid_t)(uint32_t)(h >> 32); unsigned gen = (h >> 16) & 0xffff; int rank = (int)((h >> 8) & 0xff) - 1, slot = (int)(h & 0xff);
    if (tid <= 0 || rank < 0 || rank >= LEND_RANKS) return;
    pthread_mutex_lock(&g_lend_mu);
    lend_t *e = lend_find(tid);
    if (!e) { pthread_mutex_unlock(&g_lend_mu); return; }   // over already
    if (slot == LEND_MORE) { if (!e->more[rank]) { pthread_mutex_unlock(&g_lend_mu); return; } e->more[rank]--; }
    else if (slot >= LEND_BITS || !(e->lend[rank] & 1u << slot) || e->gen[rank][slot] != gen) { pthread_mutex_unlock(&g_lend_mu); return; }   // an end that came twice: the slot is free, or another lend's now
    else e->lend[rank] &= ~(1u << slot);
    if (!rank_active(e, rank)) e->denied &= (uint8_t)~(1u << rank);
    while (apply_target(e, 1) && top_rank(e) >= 0) e->denied |= 1u << top_rank(e);   // a lower lend left on top may be refused too: mark it and fall through to the next, down to the base
    if (!lend_has(e)) e->tid = 0;   // back to its own class: the entry is free
    pthread_mutex_unlock(&g_lend_mu);
}

// ---- Time base, waits, names ----
uint64_t dm_ticks_ns(uint64_t ticks) { return ticks; }   // compat's mach_absolute_time counts nanoseconds (1:1 time base)
int dm_cond_timedwait_ns(pthread_cond_t *cv, pthread_mutex_t *mu, uint64_t rel_ns) {
    struct timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts);
    uint64_t ns = (uint64_t)ts.tv_nsec + rel_ns; ts.tv_sec += (time_t)(ns / 1000000000ull); ts.tv_nsec = (long)(ns % 1000000000ull);
    return pthread_cond_timedwait_monotonic_np(cv, mu, &ts);   // bionic: the deadline is on CLOCK_MONOTONIC whatever clock the condition was made with
}
int dm_thread_name(const char *name) { char b[16]; strncpy(b, name, sizeof b - 1); b[sizeof b - 1] = 0; return pthread_setname_np(pthread_self(), b); }

// ---- Extended attributes, descriptor paths ----
static const char *xname(const char *name, char *buf, size_t n) { snprintf(buf, n, "user.%s", name); return buf; }   // the namespace an app may use; the one compat's clone copies
ssize_t dm_xattr_get(const char *path, const char *name, void *buf, size_t n) { char x[256]; return lgetxattr(path, xname(name, x, sizeof x), buf, n); }
int dm_xattr_set(const char *path, const char *name, const void *v, size_t n) {
    char x[256]; if (!lsetxattr(path, xname(name, x, sizeof x), v, n, 0)) return 0;
    // A file system without extended attributes (FAT on removable storage) cannot carry the guest name of a case-collision file: the caller refuses that file, and it is said once
    static int said; if ((errno == ENOTSUP || errno == EOPNOTSUPP) && !said++) LOG("[RED] extended attributes are not supported on the file system holding %s: a file whose name collides on the host cannot keep its guest name there", path);
    return -1;
}
int dm_xattr_remove(const char *path, const char *name) { char x[256]; return lremovexattr(path, xname(name, x, sizeof x)); }
int dm_errno_noattr(int e) { return e == ENODATA || e == ENOTSUP || e == EOPNOTSUPP; }   // a file system without extended attributes has none either (compat's clone copies none there, the same way)
int dm_fd_path(int fd, char *out, size_t n) {
    char link[48]; snprintf(link, sizeof link, "/proc/self/fd/%d", fd);
    ssize_t k = readlink(link, out, n - 1); if (k <= 0) return -1;
    out[k] = 0; return out[0] == '/' ? 0 : -1;   // a socket or pipe reads as "socket:[…]": not a path
}

// ---- The host's own sections, the signal context ----
// The linker defines __start_<name> / __stop_<name> for a section whose name is a C identifier; weak, so a build with an empty table still links (dm_section says NULL then)
extern const char __start_swhle[] __attribute__((weak)), __stop_swhle[] __attribute__((weak));
extern const char __start_swforce[] __attribute__((weak)), __stop_swforce[] __attribute__((weak));
extern const char __start_swnvn[] __attribute__((weak)), __stop_swnvn[] __attribute__((weak));
const void *dm_section(const char *name, unsigned long *size) {
    const char *b = NULL, *e = NULL;
    if (!strcmp(name, "swhle")) { b = __start_swhle; e = __stop_swhle; }
    else if (!strcmp(name, "swforce")) { b = __start_swforce; e = __stop_swforce; }
    else if (!strcmp(name, "swnvn")) { b = __start_swnvn; e = __stop_swnvn; }
    else LOG("[RED] dm_section: %s is not a section this host registers (port_android.c lists swhle, swforce and swnvn)", name);
    *size = b && e > b ? (unsigned long)(e - b) : 0;
    return *size ? b : NULL;
}
// Apple's arm_thread_state64_t is x0..x28, fp, lr, sp, pc, cpsr; Linux's mcontext keeps regs[0..30], sp, pc, pstate in that order, so the state overlays regs[0] (pstate's low word is cpsr)
_Static_assert(offsetof(mcontext_t, sp) == offsetof(mcontext_t, regs) + 31 * 8 && offsetof(mcontext_t, pc) == offsetof(mcontext_t, sp) + 8 && offsetof(mcontext_t, pstate) == offsetof(mcontext_t, pc) + 8,
               "bionic's mcontext_t must keep regs, sp, pc, pstate contiguous for the arm_thread_state64_t overlay");
_Static_assert(offsetof(arm_thread_state64_t, __sp) == 31 * 8 && offsetof(arm_thread_state64_t, __pc) == 32 * 8 && offsetof(arm_thread_state64_t, __cpsr) == 33 * 8, "compat's arm_thread_state64_t layout");
arm_thread_state64_t *dm_uc_ss(ucontext_t *uc) { return (arm_thread_state64_t *)&uc->uc_mcontext.regs[0]; }
const dm_neon_t *dm_uc_ns(ucontext_t *uc, dm_neon_t *tmp) {
    // uc_mcontext.__reserved holds a chain of {magic, size} records; the fpsimd one (magic 0x46508001) is fpsr, fpcr, then vregs[32]
    const uint8_t *p = (const uint8_t *)uc->uc_mcontext.__reserved, *end = p + sizeof uc->uc_mcontext.__reserved;
    while (p + 8 <= end) {
        uint32_t magic, size; memcpy(&magic, p, 4); memcpy(&size, p + 4, 4);
        if (!magic || size < 8 || p + size > end) break;
        if (magic == 0x46508001u && size >= 8 + 8 + 32 * 16) {
            memcpy(&tmp->__fpsr, p + 8, 4); memcpy(&tmp->__fpcr, p + 12, 4); memcpy(tmp->__v, p + 16, sizeof tmp->__v);
            return tmp;
        }
        p += size;
    }
    return NULL;
}

int dm_uc_fault_write(ucontext_t *uc) {   // the esr record (magic 0x45535201: head, then the 64-bit ESR) of the same chain; WnR is bit 6
    const uint8_t *p = (const uint8_t *)uc->uc_mcontext.__reserved, *end = p + sizeof uc->uc_mcontext.__reserved;
    while (p + 8 <= end) {
        uint32_t magic, size; memcpy(&magic, p, 4); memcpy(&size, p + 4, 4);
        if (!magic || size < 8 || p + size > end) break;
        if (magic == 0x45535201u && size >= 16) { uint64_t esr; memcpy(&esr, p + 8, 8); return (int)((esr >> 6) & 1); }
        p += size;
    }
    return 0;
}

// ---- Mappings ----
int dm_vm_region(uintptr_t addr, uintptr_t *start, size_t *len, int *prot) {
    FILE *f = fopen("/proc/self/maps", "r"); if (!f) return -1;
    char line[512]; int found = -1;
    while (fgets(line, sizeof line, f)) {
        unsigned long long lo, hi; char perms[8];
        if (sscanf(line, "%llx-%llx %7s", &lo, &hi, perms) != 3) continue;
        if (addr < lo || addr >= hi) continue;
        *start = (uintptr_t)lo; *len = (size_t)(hi - lo);
        *prot = (perms[0] == 'r' ? PROT_READ : 0) | (perms[1] == 'w' ? PROT_WRITE : 0) | (perms[2] == 'x' ? PROT_EXEC : 0);
        found = 0; break;
    }
    fclose(f); return found;
}
void *dm_vm_alias(void *to, const void *from, size_t size) {
    static int said;
    if (!said++) LOG("[RED] dm_vm_alias: Linux cannot map an anonymous private page twice (mremap duplicates nothing); %zu bytes at %p are not aliased to %p. Virtual pools and the write watch need a memfd-backed guest block (open, port.h)", size, from, to);
    errno = ENOTSUP; return NULL;
}

// ---- Scheduling and power facts ----
int dm_thread_rt_set(uint64_t period_ns, uint64_t comp_ns) {
    static int said; if (!said++) LOG("thread policy: a time-constraint (real-time) policy is not available to an app on this platform (SCHED_FIFO needs CAP_SYS_NICE); the present thread keeps its class (asked period %.3f ms, computation %.3f ms)", period_ns / 1e6, comp_ns / 1e6);
    return -1;
}
int dm_thread_rt_live(void) { return 0; }
int dm_thread_sched(int *cur, int *base, int *policy) {
    errno = 0; int n = getpriority(PRIO_PROCESS, (id_t)gettid()); if (n == -1 && errno) return -1;
    *cur = *base = n; *policy = sched_getscheduler(0); return 0;
}
int dm_task_power(dm_task_power_t *out) {
    struct rusage ru; if (getrusage(RUSAGE_SELF, &ru)) return -1;
    memset(out, 0, sizeof *out);
    out->cpu_ns = ((uint64_t)ru.ru_utime.tv_sec + (uint64_t)ru.ru_stime.tv_sec) * 1000000000ull + ((uint64_t)ru.ru_utime.tv_usec + (uint64_t)ru.ru_stime.tv_usec) * 1000ull;
    static int said; if (!said++) LOG("power readout: the process's energy, performance-core time, wakeups and GPU time are Apple task_info facts and are not collected on this platform; only its CPU time is known");
    return -1;   // the callers print rates of all six: with five unknown the line would mislead, so they print nothing here
}
int dm_cpu_perf_levels(void) {   // one level per distinct maximum frequency among the CPUs (big.LITTLE: 2 or 3)
    DIR *d = opendir("/sys/devices/system/cpu"); if (!d) return 1;
    unsigned long freqs[8]; int nf = 0; struct dirent *e;
    while ((e = readdir(d))) {
        if (strncmp(e->d_name, "cpu", 3) || e->d_name[3] < '0' || e->d_name[3] > '9') continue;
        char p[128]; snprintf(p, sizeof p, "/sys/devices/system/cpu/%s/cpufreq/cpuinfo_max_freq", e->d_name);
        FILE *f = fopen(p, "r"); if (!f) continue;
        unsigned long v = 0; int ok = fscanf(f, "%lu", &v) == 1; fclose(f); if (!ok) continue;
        int k = 0; while (k < nf && freqs[k] != v) k++;
        if (k == nf && nf < 8) freqs[nf++] = v;
    }
    closedir(d);
    return nf ? nf : 1;
}
uint64_t dm_proc_start_ns(void) {   // /proc/self/stat field 22: start time in clock ticks since boot, on the same clock as CLOCK_BOOTTIME
    uint64_t mono = dm_clock_ns();
    FILE *f = fopen("/proc/self/stat", "r"); if (!f) return mono;
    char buf[1024]; size_t got = fread(buf, 1, sizeof buf - 1, f); fclose(f); buf[got] = 0;
    char *p = strrchr(buf, ')'); if (!p) return mono;   // the comm may hold spaces: fields are counted after its closing parenthesis
    unsigned long long start = 0; int field = 2;
    for (p++; *p && field < 22; p++) if (*p == ' ') { field++; if (field == 22) { start = strtoull(p + 1, NULL, 10); break; } }
    long hz = sysconf(_SC_CLK_TCK); if (hz <= 0 || field != 22) return mono;
    struct timespec bt; clock_gettime(CLOCK_BOOTTIME, &bt);
    uint64_t boot_ns = (uint64_t)bt.tv_sec * 1000000000ull + (uint64_t)bt.tv_nsec, start_ns = start * (1000000000ull / (uint64_t)hz);
    return boot_ns > start_ns && mono > boot_ns - start_ns ? mono - (boot_ns - start_ns) : mono;
}

// ---- A heap of its own: bionic's malloc, with usable sizes ----
struct dm_heap { const char *name; };
dm_heap_t *dm_heap_new(const char *name) { dm_heap_t *h = calloc(1, sizeof *h); if (h) h->name = name; return h; }
void *dm_heap_malloc(dm_heap_t *h, size_t n) { (void)h; return malloc(n); }
void *dm_heap_memalign(dm_heap_t *h, size_t align, size_t n) { (void)h; return memalign(align, n); }
void *dm_heap_realloc(dm_heap_t *h, void *p, size_t n) { (void)h; return realloc(p, n); }
void dm_heap_free(dm_heap_t *h, void *p) { (void)h; free(p); }
size_t dm_heap_size(dm_heap_t *h, const void *p) { (void)h; return malloc_usable_size((void *)p); }

// ---- The guest's thread slots (port.h dm_kslot_*) ----
// Rewritten guest code (patch_nso.py --target=android) reads mrs tpidr_el0, loads the word TLS_SLOT_APP of bionic's thread control block, adds key × 8 from the module's key
// page and loads or stores there. That word holds this thread's table: word 0 a tag that says the table is this host's, words 1..4 the slots under the key numbers
// dm_kslot_new hands out (0 is never a key, so a key page entry is never 0 and the loader's check of it holds as on Apple). bionic's tls_defines.h gives the other words of the
// control block to the dynamic linker (DTV, 0), the thread id (1), the GL / GLES loader (3, 4), the stack guard (5), the sanitizers (6) and ART (7); TLS_SLOT_APP (2) is the
// app's from Android 10 (it was errno before: hence API 29 in dm/android/CMakeLists.txt). Nothing else in this process may use it, so set refuses a word it did not write. The
// table is ELF TLS: it lives exactly as long as its thread, as the control block does. get reads only the control block, never the TLS variable (whose first touch in a dlopen'd
// library allocates), so it is safe in a signal handler (hle_thread.c's pause signal reads x18 there).
#define KSLOT_WORDS 5
#define KSLOT_TAG 0x31746f6c736b6d64ull   // "dmkslot1"
#define KSLOT_STR2(x) #x
#define KSLOT_STR(x) KSLOT_STR2(x)
static __thread uint64_t g_kslot[KSLOT_WORDS];
static _Atomic int g_kslot_next = 1;
static uint64_t *volatile *kslot_tp_word(void) { char *tp; __asm__ volatile("mrs %0, tpidr_el0" : "=r"(tp)); return (uint64_t *volatile *)(tp + DM_KSLOT_TP_OFF); }
int dm_kslot_new(pthread_key_t *k) {
    // The build's ANDROID_PLATFORM floor (29) says what the NDK may call, not what the device runs: on an older device word 2 is errno, which the slot table would
    // overwrite and every libc call would then scribble over. Refused there (the loader stops: "cannot create the host key")
    int api = android_get_device_api_level();
    if (api < 29) { LOG("[RED] guest thread slots: this device runs API level %d; bionic gives TLS_SLOT_APP to the app only from 29 (it holds errno before), so the rewritten guest code cannot run here", api); return ENOTSUP; }
    int n = atomic_fetch_add(&g_kslot_next, 1);
    if (n >= KSLOT_WORDS) { LOG("[RED] dm_kslot_new: the guest slot table has %d slots and all are taken", KSLOT_WORDS - 1); return EAGAIN; }
    *k = (pthread_key_t)n; return 0;
}
void *dm_kslot_get(pthread_key_t k) {
    uint64_t *t = *kslot_tp_word();
    return t && k > 0 && k < KSLOT_WORDS && t[0] == KSLOT_TAG ? (void *)(uintptr_t)t[k] : NULL;
}
int dm_kslot_set(pthread_key_t k, const void *v) {
    if (k <= 0 || k >= KSLOT_WORDS) return EINVAL;
    uint64_t *volatile *w = kslot_tp_word(), *t = *w;
    if (!t) { g_kslot[0] = KSLOT_TAG; *w = t = g_kslot; }
    else if (t != g_kslot) {   // fatal either way: overwriting breaks the word's owner, leaving it breaks every rewritten site on this thread
        LOG("[RED] guest thread slots: bionic's TLS_SLOT_APP of thread %d holds %p, not this host's table: another component of the process uses the app's TLS slot (docs/reference/android.md)", (int)gettid(), (void *)t);
        abort();
    }
    t[k] = (uint64_t)(uintptr_t)v; return 0;
}
uint64_t dm_kslot_guest_read(uint64_t key_off) {   // the instructions patch_nso.py emit_thread_base + emit_slot_addr + the slot load emit, in that order
    uint64_t v;
    __asm__ volatile("mrs %0, tpidr_el0\n\tldr %0, [%0, #" KSLOT_STR(DM_KSLOT_TP_OFF) "]\n\tadd %0, %0, %1\n\tldr %0, [%0]" : "=&r"(v) : "r"(key_off) : "memory");
    return v;
}

// ---- Semaphore, deferred call, SIGTERM ----
struct dm_sem { pthread_mutex_t mu; pthread_cond_t cv; long n; };
dm_sem_t dm_sem_new(long value) {
    dm_sem_t s = calloc(1, sizeof *s); if (!s) return NULL;
    pthread_condattr_t a; pthread_condattr_init(&a); pthread_condattr_setclock(&a, CLOCK_MONOTONIC);
    pthread_mutex_init(&s->mu, NULL); pthread_cond_init(&s->cv, &a); pthread_condattr_destroy(&a); s->n = value;
    return s;
}
void dm_sem_signal(dm_sem_t s) { pthread_mutex_lock(&s->mu); s->n++; pthread_cond_signal(&s->cv); pthread_mutex_unlock(&s->mu); }
int dm_sem_wait(dm_sem_t s, int64_t timeout_ns) {
    struct timespec dl; if (timeout_ns >= 0) { clock_gettime(CLOCK_MONOTONIC, &dl); uint64_t ns = (uint64_t)dl.tv_nsec + (uint64_t)timeout_ns; dl.tv_sec += (time_t)(ns / 1000000000ull); dl.tv_nsec = (long)(ns % 1000000000ull); }
    pthread_mutex_lock(&s->mu); int r = 0;
    while (s->n <= 0 && !r) r = timeout_ns < 0 ? pthread_cond_wait(&s->cv, &s->mu) : pthread_cond_timedwait(&s->cv, &s->mu, &dl);
    if (!r) s->n--;
    pthread_mutex_unlock(&s->mu);
    return r ? -1 : 0;
}
void dm_sem_free(dm_sem_t s) { if (!s) return; pthread_cond_destroy(&s->cv); pthread_mutex_destroy(&s->mu); free(s); }
typedef struct { uint64_t ns; void (*fn)(void *); void *arg; } after_t;
static void *after_run(void *p) { after_t a = *(after_t *)p; free(p); struct timespec ts = {(time_t)(a.ns / 1000000000ull), (long)(a.ns % 1000000000ull)}; while (nanosleep(&ts, &ts) && errno == EINTR) {} a.fn(a.arg); return NULL; }
void dm_after_ns(uint64_t ns, void (*fn)(void *), void *arg) {
    after_t *a = malloc(sizeof *a); if (!a) { fn(arg); return; }
    *a = (after_t){ns, fn, arg};
    pthread_t t; pthread_attr_t at; pthread_attr_init(&at); pthread_attr_setdetachstate(&at, PTHREAD_CREATE_DETACHED);
    if (pthread_create(&t, &at, after_run, a)) { free(a); fn(arg); }
    pthread_attr_destroy(&at);
}
// SIGTERM: a handler installed for the whole process (whichever thread the kernel picks runs it) writes one byte to a pipe, the only thing a handler may do here, and a thread
// blocked on that pipe calls fn on an ordinary stack. Blocking the signal and sigwait-ing would miss it in threads that already exist with it unblocked.
// The write end is non-blocking: signals faster than the thread reads fill the pipe, and then the handler drops a byte instead of blocking (one pending byte already calls fn).
// A second call only replaces fn (one pipe, one thread, one handler). If the reader ever stops (read() == 0 would mean every write end is closed, and reading again would
// return 0 at once: a spin), it says so and gives SIGTERM its default action back, so the signal still ends the process
typedef void (*term_fn_t)(const char *);
static _Atomic(term_fn_t) g_term_fn;
static int g_term_pipe[2] = {-1, -1};
static void on_term(int sig) { (void)sig; int e = errno; uint8_t b = 1; if (g_term_pipe[1] >= 0 && write(g_term_pipe[1], &b, 1) < 0) {} errno = e; }
static void *term_wait(void *p) {
    (void)p;
    for (;;) {
        uint8_t b; ssize_t k = read(g_term_pipe[0], &b, 1);
        if (k == 1) { atomic_load(&g_term_fn)("SIGTERM"); continue; }
        if (k < 0 && errno == EINTR) continue;
        int e = k ? errno : 0;
        signal(SIGTERM, SIG_DFL);
        LOG("[RED] SIGTERM: the hand-off pipe %s (errno %d); SIGTERM has its default action again", k ? "cannot be read" : "was closed", e);
        return NULL;
    }
}
void dm_on_sigterm(void (*fn)(const char *)) {
    static pthread_mutex_t mu = PTHREAD_MUTEX_INITIALIZER;
    pthread_mutex_lock(&mu);
    atomic_store(&g_term_fn, fn);
    if (g_term_pipe[0] >= 0) { pthread_mutex_unlock(&mu); return; }   // installed already
    int fds[2] = {-1, -1};
    if (pipe2(fds, O_CLOEXEC) || fcntl(fds[1], F_SETFL, O_NONBLOCK)) {
        LOG("[RED] SIGTERM: no pipe for the handler (errno %d); the default action stays", errno);
        if (fds[0] >= 0) { close(fds[0]); close(fds[1]); }
        pthread_mutex_unlock(&mu); return;
    }
    g_term_pipe[0] = fds[0]; g_term_pipe[1] = fds[1];
    pthread_t t; pthread_attr_t at; pthread_attr_init(&at); pthread_attr_setdetachstate(&at, PTHREAD_CREATE_DETACHED);
    if (pthread_create(&t, &at, term_wait, NULL)) {
        LOG("[RED] SIGTERM: cannot start the thread that waits for it; the default action stays");
        pthread_attr_destroy(&at); close(fds[0]); close(fds[1]); g_term_pipe[0] = g_term_pipe[1] = -1; pthread_mutex_unlock(&mu); return;
    }
    pthread_attr_destroy(&at);
    struct sigaction sa; memset(&sa, 0, sizeof sa); sa.sa_handler = on_term; sa.sa_flags = SA_RESTART; sigemptyset(&sa.sa_mask);
    if (sigaction(SIGTERM, &sa, NULL)) LOG("[RED] SIGTERM: sigaction failed (errno %d); the default action stays", errno);
    pthread_mutex_unlock(&mu);
}

// ---- The capture codec ----
size_t dm_compress(void *dst, size_t cap, const void *src, size_t n) { (void)dst; (void)cap; (void)src; (void)n; return 0; }   // no LZFSE here: nvn_capture.c stores the chunk raw
size_t dm_decompress(void *dst, size_t cap, const void *src, size_t n) {
    (void)dst; (void)cap; (void)src; (void)n;
    static int said; if (!said++) LOG("[RED] an LZFSE-compressed capture cannot be read on this platform (no LZFSE decoder in the tree); captures written here are raw");
    return 0;
}
