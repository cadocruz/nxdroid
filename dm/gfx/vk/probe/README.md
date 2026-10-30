# Vulkan capability probe

`vk_probe` answers, on one device, the questions the Android port's Vulkan replay backend depends
on: whether the game's own memory can be bound to Vulkan without copying, whether the driver can
sample the block-compressed textures the game ships, whether pipelines can be built offline,
whether `samplerMirrorClampToEdge` exists, and the exact vendor/device/driver identity the engine's
Adreno 740/750 gates are keyed on.

It is a standalone C11 program: not part of the host build, not wired into CI. It is headless — no
X11, Wayland, Android window or surface — and needs only the Vulkan headers in
`dm/third_party/vulkan-headers/include` (1.4.363) and the platform's Vulkan loader. On desktop it
links the system loader (`-lvulkan`). Only `vkGetInstanceProcAddr` is referenced from it: on Android
the NDK's `libvulkan.so` stub for the probe's minimum API level (21) carries the 1.0 entry points
only, and extension entry points have no stubs at all, so every other entry point is resolved
through `vkGetInstanceProcAddr`.

## The format is a contract

`tests/test_probe_output.py` defines the dump format as code, and the probe conforms to it. A dump
pulled from the phone is validated on any machine, with no GPU and no game files:

```sh
python3 dm/gfx/vk/probe/tests/test_probe_output.py s23-ultra.txt   # prints "valid", or [RED] lines
```

The rules it enforces:

- One fact per line, `<key> = <value>`, one space either side of `=`. `;` starts a comment line: the
  dump begins with two `;` lines saying what it is, and they are transport, not facts.
- The eleven sections appear exactly once, in this order: `instance`, `device`, `extensions`,
  `features`, `limits`, `memory`, `formats`, `external_memory_host`, `exec_pages`, `pagesize`,
  `verdict`.
- No ANSI escapes, absolute paths, timestamps or addresses: two dumps of one device must differ only
  by the device. `device.<i>.driver_info` is exempt from the path and timestamp rules: it is the
  vendor's own string and may name a build path or a date.
- Exit code 0 on success; 2 with a `[RED] ` line on stderr when Vulkan cannot be initialised.

`# device` names every physical device the loader found, so a dump can be checked against the
machine it came from; `device_selected` then says which device **`# features`, `# limits`,
`# memory`, `# formats` and `# external_memory_host` describe**. The instance sections (`# instance`,
`# extensions`) are the loader's and the selected device's.

### `# instance`

```
instance_api_version = 1.4.341          ; the loader's API version, decoded
instance_extension_count = 27
instance_extension = VK_KHR_surface     ; one line per instance extension, sorted by name
```

### `# device`

`device_count` first, then `device_selected`, then nine fields per device for every device index
`0..device_count-1`:

```
device.0.name = NVIDIA GeForce RTX 5060 Ti
device.0.device_type = discrete_gpu     ; cpu, discrete_gpu, integrated_gpu, virtual_gpu, other
device.0.vendor_id = 4318               ; VkPhysicalDeviceProperties::vendorID, decimal (0x10de)
device.0.device_id = 11524              ; decimal (0x2d04)
device.0.api_version = 1.4.312          ; decoded
device.0.driver_version = 580.178.4.0   ; decoded: three numbers, four where the vendor encodes one
device.0.driver_version_raw = 2435612928  ; the raw 32-bit VkPhysicalDeviceProperties::driverVersion, decimal
device.0.driver_id = nvidia_proprietary   ; Vulkan's VkDriverId name, lower case, or its number
device.0.driver_info = 580.178.04         ; verbatim
```

`driver_version` is decoded per vendor, like vulkan.gpuinfo.org: NVIDIA is
`10/8/8/6 bits` (four numbers), Intel's proprietary Windows driver is `14/14 bits` (printed with a
trailing `.0` because the contract wants three or four components), everything else is the Vulkan
1.1 recommendation `10/10/12`. `driver_version_raw` is the value a gate must compare against: the
decoding is the vendor's convention, the raw integer is not. `driver_id` is `unknown` on a device
below Vulkan 1.2 that does not advertise `VK_KHR_driver_properties`.

