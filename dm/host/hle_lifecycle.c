// Host lifecycle: graceful exit (SIGTERM; on iOS the App termination callback calls dm_host_shutdown).
// Pause audio, suspend graphics (wait for in-flight NVN calls to end and drain GPU work), then _exit(0); a 1.5 s fallback goes straight to _exit(0).
// The default action also exits in about 0.08 s (exit code 143); the value of this function is stopping background threads in order, exit code 0, and giving the iOS lifecycle callback an entry.
#include "hle.h"
#include "port.h"   // dm_after_ns, dm_on_sigterm: GCD on Apple; on bionic a timer thread, and a SIGTERM handler writing a self-pipe that a thread reads
#include <stdatomic.h>
#include <signal.h>
#include <unistd.h>
void hlecount_flush(void);
static void exit_late(void *arg) { (void)arg; LOG("[RED] graceful exit not done in 1.5 seconds, exiting at once"); _exit(0); }
void dm_host_shutdown(const char *why) {
    static _Atomic int once; if (atomic_exchange(&once, 1)) return;
    uint64_t t0 = now_ns(); LOG("received %s: graceful exit", why);
    dm_after_ns(1500000000ull, exit_late, NULL);
    hlecount_flush();                               // DM_HLECOUNT: _exit does not run atexit, write a copy here
    dm_audio_suspend(1);
    dm_gfx_suspend(1);
    LOG("graceful exit done (%.3f s)", (now_ns() - t0) / 1e9);
    _exit(0);
}
void dm_term_install(void) {
    dm_on_sigterm(dm_host_shutdown);   // not the default action: the signal is handed to an ordinary thread to wrap up
}
