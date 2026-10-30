// Desktop smoke test for the vendored Vulkan replay engine (dm/gfx/vulkan/engine): creates the
// Vulkan objects xbg_game_config asks for, hands them to xbg_game_initialize and shuts down again.
// No window, no surface, no guest memory, no shader directory contents: this measures how far the
// engine gets with what a desktop machine can give it.
//
// The device is the machine's default unless SMOKE_DEVICE names one (substring match on the Vulkan
// device name); `make run` restricts the ICD to Mesa lavapipe.
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <vulkan/vulkan.h>

#include "xbg_game.h"

static int g_presents;
static int g_fatals;
static int g_logs;

static void on_log(void *userdata, const char *message) {
    (void)userdata;
    ++g_logs;
    fprintf(stdout, "[xbg] %s\n", message);
    fflush(stdout);
}

static void on_fatal(void *userdata, const char *message) {
    (void)userdata;
    ++g_fatals;
    fprintf(stdout, "[xbg] fatal: %s\n", message ? message : "(null message)");
    fflush(stdout);
    // The real host unwinds the guest here; the harness has no guest to unwind, so it stops loudly.
    exit(97);
}

// The contract asks for a synchronous present that leaves the image in TRANSFER_SRC_OPTIMAL.
// Nothing in this harness submits a draw yet, so counting calls is the whole job.
static int on_present(void *userdata, void *native_window, VkImage image, VkFormat format,
                      uint32_t width, uint32_t height, const int32_t crop[4], int32_t interval) {
    (void)userdata; (void)native_window; (void)image; (void)format; (void)crop; (void)interval;
    ++g_presents;
    fprintf(stdout, "present #%d %ux%u\n", g_presents, width, height);
    return 0;
}

// A stand-in for the NVN entry table (hle_nvn.c provides the real one; see README.md). One entry is
// enough to exercise the path: it must be callable from the guest ABI, so it takes the NVN device
// pointer and two ints and writes a value.
static int smoke_nvn_device_get_integer(void *device, int info, int *out) {
    (void)device;
    if (out) *out = info;
    return 0;
}

typedef struct { const char *name; void *function; } smoke_entry;

void *xbg_nvn_get_proc_address(const char *name) {
    static const smoke_entry table[] = {
        {"nvnDeviceGetInteger", (void *)smoke_nvn_device_get_integer},
    };
    if (!name) return NULL;
    for (size_t i = 0; i < sizeof table / sizeof *table; ++i)
        if (!strcmp(table[i].name, name)) return table[i].function;
    return NULL;
}

static int fail(const char *what, VkResult r) {
    fprintf(stderr, "[RED] engine_smoke: %s failed (%d)\n", what, (int)r);
    return 1;
}

