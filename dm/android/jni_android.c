#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <jni.h>
#include <android/log.h>
#include <android/native_window.h>
#include <android/native_window_jni.h>
#include <pthread.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#include "../host/dm.h"
#include "../host/front.h"
#include "../host/dm_input.h"
#include "vulkan_present.h"

// Front-end window and refresh setters (from dm/android/front_android.c)
void front_android_set_window(void *win, int w, int h);
void front_android_set_refresh(float hz);

// Bootstrap entry points (from dm/host/main.c compiled with -Dmain=dm_main)
int dm_main(int argc, char **argv);
void dm_host_preload_start(int argc, char **argv);

// ---- Log redirection to Android logcat ("dm") ----
static int g_log_pipe[2] = {-1, -1};
static pthread_t g_log_thread;
static _Atomic int g_log_started = 0;

static void *log_worker(void *arg) {
    (void)arg;
    int fd = g_log_pipe[0];
    FILE *f = fdopen(fd, "r");
    if (!f) return NULL;

    char line[2048];
    while (fgets(line, sizeof(line), f)) {
        size_t len = strlen(line);
        if (len > 0 && line[len - 1] == '\n') line[--len] = '\0';
        if (len > 0 && line[len - 1] == '\r') line[--len] = '\0';

        int prio = ANDROID_LOG_INFO;
        if (strstr(line, "[RED] ") || strstr(line, "fatal") || strstr(line, "die:")) {
            prio = ANDROID_LOG_ERROR;
        } else if (strstr(line, "warning") || strstr(line, "warn")) {
            prio = ANDROID_LOG_WARN;
        }
        __android_log_print(prio, "dm", "%s", line);
    }
    fclose(f);
    return NULL;
}

static void start_log_redirection(void) {
    if (atomic_exchange(&g_log_started, 1)) return;
    if (pipe(g_log_pipe) != 0) return;

    dup2(g_log_pipe[1], STDOUT_FILENO);
    dup2(g_log_pipe[1], STDERR_FILENO);

    setvbuf(stdout, NULL, _IOLBF, 0);
    setvbuf(stderr, NULL, _IOLBF, 0);

    pthread_attr_t attr;
    pthread_attr_init(&attr);
    pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_DETACHED);
    pthread_create(&g_log_thread, &attr, log_worker, NULL);
    pthread_attr_destroy(&attr);
}

// ---- Window / Surface management ----
static ANativeWindow *g_current_window = NULL;
static pthread_mutex_t g_window_mu = PTHREAD_MUTEX_INITIALIZER;

static void nativeSetSurface(JNIEnv *env, jclass clazz, jobject surface, jint width, jint height) {
    (void)clazz;
    pthread_mutex_lock(&g_window_mu);
    ANativeWindow *win = surface ? ANativeWindow_fromSurface(env, surface) : NULL;
    if (win == g_current_window && win != NULL) {
        front_android_set_window(win, (int)width, (int)height);
        ANativeWindow_release(win);
        pthread_mutex_unlock(&g_window_mu);
        return;
    }
    if (g_current_window) {
        dm_android_vk_set_window(NULL);
        front_android_set_window(NULL, 0, 0);
        ANativeWindow_release(g_current_window);
        g_current_window = NULL;
    }
    if (win) {
        g_current_window = win; // retain the ref from ANativeWindow_fromSurface
        front_android_set_window(win, (int)width, (int)height);
        dm_android_vk_set_window(win);
    }
    pthread_mutex_unlock(&g_window_mu);
}

static void nativeSurfaceDestroyed(JNIEnv *env, jclass clazz) {
    (void)env; (void)clazz;
    pthread_mutex_lock(&g_window_mu);
    if (g_current_window) {
        dm_android_vk_set_window(NULL);
        front_android_set_window(NULL, 0, 0);
        ANativeWindow_release(g_current_window);
        g_current_window = NULL;
    }
    pthread_mutex_unlock(&g_window_mu);
}

static void nativeSetRefreshRate(JNIEnv *env, jclass clazz, jfloat hz) {
    (void)env; (void)clazz;
    front_android_set_refresh((float)hz);
}

