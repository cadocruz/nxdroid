// Vulkan capability probe for the Android port: what the target device (Samsung Galaxy S23 Ultra,
// Adreno 740) answers to the questions the Vulkan replay backend depends on, printed as one
// `key = value` line each so two runs, or two devices, can be diffed. Headless: no window system,
// no surface, no swapchain.
//
// Only vkGetInstanceProcAddr is linked. The NDK's libvulkan.so stub for the probe's minimum API
// (21) carries the 1.0 entry points only, and extension entry points such as
// vkGetMemoryHostPointerPropertiesEXT have no stubs at all; the loader on the device exports
// everything through vkGetInstanceProcAddr, so every other entry point is resolved through it.
//
// Build and run: see README.md in this directory.

#define _GNU_SOURCE

#define VK_NO_PROTOTYPES
#include <vulkan/vulkan_core.h>

#include <errno.h>
#include <inttypes.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#if defined(__has_include)
#  if __has_include(<sys/mman.h>)
#    define PROBE_HAVE_MMAP 1
#  endif
#endif
#if !defined(PROBE_HAVE_MMAP) && (defined(__unix__) || defined(__ANDROID__) || defined(__APPLE__))
#  define PROBE_HAVE_MMAP 1
#endif
#if defined(PROBE_HAVE_MMAP)
#  include <sys/mman.h>
#  if !defined(MAP_ANONYMOUS) && defined(MAP_ANON)
#    define MAP_ANONYMOUS MAP_ANON
#  endif
#endif

// The one loader symbol the probe links; VK_NO_PROTOTYPES removes the header's declaration of it.
VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL vkGetInstanceProcAddr(VkInstance instance, const char *pName);

#define PROBE_NAME "vk_probe"

// Every entry point the probe calls. Function pointers live in a struct so their load can be
// table-driven and checked once.
struct api {
    PFN_vkEnumerateInstanceVersion enumerate_instance_version;
    PFN_vkEnumerateInstanceExtensionProperties enumerate_instance_extension_properties;
    PFN_vkCreateInstance create_instance;
    PFN_vkDestroyInstance destroy_instance;
    PFN_vkEnumeratePhysicalDevices enumerate_physical_devices;
    PFN_vkGetPhysicalDeviceProperties get_physical_device_properties;
    PFN_vkGetPhysicalDeviceProperties2 get_physical_device_properties2;
    PFN_vkGetPhysicalDeviceFeatures2 get_physical_device_features2;
    PFN_vkGetPhysicalDeviceQueueFamilyProperties get_physical_device_queue_family_properties;
    PFN_vkGetPhysicalDeviceMemoryProperties2 get_physical_device_memory_properties2;
    PFN_vkGetPhysicalDeviceFormatProperties get_physical_device_format_properties;
    PFN_vkEnumerateDeviceExtensionProperties enumerate_device_extension_properties;
    PFN_vkCreateDevice create_device;
    PFN_vkDestroyDevice destroy_device;
    PFN_vkGetDeviceProcAddr get_device_proc_addr;
};

// Everything the probe reads about the selected physical device that does not fit in
// VkPhysicalDeviceProperties itself. Each query struct is only chained when the device's API
// version or its advertised extensions make it valid.
struct caps {
    VkPhysicalDeviceProperties props;
    VkPhysicalDeviceMaintenance3Properties maintenance3;
    VkPhysicalDeviceExternalMemoryHostPropertiesEXT host_pointer;
    VkPhysicalDeviceSubgroupProperties subgroup;
    VkPhysicalDeviceSubgroupSizeControlPropertiesEXT subgroup_control;
    int has_subgroup_control;
};

// One physical device's identity: what # device needs for every device the loader found, not just the
// selected one (a dump is compared against the device list of the machine it came from).
struct device_info {
    VkPhysicalDeviceProperties props;
    VkDriverId driver_id;
    int has_driver_id;
    char driver_info[VK_MAX_DRIVER_INFO_SIZE];
};

// The feature answers the port asks for, gathered from whichever struct the device's version
// allows (core 1.1/1.2/1.3 structs, or the promoted extension's struct on older devices).
struct feature_set {
    int timeline_semaphore;
    int dynamic_rendering;
    int synchronization2;
    int descriptor_indexing;
    int shader_float_controls;
    int robustness2;
    int maintenance4;
    int portability_subset;
    int storage_16bit;
    int storage_8bit;
    int scalar_block_layout;
    int fragment_stores_and_atomics;
    int independent_blend;
    int dual_src_blend;
    int logic_op;
    int depth_clamp;
    int sampler_anisotropy;
    int occlusion_query_precise;
    int shader_int64;
    int shader_int16;
    int shader_clip_distance;
    int shader_cull_distance;
    int geometry_shader;
    int tessellation_shader;
    int fill_mode_non_solid;
    int large_points;
    int texture_compression_bc;
    int texture_compression_astc_ldr;
    int texture_compression_etc2;
    int sampler_mirror_clamp_to_edge;
};

// A [RED] line and exit 2: the probe cannot answer its questions.
#if defined(__GNUC__)
__attribute__((noreturn, format(printf, 1, 2)))
#endif
static void fail(const char *fmt, ...)
{
    va_list ap;
    fprintf(stderr, "[RED] " PROBE_NAME ": ");
    va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    va_end(ap);
    fputc('\n', stderr);
    exit(2);
}

// Assign one resolved entry point. memcpy keeps the function pointer conversion legal C11
// (-Wcast-function-type would fire on a plain cast); PFN_vkVoidFunction and the typed pointer
// have the same representation.
static int gipa_load(PFN_vkGetInstanceProcAddr gipa, VkInstance instance, void *slot, const char *name)
{
    PFN_vkVoidFunction fn = gipa(instance, name);
    if (fn == NULL)
        return 0;
    memcpy(slot, &fn, sizeof(fn));
    return 1;
}

#define LOAD(inst, field, name)                                                                     \
    do {                                                                                            \
        if (!gipa_load(vkGetInstanceProcAddr, (inst), &api.field, (name)))                          \
            fail("%s is missing from the loader", (name));                                          \
    } while (0)

// The contract's two word pairs: true/false for a feature bit, present/absent for an extension
// (the literal extension names are in # extensions, so a capability is asked for by its own name).
static const char *bool_word(int value)
{
    return value ? "true" : "false";
}

static const char *presence_word(int present)
{
    return present ? "present" : "absent";
}

static void version_string(uint32_t version, char *out, size_t cap)
{
    snprintf(out, cap, "%u.%u.%u", (unsigned)VK_API_VERSION_MAJOR(version),
             (unsigned)VK_API_VERSION_MINOR(version), (unsigned)VK_API_VERSION_PATCH(version));
}

static const char *device_type_name(VkPhysicalDeviceType type)
{
    switch (type) {
    case VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU: return "integrated_gpu";
    case VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU: return "discrete_gpu";
    case VK_PHYSICAL_DEVICE_TYPE_VIRTUAL_GPU: return "virtual_gpu";
    case VK_PHYSICAL_DEVICE_TYPE_CPU: return "cpu";
    default: return "other";
    }
}

