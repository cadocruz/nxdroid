# Handoff: running this host on Android (nxdroid)

This file is the state of the Android port at a cut in the work, written so that the next
session (or person) can continue without re-deriving anything. It is not a design document: the
design lives in `dm/gfx/vk/address_space.md` and `docs/reference/android.md`, and the per-op detail
in `dm/gfx/vk/engine_smoke/opcode_map.txt` and `payload_mismatch.txt`. This file says **where the
work stands, what is broken, what to do next, and how to run it**.

The repository's remote is `origin https://github.com/cadocruz/nxdroid.git`. `main` holds ten commits, all
pushed (`origin/main` is at the last, `34fb039`). The first three: `8e050e9` (initial), `f7e190d` (the host
bring-up, §8 items 4, 4a, 4b, the `P6` viewport work and engine rounds F to I, §7, and the rewritten
`README.md`) and `6dc397b` (this file). Then the audit follow-ups (`c700ca3`), the app shell and first
device bring-up (`8e01dd0`), hardware video, the virtual controller and the launcher (`3e947dc`), and the
Sprint 6 graphics fixes and diagnostics (`1ff60c1`, `d33b9df`, `22cc33d`, `34fb039`). The commits were made
outside the coordinating session, with the repository-local identity
`Ricardo A. F. da Cruz <7233682+cadocruz@users.noreply.github.com>` (`.git/config`; the global one is
untouched) and mostly Portuguese messages. `AGENTS.md` asks for the `seedds` identity and English text; that
rule goes with the Apple removal (§8 item 10).

## Status at this cut (Sprint 6 – Physical Device Bring-Up & Live Diagnostics)

The Android port has been compiled with the NDK, packaged as an APK, and successfully executed on a
physical **Samsung Galaxy S23 Ultra** (Snapdragon 8 Gen 2, Adreno 740, 12 GB RAM, Android 16 / SDK 36, the
version the probe measured) via `com.nxdroid`.

The first fully running title is **Mario Kart 8 Deluxe** (`0100152000022000`, Update 4.0.1 `[v1507328]`):
- **Native AArch64 execution:** Horizon SVCs and SDK services handled by `dm/host`, NSO modules rewritten via `dm/tools/patch_nso.py --target=android`.
- **H.264 Video Playback:** Implemented using Android's NDK `AMediaCodec` in `dm/android/apple_stubs.c` (decoding H.264 menu video previews into CVPixelBufferRef NV12 and rendering cleanly in real time).
- **Audio Output:** Real audio enabled via AAudio in `dm/android/apple_stubs.c` (48 kHz stereo PCM).
- **Frontend & Virtual Controller:** Argon launcher overlay (`LauncherOverlayView.java`, `GameScanner.java`) with storage picker and game catalog; on-screen multitouch virtual gamepad (`VirtualControllerOverlayView.java`) with left stick, D-Pad, triggers, face buttons, and show/hide toggle (`🎮`).
- **Automated Game Deployment:** `scripts/prepare_game_android.py` automates base+update RomFS extraction, NSO rewriting, shader compilation, Mii database setup from emulator userdata, and ADB pushing.

### Visual & Performance Diagnostics

Detailed diagnostics and live GPU/CPU telemetry were gathered during 3D race execution on device:

1. **Vertical Banding / "Venetian Blinds" Decimation Artifacts (Resolved):**
   - *Symptom:* Display exhibited 16 vertical columns of alternating brightness and sharpness across the screen.
   - *Cause:* `present_native = true` in `vulkan_present.cpp` called `ANativeWindow_setBuffersGeometry(active, 1920, 1080)`. Because the S23 Ultra display is a physical portrait panel (1544x720 landscape, 90° rotation), Qualcomm's Hardware Composer (DPU) performed non-integer column decimation across macroblock boundaries.
   - *Fix:* Kept the swapchain at native window resolution (`1544x720`), disabled `ANativeWindow_setBuffersGeometry` override (`present_native = false`), and enabled `VK_FILTER_LINEAR` in `vkCmdBlitImage`. The Adreno GPU now performs smooth bilinear downscaling with zero DPU decimation stripes.

2. **3D Scene Color Solarization, Washed Out Tracks & Black Crushing (Resolved):**
   - *Symptom:* 2D UI elements and MP4 video playback had accurate colors, but 3D track scenes (e.g. Mario Kart Stadium) and track preview cards displayed severe solarization, posterized color steps, contour banding, and crushed black shadows.
   - *Root Causes Found & Fixed:*
     a) **3D LUT Subresource Bounds Violation (`VK_IMAGE_VIEW_TYPE_3D`):** In `xbg_game.cpp::Image::view()`, creating a view for MK8DX's 32x32x32 color correction LUT (`agl::env::ColorCorrection`) passed `layerCount = 32` (`depth`) into `VkImageSubresourceRange`, violating Vulkan spec `VUID-VkImageViewCreateInfo-imageViewType-04973` (`baseArrayLayer` must be 0 and `layerCount` must be 1 for 3D image views). This corrupted Qualcomm Adreno 740's texture sampling unit during 3D trilinear interpolation, causing solarized and posterized tone curves. Fixed by forcing `base_layer = 0` and `layer_cnt = 1` when `type == VK_IMAGE_VIEW_TYPE_3D`.
     b) **Render Target Memory Pool Aliasing in `invalidate_cpu_range`:** In `xbg_game.cpp`, the game allocates both transient CPU buffers (uniforms, scratch) and GPU render targets (e.g. serial 6030 of size 8.7 MB) inside the same memory pool (`0x7b5ba80000`). Small CPU writes (e.g. 2 KB) triggered `invalidate_cpu_range()`, resetting `im.gpu_written = false` and `im.uploaded = false` on active GPU render targets. Later draws called `get_image(..., true)`, re-uploading uninitialized CPU guest memory over active GPU render targets and destroying scene lighting. Fixed by preserving `im.gpu_written` during partial CPU memory writes.
     c) **Pipeline Blacklist False Positives (`gfx-pipe-skip`):** Stopping the app while warm threads compiled pipelines left inflight markers, causing `pipeguard::load()` to blacklist 89 critical pipelines. Removed poisoned cache files on device.
     d) **Texture View Swizzle Matching:** Fixed `registered_texture_equal` and `register_texture_record` to account for `view->set_swizzle` and `view->swz`, preventing incorrect view aliasing.
     e) **Depth Clip Control Alignment:** Added `gfx-depth-clip` marker check to avoid doubling the depth transformation (`negativeOneToOne`), as vertex shaders already have `z = 0.5 * z + 0.5 * w` baked in by `prepare_game_android.py`.
   - *Verification on S23 Ultra:* Full 256-level dynamic range across all color channels (R: 256, G: 256, B: 256), with over 21,000 smooth colors in the track preview cards and vibrant Nintendo colors (blue `#7860E8`, yellow `#FDE54F`, orange `#FEA42A`).

3. **Framerate Telemetry (~53.7 FPS achieved):**
   - *Telemetry on Galaxy S23 Ultra:* `fps = 53.67`, `gpu_ms = 7.96 ms`, `submit_cpu_ms = 6.66 ms`, `present_cpu_ms = 0.48 ms`.
   - *Bottlenecks Resolved:*
     a) Triple buffering enforced in `vulkan_present.cpp` (`ci.minImageCount = 3`), eliminating SurfaceFlinger fence stalls.
     b) Hash overhead eliminated by setting `DM_GFX_*` defaults (`DM_GFX_TEX_DIRTY=1`, `DM_GFX_READ_PREFLIGHT=0`, `DM_GFX_NOLOAD=1`, `DM_GFX_FORWARD_TEMPS=1`, etc.) in `nativeStartHost()`, avoiding redundant CPU texture hashing.
     c) Vertex/index cache (`vcache`) active with ~1,364 hits/frame and pipeline memo hitting ~800+ draws/frame.

---

## 1. The goal

Run this repository's catalogue natively on Android, on a Samsung Galaxy S23 Ultra. Native means
what it means on the Apple builds: the game's own AArch64 code runs, rewritten only where Apple's
kernel or Android's requires it; a host answers Horizon's SVCs and the SDK's services; and the
graphics layer that is Metal on Apple (`dm/gfx/nvn/nvn_mtl.m`) becomes Vulkan here.

The model does not change: guest virtual address == host address, guest memory is mapped memory,
the NVN command stream is replayed. What changes is which GPU API that replay speaks.

## 2. Decisions taken, with the reason