// ---- Input Bridge ----
static void nativeSendTouch(JNIEnv *env, jclass clazz, jint count, jintArray ids, jfloatArray xs, jfloatArray ys) {
    (void)clazz;
    if (count <= 0 || !ids || !xs || !ys) {
        dm_touch_set(NULL, 0);
        return;
    }
    jsize len_ids = (*env)->GetArrayLength(env, ids);
    jsize len_xs = (*env)->GetArrayLength(env, xs);
    jsize len_ys = (*env)->GetArrayLength(env, ys);
    jsize min_len = len_ids < len_xs ? len_ids : len_xs;
    if (len_ys < min_len) min_len = len_ys;
    if (count > min_len) count = (jint)min_len;
    if (count > 16) count = 16;
    if (count <= 0) {
        dm_touch_set(NULL, 0);
        return;
    }
    jint id_buf[16];
    jfloat x_buf[16];
    jfloat y_buf[16];
    (*env)->GetIntArrayRegion(env, ids, 0, count, id_buf);
    (*env)->GetFloatArrayRegion(env, xs, 0, count, x_buf);
    (*env)->GetFloatArrayRegion(env, ys, 0, count, y_buf);
    dm_touch touches[16];
    for (int i = 0; i < count; i++) {
        touches[i].id = (uint32_t)id_buf[i];
        touches[i].x = x_buf[i];
        touches[i].y = y_buf[i];
    }
    dm_touch_set(touches, (int)count);
}

static void nativeSendPad(JNIEnv *env, jclass clazz, jint player, jlong buttons, jint lx, jint ly, jint rx, jint ry) {
    (void)env; (void)clazz;
    dm_pad_set_player((int)player, (uint64_t)buttons, (int32_t)lx, (int32_t)ly, (int32_t)rx, (int32_t)ry);
}

static void nativeSendPadPlayers(JNIEnv *env, jclass clazz, jint mask) {
    (void)env; (void)clazz;
    dm_pad_players((uint32_t)mask);
}

static void nativeSendInput(JNIEnv *env, jclass clazz, jlong buttons, jint lx, jint ly, jint rx, jint ry) {
    (void)env; (void)clazz;
    dm_input_set((uint64_t)buttons, (int32_t)lx, (int32_t)ly, (int32_t)rx, (int32_t)ry);
}

// ---- Lifecycle & Host Thread ----
static _Atomic int g_host_running = 0;
static pthread_t g_host_thread;

typedef struct {
    int argc;
    char **argv;
    char *shader_dir;
    char *game_dir;
} host_args_t;

static void *host_thread_entry(void *arg) {
    host_args_t *ha = (host_args_t *)arg;
    pthread_setname_np(pthread_self(), "dm-host");

    // Signal alternate stack for crash reporting on the host thread
    static char alt[65536];
    stack_t ss = {.ss_sp = alt, .ss_size = sizeof alt};
    sigaltstack(&ss, NULL);

    LOG("host thread: initializing Vulkan with shader directory %s", ha->shader_dir);
    char err[256] = {0};
    int vk_rc = dm_android_vk_initialize(ha->shader_dir, err, sizeof err);
    if (vk_rc != 0) {
        LOG("[RED] host thread: dm_android_vk_initialize failed: %s (code %d)", err, vk_rc);
    } else {
        LOG("host thread: Vulkan initialized successfully");
    }

    LOG("host thread: entering dm_main (argc=%d)", ha->argc);
    int rc = dm_main(ha->argc, ha->argv);
    LOG("host thread: dm_main returned %d", rc);

    atomic_store(&g_host_running, 0);

    for (int i = 0; i < ha->argc; i++) free(ha->argv[i]);
    free(ha->argv);
    free(ha->shader_dir);
    free(ha->game_dir);
    free(ha);
    return NULL;
}