static const char *driver_id_name(VkDriverId id)
{
    switch (id) {
    case VK_DRIVER_ID_AMD_PROPRIETARY: return "AMD_PROPRIETARY";
    case VK_DRIVER_ID_AMD_OPEN_SOURCE: return "AMD_OPEN_SOURCE";
    case VK_DRIVER_ID_MESA_RADV: return "MESA_RADV";
    case VK_DRIVER_ID_NVIDIA_PROPRIETARY: return "NVIDIA_PROPRIETARY";
    case VK_DRIVER_ID_INTEL_PROPRIETARY_WINDOWS: return "INTEL_PROPRIETARY_WINDOWS";
    case VK_DRIVER_ID_INTEL_OPEN_SOURCE_MESA: return "INTEL_OPEN_SOURCE_MESA";
    case VK_DRIVER_ID_IMAGINATION_PROPRIETARY: return "IMAGINATION_PROPRIETARY";
    case VK_DRIVER_ID_QUALCOMM_PROPRIETARY: return "QUALCOMM_PROPRIETARY";
    case VK_DRIVER_ID_ARM_PROPRIETARY: return "ARM_PROPRIETARY";
    case VK_DRIVER_ID_GOOGLE_SWIFTSHADER: return "GOOGLE_SWIFTSHADER";
    case VK_DRIVER_ID_GGP_PROPRIETARY: return "GGP_PROPRIETARY";
    case VK_DRIVER_ID_BROADCOM_PROPRIETARY: return "BROADCOM_PROPRIETARY";
    case VK_DRIVER_ID_MESA_LLVMPIPE: return "MESA_LLVMPIPE";
    case VK_DRIVER_ID_MOLTENVK: return "MOLTENVK";
    case VK_DRIVER_ID_COREAVI_PROPRIETARY: return "COREAVI_PROPRIETARY";
    case VK_DRIVER_ID_JUICE_PROPRIETARY: return "JUICE_PROPRIETARY";
    case VK_DRIVER_ID_VERISILICON_PROPRIETARY: return "VERISILICON_PROPRIETARY";
    case VK_DRIVER_ID_MESA_TURNIP: return "MESA_TURNIP";
    case VK_DRIVER_ID_MESA_V3DV: return "MESA_V3DV";
    case VK_DRIVER_ID_MESA_PANVK: return "MESA_PANVK";
    case VK_DRIVER_ID_SAMSUNG_PROPRIETARY: return "SAMSUNG_PROPRIETARY";
    case VK_DRIVER_ID_MESA_VENUS: return "MESA_VENUS";
    case VK_DRIVER_ID_MESA_DOZEN: return "MESA_DOZEN";
    case VK_DRIVER_ID_MESA_NVK: return "MESA_NVK";
    case VK_DRIVER_ID_IMAGINATION_OPEN_SOURCE_MESA: return "IMAGINATION_OPEN_SOURCE_MESA";
    case VK_DRIVER_ID_MESA_HONEYKRISP: return "MESA_HONEYKRISP";
    case VK_DRIVER_ID_VULKAN_SC_EMULATION_ON_VULKAN: return "VULKAN_SC_EMULATION_ON_VULKAN";
    case VK_DRIVER_ID_MESA_KOSMICKRISP: return "MESA_KOSMICKRISP";
    case VK_DRIVER_ID_MESA_GFXSTREAM: return "MESA_GFXSTREAM";
    case VK_DRIVER_ID_APE_SOFT: return "APE_SOFT";
    default: return "UNKNOWN";
    }
}

// The driver id as the contract takes it: a name (Vulkan's, lower case, "qualcomm_proprietary") or
// a number. An id this build's header does not name is printed as its number, which is what a
// consumer compares against VkDriverId anyway.
static const char *driver_id_value(VkDriverId id, char *out, size_t cap)
{
    const char *name = driver_id_name(id);
    size_t i;

    if (strcmp(name, "UNKNOWN") == 0) {
        snprintf(out, cap, "%d", (int)id);
        return out;
    }
    for (i = 0; name[i] != '\0' && i + 1 < cap; i++)
        out[i] = (char)((name[i] >= 'A' && name[i] <= 'Z') ? name[i] - 'A' + 'a' : name[i]);
    out[i] = '\0';
    return out;
}

// vulkan.gpuinfo.org's decoding, by vendor:
//   NVIDIA      10-bit major, 8-bit minor, 8-bit subminor, 6-bit patch ("580.178.4.0")
//   Intel's Windows driver (its own scheme) 14-bit major, 14-bit minor; the contract wants three
//     or four components, so the unspecified patch is printed as 0
//   everything else the Vulkan 1.1 recommendation: 10/10/12 ("512.744.0" on Qualcomm)
static void driver_version_string(uint32_t vendor_id, VkDriverId driver_id, uint32_t version,
                                  char *out, size_t cap)
{
    if (vendor_id == 0x10DE) {
        snprintf(out, cap, "%u.%u.%u.%u", (unsigned)(version >> 22), (unsigned)((version >> 14) & 0xFF),
                 (unsigned)((version >> 6) & 0xFF), (unsigned)(version & 0x3F));
    } else if (vendor_id == 0x8086 && driver_id == VK_DRIVER_ID_INTEL_PROPRIETARY_WINDOWS) {
        snprintf(out, cap, "%u.%u.0", (unsigned)(version >> 14), (unsigned)(version & 0x3FFF));
    } else {
        snprintf(out, cap, "%u.%u.%u", (unsigned)(version >> 22), (unsigned)((version >> 12) & 0x3FF),
                 (unsigned)(version & 0xFFF));
    }
}

static int has_ext(const VkExtensionProperties *exts, uint32_t count, const char *name)
{
    for (uint32_t i = 0; i < count; i++)
        if (strcmp(exts[i].extensionName, name) == 0)
            return 1;
    return 0;
}

static int cmp_extension(const void *a, const void *b)
{
    return strcmp(((const VkExtensionProperties *)a)->extensionName,
                  ((const VkExtensionProperties *)b)->extensionName);
}

// One appended token of a compact flag string ("sampled blit-src ...").
static void token_append(char *out, size_t cap, size_t *len, const char *token)
{
    if (cap <= *len + 1)
        return;
    int written = snprintf(out + *len, cap - *len, "%s%s", *len > 0 ? " " : "", token);
    if (written > 0)
        *len += (size_t)written;
}

// Appends one query struct to a pNext chain. The chain head is a void * so the field assignment
// goes through each struct's own pNext member (casting it to VkBaseOutStructure * and writing
// through that pointer trips -Wstrict-aliasing).
#define CHAIN(head, s)                                                                              \
    do {                                                                                            \
        (s).pNext = (head);                                                                         \
        (head) = &(s);                                                                              \
    } while (0)

static VkExtensionProperties *device_extensions(const struct api *api, VkPhysicalDevice pd,
                                                uint32_t *out_count)
{
    uint32_t count = 0;
    *out_count = 0;
    if (api->enumerate_device_extension_properties(pd, NULL, &count, NULL) != VK_SUCCESS)
        fail("vkEnumerateDeviceExtensionProperties failed");
    VkExtensionProperties *exts = calloc(count ? count : 1, sizeof(*exts));
    if (exts == NULL)
        fail("out of memory");
    if (count > 0 && api->enumerate_device_extension_properties(pd, NULL, &count, exts) != VK_SUCCESS)
        fail("vkEnumerateDeviceExtensionProperties failed");
    qsort(exts, count, sizeof(*exts), cmp_extension);
    *out_count = count;
    return exts;
}

// The identity of any physical device, selected or not. The driver identity lives in the core 1.2
// properties struct from 1.2 on and in the extension's struct below that, and only when the device
// advertises the extension (chaining both is invalid).
static void query_device_info(const struct api *api, VkPhysicalDevice pd,
                              const VkExtensionProperties *exts, uint32_t ext_count,
                              struct device_info *out)
{
    VkPhysicalDeviceProperties2 props2 = { .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2 };
    VkPhysicalDeviceVulkan12Properties v12 = {
        .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_2_PROPERTIES
    };
    VkPhysicalDeviceDriverProperties driver = {
        .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_DRIVER_PROPERTIES
    };
    const int has_driver_ext = has_ext(exts, ext_count, "VK_KHR_driver_properties");
    void *head = NULL;
    int core_driver = 0;

    memset(out, 0, sizeof(*out));
    api->get_physical_device_properties(pd, &out->props);

    if (out->props.apiVersion >= VK_API_VERSION_1_2) {
        CHAIN(head, v12);
        core_driver = 1;
    } else if (has_driver_ext) {
        CHAIN(head, driver);
    }
    props2.pNext = head;
    api->get_physical_device_properties2(pd, &props2);