| Decision | Choice | Why |
|---|---|---|
| Porting base | [`jhaizhou-ops/d2r-mobile`](https://github.com/jhaizhou-ops/d2r-mobile) (MIT), pinned at `1e0e7934c9ccdf95494aee5065d1d07ab3cc3918`, tag `v2.1.0` | It is the real upstream: a Vulkan engine written by a fork of this repository, against this repository's `nvn_obj.h`/`nvn_mtl.h` ABI, with Adreno-specific driver gates and a vendored bionic compatibility layer |
| `ghostyshell/nx2apk` | reference only | It proves the model (Devil May Cry 3 at 60 fps on a Galaxy S10e, Mali-G76, no emulation) but it is Mali-shaped (no Adreno gate), 365 commits behind, requires a Mac to translate shaders, and has no scheme for the Adreno 128 MiB binding limit. Its `dm/android/nvn_vk.c` is still the best reference for the 27 missing `mtl_*` entry points: it implements exactly those, in this ABI |
| `wdjwxh/Taikou5-mobile` | rejected | Ahead of `nx2apk`, behind `d2r-mobile`; a downstream of the same engine |
| Build environment | **podman**, rootless, not docker | The host's docker daemon is down and podman is installed (5.7.0). The vendored `dm/android/docker/` is docker-shaped; it is used as a Dockerfile only |
| `dm/gfx/nvn/nvn_obj.h` | master | The engine adapts to our command vocabulary, not the reverse. 93 game profiles record through `dm/gfx/nvn/hle_nvn.c`; the engine's fork had diverged from it |
| Zero-copy | **not available**; mirror is the baseline | `VK_EXT_external_memory_host` is absent on the Adreno 740. The only remaining route is to allocate pool memory *as* an `AHardwareBuffer` and import it — unmeasured, see §8 item 6 |
| Platforms | **Android only**, owner's decision | nxdroid is never built for Mac or iOS again. Consequences: `regress.py check --games` and the Mac `make -C dm/host` are no longer requirements; the Apple branch of `port.h`, the `.m` files and the IPA tooling stay in the tree only until the **last** task (§8 item 10), because `nvn_mtl.m` is still the reference the `opcode_map` / `abi_gaps` gates compare against |

## 3. The target, measured

The full table with its consequences is in `docs/reference/android.md` under **The target device,
measured**. The load-bearing facts:

- Adreno (TM) 740, Vulkan 1.3.128, driver 512.676.1, Android 16 (SDK 36), 4 KiB pages, 11.58 GB UMA.
- `VK_EXT_external_memory_host` **absent** → the replay mirrors guest memory; the memory types a
  pool would use are `device_local` **and** `host_visible`, so a mirror copy is a plain `memcpy`.
- `maxStorageBufferRange = 128 MiB` with `shaderInt64 = false` → **this is the backend's central
  design problem**: NVN hands shaders 64-bit GPU addresses into pools of arbitrary size, and the
  device can neither bind more than 128 MiB at once nor let a shader do 64-bit pointer arithmetic.
  `VK_KHR_buffer_device_address` is present and useless for the same reason.
  `dm/gfx/vk/address_space.md` settles it: **option A1**, one descriptor per NVN binding at
  `(B & ~63) - P` with `range = min(poolEnd - (B & ~63), 128 MiB)`, and the translator answering
  `QueryHasUnalignedStorageBuffer() = true` / `QueryHostStorageBufferOffsetAlignment() = 64`, which
  it already supports and which costs two ALU ops per guest global access on Vulkan only.
- BC textures are native; `subgroupSize = 64`; no `VK_KHR_pipeline_binary` or
  `VK_EXT_graphics_pipeline_library` (so a persisted `VkPipelineCache` is mandatory for load time).

The dump itself is not in the repository (it is a device artifact); regenerate it with the probe
(§5) if the numbers need re-checking, and put any new fact in `docs/reference/android.md`, not here.

## 4. What is in the tree

| Path | What it is | State |
|---|---|---|
| `dm/gfx/vulkan/` (85 files) | the vendored Vulkan engine and its `nvn_vk.c` adapter | imported, pinned, adapted (`xbg_game.cpp` 12 handlers, `nvn_vk.c` 27 entry points) |
| `dm/android/` (compat, docker, front end, CMake) | the vendored bionic compatibility layer and build environment | imported; `CMakeLists.txt` (any profile, `-DGAME=`), `front_android.c` (our `front.h`) and `vulkan_present.cpp` (viewport features) are adapted; `tools/host_sources.py` is ours; configured and built with NDK r29, linked into `libdm.so` and `dmhost`, both run on the device (§8 item 9) |
| `dm/tools/android_vendor.py` + `.tsv` | provenance gate: 108 rows, 11 adapted | green on Linux; on a Windows checkout (autocrlf, no file modes) compare against the HEAD blobs |
| `dm/gfx/vk/probe/` | the device capability probe: `vk_probe.c`, a Makefile with a desktop and an `android` target, a frozen output contract in `tests/test_probe_output.py` | built and run on the device, 0 breaches |
| `dm/gfx/vk/engine_smoke/` | the out-of-tree harness that compiles the vendored engine against **our** headers and initializes it, plus the two generated vocabulary reports and `README.md` | green on desktop (llvmpipe + RTX 5060 Ti) |
| `dm/gfx/vk/address_space.md` | the 64-bit-address-space decision | written, unreviewed by hand |
| `dm/host/port.h`, `dm/android/port_android.c`, `dm/android/apple_stubs.c` (+ `apple_stubs/include`) | the host's platform layer (Apple inline, bionic real) and the Android implementations of the Apple media interfaces (AAudio output, MediaCodec H.264) with the remaining stubs (AAC) | compiled for arm64 with the NDK and run on the device; AAC through `AudioConverter` is still a stub (§8 items 4, 4a) |
| `dm/android/tools/{host_sources,undef_scan}.py`, `dm/tools/tests/test_{thread_slots,android_undef_scan}.py` | the source-list expander, the undefined-symbol and Mach-O assembly gate, and their tests | green |
| `dm/tools/android_audit.py` + baseline + tests | "is this file portable to Android?", with a baseline that only shrinks | green; 760 hits in 38 files |
| `README.md` | rewritten for nxdroid: Android-only, status (built and running on the S23 Ultra), build structure, open list | current; its gallery block is generated from Apple builds (§8 item 10) |
| `docs/reference/android.md` | the vendored engine reference: pin, gate, device, Adreno gates, ABI gaps, licensing | current |
| `.opencode/agents/android-{dev,qa,shaders,upstream}.md` | the four specialist agents this work was coordinated through | in use / active |

## 5. Gates, and the exact commands

Run these before believing anything:

```sh
# vendored provenance: 108 files, 11 adapted
python3 dm/tools/android_vendor.py --check

# the engine compiles against our headers, every TU, no workaround
make -C dm/gfx/vk/engine_smoke report CC=clang CXX=clang++     # 8 C + 12 C++ + 2 repo + 2 harness, all ok
make -C dm/gfx/vk/engine_smoke run                              # llvmpipe: exits 0, fatals=0
make -C dm/gfx/vk/engine_smoke run-gpu                          # RTX 5060 Ti: exits 0, fatals=0

# the two generated vocabulary reports match the tree
python3 dm/gfx/vk/engine_smoke/opcode_map.py --check
python3 dm/gfx/vk/engine_smoke/abi_gaps.py --check

# host portability audit: the baseline is the record, it only shrinks
python3 dm/tools/android_audit.py --summary
python3 dm/tools/android_audit.py --check

# docs, vendor gate, audit, probe contract, the rewriter's thread slot stubs, undef_scan's Mach-O gate
python3 -m pytest dm/tools/tests/test_docs.py \
    dm/tools/tests/test_android_vendor.py dm/tools/tests/test_android_audit.py \
    dm/tools/tests/test_thread_slots.py dm/tools/tests/test_android_undef_scan.py \
    dm/gfx/vk/probe/tests/test_probe_output.py -q
python3 dm/tools/docs_symptoms.py    # after any docs/reference edit

# engine source checks that need no device (text checks, not compiles); event_order_test needs hle_nvn.c and xbg_game.cpp as they are
python3 dm/gfx/vulkan/engine/tests/pipeline_memo_source_test.py
python3 dm/gfx/vulkan/engine/tests/event_order_test.py
```

On the Windows machine this round was done on: use LibreOffice's python with `-X utf8`, `CC=gcc` for
`opcode_map.py`, `pytest` was absent there at first (run the modules with `unittest`; a later pass reports the pytest suite passing, so check what is installed), and read §10 for the CRLF false reds.

The system `python3` has no pytest; use `python3 -m pytest`. The full
`dm/tools/tests` suite is **not** green on this machine and was not before this work: five modules
fail to import (`/usr/lib/libproc.dylib`, a macOS-only dependency) and the fuzz corpus needs
`lz4`, which the venv does not have. Those are environment gaps, not regressions — but say so
rather than claiming the suite passes.

Building and running on the device:

```sh
# toolchain image (derived from dm/android/docker/Dockerfile, adding make, git, file)
podman run --rm --userns=keep-id -v "$PWD:/src:rw" -w /src dm-android-tools:1 \
    make -C dm/gfx/vk/probe android NDK=/opt/android-sdk/ndk/29.0.14206865

# the host for one profile (GAME as in make -C dm/host; no default): configure + dmhost. Built with this
# NDK (r29) and run on the device (§8 item 9). ANDROID_PLATFORM >= 29 (the guest thread slots are in bionic's TLS_SLOT_APP,
# the app's from 29, §8 item 4a; the Vulkan 1.1 entry points need 28; the CMake stops below 29) and arm64-v8a only.
# The game's modules must be rewritten with dm/tools/patch_nso.py --target=android: the loader refuses the default (Apple) output. A profile outside the repository:
# mount its folder and pass DM_GAMES_DIR in the environment (-e DM_GAMES_DIR=/games -v <folder>:/games:ro);
# the configure keeps it in the cache for the build.
podman run --rm --userns=keep-id -v "$PWD:/src:rw" -w /src dm-android-tools:1 \
    cmake -S dm/android -B build/android/<GAME> -DGAME=<GAME> -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=29 \
      -DCMAKE_TOOLCHAIN_FILE=/opt/android-sdk/ndk/29.0.14206865/build/cmake/android.toolchain.cmake
podman run --rm --userns=keep-id -v "$PWD:/src:rw" -w /src dm-android-tools:1 cmake --build build/android/<GAME> --target dmhost

ADB=/tmp/opencode/platform-tools/adb          # 37.0.1; the device is RQCX808VH9K
$ADB push dm/gfx/vk/probe/vk_probe_android /data/local/tmp/vk_probe
$ADB shell chmod 755 /data/local/tmp/vk_probe && $ADB shell /data/local/tmp/vk_probe > /tmp/opencode/s23-ultra.txt
python3 dm/gfx/vk/probe/tests/test_probe_output.py /tmp/opencode/s23-ultra.txt   # must print "valid"

# A/B one engine switch in the installed app, no rebuild (§8 item 12, steps 4 to 6)
python3 scripts/android_gfx_ab.py gfx-noload --off --shot noload_off.png --log noload_off.txt
python3 scripts/android_gfx_ab.py gfx-noload --clear
```

## 6. What is done

**Sprint 1–2 — import and provenance.** 108 files vendored with upstream paths, per-file sha256,
license and modification record; a gate that fails on a changed byte, an unlisted file, a stale row,
a wrong pin or a lost execute bit. `dm/android/docker` keeps upstream's Dockerfile; the working
image is `localhost/dm-android-tools:1`.

**Sprint 3 — the device answered.** `vk_probe.c` written, its output contract frozen in tests,
validated on desktop (llvmpipe and an RTX 5060 Ti) and on the S23 Ultra with 0 breaches and
byte-identical repeated runs. A real defect the device exposed was fixed: Qualcomm's `driverInfo`
contains newlines, so the probe now folds whitespace runs and the dump stays one fact per line.

**Sprint 4 — the vocabularies agree.** `dm/gfx/nvn/nvn_obj.h` is now usable from C++ (eight explicit
casts, `extern "C"` guards, a `DM_STATIC_ASSERT` that is `_Static_assert` in C and `static_assert` in
C++), the fork's own commands are named `OP_XBG_*` after our `OP_COUNT_`, and the engine compiles
against our header with no `-fpermissive`. `opcode_map.py` and `abi_gaps.py` generate the two
inventories from the tree and `--check` them.

**Sprint 5 — vocabulary, replay and ABI completed.** The 12 missing NVN opcode handlers in
`xbg_game.cpp` are implemented and QA-verified, the 27 missing `mtl_*` entry points in `nvn_vk.c` are
defined, and the signature mismatch for `mtl_link_wait_tick` is resolved.

Current counts (`opcode_map.py --check`): **51 ops, 51 handled, 0 missing, 1 payload-mismatched**
(`P8`, barrier cache bits, benign; `P6`, the multi-viewport record, is handled in the draw and
still unreachable end to end: see §7), 11 fork-only. `abi_gaps.py --check`: **0 `mtl_*` entry points missing, 0 signature mismatches, 28 extra** (the adapter's own helpers and the statistics it answers for `hle_nvn.c`; 29 until `mtl_event_read` was declared in `nvn_mtl.h` and given its callers, round I: `docs/reference/android.md`, *A guest polling an event read a stale value on the Vulkan replay*).
`android_audit.py --summary`: **760 hits in 38 files** — 426 `objc-framework`, 319 `apple-api`,
12 `page-assumption`, 3 `macho-section` (gate `--check` is green; the baseline is regenerated by the tool:
759 after the host bring-up's second step, §8 item 4, and 760 after the `thread-register` pattern of
item 4a, whose one new row is Apple's `tsd_check` read of `tpidrro_el0` in `loader.c`, a line older than
the pattern).

## 7. What is completed, and what was verified

The sprint on the replay and the Vulkan ABI gap is complete:

- **12 Opcode Handlers implemented:** `OP_CLEAR_BUF`, `OP_DEPTH_CLAMP`, `OP_RENDER_COND`,
  `OP_FENCE_SYNC`, `OP_TF_BIND`, `OP_TF_STATE`, `OP_RAST_DISCARD`, `OP_VP_SWIZZLE`,
  `OP_BIND_TEX1`, `OP_PRIM_RESTART`, `OP_BIND_UBO_SMALL`, `OP_BIND_VBUF1`.
- **Pipeline and guard wiring:** `ia.primitiveRestartEnable`, `rs.depthClampEnable`, and
  `rs.rasterizerDiscardEnable` wired into pipeline create info; `state.render_cond_skip` guards draws
  and clears, reset on submission boundary (`depth == 0`); 4-byte alignment checked on `OP_CLEAR_BUF`.
- **ABI Gaps Closed:** all 27 missing `mtl_*` entry points defined in `dm/gfx/vulkan/nvn_vk.c`,
  and `mtl_sub_fill` routes directly to `OP_CLEAR_BUF`.
- **4 KiB page fix in host probe:** comment regex trigger resolved; the audit baseline is 760 hits in
  38 files (§6), down from 832 before the host bring-up.
- **`P6` (n > 1 viewports) handled in the draw, not reachable end to end yet:** `OP_VIEWPORTS`
  keeps the 16-entry array and its length; a draw declares and sets `viewport_n` viewports (dynamic
  state, the one recorded scissor and depth range for each, per-viewport swizzle applied, an unset
  index empty) when its last pre-raster shader writes `ViewportIndex` (`XbgRasterFacts`), one
  otherwise; the count is in `PipeMemoKey.viewports`; `validate_capabilities` accepts
  `MultiViewport` under `multiViewport` and 70 / 5254 / `SPV_EXT_shader_viewport_index_layer`
  under the enabled `shaderOutputViewportIndex` (`xbg_game_set_viewport_features`), and refuses
  the viewport mask (5255) with a `[RED]` line. **Done since, not measured on the device:** the
  front end (`vulkan_present.cpp`) enables `shaderOutputViewportIndex` and calls the setter. **Still
  open:** `NVN_DEVICE_INFO_MAX_VIEWPORTS` is limited nowhere the game reads (`hle_nvn.c` `g_devinfo`
  says 16; the engine's `xbg_device_integer` has no caller); `SetScissors` / `SetDepthRanges` with
  `n > 1` are collapsed to index 0 by the writer, now with a `[RED]` line each (split-screen draws
  both views through one scissor); the multiview fan-out for a viewport mask is designed (gate, SPIR-V
  rewrite, layered pass and composite, each named with what to measure first), not written. All in
  `docs/reference/android.md`, *The replay refused a record of more than one viewport*.
- **Engine items that need no device, closed by reading against `nvn_mtl.m` (round F):** NVN's
  window origin is in the engine (`xbg_game_set_window_origin`: the device origin flips every
  viewport and the present blit, the queue's captured origin decides the front face and is in
  `PipeMemoKey.origin`); primitive restart is declared only for strips and fans (Vulkan's rule for
  lists) and a restart index other than all-ones is mapped onto all-ones in a copy of the indices (the
  widened 8-bit stream included; that the GPU compares at the stream's width is unverified);
  `OP_RENDER_COND` never waits for the GPU: a counter field under a pending timestamp report
  (`TIMESTAMP` / `TIMESTAMP_TOP`) at that exact address is known 0, as `rc_value` counts it, any other
  pending report or writeback keeps the draws (not followed: `rc_occ`); `ReportCounter(TIMESTAMP_TOP)`
  (Tears of the Kingdom's conditional clears) is a top-of-pipe timestamp and a pipeline statistic is
  counter 0 with one `[RED]`, no longer a fatal; the `OP_BIND_VATTR` note
  was wrong (NVN's call has no `first`). `pipeline_memo_source_test.py` now also checks that no `//`
  or `/* */` comment on a code line swallows the code after it (a `frontFace` edit
  once hid `rs.lineWidth` and the depth-bias assignments; QA caught it). The test is a text check,
  not a compile or a run. On scratch copies it catches 40 mutations: 6 comment-swallow shapes; the
  pending-report rule, the restart masks, the counter-type fatal and the TIMESTAMP_TOP stage (7);
  and, since QA round H left
  11 of its 17 mutations uncaught, 20 more: the timestamp counter field written as non-zero, a
  timestamp reset taken as a samples reset, samples reports on the in-pass path, a dropped
  `timestamp_query`, a dropped draw or clear guard, a dropped or inverted submission reset, inverted
  render-enable modes, and a counter-type fatal in other wording; plus 7 structural mutations (the viewport
  lower-left flip and multiViewport gate removed/commented/weakened, the draw reading the origin atomic).
  QA's exact round-H mutations were not rerun here, only those categories. **Open:** the
  GL depth mode (near = -w) has no Vulkan entry point, a game that keeps it gets one `[RED]` at its
  first submission and near = 0 depth. All in `docs/reference/android.md`, *The Vulkan replay ignored
  the window origin, the depth mode and the restart index*.

The `dm/tools/android_vendor.tsv` rows for `xbg_game.cpp` and `nvn_vk.c` are updated and clean.

## 8. What to do next, in order

1. **[DONE] The 12 missing handlers** — all 12 implemented and verified by QA in `xbg_game.cpp`.
2. **[DRAW DONE, path open] `P6` n > 1** — the viewport array is dynamic state and the pipeline is
   built for the count (§7). The front end creates the device with
   `VkPhysicalDeviceVulkan12Features.shaderOutputViewportIndex` + `shaderOutputLayer` (instance
   and device at 1.2+) or `VK_EXT_shader_viewport_index_layer`, and `VK_KHR_multiview` /
   `multiview`, and calls `xbg_game_set_viewport_features` after initialize (through
   `dm_vk_config`, as the mirror clamp is): done, not measured on the device. Open: the host's `g_devinfo` should answer
   `NVN_DEVICE_INFO_MAX_VIEWPORTS` from the device (`multiViewport ? min(16, maxViewports) : 1`);
   `hle_nvn.c` records `SetScissors` / `SetDepthRanges` index 0 only (a `[RED]` line each when
   `first + n > 1`), so a split-screen draw selecting viewport 1 is cut by viewport 0's scissor and
   takes its depth range until the records carry the arrays. (Those two lines also print on the Apple
   build and `scripts/regress.py` would count the new `[RED]` kind as a regression; moot now that Mac
   validation is no longer required, §2 *Platforms*.) The
   `VK_KHR_multiview` fan-out for a
   viewport mask is designed, not written. The probe prints `multiViewport`, `multiview`,
   `shaderOutputViewportIndex`, `shaderOutputLayer` and `maxViewports` now, unmeasured on the
   S23 Ultra until it is run again. `P8` (barrier cache bits) is benign: the reader's single full
   barrier is stronger, so it is recorded and left.
3. **[DONE] The 27 missing `mtl_*` entry points.** Implemented in `dm/gfx/vulkan/nvn_vk.c`.
4. **[DONE, with the audit as the checklist] Host bring-up**: `dm/host` on bionic. Built for arm64 with
   NDK r29 and run on the device (§8 item 9). **First step**: the four
   isolated APIs (`clonefile`, QoS, Mach absolute time, CommonCrypto) are behind `dm/host/port.h`
   (Apple inline) and `dm/android/port_android.c` (bionic, over `dm/android/compat/`); see
   `docs/reference/android.md` § *The host's platform primitives live in `dm/host/port.h`*.
   The audit's `commoncrypto` and `qos-class` patterns were widened (the streaming `CC_SHA256_*`
   names, `CC_LONG`, `pthread_override_*`) and the baseline regenerated by the tool: 845 under the
   widened patterns before, 816 now, the 22 new rows all in `port.h` (§6); `port_android.c` is in
   `ANDROID_SRCS` of `dm/android/CMakeLists.txt` (item 5).
   **Second step, the rest of the Apple API list (code only, nothing compiled for arm64 yet):**
   every Apple-only call the kept C sources made is behind `port.h` now, the Apple inline path
   unchanged and no Apple code deleted — including the two inline-assembly cases QA found that the
   first pass and `undef_scan.py` had missed: `hle_bigstack.c`'s trampoline (`_dm_bigstack_enter`,
   `.private_extern`, `bl _dm_bigstack_top`: now the `DM_ASM_*` spellings, so `dm_bigstack_enter`
   exists on ELF) and `nvn_capture.c`'s LZFSE (`<compression.h>` and its `.linker_option`, now
   `dm_compress` / `dm_decompress`: on bionic chunks stay raw and an LZFSE capture cannot be read,
   said once with `[RED]`; nothing in the tree decodes LZFSE). `DM_ASM_HI` is the bare symbol on
   ELF (LLVM's assembler takes no `:pg_hi21:`, as `asm_elf.py` already knew). `undef_scan.py` now
   reads `ANDROID_SRCS` and the `.S` list (`ASM_IN`) from `dm/android/CMakeLists.txt` instead of copying
   them and flags Mach-O assembly spellings in any kept source or include, `port.h` excepted:
   `.private_extern`, `.linker_option`, `.weak_definition`, `.subsections_via_symbols`, `@PAGE` /
   `@PAGEOFF` and the `@GOTPAGE*` / `@TLVPPAGE*` forms, a `segment,section` name (`.section __TEXT,…`,
   `section("__DATA,…")`), and an `_`-prefixed symbol as the operand of `b` / `bl` / `b.cond` / `cbz` /
   `cbnz` / `tbz` / `tbnz` / `adrp` / `adr` / `.globl` / `.quad` / `.long` / `.word`, also after a C
   string's `\n` / `\t` escape and stringified (`"bl _" #n`); the earlier pattern missed 21 of the 25
   forms in `dm/tools/tests/test_android_undef_scan.py` (its `adrp|adr` alternative never matched: the
   register comes first), which also holds 14 ELF / `DM_ASM_*` lines that must not match. The ELF
   expansions of `hle_bigstack.c`'s trampoline and `HLE_FORCE_BIG`'s stubs now carry `.type …, %function`
   and `.size` (`DM_ASM_FUNC` / `DM_ASM_END`, empty on Mach-O: the Apple assembly text was compared
   with HEAD's and is identical). On bionic `dm_on_sigterm` is a `sigaction` handler writing a
   self-pipe that a waiting thread reads (blocking the signal in one thread was not reliable; the
   write end is non-blocking, a second call only replaces the callback, and a reader that stops gives
   SIGTERM its default action back instead of spinning on `read() == 0`),
   `dm_errno_noattr` takes ENOTSUP / EOPNOTSUPP as "no attribute" (storage without xattrs) and
   `dm_xattr_set` says once with `[RED]` when such storage cannot keep a case-collision name (the
   create, mkdir or rename is then undone, so the host never makes a `.dm-case-N` there; one copied in
   without its attribute is listed under its physical name: `hle_fs.c` `guest_name`). On bionic the NVN
   capture no longer allocates the `n + n/16 + 4 KiB` compression buffer (`DM_HAVE_COMPRESS` is 0). Real implementations on bionic (`port_android.c`): the
   table sections (`DM_SECTION`, `dm_section` over the linker's `__start_` / `__stop_` symbols;
   `DM_ASM_*` spell `HLE_FORCE_BIG`'s inline assembly for ELF), the signal context (`dm_uc_ss`
   overlays Apple's `arm_thread_state64_t` on `uc_mcontext.regs`, `dm_uc_ns` copies the fpsimd
   record), `dm_vm_region` (`/proc/self/maps`), `dm_cond_timedwait_ns`, `dm_thread_name`,
   `dm_xattr_*` (the guest-name attribute in the `user.` namespace: `hle_fs.c` compiles there now),
   `dm_fd_path`, `dm_heap_*` (`hle_uemalloc.c` on bionic's malloc), `dm_sem_*` / `dm_after_ns` /
   `dm_on_sigterm` (GCD's semaphore, `dispatch_after` and signal source), `dm_cpu_perf_levels`,
   `dm_proc_start_ns`, `dm_thread_sched`, `dm_ticks_ns`; `hle_nvn.c`'s `CFDictionary` is an
   `nvn_hmap`. Platform limits, said once with `[RED]` or a plain line:
   `dm_thread_rt_set` (no SCHED_FIFO for an app), `dm_task_power` (energy, p-core
   time, wakeups and GPU time are Apple task_info facts; `power_line` prints nothing there).
   `dm_vm_alias` was one of these and is no longer: `dm_guest_as_reserve` backs the guest address
   space with a `memfd` and `MAP_SHARED`, and `dm_vm_alias` maps an alias at the same file offset, so
   virtual pools and the write watch work (item 11, *[RESOLVED] First-run blocker unblocked*).
   The Apple media interfaces in `dm/android/apple_stubs.c` (headers under
   `dm/android/apple_stubs/include`) are split: the `AudioUnit` output is real (AAudio, 48 kHz stereo)
   and the H.264 decoder is real (`AMediaCodec`, NV12 into a `CVPixelBufferRef`), while AAC through
   `AudioConverter` is still a stub that says so once with `[RED]`, so an AAC track is silent.
   Measured here: `gcc -fsyntax-only` of
   the Apple branch of `port.h` (shim headers for every Apple type it names), of `port_android.c`
   and of `apple_stubs.c`; the four QoS probes still green; audit 816 → 759 in this step (760 after the
   `thread-register` row, §6; the 43 new rows are
   `port.h`'s inline Apple branch and comments naming the APIs). **Compiled since:** the NDK build of the
   host files and the device run (§8 item 9) cover the call-site
   edits in `crash.c`, `probe.c`, `hle_thread.c`, `hle_nvn.c`, `hle_audio.c`, `hle_fs.c`,
   `hle_uemalloc.c`, `loader.c`, `main.c`, `hle_lifecycle.c`, `hle_movie.c`, `hle_fdstat.c`, the
   `DM_SECTION` ELF sections and the bare-symbol / `:lo12:` spellings of `HLE_FORCE_BIG` and
   `hle_bigstack.c`. **Unverified:** that the
   weak `__start_*` references resolve when no entry exists; `dm_uc_ns`'s fpsimd
   record walk and `dm_proc_start_ns` are untested on a device. **CMake:**
   `dm/android/apple_stubs.c` is in `ANDROID_SRCS` and `dm/android/apple_stubs/include` is on `dmcore`'s
   include path (done after QA round F). `pthread_gettid_np` (used by `port_android.c` and compat's
   `mach.h`) does not exist on OHOS/musl. "`undef_scan` clean" means no dropped repository
   definition is still called, not a clean link.
4a. **[CODE DONE, unverified on a device] The guest thread slots on bionic** (`docs/reference/android.md`,
   *The guest thread slots assumed Darwin's TSD layout*). Confirmed by reading: every rewritten x18,
   `mrs`/`msr tpidr_el0`, `mrs tpidrro_el0`, `br`/`blr x18`, jump-table, spin-window and gate stub reached
   its slot as `mrs tpidrro_el0` + key page `key × 8` (13 sites in `patch_nso.py`), and the host wrote the
   slots with `pthread_setspecific` (`thread.c`, `loader.c`) and read x18 with `pthread_getspecific`
   (`hle_thread.c`'s SVC entry and pause signal); on Android `tsd_check` would have faulted at the first
   module. Done: `patch_nso.py --target=apple|android` (default apple; patched image, gates and
   fixups are byte-identical, `build_src.sha256` reflects the rewriter's own hash: the diff
   against HEAD with the helper spelled back shows only the switch, comments, one assert that cannot fire
   on Apple and two Android-only lines), `emit_thread_base` (android: `mrs xN, tpidr_el0; ldr xN, [xN, #16]`,
   bionic's `TLS_SLOT_APP`, API 29), `# KSLOT_TP_OFF 0x10` in an Android `fixups.tsv` and a target line in
   its `build_src.sha256`; `port.h` `dm_kslot_new/get/set` (Apple: the same pthread calls inline; bionic:
   `port_android.c`, a tagged five-word ELF-TLS table put in word 2 on a thread's first set, refusing a word
   another component wrote) and `dm_kslot_guest_read`; `loader.c` refuses a module of the other target and
   `tsd_check` is per platform (Apple body unchanged); `thread.c`, `hle_thread.c` go through `dm_kslot_*`;
   `dm/android/CMakeLists.txt` requires `ANDROID_PLATFORM >= 29`; `android_audit.py` pattern
   `thread-register`. Round I: `dm_kslot_new` refuses a device below API 29 (`android_get_device_api_level()`,
   `[RED]`); `crash.c` names a slot read on a thread without a table (fault address 8..0x27) with a `[RED]`
   line; its `__es.__esr` (a bionic compile error, from HEAD) is `port.h` `dm_uc_fault_write`. Verified here:
   `dm/tools/tests/test_thread_slots.py` (17 tests: the 13 sites that reach a slot run on an AArch64
   interpreter for both targets, with hand-made instructions since capstone's decoding and the x18
   substitution are given, not computed; a structural check that every `emit_slot_addr(reg, …)` follows
   `emit_thread_base(reg)` and that the Android `KSLOT_TP_OFF` line matches `port.h` / `loader.c`). Every
   mutation QA listed fails it: the raw Darwin word in six sites, the wrong register in `site_window`, the
   `KSLOT_TP_OFF` line dropped / changed / renamed, the table load removed, `tpidrro_el0` on Android, word 3.
   The Apple word sequence is pinned; `gcc -fsyntax-only -Wall` of `port_android.c`, `loader.c`, `thread.c`,
   `hle_thread.c`, `crash.c`, `hle_nvn.c` over MinGW with Linux shim headers (scratch, not in the tree). **Verified since:** an NDK
   build and a device run of the slot mechanism (§8 item 9: `test_device_bionic` on the S23 Ultra confirms
   `tpidr_el0 + 0x10` is zero on the main thread and on spawned pthreads). **Unverified:** that a new thread's word 2 is 0 (bionic zeroes the control block with the static
   TLS, from memory); that no library in the app process writes word 2 (the GL / Vulkan loaders, the
   sanitizers and ART use other words per bionic's `tls_defines.h`, quoted from memory: no bionic source in
   the tree); the inline assembly of `dm_kslot_guest_read`; and the packing step, which is settled:
   `scripts/prepare_game_android.py` runs the rewriter with `--target=android` for every module on every
   run and caches no output, so an Apple rewrite cannot be reused there. `scripts/build_ipa_from_nsp.py`'s
   `rewrite()` still reuses its output by a fingerprint of the rewriter's files, the patch files, the modules
   and capstone's version, with no target in it, and calls `patch_nso.py` without `--target`; that is the
   Apple path, and any Android path built on it later must add the target to that fingerprint (or keep its
   own output directory).
   Open (Go and other third parties): Go's runtime with cgo keeps `g` in `TLS_SLOT_APP` on android/arm64
   from API 29 (golang/go#29674, as QA reported): a Go library in the app process cannot share it.
4b. **[CODE DONE] Event reads on the Vulkan replay** (round I): `hle_nvn.c` now calls `mtl_event_read`
   (declared in `nvn_mtl.h`, weak no-op beside the callers for the Metal replay, `nvn_vk.c`'s strong
   definition on Android) before `nvnEventInitialize` / `Finalize` / `GetValue` and `ev_signal`'s
   read-modify-write; `event_order_test.py` passes (it failed at HEAD), `abi_gaps` extra 29 → 28.
5. **[DONE] Wire it into a build**: `dm/android/CMakeLists.txt` takes `-DGAME=<id>`
   like `make -C dm/host` (stops and lists the profiles without it; `DM_GAMES_DIR` honoured),
   generates `game_profile.h` with `dm/games/game.py header`, reads the source list from
   `dm/host/Makefile` through `dm/android/tools/host_sources.py` (ours), builds libvpx, and compiles
   `front_android.c` (our `front.h`; touch goes through `jni_android.c`), `vulkan_present.cpp`, `port_android.c`, the
   compat shims and `nvn_vk.c`; the D2R headers, overlay contract and touch sources are gone,
   SPIRV-Tools is optional and `libdm.so` is built with `jni_android.c` (item 8). The configure requires arm64
   and `ANDROID_PLATFORM >= 29` (28 before the guest thread slots, item 4a), sets one build type and gives C and C++ the Makefile's `-O1 -g`,
   keeps `DM_GAMES_DIR` in the cache (the first configure's environment, or `-DDM_GAMES_DIR=`) and
   gives that one value, or none, to every `game.py` call at configure and build, and runs
   `dm/android/tools/undef_scan.py` (ours): the names the kept sources use and only a dropped `.m`
   (or a `.inc` only a `.m` includes) defines, which would fail the `--no-undefined` link; the 21
   found (the Metal replay's statistics in `hle_nvn.c`'s `[nvn]` lines, `DM_CTL` texture / pass
   dumps, `DM_PSO_PREBUILD=tool`) plus `nvn_cap_submit` / `nvn_cap_present` (the `DM_NVN_CAPTURE`
   hooks of `nvn_capture.inc`) are answered in `nvn_vk.c` with the Vulkan engine's own counts or a
   one-time `[RED]` "not collected / not implemented on this platform", and `mtl_display_hz` reads
   `front_screen_max_fps`. Measured: the desktop configure
   (MinGW gcc) in the three `GAME` cases and the `game_profile` target; `gcc -fsyntax-only` of
   `front_android.c`, `nvn_vk.c` and `vulkan_present.cpp`; `undef_scan.py` clean. **Done since:** the NDK
   configure and build, the app shell (`jni_android.c`, Java activity, touch, Gradle) and the bionic
   compile of the host files all landed and ran on the device (§8 items 8, 9). **Open:** a graphics
   layer for the Vulkan / OpenGL games:
   `dm/gfx/vk/hle_vk.m` and `dm/gfx/gl/hle_gl.m` are Metal and dropped, so a profile whose game
   renders through them has no graphics HLE on Android yet (the games table names them).
6. **Probe v2, the last chance for zero-copy**: `vkGetPhysicalDeviceExternalBufferProperties` for
   opaque-fd and AHB, plus a real 64 MiB `AHardwareBuffer` import and a shader write through it. If
   that works, pools can be allocated in AHB memory from the start and the mirror's copy tax
   disappears; if it does not, the mirror stands and `nvn_dirty.c`'s page tracking is the
   performance-critical path (4 KiB pages match the device exactly).
7. **`address_space.md` §8's experiment** if the 128 MiB cap turns out to matter: it needs a SPIR-V
   shader the tree cannot currently produce (`dmsh_xlate_bin` is Mach-O and `dotnet` is not
   installed here), so first get one translated shader from a Mac build. Note: with the Android-only
   decision (§2 *Platforms*) a Mac will not be a routine tool; either keep a Mac for this one step or
   build the translator for Linux.
8. **The app shell**:
   - Target 1 **[DONE]**: `dm/android/jni_android.c` implemented and `libdm.so`
     verified compiling and linking cleanly with NDK r29 (arm64-v8a, API 29, `-Wl,--no-undefined -Wl,-Bsymbolic`).
     Features `JNI_OnLoad`, `RegisterNatives` (`com/nxdroid/NativeBridge`, `com/nxdroid/MainActivity`),
     stdout/stderr pipe redirection to logcat tag `"dm"` (`__android_log_print`), host thread lifecycle (`nativeStartHost`,
     `nativeStopHost`, `nativeIsRunning`), surface management (`nativeSetSurface`, `nativeSurfaceDestroyed`,
     `nativeSetRefreshRate`), and input bridge (`nativeSendTouch`, `nativeSendPad`, `nativeSendPadPlayers`,
     `nativeSendInput`).
   - Target 2 **[DONE]**: Complete Android application shell created in `dm/android/app/` and verified:
     * Gradle build system: `dm/android/settings.gradle`, `dm/android/build.gradle`, and `dm/android/app/build.gradle` (compileSdk 36, minSdk 29, targetSdk 36, arm64-v8a ABI filter, CMake integration with `-DGAME=`, NDK 29.0.14206865).
     * Manifest: `dm/android/app/src/main/AndroidManifest.xml` (package `com.nxdroid`, `MainActivity` sensorLandscape, fullscreen, hardware-accelerated, Vulkan 1.1+ feature requirement `android.hardware.vulkan.version` 0x401000, `WAKE_LOCK`).
     * JNI Bridge: `dm/android/app/src/main/java/com/nxdroid/NativeBridge.java` (loads `libdm.so`, declares native bridge methods).
     * Render View: `dm/android/app/src/main/java/com/nxdroid/GameSurfaceView.java` (`SurfaceHolder.Callback2`, touch event dispatch mapped to normalized coordinates `[0.0, 1.0)` with up to 16 active pointer slots).
     * Main Activity: `dm/android/app/src/main/java/com/nxdroid/MainActivity.java` (display refresh rate query and dispatch, physical controller key and axis mapping to `nativeSendPad`, host startup from intent extras with default directories, lifecycle handling).
     * End-to-end packaging verified: `aapt2 link`, `javac -source 17 -target 17`, `d8`, APK packaging with `classes.dex` and `lib/arm64-v8a/libdm.so`, and `zipalign -p 4` alignment verified cleanly.
     * Automated test suite: `dm/tools/tests/test_android_jni.py` passes all lexical, string release pairing, and signature tests.
   - Target 3 **[DONE - launcher and virtual gamepad run on the S23 Ultra; polish open] Console Home Interface & Custom SAF Game Directory (Argon Specification)**:
     * Implement `LauncherOverlayView` on top of `GameSurfaceView` in a root `FrameLayout` (Z-index 0: `GameSurfaceView`, Z-index 1: `LauncherOverlayView`).
     * Replace hardcoded `/sdcard/Android/data/...` path with user-customizable directory selection via Android Storage Access Framework (`ACTION_OPEN_DOCUMENT_TREE`, `takePersistableUriPermission`, `SharedPreferences`).
     * Dual-Pane layout for 19.5:9 landscape (Hero Card with launch CTA, shader prewarm and metadata on left; 2x2 discovered titles grid on right).
     * Top diagnostic and status chip (S23 Ultra, Adreno 740, Vulkan 1.3, battery, thermals, gamepad status) and footer gamepad shortcuts.
     * Smooth 250ms fade transition from launcher overlay to `GameSurfaceView` when "LAUNCH GAME" is pressed. Specification reference: `dm/android/mockups/design_spec_argon.md`.
9. **[VERIFIED ON S23 ULTRA] Validation that needs an NDK and the device**:
   - NDK configure and build: `dmhost` and `libdm.so` link cleanly with 0 undefined symbols.
   - S23 Ultra device measurements:
     * `vk_probe` run live: confirms Adreno 740, driver 512.676.1, `maxStorageBufferRange = 128 MiB`, `external_memory_host = absent`, `VK_ANDROID_external_memory_android_hardware_buffer = present`.
     * `TLS_SLOT_APP` verification: tested live with `test_device_bionic`; confirmed `tpidr_el0 + 0x10` is `0x0` (completely free and zeroed) on main thread and spawned pthreads; `RLIMIT_NICE = 40`.
     * `memfd_create` and `dm_vm_alias` verification: tested live with `test_vm_alias`; 100% PASS on physical kernel (aliasing, shared page write coherence, independent `mprotect` VMA permissions).
     * `dmhost` run live on device: executed in `/data/local/tmp/`; initialized NVN symbol tables and null device cleanly.
     * `com.nxdroid` app installed and run live: loaded `libdm.so`, registered JNI, started `MainActivity` and `GameSurfaceView`, verified logcat redirection, and created game directory `/sdcard/Android/data/com.nxdroid/files/game/` (that first build's path; the app now defaults to `/storage/emulated/0/nxdroid/game`, `MainActivity`).
10. **LAST: remove the Apple code** (owner's order: only after everything above). Scope: `*.m`, `*.S`
    that only Mach-O uses, `front_*.m`, `dm/gfx/nvn/nvn_mtl.m` (but see below), the iOS tree and IPA
    packing (`scripts/build_ipa_from_nsp.py`, `dm/ios`), `scripts/regress.py` and its baselines, the
    Apple branch of `port.h` and the Apple-only parts of `dm/tools` (rewriter default target becomes
    Android), `docs/development.md`, `docs/frontends.md`, `docs/playing.md` (keep the
    `README.md#how-to-play` anchor or fix the link), `dm/games/README.md` and the per-game notes'
    Mac / iPhone wording, the gallery (`docs/images/gallery.tsv`, `dm/tools/docs_gallery.py`: drop the IPA
    sizes or re-measure on Android), the README's XcodeGen acknowledgement, and `AGENTS.md` (rewrite its
    rules for Android-only, drop the `seedds` commit rule and the `regress.py` rule; the owner approves
    the text before it is saved). Before deleting `nvn_mtl.m`, retire or re-base the gates that read it
    (`opcode_map.py`, `abi_gaps.py`, the `nvn_mtl.m` line citations in `android.md` and in the tests),
    and check `dm/tools/tests/test_docs.py` (links, anchors, notes and table rows) afterwards. The
    `android_audit` baseline is the checklist: it should shrink to 0 as this lands. The git history
    (`8e050e9`) keeps everything removed. **Docs part done early (2026-11-03, owner's request):** Mac /
    iPhone / IPA instructions are out of `docs/` (development, packing, playing, frontends, settings, the
    agent guides), rewritten for Android where the tree supports it; `docs/reference` keeps its mechanism
    explanations and `nvn_mtl.m` citations, with only instruction and "ships for Mac" phrases changed.
    Left for this item: `docs/agents/game-patches.md` (generated from the profiles' `patches.py`
    `GENERALIZE` strings, which name the iPhone), `CONTRIBUTING.md`, `README.md` ~225, comments in the
    Apple sources and `build_ipa_from_nsp.py` that cite removed sections, and the 149 `env_switches.tsv`
    rows read only by Apple code. `test_env_switches` was already red before: the table lacks the
    `DM_GFX_*` switches `jni_android.c` sets and some `DM_ANDROID_*` / `DM_BC_*` rows.
11. **Independent audit follow-ups** (audit of `f7e190d` / `6dc397b`; every item below is closed; the
    "Addressed follow-ups" list at its end is the record, and the older sub-bullets keep the reasoning that
    was written before each fix landed):
    - `docs/reference/android.md` stale lines: "not wired into any build" (line ~3), "Three rows carry a
      pending adaptation" (~47; the manifest has 11 adapted rows), "Fix: none here" for the 27 `mtl_*`
      entry points (~92), and the line that calls the ~60 Apple APIs expected compile errors (~120;
      item 4 says they are behind `port.h`, with no NDK compile yet). Sweep the file, README and §4 / §8
      for other claims later rounds made false.
    - `pipeline_memo_source_test.py` does not catch removing the lower-left viewport flip
      (`origin_ll` in `xbg_game.cpp` `draw()`) nor the `need(vpn==1 || (multiViewport && vpn <=
      maxViewports))` gate: add structural assertions, prove them on scratch copies, update the
      test's vendor row (LF sha256, by hand). **[DONE]** both assertions added (plus: the draw reads
      no origin atomic, the companion ViewportIndex gate); 7 scratch mutations (flip removed /
      commented / `if(false)`, gate removed / commented / `vpn<=16`, draw reading the atomic) all fail
      it, the current file passes; row updated. §7 says 40.
    - `xbg_game.cpp` ~4116: `VkPhysicalDeviceVulkan12Features` is chained by the loader's
      `vkEnumerateInstanceVersion`, not the created instance's `apiVersion`: a 1.1 instance on a 1.2
      loader (the desktop smoke harness) gets a 1.2 struct. Use the instance's version. **[DONE (compiled later, follow-up 1
      )]** `xbg_game_config.instance_api_version` (new last field; `vulkan_present.cpp` and
      `smoke.c` fill it), used here and in the mirror-clamp setter's 1.2 query. Line ~4170 (follow-up 5)
      (`format_feature_flags2`) had the same flaw and was fixed too. The
      compile check was done afterwards (follow-up 1).
    - Window origin (`origin_ll` / `queue_origin_ll`) is read at draw time on the worker thread;
      `nvn_mtl.m` captures the queue origin at queue creation. Trace whether a host-side change can
      reach draws of an already recorded submission; if so capture it per submission. **[DONE (compiled later, follow-up 1
      )]** Traced: no worker thread translates (`gfx_async` is hard-wired false, `xbg_submit`
      translates on the submitting thread under `g_sub_mu`), so a finished submission is out of reach;
      but `nvn_vk.c`'s device-origin setter re-sent a possibly stale queue origin (lost update against
      a concurrent submit), real. Fixed: separate engine setters (`xbg_game_set_window_origin` /
      `xbg_game_set_queue_origin`), origins captured per submission in `xbg_submit` (`sub_origin`,
      also into the `gfx_async` job), `PipeMemoKey.origin` from it. The `android.md` round-F entry
      now names both setters (follow-up 4).
    - Wording: the rewriter's Apple output is not byte-identical in `build_src.sha256` (it holds the
      rewriter's own hash, so `build_ipa_from_nsp.py` re-runs it once); the patched image, gates and
      fixups are unchanged. State that exactly in item 4a and `android.md`.
    - **[RESOLVED] First-run blocker unblocked:** `dm_guest_as_reserve` backs the guest address space
      with a memfd and `MAP_SHARED`; `dm_vm_alias` maps aliases at the same file offset with
      `MAP_SHARED | (to ? MAP_FIXED : 0)`. NVN virtual pools and write-watch aliasing are unblocked
      on Android and verified with `dm/tools/tests/test_android_vm_alias.py`.
    - Process: the two commits do not follow `AGENTS.md` (identity `seedds`, English messages, no
      `regress.py` report); moot once item 10 rewrites `AGENTS.md`.
    - **Addressed follow-ups:**
      1. **[DONE]** Compilation verified: `make -C dm/gfx/vk/engine_smoke clean && make -C dm/gfx/vk/engine_smoke CC=clang CXX=clang++`
         and GCC builds succeed cleanly with 0 errors. Harness executed on lavapipe and NVIDIA RTX 5060 Ti, exiting 0.
         `xbg_game_config` size confirmed at 328 bytes (from 320, gaining `instance_api_version`). `engine_smoke/README.md` updated.
      2. **[DONE]** Gates and tests re-run and passing: `undef_scan` clean (0 undefined symbols, 0 Mach-O assembly),
         `docs_symptoms --check` (549 symptoms), `test_thread_slots`, `test_android_undef_scan`, `test_android_audit` (760 hits match baseline),
         `test_lint_python` (10 passed), and pytest suite (101 passed).
      3. **[DONE]** §7 updated to reflect 40 mutations caught by the memo test (including the lower-left flip and multiViewport gates).
      4. **[DONE]** `docs/reference/android.md` round-F entry updated to describe the separate setters `xbg_game_set_window_origin`
         and `xbg_game_set_queue_origin` and per-submission capture into `sub_origin`.
      5. **[DONE]** `dm/gfx/vulkan/engine/xbg_game.cpp` `format_feature_flags2` (search for it; ~4483 at this cut) checks
         `cfg.instance_api_version >= VK_API_VERSION_1_3 && properties.apiVersion >= VK_API_VERSION_1_3`.
      6. **[DONE]** Documentation cleanup completed: `docs/reference/android.md` stale lines updated (wired in CMake, 11 adapted
         rows, 27 entry points implemented, Apple APIs shimmed, rewriter sha256 wording) and `HANDOFF.md` §8 items 4, 4a, 9 (`dm_vm_alias`
         first-run blocker resolved).
      7. **[DONE]** `dm_vm_alias` implemented and verified: `dm/host/port.h` declares `dm_guest_as_reserve` and `dm_guest_as_release`
         (Apple inline, bionic declared). `dm/android/port_android.c` implements `dm_memfd_create` (syscall 279 on arm64, 319 on x86_64
         for API 29+ compatibility), `dm_guest_as_reserve`, `dm_guest_as_release`, and `dm_vm_alias`. `dm/host/hle_svc.c` uses `dm_guest_as_reserve`.
         `dm/tools/tests/test_android_vm_alias.py` verifies reservation, dynamic and fixed aliasing, write coherence, independent page protection,
         bounds checks, and release/re-reserve on host and via NDK cross-compilation.
12. **The graphics work on the device (open, needs a build and a log).** Both changes are in the
    working tree and compile with the NDK (`-fsyntax-only`, `aarch64-linux-android29`): the graphics
    defaults in `dm/android/jni_android.c` (Status, *Framerate Telemetry*, item b) and the present encoding in
    `dm/android/vulkan_present.cpp` (Status, *3D Scene Color*, items a–e, and *Vertical Banding*). Neither has been measured. To measure:
    1. Build and install the APK (README, *How to build*), run a race, then collect
       `adb logcat -d -s dm > log.txt`.
    2. Read, in the log, the `nativeStartHost: DM_GFX_…` lines (the value in effect for each switch),
       the engine's own `NVN texture checks through the dirty tracker=`, `NVN vertex/index cross-frame
       cache=`, `NVN pipeline memo=`, `NVN native BC textures=` and `NVN defer events=` lines, then
       `NVN PERF` for `fps`, `submit_cpu_ms`, `gpu_ms`, `parts_ms_per_frame` (`fence`, `image`,
       `draw`, `snapshot`) and `NVN PERF texdirty tracked/checks/changed`. The `image` scope is the
       one the defaults were meant to remove.
    3. Read `Swapchain: … format= srgb= source_srgb=` once per rebuild: if `source_srgb=1` the
       present fix applies; if it is 0 the 3D colour fault is inside the 3D chain, and the engine's
       `NVN viewfmt image=… view=… nvn=0x38->0x25` and `NVN mutable upgrade …` lines are the next
       evidence (each prints once per distinct pair).
    3b. `vulkan_present.cpp` now takes only a surface format in `VK_COLOR_SPACE_SRGB_NONLINEAR_KHR` when the
       device lists one (before: the first-listed format, whatever its colour space; Samsung also lists 8-bit
       formats under `DISPLAY_P3_NONLINEAR_EXT`), and logs every `Swapchain surface format=<f> colorSpace=<c>`
       once per rebuild. Not compiled, not measured; a hardening, not a proven cause of the dark picture. Read
       those lines first: if the chosen format was not the first listed, this was live.
    4. A/B any single switch without a rebuild: the engine reads a marker file from the parent of the
       shader directory (`<game folder>/shaders` → `<game folder>`, and the game folder's parent when
       the game has no `shaders` subdirectory; `MainActivity` passes `<game folder>/shaders` as the
       shader directory). Write `gfx-tex-dirty`, `gfx-vcache`, `gfx-pipe-memo`, `gfx-native-bc`,
       `gfx-perf-sample`, `gfx-defer-events`, `gfx-wb-skip`, `gfx-shader-reuse`,
       `gfx-upload-prologue`, `gfx-xview-guard`, `gfx-ldc-fold`, `gfx-forward-temps`,
       `gfx-quad-derivatives` or `gfx-warp32` with `0` in it to turn that switch off. A marker wins
       over the environment, so this needs no rebuild at all. `gfx-noload` (proven full-overwrite first
       draws skip the attachment load) takes the same `0`.
    5. `scripts/android_gfx_ab.py` does step 4 over `adb`: it writes the marker (`--off` / `--on`), reads
       it back, force-stops and starts `com.nxdroid`, and after `--wait` seconds (45 by default; start the
       race by hand meanwhile) saves `--shot <png>` and `--log <txt>` (`logcat -d -s dm`); `--clear`,
       `--clear-all` and `--list` manage the markers. It assumes the game folder is
       `/storage/emulated/0/nxdroid/game`, `MainActivity`'s default and `prepare_game_android.py`'s
       `--device-dir` (`--game-dir` otherwise, for a folder picked in the launcher; a game without `shaders/`
       reads its markers from the folder's parent, step 4). Syntax-checked only: no `adb` or device on the
       machine it was written on.
    6. **The 3D picture on the S23 Ultra (2026-11-03, before 3b), and what to A/B first.** Two screenshots
       of Mario Kart Stadium (the owner's, not in the tree): the 2D HUD and text are right; the 3D scene is
       posterized, with a flat blue sky, hard white edges on buildings, large black holes, colour fringes
       on letters and dense yellow / black / white speckle on the road. That is wrong data in the 3D chain's
       intermediate targets, not a gamma or swapchain fault (those darken or wash out a smooth picture), so
       3b is unlikely to fix it. Read so far, no fault found: `xbg_spirv_temps.cpp` (`gfx-forward-temps`) and
       `xbg_spirv_ldc.cpp` (`gfx-ldc-fold`) keep the module's values; `gfx-quad-derivatives` and
       `gfx-warp32` already default off on Adreno 740-799 (`xbg_adreno_policy.h`, DEVICE_LOST there) and the
       profile ships no `gfx-*` marker; `gfx-bright` acts only when the host defines `dm_bright_k` above
       1.005. `gfx-noload`'s proof (`first_draw_covers`, `nvn_cover.h`) was read too: it requires `w = 1`
       and `z` in [0, 1] on every vertex, so depth clipping cannot remove covered pixels, plus a full
       viewport and scissor, no blend, full colour mask, no discard, single sample. No hole found; it stays
       first in the order only because a missed proof leaves undefined tile contents on Adreno, which looks
       like this speckle. Order, one marker at a time with `0`: `gfx-noload`; `gfx-tex-dirty` (a missed
       guest write leaves a stale texture; its write tracking on Android rests on the memfd
       `dm_vm_alias`, item 11); `gfx-wb-skip`, `gfx-upload-prologue`; `gfx-vcache`, `gfx-pipe-memo`,
       `gfx-native-bc`; `gfx-forward-temps`, `gfx-ldc-fold` last. Record which one changes the picture here.
    7. **`gfx-tex-dirty` read (2026-11-03), no fault found.** `get_image` (`xbg_game.cpp` ~1786) hashes a
       texture each submission until 4 unchanged checks, then (switch on, pool tracked) write-protects its
       pages and stamps before the 4th hash, and from then on hashes only when `nvn_dirty_since` says a page
       was written after the stamp (protect and stamp again before reading). `nvn_dirty.c` keeps the
       BUSY / PROT / NONE order, releases every range sharing a faulting page, and treats an untracked
       range as dirty. Host writes that cannot fault (syscalls) go through `dm_guest_write_prepare`
       (`MapMemory`, `UnmapMemory`, `MapPhysicalMemory`). The Android pieces under it hold too: the whole
       guest block is one `MAP_SHARED` memfd mapping that the host only `mprotect`s (no anonymous mapping is
       put over it), so `dm_vm_alias`'s file offset `from - base` is the right page; virtual pools are not
       registered with the tracker, so their textures are hashed every time (safe). Two open points, neither
       Android-only: (a) a write through a virtual-pool alias (`vpool_map`, `dm_vm_alias` over a physical
       pool's pages) does not fault on the physical pool's protected pages, so a texture of that physical
       pool would stay stale; it needs a game that writes texture data through a virtual pool (the log's
       `[nvn] virtual pool … mapped up to` lines say whether MK8DX has any); (b) a fault whose write bit
       is read wrong (`dm_uc_fault_write`, the ESR record on bionic) makes `on_fault` refuse it, which is a
       crash, not a stale texture. So `gfx-tex-dirty` stays second in the order on the evidence of the
       picture alone. Side finding, memory not picture: `UnmapPhysicalMemory` frees pages with
       `madvise(MADV_FREE)` (`hle_svc.c` ~589), which applies to private anonymous memory only; on the
       memfd `MAP_SHARED` block it fails (result ignored) and the pages stay resident, so the process never
       gives unmapped guest memory back on Android. `fallocate(FALLOC_FL_PUNCH_HOLE)` on the memfd (or
       `MADV_REMOVE`) is the bionic equivalent; not changed, unmeasured.

## 9. How to work in this tree

- `AGENTS.md` governs. The short version: English everywhere; `[RED] ` prefixes for lines that mean
  something is wrong; a game-specific rule only when no general rule works; fix causes, not symptoms;
  keep game-derived files out of the repository.
- Specialist subagents (`android_dev`, `android_qa`, `android_shaders`, `android_upstream`) coordinate
  implementation and quality control autonomously via the defined subagent system.
- Podman is rootless; docker's daemon is down. Build the probe with the command in §5. The local
  image `localhost/dm-android-tools:1` is derived from `dm/android/docker/Dockerfile` by
  `/tmp/opencode/Dockerfile.tools`, which only adds `make`, `git` and `file`.
- `adb` comes from `/tmp/opencode/platform-tools/adb`, not from the image. If the phone refuses the
  authorization, revoke USB debugging authorizations and re-accept on the device.
- `xbg_game_initialize` needs neither guest memory nor a shader bundle, so the smoke harness can
  initialize and shut down the engine on any desktop Vulkan driver. The fatal path for a missing
  shader is an `xbg_fatalf` in `xbg_game.cpp` (search for it; its line has moved since the first rounds).

## 10. Traps, so they are found once

- **`android_vendor.py --write` recomputes the sha256 of existing rows.** Needed for the adapted
  files, but it means "edit a vendored file, run `--write`" hides the edit. The right shape is two
  hashes per row (upstream's and ours) and two checks; not implemented.
- **`dm/gfx/vulkan/engine/SOURCE.json` has stale hashes for five files** (`xbg_game.cpp`,
  `xbg_game.h`, `xbg_game_internal.h`, `xbg_texture.c`, `xbg_texture.h`). Our copies match the pin;
  upstream's own manifest does not. Recorded, not fixed — it is upstream's file.
- **The fork's `OP_COPY_IMAGE_STRIDE` (61) and our `OP_COPY_STRIDE{image=1}` now collide in
  meaning.** One case is dead because our writer never emits the fork's op; that "never" is an
  assumption to guard, not to remember.
- **`viewport_n` is a pipeline input now** (`PipeMemoKey.viewports`, through `draw_viewports()`):
  the pipeline declares the recorded array for a viewport-selecting shader. The earlier note said the
  opposite, when every pipeline declared one viewport.
- **The Windows checkout is CRLF (`core.autocrlf = true`)**: `android_vendor.py --check` and the
  generated-file checks report false reds there (and a lost execute bit on `dm/android/docker/build.sh`,
  which the index has as 100755). Compare manifest hashes against the committed bytes: the HEAD blob
  (`git cat-file -p HEAD:<path>`) for an unmodified file; for a modified one the checkout with `\r\n`
  folded to `\n`, **except** the 11 vendored files whose committed blobs are themselves CRLF
  (upstream's bytes: `dm/gfx/vulkan/engine/SOURCE.json`, `xbg_blit.cpp`, `xbg_blit.h`, `xbg_clear.cpp`,
  `xbg_clear_spv.h`, `xbg_cpu_timing.h`, `xbg_descriptor_timing.h`, `xbg_provenance.h`,
  `xbg_shader_key.c`, `third_party/bcdec/provenance.json`, `third_party/pillow_reference/bc6_tables.json`),
  which are hashed as they are: folding them breaks a correct row. Never run `--write` on such a
  checkout (it would record CRLF hashes for every row); edit the one row's sha256 by hand.
- **`exec_pages = ok` was measured in the `shell` SELinux domain.** The app runs in
  `untrusted_app`; the packaged app has since run on the device (§8 item 9), so executable mappings work there; keep the measurement as a caveat only for a different Android build.
- **The desktop smoke build proves compilation and initialization, not a frame.** `presents=0` is
  correct there: there is no guest and no shader bundle.

## 11. Where the knowledge lives

| Question | File |
|---|---|
| What the device is, and what each capability constrains | `docs/reference/android.md`, *The target device, measured* |
| How to address >128 MiB pools without 64-bit shaders | `dm/gfx/vk/address_space.md` |
| Which opcode does what, which handler exists, what a handler must do | `dm/gfx/vk/engine_smoke/opcode_map.txt` (generated) |
| Which writer and reader disagree, and who is right | `dm/gfx/vk/engine_smoke/payload_mismatch.txt` |
| Which `mtl_*` entry points the adapter still lacks | `dm/gfx/vk/engine_smoke/abi_gaps.txt` (generated) |
| What is Apple-specific in the host, and what breaks on 4 KiB pages | `dm/tools/android_audit_baseline.tsv`, `docs/reference/android.md` § *The portability audit* |
| What the vendored engine is, and its driver gates | `docs/reference/android.md` |
| How the Metal replay does each of the above | `dm/gfx/nvn/nvn_mtl.m` |
| The command-record ABI both readers share | `dm/gfx/nvn/nvn_obj.h` |