int main(void) {
    int rc = 1;
    VkInstance instance = VK_NULL_HANDLE;
    VkDevice device = VK_NULL_HANDLE;
    VkQueue queue = VK_NULL_HANDLE;

    VkApplicationInfo app = {VK_STRUCTURE_TYPE_APPLICATION_INFO};
    app.pApplicationName = "engine_smoke";
    app.apiVersion = VK_API_VERSION_1_1;
    VkInstanceCreateInfo ici = {VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO};
    ici.pApplicationInfo = &app;
    VkResult r = vkCreateInstance(&ici, NULL, &instance);
    if (r != VK_SUCCESS) return fail("vkCreateInstance", r);

    uint32_t count = 0;
    if (vkEnumeratePhysicalDevices(instance, &count, NULL) != VK_SUCCESS || !count) {
        fprintf(stderr, "[RED] engine_smoke: no Vulkan physical device\n");
        goto out;
    }
    VkPhysicalDevice *devices = calloc(count, sizeof *devices);
    if (!devices) goto out;
    vkEnumeratePhysicalDevices(instance, &count, devices);
    const char *want = getenv("SMOKE_DEVICE");
    VkPhysicalDevice physical = VK_NULL_HANDLE;
    for (uint32_t i = 0; i < count; ++i) {
        VkPhysicalDeviceProperties p;
        vkGetPhysicalDeviceProperties(devices[i], &p);
        printf("device %u: %s vendor %#x api %u.%u.%u driver %u\n", i, p.deviceName, p.vendorID,
               VK_API_VERSION_MAJOR(p.apiVersion), VK_API_VERSION_MINOR(p.apiVersion),
               VK_API_VERSION_PATCH(p.apiVersion), p.driverVersion);
        if (!want || strstr(p.deviceName, want)) {
            if (physical == VK_NULL_HANDLE) physical = devices[i];
        }
    }
    free(devices);
    if (physical == VK_NULL_HANDLE) {
        fprintf(stderr, "[RED] engine_smoke: SMOKE_DEVICE=%s matches no device\n", want);
        goto out;
    }

    uint32_t families = 0;
    vkGetPhysicalDeviceQueueFamilyProperties(physical, &families, NULL);
    VkQueueFamilyProperties *props = calloc(families ? families : 1, sizeof *props);
    if (!props) goto out;
    vkGetPhysicalDeviceQueueFamilyProperties(physical, &families, props);
    uint32_t family = UINT32_MAX;
    for (uint32_t i = 0; i < families; ++i) {
        const VkQueueFamilyProperties *f = &props[i];
        if ((f->queueFlags & (VK_QUEUE_GRAPHICS_BIT | VK_QUEUE_COMPUTE_BIT)) ==
                (VK_QUEUE_GRAPHICS_BIT | VK_QUEUE_COMPUTE_BIT) && f->queueCount) {
            family = i;
            break;
        }
    }
    free(props);
    if (family == UINT32_MAX) {
        fprintf(stderr, "[RED] engine_smoke: no graphics+compute queue family\n");
        goto out;
    }

    // The engine checks that every feature bit it is asked for exists, and that shaderDrawParameters
    // is enabled when the config says so. Ask for nothing beyond that.
    VkPhysicalDeviceShaderDrawParametersFeatures draw_parameters =
        {VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SHADER_DRAW_PARAMETERS_FEATURES};
    VkPhysicalDeviceFeatures2 supported = {VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2};
    supported.pNext = &draw_parameters;
    vkGetPhysicalDeviceFeatures2(physical, &supported);

    VkPhysicalDeviceShaderDrawParametersFeatures want_draw =
        {VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SHADER_DRAW_PARAMETERS_FEATURES};
    want_draw.shaderDrawParameters = draw_parameters.shaderDrawParameters;
    VkPhysicalDeviceFeatures core = {0};
    VkDeviceCreateInfo dci = {VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO};
    dci.pNext = want_draw.shaderDrawParameters ? &want_draw : NULL;
    dci.pEnabledFeatures = &core;
    dci.queueCreateInfoCount = 1;
    VkDeviceQueueCreateInfo qci = {VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO};
    qci.queueFamilyIndex = family;
    qci.queueCount = 1;
    float priority = 1.0f;
    qci.pQueuePriorities = &priority;
    dci.pQueueCreateInfos = &qci;
    r = vkCreateDevice(physical, &dci, NULL, &device);
    if (r != VK_SUCCESS) return fail("vkCreateDevice", r);
    vkGetDeviceQueue(device, family, 0, &queue);
    if (!queue) fprintf(stderr, "[RED] engine_smoke: vkGetDeviceQueue(family %u) returned NULL\n", family);

    // The engine reads marker files out of this directory and takes the shader directory as given;
    // an empty one is enough for initialize (bundles are opened per program).
    const char *shader_directory = getenv("SMOKE_SHADER_DIR");
    if (!shader_directory || !*shader_directory) shader_directory = "build/shader_dir";
    mkdir(shader_directory, 0777);

    xbg_game_config config;
    memset(&config, 0, sizeof config);
    config.size = (uint32_t)sizeof config;
    config.physical = physical;
    config.device = device;
    config.queue = queue;
    config.queue_family = family;
    config.enabled_core = core;
    config.enabled_shader_draw_parameters = want_draw.shaderDrawParameters;
    config.fence_timeout_ns = 1000000000ull;
    config.shader_directory = shader_directory;
    config.userdata = NULL;
    config.invoke_guest = NULL;   // no guest trampoline: callbacks are directly callable
    config.present = on_present;
    config.log = on_log;
    config.fatal = on_fatal;
    config.instance_api_version = app.apiVersion;   // 1.1: the engine then asks no 1.2 feature struct, whatever the loader is

    char error[512] = {0};
    printf("config: size=%u/%zu physical=%p device=%p queue=%p family=%u draw_params=%u timeout=%" PRIu64
           " shader_directory=%s\n", config.size, sizeof config, (void *)config.physical,
           (void *)config.device, (void *)config.queue, config.queue_family,
           config.enabled_shader_draw_parameters, config.fence_timeout_ns, shader_directory);
    printf("xbg_game_initialize(queue_family=%u, shader_directory=%s)\n", family, shader_directory);
    int result = xbg_game_initialize(&config, error, sizeof error);
    printf("xbg_game_initialize -> %d%s%s\n", result, error[0] ? ", " : "", error);
    if (result) {
        printf("last error: %s\n", xbg_game_last_error() ? xbg_game_last_error() : "(none)");
        goto out_device;
    }

    void *entry = xbg_nvn_get_proc_address("nvnDeviceGetInteger");
    printf("xbg_nvn_get_proc_address(\"nvnDeviceGetInteger\") -> %p\n", entry);
    if (entry) {
        int value = -1;
        int (*getter)(void *, int, int *) = (int (*)(void *, int, int *))entry;
        int entry_result = getter(NULL, 7, &value);
        printf("  entry point call -> %d, value %d\n", entry_result, value);
    }

    xbg_game_stats stats;
    memset(&stats, 0, sizeof stats);
    xbg_game_get_stats(&stats);
    printf("stats: submissions=%" PRIu64 " draws=%" PRIu64 " dispatches=%" PRIu64
           " presents=%" PRIu64 " shader_loads=%" PRIu64 "\n",
           stats.submissions, stats.draws, stats.dispatches, stats.presents, stats.shader_loads);

    int mirror = xbg_game_set_sampler_mirror_clamp_to_edge(VK_FALSE);
    printf("xbg_game_set_sampler_mirror_clamp_to_edge(false) -> %d\n", mirror);

    result = xbg_game_shutdown();
    printf("xbg_game_shutdown -> %d\n", result);
    printf("log lines=%d presents=%d fatals=%d\n", g_logs, g_presents, g_fatals);
    rc = 0;

out_device:
    vkDeviceWaitIdle(device);
    vkDestroyDevice(device, NULL);
out:
    vkDestroyInstance(instance, NULL);
    return rc;
}