    if (core_driver || has_driver_ext) {
        out->has_driver_id = 1;
        out->driver_id = core_driver ? v12.driverID : driver.driverID;
        memcpy(out->driver_info, core_driver ? v12.driverInfo : driver.driverInfo,
               sizeof(out->driver_info));
    }
    out->driver_info[sizeof(out->driver_info) - 1] = '\0';
    if (out->driver_info[0] == '\0')
        snprintf(out->driver_info, sizeof(out->driver_info), "unknown");

    // The driver string is the vendor's and is not always one line: Qualcomm's reads
    // "Driver Build: ...\nDate: 01/27/26\nCompiler Version: ...\nDriver Branch: ". The dump is
    // one "key = value" per line, so a newline in a value would split one fact into several
    // lines and make the file unparseable. Fold every run of whitespace into a single space and
    // drop the trailing one, which leaves the vendor's text readable and the format intact.
    {
        char *src = out->driver_info, *dst = out->driver_info;
        int space = 0;
        for (; *src; src++) {
            if (*src == '\n' || *src == '\r' || *src == '\t' || *src == ' ') { space = 1; continue; }
            if (space && dst != out->driver_info) *dst++ = ' ';
            space = 0;
            *dst++ = *src;
        }
        *dst = '\0';
    }
}

static void query_caps(const struct api *api, VkPhysicalDevice pd,
                       const VkExtensionProperties *exts, uint32_t ext_count, struct caps *caps)
{
    VkPhysicalDeviceProperties2 props2 = { .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2 };
    void *head = NULL;

    api->get_physical_device_properties(pd, &caps->props);

    // The driver identity (driverID, driverInfo) is not a capability: query_device_info answers it
    // for every device, so this chain carries only what the detailed sections read.
    caps->maintenance3.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_MAINTENANCE_3_PROPERTIES;
    CHAIN(head, caps->maintenance3);

    caps->subgroup.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SUBGROUP_PROPERTIES;
    CHAIN(head, caps->subgroup);

    if (has_ext(exts, ext_count, "VK_EXT_subgroup_size_control")) {
        caps->subgroup_control.sType =
            VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SUBGROUP_SIZE_CONTROL_PROPERTIES;
        CHAIN(head, caps->subgroup_control);
        caps->has_subgroup_control = 1;
    }

    if (has_ext(exts, ext_count, "VK_EXT_external_memory_host")) {
        caps->host_pointer.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_EXTERNAL_MEMORY_HOST_PROPERTIES_EXT;
        CHAIN(head, caps->host_pointer);
    }

    props2.pNext = head;
    api->get_physical_device_properties2(pd, &props2);
}

static struct feature_set query_features(const struct api *api, VkPhysicalDevice pd,
                                         const VkExtensionProperties *exts, uint32_t ext_count,
                                         uint32_t version)
{
    struct feature_set out;
    memset(&out, 0, sizeof(out));

    VkPhysicalDeviceFeatures2 features2 = { .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2 };
    VkPhysicalDeviceVulkan11Features v11 = { .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_1_FEATURES };
    VkPhysicalDeviceVulkan12Features v12 = { .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_2_FEATURES };
    VkPhysicalDeviceVulkan13Features v13 = { .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_3_FEATURES };
    VkPhysicalDeviceDescriptorIndexingFeatures indexing = {
        .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_DESCRIPTOR_INDEXING_FEATURES
    };
    VkPhysicalDeviceTimelineSemaphoreFeatures timeline = {
        .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_TIMELINE_SEMAPHORE_FEATURES
    };
    VkPhysicalDeviceScalarBlockLayoutFeatures scalar = {
        .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SCALAR_BLOCK_LAYOUT_FEATURES
    };
    VkPhysicalDevice8BitStorageFeatures storage8 = {
        .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_8BIT_STORAGE_FEATURES
    };
    VkPhysicalDeviceDynamicRenderingFeatures dynamic_rendering = {
        .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_DYNAMIC_RENDERING_FEATURES
    };
    VkPhysicalDeviceSynchronization2Features synchronization2 = {
        .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SYNCHRONIZATION_2_FEATURES
    };
    VkPhysicalDeviceMaintenance4Features maintenance4 = {
        .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_MAINTENANCE_4_FEATURES
    };
    VkPhysicalDeviceRobustness2FeaturesEXT robustness2 = {
        .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_ROBUSTNESS_2_FEATURES_EXT
    };
    void *head = NULL;

    int have_indexing = 0, have_timeline = 0, have_scalar = 0, have_storage8 = 0;
    int have_dynamic_rendering = 0, have_synchronization2 = 0, have_maintenance4 = 0;

    CHAIN(head, v11);
    if (version >= VK_API_VERSION_1_2) {
        CHAIN(head, v12);
    } else {
        if (has_ext(exts, ext_count, "VK_EXT_descriptor_indexing")) {
            CHAIN(head, indexing);
            have_indexing = 1;
        }
        if (has_ext(exts, ext_count, "VK_KHR_timeline_semaphore")) {
            CHAIN(head, timeline);
            have_timeline = 1;
        }
        if (has_ext(exts, ext_count, "VK_EXT_scalar_block_layout")) {
            CHAIN(head, scalar);
            have_scalar = 1;
        }
        if (has_ext(exts, ext_count, "VK_KHR_8bit_storage")) {
            CHAIN(head, storage8);
            have_storage8 = 1;
        }
    }
    if (version >= VK_API_VERSION_1_3) {
        CHAIN(head, v13);
    } else {
        if (has_ext(exts, ext_count, "VK_KHR_dynamic_rendering")) {
            CHAIN(head, dynamic_rendering);
            have_dynamic_rendering = 1;
        }
        if (has_ext(exts, ext_count, "VK_KHR_synchronization2")) {
            CHAIN(head, synchronization2);
            have_synchronization2 = 1;
        }
        if (has_ext(exts, ext_count, "VK_KHR_maintenance4")) {
            CHAIN(head, maintenance4);
            have_maintenance4 = 1;
        }
    }
    if (has_ext(exts, ext_count, "VK_EXT_robustness2") ||
        has_ext(exts, ext_count, "VK_KHR_robustness2"))
        CHAIN(head, robustness2);

    features2.pNext = head;
    api->get_physical_device_features2(pd, &features2);

    out.timeline_semaphore = version >= VK_API_VERSION_1_2
        ? (int)v12.timelineSemaphore : (have_timeline ? (int)timeline.timelineSemaphore : 0);
    out.dynamic_rendering = version >= VK_API_VERSION_1_3
        ? (int)v13.dynamicRendering : (have_dynamic_rendering ? (int)dynamic_rendering.dynamicRendering : 0);
    out.synchronization2 = version >= VK_API_VERSION_1_3
        ? (int)v13.synchronization2 : (have_synchronization2 ? (int)synchronization2.synchronization2 : 0);
    out.maintenance4 = version >= VK_API_VERSION_1_3
        ? (int)v13.maintenance4 : (have_maintenance4 ? (int)maintenance4.maintenance4 : 0);

    // What the replay backend's bindless path needs: runtime-sized descriptor arrays, non-uniform
    // indexing of sampled images and storage buffers, partially bound and variable-count bindings.
    if (version >= VK_API_VERSION_1_2) {
        out.descriptor_indexing = (int)(v12.runtimeDescriptorArray &&
                                        v12.shaderSampledImageArrayNonUniformIndexing &&
                                        v12.shaderStorageBufferArrayNonUniformIndexing &&
                                        v12.descriptorBindingPartiallyBound &&
                                        v12.descriptorBindingVariableDescriptorCount);
    } else if (have_indexing) {
        out.descriptor_indexing = (int)(indexing.runtimeDescriptorArray &&
                                        indexing.shaderSampledImageArrayNonUniformIndexing &&
                                        indexing.shaderStorageBufferArrayNonUniformIndexing &&
                                        indexing.descriptorBindingPartiallyBound &&
                                        indexing.descriptorBindingVariableDescriptorCount);
    }

    out.scalar_block_layout = version >= VK_API_VERSION_1_2
        ? (int)v12.scalarBlockLayout : (have_scalar ? (int)scalar.scalarBlockLayout : 0);
    out.storage_8bit = version >= VK_API_VERSION_1_2
        ? (int)v12.storageBuffer8BitAccess : (have_storage8 ? (int)storage8.storageBuffer8BitAccess : 0);
    out.storage_16bit = (int)v11.storageBuffer16BitAccess;

    // VK_KHR_shader_float_controls carries no feature bits: support is the extension (or core 1.2).
    out.shader_float_controls = version >= VK_API_VERSION_1_2 ||
                                has_ext(exts, ext_count, "VK_KHR_shader_float_controls");

    // robustness2 answers for the feature the replay backend can use: an empty descriptor slot
    // (nullDescriptor). Robust buffer/image access are not required for it.
    out.robustness2 = (has_ext(exts, ext_count, "VK_EXT_robustness2") ||
                       has_ext(exts, ext_count, "VK_KHR_robustness2")) &&
                      (int)robustness2.nullDescriptor;
    // VK_EXT_portability_subset appears as VK_KHR_portability_subset in the 1.4 registry; the
    // vendored header carries neither its struct nor its name macro, so the answer is the
    // extension's presence (only a portability implementation advertises it).
    out.portability_subset = has_ext(exts, ext_count, "VK_EXT_portability_subset") ||
                             has_ext(exts, ext_count, "VK_KHR_portability_subset");

    // VK_KHR_sampler_mirror_clamp_to_edge has no feature struct below core 1.2; the answer is the
    // core feature bit on 1.2+ and the extension's presence before that.
    out.sampler_mirror_clamp_to_edge = version >= VK_API_VERSION_1_2
        ? (int)v12.samplerMirrorClampToEdge
        : has_ext(exts, ext_count, "VK_KHR_sampler_mirror_clamp_to_edge");

    out.fragment_stores_and_atomics = (int)features2.features.fragmentStoresAndAtomics;
    out.independent_blend = (int)features2.features.independentBlend;
    out.dual_src_blend = (int)features2.features.dualSrcBlend;
    out.logic_op = (int)features2.features.logicOp;
    out.depth_clamp = (int)features2.features.depthClamp;
    out.sampler_anisotropy = (int)features2.features.samplerAnisotropy;
    out.occlusion_query_precise = (int)features2.features.occlusionQueryPrecise;
    out.shader_int64 = (int)features2.features.shaderInt64;
    out.shader_int16 = (int)features2.features.shaderInt16;
    out.shader_clip_distance = (int)features2.features.shaderClipDistance;
    out.shader_cull_distance = (int)features2.features.shaderCullDistance;
    out.geometry_shader = (int)features2.features.geometryShader;
    out.tessellation_shader = (int)features2.features.tessellationShader;
    out.fill_mode_non_solid = (int)features2.features.fillModeNonSolid;
    out.large_points = (int)features2.features.largePoints;
    out.texture_compression_bc = (int)features2.features.textureCompressionBC;
    out.texture_compression_astc_ldr = (int)features2.features.textureCompressionASTC_LDR;
    out.texture_compression_etc2 = (int)features2.features.textureCompressionETC2;

    return out;
}