static jboolean nativeStartHost(JNIEnv *env, jclass clazz, jstring gameDir, jstring shaderDir, jstring romfsDir, jstring saveDir, jobjectArray extraArgs) {
    (void)clazz;
    if (atomic_exchange(&g_host_running, 1)) {
        LOG("[RED] nativeStartHost: host is already running");
        return JNI_FALSE;
    }

    if (!gameDir || !shaderDir) {
        LOG("[RED] nativeStartHost: gameDir and shaderDir are required");
        atomic_store(&g_host_running, 0);
        return JNI_FALSE;
    }

    const char *game_str = (*env)->GetStringUTFChars(env, gameDir, NULL);
    const char *shader_str = (*env)->GetStringUTFChars(env, shaderDir, NULL);
    const char *romfs_str = romfsDir ? (*env)->GetStringUTFChars(env, romfsDir, NULL) : NULL;
    const char *save_str = saveDir ? (*env)->GetStringUTFChars(env, saveDir, NULL) : NULL;

    jboolean started = JNI_FALSE;
    if (!game_str || !shader_str) {
        LOG("[RED] nativeStartHost: GetStringUTFChars failed for gameDir or shaderDir");
        atomic_store(&g_host_running, 0);
        goto cleanup_strings;
    }

    if (romfs_str && *romfs_str) {
        setenv("DM_ROMFS", romfs_str, 1);
        LOG("nativeStartHost: setenv DM_ROMFS=%s", romfs_str);
    }
    if (save_str && *save_str) {
        setenv("DM_SAVE", save_str, 1);
        char temp_dir[1024];
        snprintf(temp_dir, sizeof(temp_dir), "%s/temp", save_str);
        mkdir(temp_dir, 0755);
        setenv("DM_TEMP", temp_dir, 0);
        LOG("nativeStartHost: setenv DM_SAVE=%s, DM_TEMP=%s", save_str, temp_dir);
    }
    if (shader_str && *shader_str) {
        char shmap_path[1024];
        snprintf(shmap_path, sizeof(shmap_path), "%s/shader_map.tsv", shader_str);
        struct stat st;
        if (stat(shmap_path, &st) == 0) {
            setenv("DM_NVN_SHMAP", shmap_path, 0);
            LOG("nativeStartHost: found shader_map.tsv: %s", shmap_path);
        }
    }
    if (game_str && *game_str && !getenv("DM_NVN_SHMAP")) {
        char shmap_game[1024];
        snprintf(shmap_game, sizeof(shmap_game), "%s/shader_map.tsv", game_str);
        struct stat st;
        if (stat(shmap_game, &st) == 0) {
            setenv("DM_NVN_SHMAP", shmap_game, 0);
            LOG("nativeStartHost: found shader_map.tsv in game dir: %s", shmap_game);
        }
    }

    const char *sys_font = "/system/fonts/Roboto-Regular.ttf";
    if (access(sys_font, R_OK) == 0) {
        setenv("DM_SHARED_FONT", sys_font, 0);
        LOG("nativeStartHost: setenv DM_SHARED_FONT=%s", sys_font);
    }
    if (shader_str && *shader_str) {
        setenv("DM_FONT_DIR", shader_str, 0);
    }

    // Docked mode default (1080p crisp graphics)
    setenv("DM_OPMODE", "1", 1); // 1 = Docked/Console mode (1080p)
    LOG("nativeStartHost: DM_OPMODE=%s", getenv("DM_OPMODE"));

    // Enable AAudio real audio by default on Android
    setenv("DM_AUDIO", "1", 0);

    // Set working directory
    if (save_str && *save_str) {
        chdir(save_str);
    } else if (game_str && *game_str) {
        chdir(game_str);
    }

    // Build argc / argv
    int max_args = 64;
    char **argv = calloc((size_t)max_args, sizeof(char *));
    argv[0] = strdup("dmhost");
    argv[1] = strdup(game_str);
    int argc = 2;

    if (extraArgs) {
        jsize count = (*env)->GetArrayLength(env, extraArgs);
        for (jsize i = 0; i < count && argc < max_args - 1; i++) {
            jstring arg_str = (jstring)(*env)->GetObjectArrayElement(env, extraArgs, i);
            if (arg_str) {
                const char *s = (*env)->GetStringUTFChars(env, arg_str, NULL);
                if (s) {
                    argv[argc++] = strdup(s);
                    (*env)->ReleaseStringUTFChars(env, arg_str, s);
                }
                (*env)->DeleteLocalRef(env, arg_str);
            }
        }
    }

    host_args_t *ha = malloc(sizeof(*ha));
    ha->argc = argc;
    ha->argv = argv;
    ha->shader_dir = strdup(shader_str);
    ha->game_dir = strdup(game_str);

    // Start background loading early before Vulkan waits for window
    dm_host_preload_start(ha->argc, ha->argv);

    pthread_attr_t attr;
    pthread_attr_init(&attr);
    pthread_attr_setstacksize(&attr, 64 * 1024 * 1024); // 64 MiB guest stack
    int rc = pthread_create(&g_host_thread, &attr, host_thread_entry, ha);
    pthread_attr_destroy(&attr);
    if (rc != 0) {
        LOG("[RED] nativeStartHost: pthread_create failed (errno %d)", rc);
        atomic_store(&g_host_running, 0);
        for (int i = 0; i < ha->argc; i++) free(ha->argv[i]);
        free(ha->argv);
        free(ha->shader_dir);
        free(ha->game_dir);
        free(ha);
        goto cleanup_strings;
    }
    pthread_detach(g_host_thread);
    started = JNI_TRUE;

cleanup_strings:
    if (game_str) (*env)->ReleaseStringUTFChars(env, gameDir, game_str);
    if (shader_str) (*env)->ReleaseStringUTFChars(env, shaderDir, shader_str);
    if (romfs_str) (*env)->ReleaseStringUTFChars(env, romfsDir, romfs_str);
    if (save_str) (*env)->ReleaseStringUTFChars(env, saveDir, save_str);
    return started;
}

static jboolean nativeIsRunning(JNIEnv *env, jclass clazz) {
    (void)env; (void)clazz;
    return atomic_load(&g_host_running) ? JNI_TRUE : JNI_FALSE;
}

static void nativeStopHost(JNIEnv *env, jclass clazz) {
    (void)env; (void)clazz;
    if (atomic_load(&g_host_running)) {
        LOG("nativeStopHost: raising SIGTERM to initiate graceful exit");
        raise(SIGTERM);
    }
}