### `# extensions`

One line per device extension of the selected device, sorted by name:

```
device_extension = VK_EXT_external_memory_host 1
```

### `# features`

Vulkan feature names in lowerCamelCase, `true`/`false` for a feature bit and `present`/`absent` for
an extension-backed capability. The literal extension names and their specVersions are in
`# extensions`; this section answers the orthogonal question "is the capability there".

```
timelineSemaphore = true
storageBuffer16BitAccess = true
textureCompressionASTC_LDR = false
samplerMirrorClampToEdge = true
robustness2 = true
externalMemoryHost = present
graphicsPipelineLibrary = present
hostImageCopy = present
memoryBudget = present
pipelineBinary = present
portabilitySubset = absent
shaderFloatControls = true
shaderFloatControls2 = present
```

Some answers have a definition the key does not spell out:

- `descriptorIndexing` — runtime-sized descriptor arrays, non-uniform indexing of sampled images and
  storage buffers, partially bound bindings and variable descriptor counts are all supported (the
  bindless set the replay backend would use).
- `robustness2` — `VK_EXT_robustness2` (or `VK_KHR_robustness2`) is advertised *and* its
  `nullDescriptor` feature is set; robust buffer/image access are not required by the port.
- `portabilitySubset` — the vendored header carries the portability-subset `sType` values but not the
  extension's name or feature struct, so the answer is the extension's presence
  (`VK_EXT_portability_subset` or `VK_KHR_portability_subset`), which only a portability
  implementation advertises.
- `shaderFloatControls` — the feature group carries no bits: true from Vulkan 1.2 on, or when
  `VK_KHR_shader_float_controls` is advertised.

### `# limits`

Vulkan limit names (lowerCamelCase) as decimals; array limits take a dotted index and the three
float limits carry three decimals:

```
maxImageDimension2D = 32768
maxViewportDimensions.0 = 32768
maxViewportDimensions.1 = 32768
maxComputeWorkGroupSize.2 = 64
maxMemoryAllocationSize = 4292870144
timestamp_compute_and_graphics = true
timestampPeriod = 1.000
maxSamplerLodBias = 15.000
maxSamplerAnisotropy = 16.000
```

`subgroupSize`, `minSubgroupSize` and `maxSubgroupSize` are properties rather than limits, printed
here because the shader path needs them (subgroup-dependent rewrites) and the contract has no
properties section.

### `# memory`

```
memory_heap_count = 2
memory_type_count = 5
memory_heap.0.size = 17103323136        ; bytes
memory_heap.0.flags = device_local      ; flag names, space separated, or none
memory_type.2.flags = host_visible host_coherent
memory_type.2.heap_index = 1
```

Heap budget and usage are deliberately not printed: they are live driver counters (another process
allocating memory moves `usage`, so two runs would differ) and the contract has no key for them.
The extension's presence is `memoryBudget` in `# features`.

### `# formats`

Optimal-tiling format features, one `VK_FORMAT_` name per line, value a space-separated subset of
`sampled storage color depth blit-src blit-dst filter-linear transfer-dst atomic`, or `none`:

```
VK_FORMAT_BC1_RGBA_UNORM_BLOCK = sampled blit-src filter-linear transfer-dst
VK_FORMAT_ASTC_4x4_UNORM_BLOCK = none
```

### `# external_memory_host`

Absent:

```
external_memory_host = absent
```

Present:

```
external_memory_host = present
min_imported_host_pointer_alignment = 4096
host_pointer.4096 = 0x0000000c          ; the memory type mask the query answered, per tested size
host_pointer.4194304 = 0x0000000c
unaligned_rejected = true
largest_importable = 4194304            ; bytes, or none
```

A `host_pointer.<size>` mask of `0` means no memory type takes a pointer of that size.
`unaligned_rejected` answers a pointer deliberately not aligned to
`minImportedHostPointerAlignment`: `true` is what the Vulkan spec requires; `false` means the driver
does not check, which is still undefined behaviour, so the port must keep imports aligned either
way.