// One device's nine fields. # device lists every device like this, so `device_selected` stays a
// number a diff can follow: which device the detailed sections below describe.
static void print_device_fields(const struct device_info *info, uint32_t index)
{
    char version[32], driver[64], id[64];
    const VkPhysicalDeviceProperties *p = &info->props;

    version_string(p->apiVersion, version, sizeof(version));
    driver_version_string(p->vendorID, info->driver_id, p->driverVersion, driver, sizeof(driver));

    printf("device.%u.name = %s\n", (unsigned)index, p->deviceName);
    printf("device.%u.device_type = %s\n", (unsigned)index, device_type_name(p->deviceType));
    printf("device.%u.vendor_id = %u\n", (unsigned)index, (unsigned)p->vendorID);
    printf("device.%u.device_id = %u\n", (unsigned)index, (unsigned)p->deviceID);
    printf("device.%u.api_version = %s\n", (unsigned)index, version);
    printf("device.%u.driver_version = %s\n", (unsigned)index, driver);
    printf("device.%u.driver_version_raw = %u\n", (unsigned)index, (unsigned)p->driverVersion);
    printf("device.%u.driver_id = %s\n", (unsigned)index,
           info->has_driver_id ? driver_id_value(info->driver_id, id, sizeof(id)) : "unknown");
    printf("device.%u.driver_info = %s\n", (unsigned)index, info->driver_info);
}

static void print_device_extensions(const VkExtensionProperties *exts, uint32_t count)
{
    printf("# extensions\n");
    for (uint32_t i = 0; i < count; i++)
        printf("device_extension = %s %u\n", exts[i].extensionName, (unsigned)exts[i].specVersion);
}

static void print_features_block(const struct feature_set *f, const VkExtensionProperties *exts,
                                 uint32_t ext_count)
{
    printf("# features\n");
    printf("timelineSemaphore = %s\n", bool_word(f->timeline_semaphore));
    printf("dynamicRendering = %s\n", bool_word(f->dynamic_rendering));
    printf("synchronization2 = %s\n", bool_word(f->synchronization2));
    printf("descriptorIndexing = %s\n", bool_word(f->descriptor_indexing));
    printf("robustness2 = %s\n", bool_word(f->robustness2));
    printf("maintenance4 = %s\n", bool_word(f->maintenance4));
    printf("storageBuffer16BitAccess = %s\n", bool_word(f->storage_16bit));
    printf("storageBuffer8BitAccess = %s\n", bool_word(f->storage_8bit));
    printf("scalarBlockLayout = %s\n", bool_word(f->scalar_block_layout));
    printf("fragmentStoresAndAtomics = %s\n", bool_word(f->fragment_stores_and_atomics));
    printf("independentBlend = %s\n", bool_word(f->independent_blend));
    printf("dualSrcBlend = %s\n", bool_word(f->dual_src_blend));
    printf("logicOp = %s\n", bool_word(f->logic_op));
    printf("depthClamp = %s\n", bool_word(f->depth_clamp));
    printf("samplerAnisotropy = %s\n", bool_word(f->sampler_anisotropy));
    printf("occlusionQueryPrecise = %s\n", bool_word(f->occlusion_query_precise));
    printf("shaderInt64 = %s\n", bool_word(f->shader_int64));
    printf("shaderInt16 = %s\n", bool_word(f->shader_int16));
    printf("shaderClipDistance = %s\n", bool_word(f->shader_clip_distance));
    printf("shaderCullDistance = %s\n", bool_word(f->shader_cull_distance));
    printf("geometryShader = %s\n", bool_word(f->geometry_shader));
    printf("tessellationShader = %s\n", bool_word(f->tessellation_shader));
    printf("fillModeNonSolid = %s\n", bool_word(f->fill_mode_non_solid));
    printf("largePoints = %s\n", bool_word(f->large_points));
    printf("textureCompressionBC = %s\n", bool_word(f->texture_compression_bc));
    printf("textureCompressionASTC_LDR = %s\n", bool_word(f->texture_compression_astc_ldr));
    printf("textureCompressionETC2 = %s\n", bool_word(f->texture_compression_etc2));
    printf("samplerMirrorClampToEdge = %s\n", bool_word(f->sampler_mirror_clamp_to_edge));

    // Extension presence, asked for by the capability's Vulkan name: the literal extension name and
    // its specVersion are in # extensions, so the two questions stay separate.
    printf("shaderFloatControls = %s\n", bool_word(f->shader_float_controls));
    printf("graphicsPipelineLibrary = %s\n",
           presence_word(has_ext(exts, ext_count, "VK_EXT_graphics_pipeline_library")));
    printf("memoryBudget = %s\n", presence_word(has_ext(exts, ext_count, "VK_EXT_memory_budget")));
    printf("externalMemoryHost = %s\n",
           presence_word(has_ext(exts, ext_count, "VK_EXT_external_memory_host")));
    printf("pipelineBinary = %s\n", presence_word(has_ext(exts, ext_count, "VK_KHR_pipeline_binary")));
    // The registry renamed VK_EXT_shader_float_controls2 to VK_KHR_shader_float_controls2 for
    // Vulkan 1.4; drivers may advertise either name, so the requested name answers for both.
    printf("shaderFloatControls2 = %s\n",
           presence_word(has_ext(exts, ext_count, "VK_EXT_shader_float_controls2") ||
                         has_ext(exts, ext_count, "VK_KHR_shader_float_controls2")));
    printf("hostImageCopy = %s\n", presence_word(has_ext(exts, ext_count, "VK_EXT_host_image_copy")));
    printf("portabilitySubset = %s\n", presence_word(f->portability_subset));
}