// ---- JNI Native Registration and JNI_OnLoad ----
static const JNINativeMethod k_methods[] = {
    {"nativeStartHost", "(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;[Ljava/lang/String;)Z", (void *)nativeStartHost},
    {"nativeStopHost", "()V", (void *)nativeStopHost},
    {"nativeIsRunning", "()Z", (void *)nativeIsRunning},
    {"nativeSetSurface", "(Landroid/view/Surface;II)V", (void *)nativeSetSurface},
    {"nativeSurfaceDestroyed", "()V", (void *)nativeSurfaceDestroyed},
    {"nativeSetRefreshRate", "(F)V", (void *)nativeSetRefreshRate},
    {"nativeSendTouch", "(I[I[F[F)V", (void *)nativeSendTouch},
    {"nativeSendPad", "(IJIIII)V", (void *)nativeSendPad},
    {"nativeSendPadPlayers", "(I)V", (void *)nativeSendPadPlayers},
    {"nativeSendInput", "(JIIII)V", (void *)nativeSendInput},
};

static void register_class_natives(JNIEnv *env, const char *class_name) {
    jclass cls = (*env)->FindClass(env, class_name);
    if (cls) {
        if ((*env)->RegisterNatives(env, cls, k_methods, (jint)(sizeof(k_methods) / sizeof(k_methods[0]))) != 0) {
            (*env)->ExceptionClear(env);
        }
        (*env)->DeleteLocalRef(env, cls);
    } else {
        (*env)->ExceptionClear(env);
    }
}

JNIEXPORT jint JNI_OnLoad(JavaVM *vm, void *reserved) {
    (void)reserved;
    JNIEnv *env = NULL;
    if ((*vm)->GetEnv(vm, (void **)&env, JNI_VERSION_1_6) != JNI_OK) {
        return JNI_ERR;
    }

    start_log_redirection();

    register_class_natives(env, "com/nxdroid/NativeBridge");
    if ((*env)->ExceptionCheck(env)) {
        (*env)->ExceptionClear(env);
    }

    return JNI_VERSION_1_6;
}

// Exported symbols for static JNI method resolution
#define JNI_EXPORT_BRIDGE(name, ret, sig_args, call_args) \
    JNIEXPORT ret JNICALL Java_com_nxdroid_NativeBridge_##name sig_args { return name call_args; } \
    JNIEXPORT ret JNICALL Java_com_nxdroid_MainActivity_##name sig_args { return name call_args; }

#define JNI_EXPORT_BRIDGE_VOID(name, sig_args, call_args) \
    JNIEXPORT void JNICALL Java_com_nxdroid_NativeBridge_##name sig_args { name call_args; } \
    JNIEXPORT void JNICALL Java_com_nxdroid_MainActivity_##name sig_args { name call_args; }

JNI_EXPORT_BRIDGE(nativeStartHost, jboolean, (JNIEnv *env, jclass clazz, jstring a, jstring b, jstring c, jstring d, jobjectArray e), (env, clazz, a, b, c, d, e))
JNI_EXPORT_BRIDGE_VOID(nativeStopHost, (JNIEnv *env, jclass clazz), (env, clazz))
JNI_EXPORT_BRIDGE(nativeIsRunning, jboolean, (JNIEnv *env, jclass clazz), (env, clazz))
JNI_EXPORT_BRIDGE_VOID(nativeSetSurface, (JNIEnv *env, jclass clazz, jobject s, jint w, jint h), (env, clazz, s, w, h))
JNI_EXPORT_BRIDGE_VOID(nativeSurfaceDestroyed, (JNIEnv *env, jclass clazz), (env, clazz))
JNI_EXPORT_BRIDGE_VOID(nativeSetRefreshRate, (JNIEnv *env, jclass clazz, jfloat hz), (env, clazz, hz))
JNI_EXPORT_BRIDGE_VOID(nativeSendTouch, (JNIEnv *env, jclass clazz, jint c, jintArray i, jfloatArray x, jfloatArray y), (env, clazz, c, i, x, y))
JNI_EXPORT_BRIDGE_VOID(nativeSendPad, (JNIEnv *env, jclass clazz, jint p, jlong b, jint lx, jint ly, jint rx, jint ry), (env, clazz, p, b, lx, ly, rx, ry))
JNI_EXPORT_BRIDGE_VOID(nativeSendPadPlayers, (JNIEnv *env, jclass clazz, jint m), (env, clazz, m))
JNI_EXPORT_BRIDGE_VOID(nativeSendInput, (JNIEnv *env, jclass clazz, jlong b, jint lx, jint ly, jint rx, jint ry), (env, clazz, b, lx, ly, rx, ry))