### `# exec_pages` and `# pagesize`

```
exec_pages = ok                         ; or denied
exec_pages_errno = 13                   ; only when denied: the errno of the failed mmap
pagesize = 4096
```

The errno separates a kernel/SELinux W^X denial (`EACCES`/`EPERM`) from a probe bug (`EINVAL`,
`ENOMEM`) — the two need different answers from the port.

### `# verdict`

Five decisions derived from the answers above:

```
zero_copy = ok                          ; or copy-only
bc_textures = ok                        ; or missing
guest_upload_cost = none                ; or mirror
pipeline_cache_offline = ok             ; or recompile
mirror_clamp = ok                       ; or missing
```

`zero_copy = ok` goes with `guest_upload_cost = none`, and `copy-only` with `mirror`: a verdict that
contradicts itself is reported by the checker. `pipeline_cache_offline = ok` when
`VK_KHR_pipeline_binary` is advertised (pipelines are written and consumed offline); otherwise every
pipeline is compiled on the device, at best through an on-device `VkPipelineCache`.

## Desktop

```sh
make -C dm/gfx/vk/probe            # cc -std=c11 -O2 -Wall -Wextra -Werror ... -lvulkan
make -C dm/gfx/vk/probe run        # or: dm/gfx/vk/probe/vk_probe [--device N]
dm/gfx/vk/probe/vk_probe > dump.txt   # a dump is the binary's own stdout (make prints its own lines too)
```

The probe never needs a window, so a device without a display works. `# device` lists what the loader
found; pick one with `--device N` (default 0), for example the Mesa CPU driver (lavapipe) when a GPU
node is not wanted:

```sh
dm/gfx/vk/probe/vk_probe --device 1
VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/lvp_icd.json dm/gfx/vk/probe/vk_probe
```

`vulkaninfo --summary` shows the same device list if the indices are unclear.

## Samsung Galaxy S23 Ultra

Build the arm64-v8a PIE executable (needs an NDK; the target fails with a message when `NDK` /
`ANDROID_NDK` is not set):

```sh
make -C dm/gfx/vk/probe android NDK=$HOME/Android/Sdk/ndk/27.2.12479018
```

Copy it over and run it from `/data/local/tmp` (the one place on the phone where a pushed binary may
be executed without being installed in an app):

```sh
adb push dm/gfx/vk/probe/vk_probe_android /data/local/tmp/
adb shell chmod 755 /data/local/tmp/vk_probe_android
adb shell /data/local/tmp/vk_probe_android        # every device named, device 0 probed
adb exec-out /data/local/tmp/vk_probe_android > s23-ultra.txt
```

`adb push` lands the file non-executable, hence the `chmod 755`; without it the shell answers
`Permission denied`. Keep the binary in `/data/local/tmp` — a push to `/sdcard` lands on a noexec
mount. The probe needs no root and no app package. It runs in the shell's SELinux domain, which is
the easiest case for `exec_pages`; an app's domain is stricter, so a `denied` here is final and an
`ok` here does not guarantee the same inside the app.

## What to look for