static void print_limits(const struct caps *caps)
{
    const VkPhysicalDeviceLimits *l = &caps->props.limits;
    const uint32_t subgroup = caps->has_subgroup_control ? caps->subgroup_control.minSubgroupSize
                                                         : caps->subgroup.subgroupSize;

    printf("# limits\n");
    printf("maxMemoryAllocationCount = %u\n", (unsigned)l->maxMemoryAllocationCount);
    printf("maxMemoryAllocationSize = %" PRIu64 "\n", (uint64_t)caps->maintenance3.maxMemoryAllocationSize);
    printf("bufferImageGranularity = %" PRIu64 "\n", (uint64_t)l->bufferImageGranularity);
    printf("nonCoherentAtomSize = %" PRIu64 "\n", (uint64_t)l->nonCoherentAtomSize);
    printf("minStorageBufferOffsetAlignment = %" PRIu64 "\n", (uint64_t)l->minStorageBufferOffsetAlignment);
    printf("minUniformBufferOffsetAlignment = %" PRIu64 "\n", (uint64_t)l->minUniformBufferOffsetAlignment);
    printf("maxStorageBufferRange = %u\n", (unsigned)l->maxStorageBufferRange);
    printf("maxUniformBufferRange = %u\n", (unsigned)l->maxUniformBufferRange);
    printf("maxDescriptorSetStorageBuffers = %u\n", (unsigned)l->maxDescriptorSetStorageBuffers);
    printf("maxPerStageDescriptorStorageBuffers = %u\n", (unsigned)l->maxPerStageDescriptorStorageBuffers);
    printf("maxDescriptorSetSampledImages = %u\n", (unsigned)l->maxDescriptorSetSampledImages);
    printf("maxPerStageDescriptorSamplers = %u\n", (unsigned)l->maxPerStageDescriptorSamplers);
    printf("maxPushConstantsSize = %u\n", (unsigned)l->maxPushConstantsSize);
    printf("maxColorAttachments = %u\n", (unsigned)l->maxColorAttachments);
    printf("maxFramebufferWidth = %u\n", (unsigned)l->maxFramebufferWidth);
    printf("maxFramebufferHeight = %u\n", (unsigned)l->maxFramebufferHeight);
    printf("maxImageDimension2D = %u\n", (unsigned)l->maxImageDimension2D);
    printf("maxImageDimension3D = %u\n", (unsigned)l->maxImageDimension3D);
    printf("maxImageArrayLayers = %u\n", (unsigned)l->maxImageArrayLayers);
    printf("maxViewportDimensions.0 = %u\n", (unsigned)l->maxViewportDimensions[0]);
    printf("maxViewportDimensions.1 = %u\n", (unsigned)l->maxViewportDimensions[1]);
    printf("maxComputeWorkGroupInvocations = %u\n", (unsigned)l->maxComputeWorkGroupInvocations);
    printf("maxComputeWorkGroupSize.0 = %u\n", (unsigned)l->maxComputeWorkGroupSize[0]);
    printf("maxComputeWorkGroupSize.1 = %u\n", (unsigned)l->maxComputeWorkGroupSize[1]);
    printf("maxComputeWorkGroupSize.2 = %u\n", (unsigned)l->maxComputeWorkGroupSize[2]);
    printf("maxComputeWorkGroupCount.0 = %u\n", (unsigned)l->maxComputeWorkGroupCount[0]);
    printf("maxComputeWorkGroupCount.1 = %u\n", (unsigned)l->maxComputeWorkGroupCount[1]);
    printf("maxComputeWorkGroupCount.2 = %u\n", (unsigned)l->maxComputeWorkGroupCount[2]);
    printf("maxVertexInputAttributes = %u\n", (unsigned)l->maxVertexInputAttributes);
    printf("maxVertexInputBindings = %u\n", (unsigned)l->maxVertexInputBindings);
    printf("maxVertexInputAttributeOffset = %u\n", (unsigned)l->maxVertexInputAttributeOffset);
    printf("maxVertexOutputComponents = %u\n", (unsigned)l->maxVertexOutputComponents);
    printf("optimalBufferCopyOffsetAlignment = %" PRIu64 "\n", (uint64_t)l->optimalBufferCopyOffsetAlignment);
    printf("optimalBufferCopyRowPitchAlignment = %" PRIu64 "\n", (uint64_t)l->optimalBufferCopyRowPitchAlignment);
    printf("timestamp_compute_and_graphics = %s\n", bool_word((int)l->timestampComputeAndGraphics));
    printf("timestampPeriod = %.3f\n", (double)l->timestampPeriod);
    printf("subgroupSize = %u\n", (unsigned)caps->subgroup.subgroupSize);
    printf("minSubgroupSize = %u\n", (unsigned)subgroup);
    printf("maxSubgroupSize = %u\n", (unsigned)(caps->has_subgroup_control
                                                    ? caps->subgroup_control.maxSubgroupSize
                                                    : caps->subgroup.subgroupSize));
    printf("maxSamplerLodBias = %.3f\n", (double)l->maxSamplerLodBias);
    printf("maxSamplerAnisotropy = %.3f\n", (double)l->maxSamplerAnisotropy);
}

static void memory_heap_flags(VkMemoryHeapFlags flags, char *out, size_t cap)
{
    size_t len = 0;
    out[0] = '\0';
    if (flags & VK_MEMORY_HEAP_DEVICE_LOCAL_BIT)
        token_append(out, cap, &len, "device_local");
    if (flags & VK_MEMORY_HEAP_MULTI_INSTANCE_BIT)
        token_append(out, cap, &len, "multi_instance");
    if (len == 0)
        snprintf(out, cap, "none");
}

static void memory_type_flags(VkMemoryPropertyFlags flags, char *out, size_t cap)
{
    size_t len = 0;
    out[0] = '\0';
    if (flags & VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT)
        token_append(out, cap, &len, "device_local");
    if (flags & VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT)
        token_append(out, cap, &len, "host_visible");
    if (flags & VK_MEMORY_PROPERTY_HOST_COHERENT_BIT)
        token_append(out, cap, &len, "host_coherent");
    if (flags & VK_MEMORY_PROPERTY_HOST_CACHED_BIT)
        token_append(out, cap, &len, "host_cached");
    if (flags & VK_MEMORY_PROPERTY_LAZILY_ALLOCATED_BIT)
        token_append(out, cap, &len, "lazily_allocated");
    if (flags & VK_MEMORY_PROPERTY_PROTECTED_BIT)
        token_append(out, cap, &len, "protected");
    if (flags & VK_MEMORY_PROPERTY_DEVICE_COHERENT_BIT_AMD)
        token_append(out, cap, &len, "device_coherent_amd");
    if (flags & VK_MEMORY_PROPERTY_DEVICE_UNCACHED_BIT_AMD)
        token_append(out, cap, &len, "device_uncached_amd");
    if (flags & VK_MEMORY_PROPERTY_RDMA_CAPABLE_BIT_NV)
        token_append(out, cap, &len, "rdma_capable_nv");
    if (len == 0)
        snprintf(out, cap, "none");
}

