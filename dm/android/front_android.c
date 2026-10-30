// Android front end: the Android implementation of dm/host/front.h (the counterpart of Mac's front_mac.m and iOS's front_ios.m), for any game
// profile (nothing of one game lives here; the host takes its constants from game_profile.h).
// Two forms:
//   Command line (dmhost run directly from adb shell, for development checks): no window, front_run runs the guest directly on the current
//   thread, front_metal_layer is NULL (the graphics layer takes the no-window path).
//   App (a Java shell hands over an ANativeWindow through JNI, not imported yet): the guest runs on its own thread, started by the JNI side before
//   dm_main, and front_metal_layer returns the ANativeWindow* (the surface vulkan_present.cpp presents to).
// What the window and the screen are is pushed in by the shell through front_android_set_window / front_android_set_refresh; nothing here calls
// into Java, so the command-line form needs no shell.
#include "../host/dm.h"
#include "../host/front.h"
#include <math.h>
#include <stdatomic.h>

static void *_Atomic g_window;              // ANativeWindow*; NULL in the command-line form
static _Atomic int g_screen_w, g_screen_h;
void front_android_set_window(void *win, int w, int h) { atomic_store(&g_window, win); atomic_store(&g_screen_w, w); atomic_store(&g_screen_h, h); }

// front.h asks for the screen's highest refresh rate (front_screen_max_fps; on a Mac the display mode's rate). The shell has Display.getRefreshRate(),
// the rate of the mode the system chose now, and that is what it pushes in here: on an adaptive panel (the S23 Ultra: 1-120 Hz) that is the current
// rate, not the maximum, and the host's pacing (hle_nvn.c g_fs.shown_slack, mtl_display_hz) sees it change with the system's choice. The highest
// supported rate would be the maximum over Display.getSupportedModes(): a shell that has it should push that instead. 0 means unknown, not a guessed 60 Hz.
static _Atomic int g_refresh_millihz;
void front_android_set_refresh(float hz) {
    atomic_store(&g_refresh_millihz, isfinite(hz) && hz > 0 && hz < 1000 ? (int)lroundf(hz * 1000) : 0);
}
int front_screen_max_fps(void) { return (atomic_load(&g_refresh_millihz) + 500) / 1000; }
// A phone's display mode is the system's to switch (the shell may ask for a preferred refresh rate; a Mac switches the screen mode here): nothing to do.
void front_screen_match(int fps) { (void)fps; }

void *front_metal_layer(void) { return atomic_load(&g_window); }

// Both forms run the guest on the calling thread: in the App form the JNI side starts the guest thread first and then enters dm_main.
void front_run(void (*guest)(void)) { guest(); }

// The first-start prepare screen ("Preparing shaders", nvn_mtl.m warm_prepare on Apple): the Vulkan replay has no prewarm step yet and the
// command-line form has no view, so progress goes to the log once per title, where the shell can pick it up later.
void front_progress(const char *title, long done, long total) {
    static const char *_Atomic last;   // front.h: any thread
    if (!title) { atomic_store(&last, NULL); return; }
    if (atomic_exchange(&last, title) != title) LOG("front_progress: %s", title);
    (void)done; (void)total;
}

// Text input box (the software keyboard, hle_swkbd.c): the App shell overrides front_android_text_input with the system input box; the
// command-line form has no window and returns -1, which front.h defines as "nothing shown".
__attribute__((weak)) int front_android_text_input(const char *title, const char *sub, const char *guide, const char *initial, int max_chars, char *out, int out_cap) {
    (void)title; (void)sub; (void)guide; (void)initial; (void)max_chars; (void)out; (void)out_cap; return -1;
}
int front_text_input(const char *title, const char *sub, const char *guide, const char *initial, int max_chars, char *out, int out_cap) {
    if (!front_metal_layer()) return -1;
    return front_android_text_input(title, sub, guide, initial, max_chars, out, out_cap);
}