| Key | What to look for | What it means for the port |
|---|---|---|
| `device.i.vendor_id`, `device.i.device_id`, `device.i.driver_version`, `device.i.driver_version_raw`, `device.i.driver_id` | `vendor_id = 20803` (0x5143, Qualcomm) and `driver_id = qualcomm_proprietary` on the S23 Ultra; record the exact `device_id`/`driver_version_raw` pair | Key for the adopted engine's Adreno 740/750 gates: on those parts its `gfx-quad-derivatives` and `gfx-warp32` shader rewrites must stay off or the driver drops the device. Compare with what the engine's gate tests before trusting a hardcoded value; the probe is the only source for this triple on our device. Gate on `driver_version_raw`, not on the decoded string |
| `device.i.api_version` | 1.3 or later on the S23 Ultra | Sets which core features and structs the backend can rely on without extension fallbacks |
| `samplerMirrorClampToEdge`, `mirror_clamp` verdict | `true` (core 1.2 feature from 1.2 on, extension presence before that) | *Required*: the adopted engine creates its device with `samplerMirrorClampToEdge` enabled, so `mirror_clamp = missing` blocks the adoption as is |
| `external_memory_host`, `host_pointer.<size>`, `largest_importable`, `zero_copy`, `guest_upload_cost` | `present`, a non-zero mask for at least `host_pointer.4096`, `largest_importable >= 4194304` | The execution model wants guest memory bound as Vulkan memory (`vkAllocateMemory` from the host pointer). `ok`/`none` = zero copy; `copy-only`/`mirror` = every buffer/texture upload is copied, which is the plan's fallback but costs bandwidth and memory |
| `min_imported_host_pointer_alignment`, `unaligned_rejected` | Alignment is expected to be the page size; an unaligned pointer should be rejected | Imports must be aligned to it even when the driver does not check; a page or larger alignment matching the game's pages keeps the mapping straightforward |
| `textureCompressionBC`, `bc_textures`, the BC rows of `# formats` | Adreno does not support BC; expect `textureCompressionBC = false`, `bc_textures = missing` | The Switch ships BC1/BC3/BC5/BC7 textures. `missing` means BC must be transcoded to ASTC or decompressed at load; that choice drives the texture upload path and its cost |
| `textureCompressionASTC_LDR`, the ASTC rows | `true` on Adreno, ASTC 4x4/6x6/8x8 sampleable | The transcode target (and the format the engine's own textures use) |
| `pipelineBinary`, `pipeline_cache_offline` | extension usually absent on mobile | `recompile` = the device compiles every pipeline; the build must ship SPIR-V and expect a first-run pipeline cache warm-up |
| `timelineSemaphore`, `synchronization2`, `dynamicRendering`, `maintenance4`, `descriptorIndexing` | all `true` on a Vulkan 1.3 phone | What the replay backend may use without fallbacks; `descriptorIndexing = false` forces a descriptor-set-per-texture path |
| `maxMemoryAllocationSize`, `bufferImageGranularity`, `nonCoherentAtomSize` | `maxMemoryAllocationSize` in the GB range, `bufferImageGranularity` 64–4096 | One allocation for the game's pools, and how uploads/bindings must be split; `nonCoherentAtomSize` sets the flush granularity for host-visible memory |
| `maxStorageBufferRange`, `maxDescriptorSetStorageBuffers`, `maxPerStageDescriptorStorageBuffers` | large ranges and descriptor counts | Guest pools are big and bindless: a small `maxStorageBufferRange` means binding per range; small descriptor counts mean descriptor updates per draw |
| `maxImageDimension2D`/`3D`, `maxImageArrayLayers`, `maxFramebufferWidth`/`Height`, `maxColorAttachments` | at least 8192/2048, 8 attachments | The game's render targets and array layers must fit; MRT count matters for deferred passes |
| `maxComputeWorkGroupInvocations`, `maxComputeWorkGroupSize.0..2`, `maxComputeWorkGroupCount.0..2`, `subgroupSize`, `minSubgroupSize`/`maxSubgroupSize` | 128–1024 invocations; subgroup 32 or 64 | The compute passes' workgroup shapes and any subgroup-dependent shader rewrite |
| `# memory` heaps and types | the Adreno heap sizes, a `host_visible host_coherent` type | Sizing the port's pools and upload staging |
| `timestamp_compute_and_graphics`, `timestampPeriod` | `true`, ~1–52 ns/tick | GPU timing for frame pacing (power work depends on it) |
| `exec_pages`, `exec_pages_errno` | `ok`, or `denied` with `13`/`1` (SELinux W^X) | `denied` = a page cannot be written and executed at once; runtime code patching must use a writable alias of the same physical page (or write, then `mprotect` to executable), never one RWX mapping |
| `pagesize` | `4096` on the S23 Ultra | 4 KiB pages are the layout the NVN dirty tracking and the zero-copy pools assume; a 16 KiB device would change the granularity everywhere |
| `# verdict` | `zero_copy`, `bc_textures`, `guest_upload_cost`, `pipeline_cache_offline`, `mirror_clamp` | The five decisions this probe exists for, derived from the answers above |