static void print_memory(const struct api *api, VkPhysicalDevice pd)
{
    VkPhysicalDeviceMemoryProperties2 memory = { .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_MEMORY_PROPERTIES_2 };

    api->get_physical_device_memory_properties2(pd, &memory);

    printf("# memory\n");
    printf("memory_heap_count = %u\n", (unsigned)memory.memoryProperties.memoryHeapCount);
    printf("memory_type_count = %u\n", (unsigned)memory.memoryProperties.memoryTypeCount);
    for (uint32_t i = 0; i < memory.memoryProperties.memoryHeapCount; i++) {
        const VkMemoryHeap *heap = &memory.memoryProperties.memoryHeaps[i];
        char flags[64];
        memory_heap_flags(heap->flags, flags, sizeof(flags));
        printf("memory_heap.%u.size = %" PRIu64 "\n", (unsigned)i, (uint64_t)heap->size);
        printf("memory_heap.%u.flags = %s\n", (unsigned)i, flags);
    }
    for (uint32_t i = 0; i < memory.memoryProperties.memoryTypeCount; i++) {
        const VkMemoryType *type = &memory.memoryProperties.memoryTypes[i];
        char flags[128];
        memory_type_flags(type->propertyFlags, flags, sizeof(flags));
        printf("memory_type.%u.flags = %s\n", (unsigned)i, flags);
        printf("memory_type.%u.heap_index = %u\n", (unsigned)i, (unsigned)type->heapIndex);
    }
}

struct format_entry {
    VkFormat format;
    const char *name;
    int bc;
};

#define FORMAT(f) { (f), #f, 0 }
#define BC_FORMAT(f) { (f), #f, 1 }

static void format_features_string(VkFormatFeatureFlags flags, char *out, size_t cap)
{
    static const struct {
        VkFormatFeatureFlags bit;
        const char *name;
    } map[] = {
        { VK_FORMAT_FEATURE_SAMPLED_IMAGE_BIT, "sampled" },
        { VK_FORMAT_FEATURE_STORAGE_IMAGE_BIT, "storage" },
        { VK_FORMAT_FEATURE_COLOR_ATTACHMENT_BIT, "color" },
        { VK_FORMAT_FEATURE_DEPTH_STENCIL_ATTACHMENT_BIT, "depth" },
        { VK_FORMAT_FEATURE_BLIT_SRC_BIT, "blit-src" },
        { VK_FORMAT_FEATURE_BLIT_DST_BIT, "blit-dst" },
        { VK_FORMAT_FEATURE_SAMPLED_IMAGE_FILTER_LINEAR_BIT, "filter-linear" },
        { VK_FORMAT_FEATURE_TRANSFER_DST_BIT, "transfer-dst" },
        { VK_FORMAT_FEATURE_STORAGE_IMAGE_ATOMIC_BIT, "atomic" },
    };
    size_t len = 0;
    out[0] = '\0';
    for (size_t i = 0; i < sizeof(map) / sizeof(map[0]); i++)
        if (flags & map[i].bit)
            token_append(out, cap, &len, map[i].name);
    if (len == 0)
        snprintf(out, cap, "none");
}

// Returns 1 when every BC format the port needs is sampleable.
static int print_formats(const struct api *api, VkPhysicalDevice pd)
{
    static const struct format_entry entries[] = {
        BC_FORMAT(VK_FORMAT_BC1_RGB_UNORM_BLOCK),
        BC_FORMAT(VK_FORMAT_BC1_RGBA_UNORM_BLOCK),
        BC_FORMAT(VK_FORMAT_BC1_RGBA_SRGB_BLOCK),
        BC_FORMAT(VK_FORMAT_BC2_UNORM_BLOCK),
        BC_FORMAT(VK_FORMAT_BC2_SRGB_BLOCK),
        BC_FORMAT(VK_FORMAT_BC3_UNORM_BLOCK),
        BC_FORMAT(VK_FORMAT_BC3_SRGB_BLOCK),
        BC_FORMAT(VK_FORMAT_BC4_UNORM_BLOCK),
        BC_FORMAT(VK_FORMAT_BC4_SNORM_BLOCK),
        BC_FORMAT(VK_FORMAT_BC5_UNORM_BLOCK),
        BC_FORMAT(VK_FORMAT_BC5_SNORM_BLOCK),
        BC_FORMAT(VK_FORMAT_BC6H_UFLOAT_BLOCK),
        BC_FORMAT(VK_FORMAT_BC6H_SFLOAT_BLOCK),
        BC_FORMAT(VK_FORMAT_BC7_UNORM_BLOCK),
        BC_FORMAT(VK_FORMAT_BC7_SRGB_BLOCK),
        FORMAT(VK_FORMAT_R8_UNORM),
        FORMAT(VK_FORMAT_R8G8_UNORM),
        FORMAT(VK_FORMAT_R8G8B8A8_UNORM),
        FORMAT(VK_FORMAT_R8_SRGB),
        FORMAT(VK_FORMAT_R8G8B8A8_SRGB),
        FORMAT(VK_FORMAT_R16_SFLOAT),
        FORMAT(VK_FORMAT_R16G16B16A16_SFLOAT),
        FORMAT(VK_FORMAT_R32_SFLOAT),
        FORMAT(VK_FORMAT_R32G32B32A32_SFLOAT),
        FORMAT(VK_FORMAT_D16_UNORM),
        FORMAT(VK_FORMAT_D24_UNORM_S8_UINT),
        FORMAT(VK_FORMAT_D32_SFLOAT),
        FORMAT(VK_FORMAT_ASTC_4x4_UNORM_BLOCK),
        FORMAT(VK_FORMAT_ASTC_4x4_SRGB_BLOCK),
        FORMAT(VK_FORMAT_ASTC_6x6_UNORM_BLOCK),
        FORMAT(VK_FORMAT_ASTC_6x6_SRGB_BLOCK),
        FORMAT(VK_FORMAT_ASTC_8x8_UNORM_BLOCK),
        FORMAT(VK_FORMAT_ASTC_8x8_SRGB_BLOCK),
        FORMAT(VK_FORMAT_ETC2_R8G8B8A8_UNORM_BLOCK),
    };
    int bc_ok = 1;

    printf("# formats\n");
    for (size_t i = 0; i < sizeof(entries) / sizeof(entries[0]); i++) {
        VkFormatProperties props;
        char flags[128];
        memset(&props, 0, sizeof(props));
        api->get_physical_device_format_properties(pd, entries[i].format, &props);
        format_features_string(props.optimalTilingFeatures, flags, sizeof(flags));
        printf("%s = %s\n", entries[i].name, flags);
        if (entries[i].bc && !(props.optimalTilingFeatures & VK_FORMAT_FEATURE_SAMPLED_IMAGE_BIT))
            bc_ok = 0;
    }
    return bc_ok;
}

// Imports host memory through VK_EXT_external_memory_host. Returns 1 when a 4 KiB host allocation
// imports, and leaves the largest importable size in *largest (0 when none). A `host_pointer.<size>`
// line carries the memory type mask the query answered: 0 means no memory type takes that pointer
// (and is also printed when the test allocation itself could not be made).
static int probe_external_memory_host(VkDevice device, const struct caps *caps,
                                      PFN_vkGetMemoryHostPointerPropertiesEXT query, uint64_t *largest)
{
    static const uint64_t sizes[] = { 4096, 16384, 65536, 1048576, 4194304 };
    const size_t page = (size_t)getpagesize();
    size_t align = (size_t)caps->host_pointer.minImportedHostPointerAlignment;
    int four_k_ok = 0;

    *largest = 0;
    if (align < page)
        align = page;
    printf("# external_memory_host\n");
    printf("external_memory_host = present\n");
    printf("min_imported_host_pointer_alignment = %" PRIu64 "\n",
           (uint64_t)caps->host_pointer.minImportedHostPointerAlignment);

    for (size_t i = 0; i < sizeof(sizes) / sizeof(sizes[0]); i++) {
        size_t size = (size_t)sizes[i];
        size_t map_size = size + align;
        uint8_t *raw = mmap(NULL, map_size, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        uint32_t memory_type_bits = 0;
        if (raw == MAP_FAILED) {
            printf("host_pointer.%" PRIu64 " = 0x%08x\n", sizes[i], (unsigned)memory_type_bits);
            continue;
        }
        uintptr_t base = (uintptr_t)raw;
        size_t offset = (size_t)((align - (base % align)) % align);
        void *pointer = raw + offset;
        VkMemoryHostPointerPropertiesEXT props = {
            .sType = VK_STRUCTURE_TYPE_MEMORY_HOST_POINTER_PROPERTIES_EXT
        };
        VkResult result = query(device, VK_EXTERNAL_MEMORY_HANDLE_TYPE_HOST_ALLOCATION_BIT_EXT, pointer,
                                &props);
        if (result == VK_SUCCESS)
            memory_type_bits = props.memoryTypeBits;
        printf("host_pointer.%" PRIu64 " = 0x%08x\n", sizes[i], (unsigned)memory_type_bits);
        if (memory_type_bits != 0) {
            *largest = sizes[i];
            if (sizes[i] == 4096)
                four_k_ok = 1;
        }
        munmap(raw, map_size);
    }

    // A deliberately unaligned pointer must be rejected (spec: pMemoryHostPointer must be aligned
    // to minImportedHostPointerAlignment). The answer is safety-relevant, so a failed test
    // allocation ends the probe instead of guessing.
    {
        size_t map_size = 4096 + align + 4096;
        uint8_t *raw = mmap(NULL, map_size, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        if (raw == MAP_FAILED)
            fail("mmap failed for the unaligned host pointer test");
        uintptr_t base = (uintptr_t)raw;
        size_t offset = (size_t)((align - (base % align)) % align);
        uint8_t *pointer = raw + offset + (align > 1 ? align / 2 : 1);
        VkMemoryHostPointerPropertiesEXT props = {
            .sType = VK_STRUCTURE_TYPE_MEMORY_HOST_POINTER_PROPERTIES_EXT
        };
        VkResult result = query(device, VK_EXTERNAL_MEMORY_HANDLE_TYPE_HOST_ALLOCATION_BIT_EXT, pointer,
                                &props);
        printf("unaligned_rejected = %s\n", bool_word(result != VK_SUCCESS || props.memoryTypeBits == 0));
        munmap(raw, map_size);
    }

    printf("largest_importable = ");
    if (*largest != 0)
        printf("%" PRIu64 "\n", *largest);
    else
        printf("none\n");
    return four_k_ok;
}

int main(int argc, char **argv)
{
    uint32_t wanted_device = 0;

    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--device") == 0 && i + 1 < argc) {
            char *end = NULL;
            unsigned long value = strtoul(argv[++i], &end, 10);
            if (end == argv[i] || *end != '\0' || value > 0x7FFFFFFFul)
                fail("--device takes a device index");
            wanted_device = (uint32_t)value;
        } else if (strcmp(argv[i], "--help") == 0 || strcmp(argv[i], "-h") == 0) {
            printf("usage: " PROBE_NAME " [--device N]\n");
            return 0;
        } else {
            fail("unknown argument: %s", argv[i]);
        }
    }

    struct api api;
    memset(&api, 0, sizeof(api));

    // vkEnumerateInstanceVersion is 1.1; a 1.0 loader simply leaves the pointer unset.
    gipa_load(vkGetInstanceProcAddr, NULL, &api.enumerate_instance_version, "vkEnumerateInstanceVersion");
    if (!gipa_load(vkGetInstanceProcAddr, NULL, &api.create_instance, "vkCreateInstance"))
        fail("vkCreateInstance is missing from the loader");
    if (!gipa_load(vkGetInstanceProcAddr, NULL, &api.enumerate_instance_extension_properties,
                   "vkEnumerateInstanceExtensionProperties"))
        fail("vkEnumerateInstanceExtensionProperties is missing from the loader");

    uint32_t loader_api = VK_API_VERSION_1_0;
    if (api.enumerate_instance_version != NULL)
        api.enumerate_instance_version(&loader_api);
    if (loader_api < VK_API_VERSION_1_1) {
        char version[32];
        version_string(loader_api, version, sizeof(version));
        fail("Vulkan 1.1 or later is needed; the loader reports %s", version);
    }

    // The instance extension list is needed before the instance exists (to enable the one
    // extension the probe queries), so enumerate it through the loader's global entry point.
    uint32_t instance_ext_count = 0;
    if (api.enumerate_instance_extension_properties(NULL, &instance_ext_count, NULL) != VK_SUCCESS)
        fail("vkEnumerateInstanceExtensionProperties failed");
    VkExtensionProperties *instance_exts =
        calloc(instance_ext_count ? instance_ext_count : 1, sizeof(*instance_exts));
    if (instance_exts == NULL)
        fail("out of memory");
    if (instance_ext_count > 0 &&
        api.enumerate_instance_extension_properties(NULL, &instance_ext_count, instance_exts) != VK_SUCCESS)
        fail("vkEnumerateInstanceExtensionProperties failed");
    qsort(instance_exts, instance_ext_count, sizeof(*instance_exts), cmp_extension);

    VkApplicationInfo app = {
        .sType = VK_STRUCTURE_TYPE_APPLICATION_INFO,
        .pApplicationName = PROBE_NAME,
        .applicationVersion = 1,
        .pEngineName = "nxnative",
        .engineVersion = 1,
        .apiVersion = loader_api,
    };
    VkInstanceCreateInfo instance_info = {
        .sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO,
        .pApplicationInfo = &app,
    };
    VkInstance instance = VK_NULL_HANDLE;
    VkResult result = api.create_instance(&instance_info, NULL, &instance);
    if (result != VK_SUCCESS) {
        char version[32];
        version_string(loader_api, version, sizeof(version));
        fail("vkCreateInstance failed (VkResult %d) at API %s; is a Vulkan driver installed?", (int)result,
             version);
    }

    LOAD(instance, destroy_instance, "vkDestroyInstance");
    LOAD(instance, enumerate_physical_devices, "vkEnumeratePhysicalDevices");
    LOAD(instance, get_physical_device_properties, "vkGetPhysicalDeviceProperties");
    LOAD(instance, get_physical_device_properties2, "vkGetPhysicalDeviceProperties2");
    LOAD(instance, get_physical_device_features2, "vkGetPhysicalDeviceFeatures2");
    LOAD(instance, get_physical_device_queue_family_properties, "vkGetPhysicalDeviceQueueFamilyProperties");
    LOAD(instance, get_physical_device_memory_properties2, "vkGetPhysicalDeviceMemoryProperties2");
    LOAD(instance, get_physical_device_format_properties, "vkGetPhysicalDeviceFormatProperties");
    LOAD(instance, enumerate_device_extension_properties, "vkEnumerateDeviceExtensionProperties");
    LOAD(instance, create_device, "vkCreateDevice");
    LOAD(instance, destroy_device, "vkDestroyDevice");
    LOAD(instance, get_device_proc_addr, "vkGetDeviceProcAddr");

    uint32_t device_count = 0;
    if (api.enumerate_physical_devices(instance, &device_count, NULL) != VK_SUCCESS)
        fail("vkEnumeratePhysicalDevices failed");
    if (device_count == 0)
        fail("no Vulkan physical device found");
    VkPhysicalDevice *devices = calloc(device_count, sizeof(*devices));
    if (devices == NULL)
        fail("out of memory");
    if (api.enumerate_physical_devices(instance, &device_count, devices) != VK_SUCCESS)
        fail("vkEnumeratePhysicalDevices failed");

    if (wanted_device >= device_count)
        fail("--device %u: only %u physical device(s) present", (unsigned)wanted_device,
             (unsigned)device_count);

    // The contract asks a dump to say what it is in `;` lines. Nothing here names a machine, a moment
    // or a path, so the header is identical in every run.
    printf("; vk_probe: one Vulkan device's answers, one \"key = value\" per line under each \"# section\"\n");
    printf("; format and validity: dm/gfx/vk/probe/README.md, dm/gfx/vk/probe/tests/test_probe_output.py\n");

    char instance_version[32];
    version_string(loader_api, instance_version, sizeof(instance_version));
    printf("# instance\n");
    printf("instance_api_version = %s\n", instance_version);
    printf("instance_extension_count = %u\n", (unsigned)instance_ext_count);
    for (uint32_t i = 0; i < instance_ext_count; i++)
        printf("instance_extension = %s\n", instance_exts[i].extensionName);

    // # device names every device the loader found, so a dump can be checked against the machine it
    // came from; device_selected says which one the sections below describe.
    printf("# device\n");
    printf("device_count = %u\n", (unsigned)device_count);
    printf("device_selected = %u\n", (unsigned)wanted_device);

    VkPhysicalDevice pd = devices[wanted_device];
    VkExtensionProperties *device_exts = NULL;
    uint32_t device_ext_count = 0;
    for (uint32_t i = 0; i < device_count; i++) {
        uint32_t ext_count = 0;
        VkExtensionProperties *exts = device_extensions(&api, devices[i], &ext_count);
        struct device_info info;
        query_device_info(&api, devices[i], exts, ext_count, &info);
        print_device_fields(&info, i);
        if (i == wanted_device) {
            device_exts = exts;
            device_ext_count = ext_count;
        } else {
            free(exts);
        }
    }

    struct caps caps;
    memset(&caps, 0, sizeof(caps));
    query_caps(&api, pd, device_exts, device_ext_count, &caps);

    if (caps.props.apiVersion < VK_API_VERSION_1_1) {
        char version[32];
        version_string(caps.props.apiVersion, version, sizeof(version));
        fail("the selected device reports Vulkan %s; the probe needs 1.1 or later", version);
    }

    print_device_extensions(device_exts, device_ext_count);
    struct feature_set features = query_features(&api, pd, device_exts, device_ext_count, caps.props.apiVersion);
    print_features_block(&features, device_exts, device_ext_count);
    print_limits(&caps);
    print_memory(&api, pd);
    int bc_ok = print_formats(&api, pd);

    const int has_external_memory_host = has_ext(device_exts, device_ext_count, "VK_EXT_external_memory_host");
    int zero_copy_ok = 0;
    if (!has_external_memory_host) {
        printf("# external_memory_host\n");
        printf("external_memory_host = absent\n");
    } else {
        // A device is needed for the device-level query. No queues are used, so one is created on
        // the first family that can run graphics (falling back to any family with a queue).
        uint32_t family_count = 0;
        api.get_physical_device_queue_family_properties(pd, &family_count, NULL);
        VkQueueFamilyProperties *families = calloc(family_count ? family_count : 1, sizeof(*families));
        if (families == NULL)
            fail("out of memory");
        if (family_count > 0)
            api.get_physical_device_queue_family_properties(pd, &family_count, families);
        uint32_t family_index = 0;
        int found_family = 0;
        for (int want_graphics = 1; want_graphics >= 0 && !found_family; want_graphics--) {
            for (uint32_t i = 0; i < family_count; i++) {
                if (families[i].queueCount == 0)
                    continue;
                if (!want_graphics || (families[i].queueFlags & VK_QUEUE_GRAPHICS_BIT)) {
                    family_index = i;
                    found_family = 1;
                    break;
                }
            }
        }
        free(families);
        if (!found_family)
            fail("the selected device has no queue family to create a device on");

        float priority = 1.0f;
        VkDeviceQueueCreateInfo queue_info = {
            .sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,
            .queueFamilyIndex = family_index,
            .queueCount = 1,
            .pQueuePriorities = &priority,
        };
        const char *enabled_device_exts[2] = { "VK_EXT_external_memory_host", "VK_EXT_memory_budget" };
        uint32_t enabled_device_ext_count =
            has_ext(device_exts, device_ext_count, "VK_EXT_memory_budget") ? 2u : 1u;
        VkPhysicalDeviceFeatures enabled_features;
        memset(&enabled_features, 0, sizeof(enabled_features));
        VkDeviceCreateInfo device_info = {
            .sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO,
            .queueCreateInfoCount = 1,
            .pQueueCreateInfos = &queue_info,
            .enabledExtensionCount = enabled_device_ext_count,
            .ppEnabledExtensionNames = enabled_device_exts,
            .pEnabledFeatures = &enabled_features,
        };
        VkDevice device = VK_NULL_HANDLE;
        result = api.create_device(pd, &device_info, NULL, &device);
        if (result != VK_SUCCESS)
            fail("vkCreateDevice failed (VkResult %d)", (int)result);

        PFN_vkGetMemoryHostPointerPropertiesEXT host_pointer_query = NULL;
        PFN_vkVoidFunction raw = api.get_device_proc_addr(device, "vkGetMemoryHostPointerPropertiesEXT");
        if (raw == NULL) {
            api.destroy_device(device, NULL);
            fail("VK_EXT_external_memory_host is advertised but vkGetMemoryHostPointerPropertiesEXT is missing");
        }
        memcpy(&host_pointer_query, &raw, sizeof(raw));

        uint64_t largest = 0;
        zero_copy_ok = probe_external_memory_host(device, &caps, host_pointer_query, &largest);

        api.destroy_device(device, NULL);
    }

    printf("# exec_pages\n");
#if defined(PROBE_HAVE_MMAP) && defined(MAP_ANONYMOUS)
    {
        long page = (long)getpagesize();
        errno = 0;
        void *exec = mmap(NULL, (size_t)page, PROT_READ | PROT_WRITE | PROT_EXEC,
                          MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        if (exec == MAP_FAILED) {
            // The errno separates a kernel/SELinux denial (EACCES/EPERM) from a probe bug (EINVAL,
            // ENOMEM), which is why the contract carries it beside the answer.
            printf("exec_pages = denied\n");
            printf("exec_pages_errno = %d\n", errno);
        } else {
            printf("exec_pages = ok\n");
            munmap(exec, (size_t)page);
        }
    }
#else
    // No anonymous mmap: the answer is not "denied", so the dump must not claim it.
    fail("no <sys/mman.h> anonymous mapping to test exec pages with");
#endif

    printf("# pagesize\n");
    printf("pagesize = %d\n", (int)getpagesize());

    printf("# verdict\n");
    printf("zero_copy = %s\n", zero_copy_ok ? "ok" : "copy-only");
    printf("bc_textures = %s\n", bc_ok ? "ok" : "missing");
    printf("guest_upload_cost = %s\n", zero_copy_ok ? "none" : "mirror");
    // Offline pipelines are the ones the device does not have to compile: VK_KHR_pipeline_binary
    // writes and consumes them; without it every pipeline is compiled on the device (into an
    // on-device VkPipelineCache at best).
    printf("pipeline_cache_offline = %s\n",
           has_ext(device_exts, device_ext_count, "VK_KHR_pipeline_binary") ? "ok" : "recompile");
    printf("mirror_clamp = %s\n", features.sampler_mirror_clamp_to_edge ? "ok" : "missing");

    free(device_exts);
    free(devices);
    free(instance_exts);
    api.destroy_instance(instance, NULL);
    return 0;
}
