# Handoff: running this host on Android (nxdroid)

This file is the state of the Android port, written so that the next session (or person) can continue
without re-deriving anything: **where the work stands, what is broken, what to do next, and how to run
it**. It is not a design document: the design lives in `dm/gfx/vk/address_space.md` and
`docs/reference/android.md`, the per-op detail in `dm/gfx/vk/engine_smoke/opcode_map.txt` and
`payload_mismatch.txt`. Older versions of this file, with the narration of how each fix was found, are
in `git log -p HANDOFF.md`.

The repository's remote is `origin https://github.com/cadocruz/nxdroid.git`, branch `main`. Commits are
made and pushed by the owner, with the repository-local identity
`Ricardo A. F. da Cruz <7233682+cadocruz@users.noreply.github.com>` (`.git/config`; the global identity
is untouched). `AGENTS.md` (rewritten for Android, approved by the owner on 2026-11-03) asks for that
identity and English text; the early commits have Portuguese messages. Check `git log origin/main..main`
before assuming a commit is on GitHub.

> **Before every commit that touches a vendored file, run the two gates below; CI fails otherwise.**
> It happened three times (`89dc2dc`, `85031c7`, and once caught before the push): an edit to
> `dm/gfx/vulkan/engine/xbg_game.cpp` was committed without its manifest row and the opcode report, and
> CI's `android-gates` went red ("Vendored engine provenance" fails first; "Opcode and ABI vocabularies"
> would fail next). Every file under `dm/gfx/vulkan/` and most of `dm/android/` is vendored: it has a row
> in `dm/tools/android_vendor.tsv` with the sha256 of its bytes, and `opcode_map.txt` cites line numbers
> of `xbg_game.cpp`, so **any** edit to that file (a comment included) changes both. On the Linux machine
> (an LF checkout), after editing and before `git commit`:
>
> ```sh
> # 1. which vendored files changed (a path printed here needs its row refreshed)
> git diff --name-only HEAD | grep -Fxf <(cut -f1 dm/tools/android_vendor.tsv)
> # 2. refresh the row of each such file (LF bytes; edit FILES), then the opcode report
> FILES="dm/gfx/vulkan/engine/xbg_game.cpp" python3 - <<'EOF'
> import hashlib, os
> files = os.environ["FILES"].split()
> t = "dm/tools/android_vendor.tsv"; rows = open(t, encoding="utf-8", newline="").read().split("\n")
> for i, row in enumerate(rows):
>     f = row.split("\t")
>     if f[0] in files:
>         f[3] = hashlib.sha256(open(f[0], "rb").read().replace(b"\r\n", b"\n")).hexdigest(); rows[i] = "\t".join(f)
> open(t, "w", encoding="utf-8", newline="").write("\n".join(rows))
> EOF
> CC=gcc python3 dm/gfx/vk/engine_smoke/opcode_map.py
> # 3. both gates must print no [RED] before the commit
> python3 dm/tools/android_vendor.py --check && CC=gcc python3 dm/gfx/vk/engine_smoke/opcode_map.py --check \
>   && python3 dm/gfx/vk/engine_smoke/abi_gaps.py --check
> ```
>
> Commit the refreshed `android_vendor.tsv` and `opcode_map.txt` with the edit. Do not use
> `android_vendor.py --write` for this (it rewrites every row, §10). The 11 vendored files whose committed
> bytes are CRLF (§10) are hashed as they are, not LF-folded: do not refresh their rows with the snippet
> above. On the Windows machine read §10 first (its checkout is CRLF).

## Status at this cut (2026-11-17; last device run: Run 39, 2026-11-08, `501c56e`)

The port is built with NDK r29, packaged as an APK (`com.nxdroid`) and runs on a physical **Samsung
Galaxy S23 Ultra** (Snapdragon 8 Gen 2, Adreno 740, 12 GB RAM, Android 16 / SDK 36, as the probe
measured). The one title run so far is **Mario Kart 8 Deluxe** (`0100152000022000`, update 4.0.1
`[v1507328]`): it boots, plays its menus and videos, and races with a correct 3D picture at a locked
60 fps (Run 36: 60.01–60.22 fps on the 12-kart start grid, 1,247 draws a frame, `submit_cpu_ms`
11.90–12.56, `gpu_ms` 9.44–10.08, `legacy_wait` 0.00). The abort on the way to the second Grand Prix
course is fixed (Run 39). Its note, `dm/games/0100152000022000/README.md`, has every finding on it.

- **Native AArch64 execution:** Horizon SVCs and SDK services answered by `dm/host`; NSO modules
  rewritten by `dm/tools/patch_nso.py --target=android`.
- **H.264 video:** `AMediaCodec` in `dm/android/apple_stubs.c`, decoded into an NV12 `CVPixelBufferRef`;
  menu video previews play in real time.
- **Audio:** AAudio output in `dm/android/apple_stubs.c` (48 kHz stereo PCM, low-latency mode, 240-frame
  callbacks; 0 underruns in 6,000+ callbacks in Run 38). AAC movie tracks decode through MediaCodec since
  2026-11-17 (`AudioConverter` in `apple_stubs.c`; docs/reference/movies.md, *AAC movie sound on Android goes
  through MediaCodec*): tested on the PC against a stand-in decoder, not on the device, and no game run so
  far has AAC movies (Mario Kart 8 Deluxe's previews are H.264).
- **Front end:** `MainActivity` opens on the Argon launcher (since 2026-11-17), which lists the prepared
  games of a library folder (default `/storage/emulated/0/nxdroid`, whose `game/` is where the prepare
  script pushes) and starts the one the APK was built for (§8 item 8; written, not yet run on the device); an
  on-screen multitouch gamepad (`VirtualControllerOverlayView.java`) and physical controllers drive it; an
  on-screen FPS / frame-time / GPU-time HUD (`NativeBridge.nativeGetPerformanceStats()`, a setting).
- **Deployment:** `scripts/prepare_game_android.py` does base + update RomFS extraction, the rewrite,
  shader translation into `.xgs` bundles, the Mii database from emulator user data, and the `adb` push.
  Since 2026-11-04 it scans every RomFS file for shaders and does not rewrite depth into the vertex
  shaders by default (`--depth-rewrite` only for a device without `VK_EXT_depth_clip_control`; the stamp
  `xgs_build.txt` records the setting).

### How the 3D picture and the frame rate were fixed (2026-11-06 to 11-08)

Every fix below is in the tree; the record of each run is in §8 item 12 step 9, the general mechanisms in
`docs/reference/android.md`, `rendering.md` and `audio.md`, linked from the game note's "Found on this
game".

| Run | Symptom | Cause | Fix (where) |
|---|---|---|---|
| 28 | 3D scene posterized, speckled, road and kart black (2D right) | `_inspect_image_type` in `scripts/prepare_game_android.py` broke out of its walk before testing for `OpTypeSampledImage`, so every texture binding of every bundle was written as `SAMPLED_IMAGE` (2), and the engine bound `VK_NULL_HANDLE` samplers. Found with RenderDoc 1.47 on the device (`Colour Pass #6`, draw 2425: `Image & Sampler: No Resource`) | the script records type 1 (`COMBINED_IMAGE_SAMPLER`); the device's bundles were patched in place, and any new preparation writes them right. The engine was not changed |
| 29 | race start aborts: `NVN sampler linear filtering unsupported` | Adreno 740 has no linear filtering on `D32_SFLOAT`, `R32_SFLOAT`, `R32G32B32A32_SFLOAT`; `null_texture` made dummy depth in `D32_SFLOAT` | `sampler_slow` (`xbg_game.cpp`) falls back to nearest with one log line (a device limit: android.md, *Adreno 740 aborts on linear filtering…*); dummy depth uses NVN `0x32`; shadow flags in `ImgKey::kind`; stale `vk-pipeline-*.bin` removed on the device |
| 29 | 25–38 fps with `gpu_ms` 6–8 | synchronous fence waits (`legacy_waitall`), `OP_BARRIER` closing open passes 72 times a frame, memo generations bumped on first registration | async retirement on Android, a barrier splits a pass only after shader writes (as `nvn_mtl.m` `g_pass_swrite`), memo bumps only on a change (`xbg_game.cpp`) |
| 29–31 | `warm_built=0 warm_failed=974`, mid-race compile hitches | `warm::build()` read 5 viewport words where `xbg_graphics_pipeline_key()` writes 6 (`negativeOneToOne`) | read `neg11` and chain `VkPipelineViewportDepthClipControlCreateInfoEXT`; Run 31: `warm_built=1058 warm_failed=0` |
| 31–32 | 28–39 fps, `legacy_wait` 5–9 ms, `retire` 2–3.5 ms, `fb_creates` 4–5 a frame | `mtl_wait_acq` waited on the previous frame's fence; the game finalizes and re-creates 4–5 transient render targets a frame at the same pool address | `mtl_wait_acq` returns 1 (`nvn_vk.c`); released render-target / GPU-written images kept in a bounded `released_images` list and re-adopted (`xbg_game.cpp`). Run 32: ~56 fps |
| 33, 35 | `SIGSEGV` in `vulkan.adreno.so + 0x22c24c`, `addr=0xb4` | experiments: `mtl_wait` not waiting (33); an unconstrained early return in `xbg_legacy_wait` that submitted mid-frame (35) | reverted; `mtl_wait` keeps `xbg_legacy_wait` |
| 34, 36 | start grid at 29–35 fps, `legacy_wait` 9–12 ms | `xbg_legacy_wait` waited for frame N's GPU work before frame N+1 was recorded | on Android, return at once when the target batch is in flight, the other slot is free and nothing is being recorded (`xbg_game.cpp`). Run 36: locked 60 fps |
| 37 | `SIGSEGV` at the same `0x22c24c` / `0xb4`, after the race starts, in `vkCmdDispatch` | Adreno 7xx: a dispatch recorded into a command buffer that already holds draws finds stale graphics dirty bits and reads a null subpass state (reading of the driver in `xbg_adreno_policy.h`) | `xbg_adreno_compute_needs_clean_cmd` (Qualcomm vendor ID): submit the slot before a dispatch when it has draws (`has_draws`); a reused slot also clears a stale `open_pass` |
| 38 | crackling audio: 1,400 of 2,000 callbacks short | AAudio in `PERFORMANCE_MODE_NONE` with bursts up to 1,600 frames against a ~960-frame queue | low-latency mode, 240-frame callbacks, `NBUF` 4 → 8 in `dm/host/hle_audren.c` |
| 39 | abort on the second course: `NVN sampler invalid LOD range/bias result=-4 … bias=-32` | NVN allows LOD bias down to -32; Adreno's `maxSamplerLodBias` is 15–16 (VUID 01079) | `xbg_sampler.cpp` clamps the bias and the anisotropy to the device limits |

Findings of the earlier sessions that still hold:

- **Ruled out as the cause of the 3D picture** (2026-11-03 to 11-05, runs 00–27; they ran before the
  sampler fix, so their pictures say nothing about the switches themselves): the ten single-switch A/B
  runs (`gfx-noload`, `gfx-read-preflight`, `gfx-tex-dirty`, `gfx-wb-skip`, `gfx-upload-prologue`,
  `gfx-vcache`, `gfx-pipe-memo`, `gfx-native-bc`, `gfx-forward-temps`, `gfx-ldc-fold`), the depth
  convention (`gfx-depth-clip`, re-pack without `_rewrite_depth`), repeated colour slots
  (`gfx-rt-dedupe`), pool-alias invalidation (`gfx-alias-invalidate`) and CPU re-upload of GPU-drawn
  textures (`gfx-cpugpu-refresh`). `gfx-read-preflight` on costs 50–74 ms of submit time a frame.
- **Diagnostics the log still prints:** the game attaches one `1920x1080` `0x3d` target at colour slots 3
  and 4 (masks `0xf`, `0`): `[RED] NVN one texture at two colour slots`; `CopyBufferToTexture` writes
  small textures into pool ranges that transient render targets also cover: `[YELLOW] Preserving
  GPU-written image on partial memory pool write` and `[RED] NVN CPU wrote the storage of a GPU-drawn
  texture after the GPU`; `[RED] … hybrid draws are not collected` is a Metal-only statistic the Vulkan
  replay answers with 0. None of them is now known to change the picture; whether the kept GPU pixels
  are right in every case is not checked (§8 item 12 step 8a).
- **Behind markers, off by default, not needed by the game so far:** `gfx-rt-dedupe` (attach a repeated
  level once, as `nvn_mtl.m` `rt_dup_slot`), `gfx-sampler-match` (sampler compare follows the shader's
  depth-compare flag), `gfx-alias-invalidate` and `gfx-cpugpu-refresh` (diagnostic experiments).
- **Written on 2026-11-05, default on, not measured on the device:** alpha 1 for every format
  `nvn_fmt_mtl.c` marks without alpha, composed with the game's swizzle, and 16-bit packed formats chosen
  by bit layout (`0x3c` → `B5G6R5`, `0x96` → `A1R5G5B5`, `0x98` → `R5G5B5A1`; `0x3a` / `0x3b` keep red
  and blue swapped without `VK_KHR_maintenance5`, one `[RED]`). A wrong colour in a menu or a font is
  where these would show. Still open: min / max sampler reduction is dropped by `xbg_sampler_from_nvn`.
- **Sprint 6 fixes still in the tree:** the present path keeps the swapchain at the window's size
  (`present_native = false`; `gfx-present-native` brings the old path back) against vertical banding,
  with a linear present blit and at least three swapchain images; a 3D view takes one layer (the LUT);
  `gpu_written` survives partial CPU writes; swizzled views do not alias; the graphics defaults
  `nativeStartHost()` sets (`DM_GFX_*`, §8 item 12).

### Open after Run 39

1. **Coverage:** one game, one course start and one course transition. Other courses, a full Grand
   Prix, battle mode, 2–4 player split screen and a long session (memory after a level change:
   `adb shell dumpsys meminfo com.nxdroid`, the `dm_guest_discard` fix) are not run.
2. **The `0x22c24c` crashes have one driver path.** Runs 33 and 35 (`vkCmdDrawIndexed`) and Run 37
   (`vkCmdDispatch`) fault at the same offset with the same `addr=0xb4`; Run 37's reading of the driver
   (a stale graphics dirty bit at `[cmd, #0x78]` leading to a null `GetSubpassState`) may also be what
   the earlier two hit after a mid-frame submit. Not checked; worth knowing before trying another
   change to submission or pass boundaries.
3. **[DONE 2026-11-17] Records for Run 37:** `docs/reference/android.md`, *Adreno 7xx crashes in
   vkCmdDispatch recorded after draws in the same command buffer* (under *Adreno driver gates*), its
   symptom-index line and the game note's "Found on this game" line.
4. **Records to correct:** `mtl_wait_acq` in `dm/gfx/vulkan/nvn_vk.c` returns 1 with no comment saying
   why (the reason is in android.md, *Guest CPU blocks synchronously on previous frame fence in
   mtl_wait_acq*); `docs/reference/audio.md`, *AAudio's default buffer duration…*, says "buffer capacity
   of 8 frames" where the code asks for 8 callbacks (1,920 frames); `README.md` (Vulkan Graphics, 3D
   picture) still says the 3D scene is wrong and gives ~54 fps; the game note points at a "Next device
   session" this file no longer has.
5. **Performance margin:** at the start grid CPU recording takes 11.9–12.6 ms of the 16.7 ms frame; a
   heavier scene or split screen may not hold 60. `NVN PERF` `parts_ms_per_frame` is where to look.
6. **The device's bundles were patched in place (Run 28).** A preparation from scratch with the current
   script must give the same `type = 1` bindings; it has not been run since the fix. The counts of the
   earlier preparation: 29,651 shaders found, 29,642 bundles, 9 without one (`missing_shaders.tsv` in the
   work folder).
7. The rest of the list is §8: items 2 (viewport mask), 5 (Vulkan / OpenGL games), 6 (zero-copy probe),
   7 (128 MiB experiment), 8 (the launcher: a first run on the device) and 10 (Apple code, last).

### How a device run is made

On the Linux machine with `adb`, podman and the phone (USB debugging on), from the repository root.
`ADB` is the `adb` used there (`/opt/platform-tools/adb` in the 2026-11-03 session); pass it to the
script with `--adb "$ADB"`. Name captures with the next free number in `/tmp/nxdroid-test/` (the next is
40).

1. `git pull`, `git log -1 --oneline`; CI green for that commit. Build the APK (§5, with the persistent
   keystore mount) and `"$ADB" install -r dm/android/app/build/outputs/apk/debug/app-debug.apk`. If it
   fails on the signature, `"$ADB" uninstall com.nxdroid` deletes the app's saves
   (`/data/user/0/com.nxdroid/files/save`) but not `/storage/emulated/0/nxdroid/`; check afterwards that
   `ls /storage/emulated/0/nxdroid/game` still lists `main`, `romfs.img` and the `.xgs` bundles. Record
   the installed commit.
2. `"$ADB" logcat -G 16M`, then `python3 scripts/android_gfx_ab.py --adb "$ADB" --clear-all --no-restart`
   and `--list` (it must print no marker). The engine reads markers from the game folder's parent,
   `/storage/emulated/0/nxdroid/`; do not pass `--game-dir /storage/emulated/0/nxdroid`.
3. `"$ADB" logcat -c`, start the app, press **Launch** (the old front end: **START GAME**), race, then
   `"$ADB" exec-out screencap -p > /tmp/nxdroid-test/<n>_<name>.png` and
   `"$ADB" logcat -d -s dm > /tmp/nxdroid-test/<n>_<name>.txt`; after a crash also
   `"$ADB" logcat -d -b crash`. The app can also start straight into the game:
   `am start -n com.nxdroid/.MainActivity --es gameDir /storage/emulated/0/nxdroid/game --ez autoStart true`
   (used for RenderDoc).
4. One switch: `python3 scripts/android_gfx_ab.py --adb "$ADB" <marker> --off|--on --wait 120 --shot …
   --log …`, then `<marker> --clear --no-restart`; one marker at a time (§8 item 12 steps 4 and 5).
5. Read first: the `nativeStartHost: DM_GFX_…` lines and the engine's `(marker gfx-…)` lines, every
   `[RED]`, `Swapchain …`, `NVN PERF` (`fps`, `gpu_ms`, `submit_cpu_ms`, `legacy_wait`,
   `parts_ms_per_frame`, `warm_built` / `warm_failed`). Append the run to §8 item 12 step 9.
6. A GPU frame capture: RenderDoc 1.47, with `libVkLayer_GLES_RenderDoc.so` packaged into
   `dm/android/app/src/main/jniLibs/arm64-v8a/` of a debug APK (Android 16 One UI refuses an external
   layer for a debug app). Copy the layer from the RenderDoc install for the capture only: the folder
   `jniLibs/` is in `.gitignore`, since everything in it is packaged into the APK. (The layer, 27.8 MB, was
   committed by mistake in `c6427e3` and removed on 2026-11-17; nothing in the app loads it.)
7. After a stopped warm-up or a change to descriptor layouts, remove the pipeline cache files on the
   device (`/sdcard/nxdroid/vk-pipeline-*.bin`; §10).

---

## 1. The goal

Run this repository's catalogue natively on Android, on a Samsung Galaxy S23 Ultra. Native means what
it meant for nxnative on Apple: the game's own AArch64 code runs, rewritten only where the platform
requires it; a host answers Horizon's SVCs and the SDK's services; and the NVN command stream, which
nxnative replayed on Metal (`dm/gfx/nvn/nvn_mtl.m`), is replayed on Vulkan. Guest virtual address ==
host address, and guest memory is mapped memory.

## 2. Decisions taken, with the reason

| Decision | Choice | Why |
|---|---|---|
| Porting base | [`jhaizhou-ops/d2r-mobile`](https://github.com/jhaizhou-ops/d2r-mobile) (MIT), pinned at `1e0e7934c9ccdf95494aee5065d1d07ab3cc3918`, tag `v2.1.0` | It is the real upstream: a Vulkan engine written by a fork of this repository, against this repository's `nvn_obj.h`/`nvn_mtl.h` ABI, with Adreno-specific driver gates and a vendored bionic compatibility layer |
| `ghostyshell/nx2apk` | reference only | It proves the model (Devil May Cry 3 at 60 fps on a Galaxy S10e, Mali-G76) but it is Mali-shaped (no Adreno gate), far behind, needs a Mac to translate shaders, and has no scheme for the Adreno 128 MiB binding limit. Its `dm/android/nvn_vk.c` was the reference for the 27 `mtl_*` entry points the adapter lacked |
| `wdjwxh/Taikou5-mobile` | rejected | Ahead of `nx2apk`, behind `d2r-mobile`; a downstream of the same engine |
| Build environment | **podman**, rootless, not docker, on the Linux work machine; CI on GitHub's Linux runners | The Linux machine's docker daemon is down and podman (5.7.0) is installed. The vendored `dm/android/docker/` is used as a Dockerfile only |
| `dm/gfx/nvn/nvn_obj.h` | master | The engine adapts to our command vocabulary, not the reverse. The NVN profiles (93 when this was decided) record through `dm/gfx/nvn/hle_nvn.c`; the engine's fork had diverged from it |
| Zero-copy | **not available**; mirror is the baseline | `VK_EXT_external_memory_host` is absent on the Adreno 740. The only remaining route is to allocate pool memory *as* an `AHardwareBuffer` and import it, unmeasured: §8 item 6 |
| Platforms | **Android only**, owner's decision | nxdroid is never built for Mac or iOS again. `regress.py check --games` and the Mac `make -C dm/host` are no longer requirements; the Apple branch of `port.h`, the `.m` files and the IPA tooling stay in the tree only until the **last** task (§8 item 10), because `nvn_mtl.m` is still the reference the `opcode_map` / `abi_gaps` gates compare against |
| Adreno 740 float/depth sampler filtering | **Nearest fallback + D16/D24 dummy depth** | On Adreno 740, `VK_FORMAT_D32_SFLOAT`, `VK_FORMAT_R32_SFLOAT`, and `VK_FORMAT_R32G32B32A32_SFLOAT` lack `VK_FORMAT_FEATURE_SAMPLED_IMAGE_FILTER_LINEAR_BIT`. Aborting in `sampler_slow` crashes the race start immediately when `.xgs` bindings are `COMBINED_IMAGE_SAMPLER` (`type = 1`). Clamping unsupported linear/aniso sampler states to `VK_FILTER_NEAREST` with a one-time log avoids aborts, and using NVN format `0x32` (`D16` / `X8_D24`) for unbound depth/shadow dummy textures in `null_texture` provides hardware-supported linear/PCF filtering |
| Android fence retirement | **Async completion wait (`legacy_waitall = false`)** | `legacy_waitall = true` locked the engine mutex and called `submit_slots(false)` followed by synchronous `vkWaitForFences` on every submission wait, stalling the CPU for 10–12 ms/frame. Enabling `completion_wait_default = true` allows slots and fences to retire asynchronously |
| Render pass barrier coalescing | **Split on `open_pass.shader_writes` only** | `OP_BARRIER` previously closed open passes unconditionally, splitting them 72.4 times/frame. Checking `open_pass.shader_writes` matches `nvn_mtl.m` (`g_pass_swrite`) and prevents pass fragmentation when passes only perform plain vertex/fragment sampling |
| Pipeline warm-up viewport deserialization | **Explicit `negativeOneToOne` deserialization** | `xbg_graphics_pipeline_key()` serializes 6 words for viewport state (including `negativeOneToOne`), but `warm::build()` read 5, shifting all subsequent words by 4 bytes and failing 100% of pipeline records (`warm_failed=974`). Deserializing `neg11` aligns words and restores pipeline precompilation |
| `mtl_wait_acq` non-blocking return | **Non-blocking return (`return 1`)** | `nvnWindowAcquireTexture` synchronization is already handled by swapchain semaphores; returning 1 unblocks Frame N+1 CPU recording |
| `mtl_wait` submission flush | **Calls `xbg_legacy_wait`** | Unlike `mtl_wait_acq`, `mtl_wait` gates queue fence syncs (`nvnQueueFenceSync`). Bypassing `xbg_legacy_wait` causes command buffers to remain unretired and desynchronizes render pass state, causing `SIGSEGV` in `vulkan.adreno.so` (`vkCmdDrawIndexed`). `mtl_wait` must flush and retire slots |
| `xbg_legacy_wait` safe 1-frame pipelining | **Return 1 on `t->pending && t->covers>=fence && !cur.pending && !(cur.recording && cur.ops)`** | An unconstrained `fence <= submitted` return in Run 35 caused mid-frame submissions that split render passes and crashed Adreno in `vkCmdDrawIndexed`. Restricting early return to clean frame boundaries (`!(cur.recording && cur.ops)`) with target in-flight and alternate slot free pipelines Frame N+1 CPU work (11.9 ms) concurrently with Frame N GPU execution (9.4–10.1 ms), locking 60.01–60.22 FPS at race start with zero stalls (`legacy_wait = 0.00 ms`) and zero crashes |
| Android debug signing keystore | **Persistent `~/.android-dm/debug.keystore`** | Gradle recreates a random debug keystore when the container user home is ephemeral, causing `INSTALL_FAILED_UPDATE_INCOMPATIBLE` on subsequent installs. Mounting a persistent directory to `/android-user` keeps the debug certificate stable across builds |
| Transient render-target retention | **`released_images` standby list** | Finalizing and re-initializing 4–5 transient render targets per frame destroyed and recreated `VkFramebuffer`, `VkImageView`, and `VkImage` every frame. Retaining pool-backed GPU-written/render-target images at identical descriptor and `t->mem` reduced `retire` from 3.54 ms to 0.05 ms/frame and eliminated per-frame churn (`fb_creates = 0.00`). Restricted to render targets to avoid upload desynchronization |

## 3. The target, measured

The full table with its consequences is in `docs/reference/android.md` under **The target device,
measured**. The load-bearing facts:

- Adreno (TM) 740, Vulkan 1.3.128, driver 512.676.1, Android 16 (SDK 36), 4 KiB pages, 11.58 GB UMA.
- `VK_EXT_external_memory_host` **absent** → the replay mirrors guest memory; the memory types a pool
  would use are `device_local` **and** `host_visible`, so a mirror copy is a plain `memcpy`.
  `VK_ANDROID_external_memory_android_hardware_buffer` is present.
- `maxStorageBufferRange = 128 MiB` with `shaderInt64 = false` → **the backend's central design
  problem**: NVN hands shaders 64-bit GPU addresses into pools of arbitrary size, and the device can
  neither bind more than 128 MiB at once nor do 64-bit pointer arithmetic in a shader.
  `VK_KHR_buffer_device_address` is present and useless for the same reason. `dm/gfx/vk/address_space.md`
  settles it: **option A1**, one descriptor per NVN binding at `(B & ~63) - P` with
  `range = min(poolEnd - (B & ~63), 128 MiB)`, the translator answering
  `QueryHasUnalignedStorageBuffer() = true` / `QueryHostStorageBufferOffsetAlignment() = 64` (two ALU
  ops per guest global access, Vulkan only).
- BC textures are native; `subgroupSize = 64`; no `VK_KHR_pipeline_binary` or
  `VK_EXT_graphics_pipeline_library` (so a persisted `VkPipelineCache` is mandatory for load time).
- Bionic: `tpidr_el0 + 0x10` (`TLS_SLOT_APP`) is zero on the main thread and on spawned pthreads;
  `RLIMIT_NICE = 40`; `memfd_create` aliasing works (§8 item 9).
- Measured 3D performance on target (Galaxy S23 Ultra, Adreno 740): locked 60.01–60.22 FPS in Mario Kart 8 Deluxe 4.0.1 3D race start (12-kart grid, 1,247 draws/frame, `submit_cpu_ms = 11.90–12.56 ms`, `gpu_ms = 9.44–10.08 ms`, `legacy_wait = 0.00 ms`).

The dump is a device artifact, not in the repository; regenerate it with the probe (§5) and put any
new fact in `docs/reference/android.md`, not here.

## 4. What is in the tree

| Path | What it is | State |
|---|---|---|
| `dm/gfx/vulkan/` (85 tracked files) | the vendored Vulkan engine and its `nvn_vk.c` adapter | pinned, adapted (12 handlers in `xbg_game.cpp`, 27 entry points in `nvn_vk.c`, the Sprint 6 fixes, sampler linear filtering fallback, D16 dummy depth, ImgKey shadow separation, async fence retirement, barrier pass coalescing, memo epoch stability, warm::build negativeOneToOne alignment, mtl_wait_acq non-blocking return, transient render-target retention, xbg_legacy_wait safe 1-frame boundary pipelining, the Adreno compute-after-draw gate `xbg_adreno_compute_needs_clean_cmd`, sampler LOD bias / anisotropy clamp in `xbg_sampler.cpp`) |
| `dm/android/` | the bionic compatibility layer (`compat/`), build environment (`docker/`, `CMakeLists.txt`, Gradle), `front_android.c` (our `front.h`), `vulkan_present.cpp`, `jni_android.c`, `port_android.c`, `apple_stubs.c` (+ `apple_stubs/include`), `app/` (Java, real-time FPS HUD), `tools/`, `tests/` (`test_device_bionic.c`, `test_vm_alias.c`), `mockups/` | NDK r29 build of `dmhost` and `libdm.so`, both run on the device; CI compiles them |
| `dm/tools/android_vendor.py` + `.tsv` | provenance gate: 108 rows, 13 adapted | green in CI; on a Windows checkout read §10 |
| `dm/gfx/vk/probe/` | the device capability probe (`vk_probe.c`, Makefile with desktop and `android` targets, output contract in `tests/test_probe_output.py`) | run on the device, 0 breaches |
| `dm/gfx/vk/engine_smoke/` | out-of-tree harness: compiles the vendored engine against **our** headers and initializes it; the generated `opcode_map.txt` / `abi_gaps.txt` and `payload_mismatch.txt` | green on desktop (llvmpipe, RTX 5060 Ti); not in CI |
| `dm/gfx/vk/address_space.md` | the 64-bit address space decision | written, not reviewed by hand |
| `dm/host/port.h` | the host's platform layer: Apple inline, bionic in `dm/android/port_android.c` | compiled with the NDK, runs on the device |
| `dm/android/tools/{host_sources,undef_scan}.py`, `dm/tools/tests/test_{thread_slots,android_undef_scan,android_jni,android_vm_alias,launcher_settings,env_switches}.py` | source-list expander, undefined-symbol and Mach-O assembly gate, and the Android tool tests | green in CI |
| `dm/tools/android_audit.py` + baseline + tests | "is this file portable to Android?"; the baseline only shrinks | 760 hits in 38 files |
| `scripts/prepare_game_android.py` | prepares a game folder for the device and can push it, build and install the APK | in use |
| `scripts/android_gfx_ab.py` | A/B one engine switch over `adb` without a rebuild (§8 item 12 step 5) | used on the device in runs 01–27; no unit test |
| `.github/workflows/tests.yml` | CI: `android-gates`, `android-build` and `android-app` (since 2026-11-17), Linux | the first two green and blocking since `94d3ee4`; `android-app` not run yet |
| `README.md`, `CONTRIBUTING.md`, `AGENTS.md`, `.github` templates | describe the Android port; README's game gallery is folded below the Android games section and labelled as nxnative's Mac / iPhone builds | current |
| `docs/reference/android.md` | the vendored engine reference: pin, gate, device, Adreno gates, ABI gaps, licensing, the Android findings | current, with the stale lines named in §8 item 11 |
| `.opencode/agents/android-{dev,qa,shaders,upstream}.md` | the four specialist agents this work was coordinated through | in use |

## 5. Gates, and the exact commands

Run these before believing anything. CI (`.github/workflows/tests.yml`, GitHub's Linux runners) runs
them on every push to `main` and every pull request: `android-gates` (provenance, both vocabularies,
the audit, the symptom index, the four engine source checks, the tool tests below) and `android-build`
(NDK `ndk;29.0.14206865` through `sdkmanager`, `GAME=0100152000022000`, configure, then
`cmake --build … --target dmhost dm`), both green and blocking since `94d3ee4`; and, since 2026-11-17,
`android-app` (the SDK packages, JDK 17 and Gradle 9.8.1 of `dm/android/docker/Dockerfile`, then
`gradle -p dm/android :app:compileDebugJavaWithJavac :app:testDebugUnitTest`: the app's Java and its JVM
unit tests in `dm/android/app/src/test`, no APK and no native build; not yet run on GitHub). CI never runs the
`engine_smoke` build (it needs a Vulkan driver) nor anything on a device.

```sh
# vendored provenance: 108 files, 13 adapted
python3 dm/tools/android_vendor.py --check

# the engine compiles against our headers, every TU, no workaround (local only, not in CI)
make -C dm/gfx/vk/engine_smoke report CC=clang CXX=clang++     # 8 C + 12 C++ + 2 repo + 2 harness, all ok
make -C dm/gfx/vk/engine_smoke run                              # llvmpipe: exits 0, fatals=0
make -C dm/gfx/vk/engine_smoke run-gpu                          # RTX 5060 Ti: exits 0, fatals=0

# the two generated vocabulary reports match the tree (CI sets CC=gcc for opcode_map.py)
python3 dm/gfx/vk/engine_smoke/opcode_map.py --check
python3 dm/gfx/vk/engine_smoke/abi_gaps.py --check

# host portability audit: the baseline is the record, it only shrinks
python3 dm/tools/android_audit.py --summary
python3 dm/tools/android_audit.py --check

# symptom index (run without --check after any docs/reference edit)
python3 dm/tools/docs_symptoms.py --check

# engine source checks: text checks, not compiles (event_order_test needs hle_nvn.c and xbg_game.cpp as they are)
for t in pipeline_memo_source_test event_order_test source_structure_test copy_stride_test; do
    python3 dm/gfx/vulkan/engine/tests/$t.py; done

# tool tests: unittest for these, pytest for the probe contract (its tests are plain functions)
for f in test_docs test_android_vendor test_android_audit test_thread_slots test_android_undef_scan \
         test_android_jni test_android_vm_alias test_launcher_settings test_env_switches; do
    python3 -m unittest -v dm/tools/tests/$f.py; done
python3 -m pytest -q dm/gfx/vk/probe/tests/test_probe_output.py
```

The full `dm/tools/tests` suite is **not** green outside CI's subset, for environment reasons: five
modules import `/usr/lib/libproc.dylib` (macOS only) and the fuzz corpus needs `lz4`. Say so rather
than claiming the suite passes. On the Linux machine the system `python3` has no pytest; use
`python3 -m pytest` from a venv.

On the Windows machine: there is no `python3` on `PATH`; use LibreOffice's python
(`"C:/Program Files/LibreOffice/program/python.exe" -X utf8`, 3.10), `CC=gcc` for `opcode_map.py`,
check whether pytest is installed before using it, and read §10 for the CRLF false reds.

Building and running on the device (Linux machine, podman image `dm-android-tools:1`, §9):

```sh
# the probe
podman run --rm --userns=keep-id -v "$PWD:/src:rw" -w /src dm-android-tools:1 \
    make -C dm/gfx/vk/probe android NDK=/opt/android-sdk/ndk/29.0.14206865

# the host for one profile (GAME as in make -C dm/host; no default). ANDROID_PLATFORM >= 29 (the guest
# thread slots are in bionic's TLS_SLOT_APP, the app's from 29; the CMake stops below), arm64-v8a only.
# A profile outside the repository: -e DM_GAMES_DIR=/games -v <folder>:/games:ro (the configure caches it).
podman run --rm --userns=keep-id -v "$PWD:/src:rw" -w /src dm-android-tools:1 \
    cmake -S dm/android -B build/android/<GAME> -DGAME=<GAME> -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=29 \
      -DCMAKE_TOOLCHAIN_FILE=/opt/android-sdk/ndk/29.0.14206865/build/cmake/android.toolchain.cmake
podman run --rm --userns=keep-id -v "$PWD:/src:rw" -w /src dm-android-tools:1 \
    cmake --build build/android/<GAME> --target dmhost dm

# a game folder: the rewriter runs with --target=android (the loader refuses Apple output); see its --help
python3 scripts/prepare_game_android.py <.nsp, .xci or folder> --title-id <id> [-u <update>] [-k <prod.keys>] [--push]

# the APK (in the same image, with persistent keystore mounted to /android-user), then install it
podman run --rm --userns=keep-id -v "$PWD:/src:rw" -v "$HOME/.android-dm:/android-user:rw" -w /src dm-android-tools:1 \
    gradle -p dm/android :app:assembleDebug -PdmGame=<id>
adb install -r dm/android/app/build/outputs/apk/debug/app-debug.apk

ADB=/tmp/opencode/platform-tools/adb          # 37.0.1; the device is RQCX808VH9K
$ADB push dm/gfx/vk/probe/vk_probe_android /data/local/tmp/vk_probe
$ADB shell chmod 755 /data/local/tmp/vk_probe && $ADB shell /data/local/tmp/vk_probe > /tmp/opencode/s23-ultra.txt
python3 dm/gfx/vk/probe/tests/test_probe_output.py /tmp/opencode/s23-ultra.txt   # must print "valid"

# a run's log
adb logcat -c   # before the run
adb logcat -d -s dm > log.txt

# A/B one engine switch in the installed app, no rebuild (§8 item 12, steps 4 to 6)
python3 scripts/android_gfx_ab.py gfx-noload --off --shot noload_off.png --log noload_off.txt
python3 scripts/android_gfx_ab.py gfx-noload --clear
```

## 6. What is done

Sprints 1–2 vendored the engine with a provenance gate (it fails on a changed byte, an unlisted file,
a stale row, a wrong pin or a lost execute bit); Sprint 3 wrote the probe and ran it on the device
(Qualcomm's `driverInfo` contains newlines, so the probe folds whitespace); Sprint 4 made `nvn_obj.h`
usable from C++ and named the fork's commands `OP_XBG_*` after our `OP_COUNT_`; Sprint 5 completed the
replay and the ABI (§7); then the host bring-up, app shell and device run (§8 items 4 to 9), the
Sprint 6 fixes (Status) and CI on Linux (§5).

Current counts:

- `opcode_map.py --check`: **53 ops, 53 handled, 0 missing, 1 payload-mismatched** (51 until `OP_SCISSORS` / `OP_DEPTH_RANGES`, 2026-11-05) (`P8`, barrier
  cache bits, benign: the reader's single full barrier is stronger), **11 fork-only**. `P6`, the
  multi-viewport record, is handled in the draw and not yet reachable end to end (§8 item 2).
- `abi_gaps.py --check`: **0 `mtl_*` entry points missing, 0 signature mismatches, 28 extra** (the
  adapter's helpers and the statistics it answers for `hle_nvn.c`).
- `android_audit.py --summary`: **760 hits in 38 files**: 426 `objc-framework`, 319 `apple-api`,
  12 `page-assumption`, 3 `macho-section`.

## 7. What is completed, and what was verified

- **12 opcode handlers** in `xbg_game.cpp`: `OP_CLEAR_BUF`, `OP_DEPTH_CLAMP`, `OP_RENDER_COND`,
  `OP_FENCE_SYNC`, `OP_TF_BIND`, `OP_TF_STATE`, `OP_RAST_DISCARD`, `OP_VP_SWIZZLE`, `OP_BIND_TEX1`,
  `OP_PRIM_RESTART`, `OP_BIND_UBO_SMALL`, `OP_BIND_VBUF1`. `primitiveRestartEnable`,
  `depthClampEnable` and `rasterizerDiscardEnable` are in the pipeline create info;
  `state.render_cond_skip` guards draws and clears and resets at a submission boundary (`depth == 0`);
  `OP_CLEAR_BUF` checks 4-byte alignment.
- **27 `mtl_*` entry points** in `dm/gfx/vulkan/nvn_vk.c` (`mtl_sub_fill` routes to `OP_CLEAR_BUF`),
  the `mtl_link_wait_tick` signature mismatch resolved.
- **Engine semantics checked against `nvn_mtl.m` (round F):** NVN's window origin is in the engine
  (`xbg_game_set_window_origin` / `xbg_game_set_queue_origin`; the device origin flips every viewport
  and the present blit; the queue origin, captured per submission in `xbg_submit` as `sub_origin`,
  decides the front face and is in `PipeMemoKey.origin`). Primitive restart is declared only for strips
  and fans, and a restart index other than all-ones is mapped onto all-ones in a copy of the indices
  (the widened 8-bit stream included; that the GPU compares at the stream's width is unverified).
  `OP_RENDER_COND` never waits for the GPU: a counter field under a pending `TIMESTAMP` /
  `TIMESTAMP_TOP` report at that exact address is known 0; any other pending report or writeback keeps
  the draws (`rc_occ` not followed). `ReportCounter(TIMESTAMP_TOP)` (Tears of the Kingdom's conditional
  clears) is a top-of-pipe timestamp; a pipeline statistic is counter 0 with one `[RED]`, not a fatal.
  `docs/reference/android.md`, *The Vulkan replay ignored the window origin, the depth mode and the
  restart index*.
- **`pipeline_memo_source_test.py`** is a text check, not a compile; it also fails when a comment on a
  code line swallows code after it (a `frontFace` edit once hid `rs.lineWidth` and the depth-bias
  assignments). On scratch copies it catches **40 mutations** (among them the pending-report rule, the
  restart masks, the lower-left viewport flip and the `multiViewport` gate); QA's exact round-H
  mutations were not rerun, only their categories.
- **GL depth mode (near = -w):** a game that keeps it gets `negativeOneToOne` through
  `VK_EXT_depth_clip_control` (`nvn_vk.c`, the log line `NVN depth mode near=-w (GL) kept by the game:
  active via VK_EXT_depth_clip_control`; the Adreno 740 has the extension). **Open:** on a device without
  it the replay has no near = -w vertex entry point (`nvn_mtl.m` `entry_z`): one `[RED]` and near = 0
  depth, unless the game is prepared with `--depth-rewrite` (Status).

## 8. What to do next, in order

1. **[DONE] The 12 missing handlers** (§7).
2. **[DRAW DONE, path open] `P6` n > 1 viewports.** Done: `OP_VIEWPORTS` keeps the 16-entry array and
   its length; a draw whose last pre-raster shader writes `ViewportIndex` (`XbgRasterFacts`) declares
   and sets `viewport_n` viewports (dynamic state, the recorded scissor and depth range for each,
   per-viewport swizzle, an unset index empty), one otherwise; the count is in `PipeMemoKey.viewports`;
   `validate_capabilities` accepts `MultiViewport` under `multiViewport` and 70 / 5254 /
   `SPV_EXT_shader_viewport_index_layer` under `shaderOutputViewportIndex`, and refuses the viewport
   mask (5255) with a `[RED]`. The front end creates the device with
   `VkPhysicalDeviceVulkan12Features.shaderOutputViewportIndex` + `shaderOutputLayer` (or
   `VK_EXT_shader_viewport_index_layer`) and `VK_KHR_multiview`, and calls
   `xbg_game_set_viewport_features` (through `dm_vk_config`); the 1.2 feature struct is chained by the
   instance's `apiVersion` (`xbg_game_config.instance_api_version`), not the loader's. **Not measured on
   the device.** Open:
   - **[DONE 2026-11-05, measured on the device in run 26]** `NVN_DEVICE_INFO_MAX_VIEWPORTS` comes from the
     device: `nvnDeviceGetInteger` asks the replay (`mtl_device_integer`, `nvn_mtl.h`; `nvn_vk.c` →
     `xbg_device_integer`, `multiViewport ? min(16, maxViewports) : 1`); the Tegra table's 16 is left
     only before the Vulkan replay is up (`[RED] nvnDeviceGetInteger item 0x26 before the Vulkan replay is
     initialized`, which a device log should not show; confirmed absent in run 26).
   - **[DONE 2026-11-05, measured on the device in run 26]** `SetScissors` / `SetDepthRanges` keep every
     index: index 0 as before (`OP_SCISSOR` / `OP_DEPTH_RANGE`), 1..15 in the new `OP_SCISSORS` /
     `OP_DEPTH_RANGES` records (`OP_COUNT_` is 53, the `OP_XBG_*` block 54..64, the capture layout says
     `ops 53`), and a draw that declares viewport *i* sets scissor and depth range *i*. A range past 16
     is refused with `[RED] SetScissors first=… n=…: outside NVN's 16 viewports`. The Metal replay skips
     the new records (index 0 only, as before). Checked by a harness of the extracted writer and by the
     gates; CI's NDK build is the first compile. Confirmed clean on device in run 26 (no out-of-range red).
   - The `VK_KHR_multiview` fan-out for a viewport mask (gate, SPIR-V rewrite, layered pass and
     composite) is designed, not written.
   - The probe prints `multiViewport`, `multiview`, `shaderOutputViewportIndex`, `shaderOutputLayer` and
     `maxViewports`; not yet run on the S23 Ultra with that version.
   All in `docs/reference/android.md`, *The replay refused a record of more than one viewport*.
3. **[DONE] The 27 missing `mtl_*` entry points** (§7).
4. **[DONE] Host bring-up on bionic**, built with NDK r29 and run on the device (item 9). Every
   Apple-only call the kept C sources make goes through `dm/host/port.h` (Apple inline, unchanged) and
   `dm/android/port_android.c` (bionic, over `dm/android/compat/`); the list is in
   `docs/reference/android.md`, *The host's platform primitives live in `dm/host/port.h`*, and in
   `port.h` itself. Behaviours worth knowing: case-collision names use a `user.` xattr, and on storage
   without xattrs the operation is undone with one `[RED]`; the NVN capture's LZFSE is off on bionic
   (`DM_HAVE_COMPRESS` 0: chunks stay raw, an LZFSE capture cannot be read); `dm_thread_rt_set` (no
   SCHED_FIFO for an app) and `dm_task_power` (Apple `task_info` facts) are platform limits, said once.
   **Unverified:** that the weak `__start_*` references resolve when a section has no entry;
   `dm_uc_ns`'s fpsimd record walk and `dm_proc_start_ns` are untested on a device. "`undef_scan`
   clean" means no dropped repository definition is still called, not a clean link (the NDK link is).
   `pthread_gettid_np` (`port_android.c`, compat's `mach.h`) does not exist on OHOS/musl.
4a. **[DONE, device-checked] The guest thread slots on bionic** (`docs/reference/android.md`, *The guest
   thread slots assumed Darwin's TSD layout*). `patch_nso.py --target=android` reaches every slot (13
   sites) through `mrs xN, tpidr_el0; ldr xN, [xN, #16]` (bionic's `TLS_SLOT_APP`, API 29); the host's
   `port.h` `dm_kslot_*` keep a tagged five-word table in that word; `loader.c` refuses a module of the
   other target. Verified: `test_thread_slots.py` (17 tests, every mutation QA listed fails it) and
   `test_device_bionic` on the S23 Ultra (word 2 is zero on the main thread and on spawned pthreads).
   **Unverified:** that no library in the app process writes word 2 (the GL / Vulkan loaders, sanitizers
   and ART use other words per bionic's `tls_defines.h`, quoted from memory); the inline assembly of
   `dm_kslot_guest_read`. **Open:** Go's runtime with cgo keeps `g` in `TLS_SLOT_APP` on android/arm64
   from API 29 (golang/go#29674): a Go library cannot share the process. `prepare_game_android.py`
   rewrites every module with `--target=android` on every run and caches nothing; the Apple
   `build_ipa_from_nsp.py` caches its rewrite by a fingerprint with no target in it, so any Android path
   built on it must add the target to that fingerprint (moot once item 10 removes it).
4b. **[DONE] Event reads on the Vulkan replay** (round I): `hle_nvn.c` calls `mtl_event_read` (declared
   in `nvn_mtl.h`, weak no-op for Metal, strong in `nvn_vk.c`) before `nvnEventInitialize` / `Finalize` /
   `GetValue` and `ev_signal`'s read-modify-write; `event_order_test.py` passes.
5. **[DONE] The build.** `dm/android/CMakeLists.txt` takes `-DGAME=<id>` like `make -C dm/host`,
   reads the source list from `dm/host/Makefile` (`host_sources.py`), requires arm64 and
   `ANDROID_PLATFORM >= 29`, and runs `undef_scan.py` at configure; what only a dropped `.m` defined is
   answered in `nvn_vk.c` (the engine's counts, or a one-time `[RED]` "not collected / not implemented on
   this platform"; `docs/reference/android.md`). **Open:** no graphics layer for the Vulkan / OpenGL games: `dm/gfx/vk/hle_vk.m` and
   `dm/gfx/gl/hle_gl.m` are Metal and dropped, so a profile that renders through them has no graphics
   HLE on Android (the games table names their API).
6. **Probe v2, the last chance for zero-copy** (not started):
   `vkGetPhysicalDeviceExternalBufferProperties` for opaque-fd and AHB, plus a real 64 MiB
   `AHardwareBuffer` import and a shader write through it. If that works, pools can be allocated in AHB
   memory and the mirror's copy tax disappears; if not, the mirror stands and `nvn_dirty.c`'s page
   tracking is the performance-critical path (4 KiB pages match the device).
7. **`address_space.md` §8's experiment**, if the 128 MiB cap turns out to matter (not started). It
   needs a translated SPIR-V shader: `prepare_game_android.py` now produces them, running the
   translator's `dmsh_xlate.dll` through `dotnet` (or the `mcr.microsoft.com/dotnet/sdk` container), so a
   Mac is no longer needed for this; that the experiment's shader can be taken from there is read from
   the code, not tried.
8. **[DONE] The app shell; [WRITTEN 2026-11-17, not run on the device] the Argon launcher.**
   `dm/android/jni_android.c` (JNI registration, stdout/stderr to logcat tag `dm`, host start/stop,
   surface, refresh rate, touch and pad input, the graphics defaults of Status, `nativeGetBuiltGame`;
   tested by `test_android_jni.py`) and `dm/android/app/` (Gradle: compileSdk 36, minSdk 29, targetSdk 36,
   arm64-v8a, NDK 29.0.14206865, `-DGAME=`; package `com.nxdroid`). The virtual gamepad runs on the
   device.
   **The launcher** (`LauncherOverlayView.java`, spec `dm/android/mockups/design_spec_argon.md`) is now
   `MainActivity`'s only front screen; the old folder card, with its Portuguese strings, is gone and every
   string is English. What it shows is read, not made up: `GameScanner.java` lists the library folder
   (default `/storage/emulated/0/nxdroid`; the folder itself when it holds `main`, else each subfolder
   that does; a saved folder of the old front end is moved to its parent) and reads each game's
   `control.nacp` (name and publisher of the first language, the deflated title area of newer SDKs too,
   display version, title ID from `SaveDataOwnerId`, else `PresenceGroupId`, else a 16-hex-digit part of
   the folder name), `icon.jpg`, the size, the `.xgs` count and the RomFS; the status bar has the device,
   SoC, refresh rate, controller, temperature, battery and clock. `nativeGetBuiltGame` returns the
   profile this APK was built for (`DM_GAME_ID`, `DM_GAME_NAME`, `DM_GAME_PROGRAM_ID` from
   `game_profile.h`): a game with that ID is "Built into this APK", another ID is refused with the
   `-PdmGame=` command, an unknown ID asks first. Gamepad: D-pad / left stick move, A launches, Y
   rescans, X changes the folder, + settings (HUD, touch controls, typed folder, default folder,
   all-files access), − touch controls, L / R page by four. The launcher fades out on launch; the
   `gameDir` / `autoStart` intent extras still start a folder directly.
   **Checked:** the Java compiled with `javac` 21 against hand-written stubs of the Android classes it
   uses (no Android SDK on the Windows machine; the stubs carry the real signatures as remembered, so a
   wrong assumption about an Android API would pass), `GameScanner`'s NACP and folder reading ran on the
   JVM over synthetic folders (20 checks, compressed title area included), `nativeGetBuiltGame`
   compiled with `-Wall -Wextra -Werror` against the JDK's `jni.h`. **Not checked:** the Gradle build,
   the layout on the S23 Ultra's screen, a controller in the launcher. CI's `android-app` job (§5) now
   compiles the Java and runs the JVM tests of the scanner and the navigation
   (`dm/android/app/src/test`, 11 tests; they passed locally against the same stubs); it builds no APK.
   **Limits that stay:** the APK starts only the game it was built for; quitting a game ends the app's
   process (`nativeStopHost` → SIGTERM → `_exit(0)`, `hle_lifecycle.c`), so there is no return to the
   launcher without moving the host to a separate process; no favourites, recent list or search (the
   spec's tabs); no per-game settings.
9. **[VERIFIED ON S23 ULTRA] Validation with the NDK and the device.** `dmhost` and `libdm.so` link
   with no undefined symbols; on the device: `vk_probe` (§3), `test_device_bionic` (`TLS_SLOT_APP` free,
   `RLIMIT_NICE = 40`), `test_vm_alias` (memfd aliasing, shared write coherence, independent
   `mprotect`), `dmhost` in `/data/local/tmp/`, and the app.
10. **LAST: remove the Apple code** (owner's order: only after everything above).
    **Done early (2026-11-03, the owner's request):** `AGENTS.md` rewritten for Android only and
    approved; Mac / iPhone / IPA instructions out of `docs/` (development, packing, playing, frontends,
    settings, the agent guides; `docs/reference` keeps its mechanism explanations and `nvn_mtl.m`
    citations); `README.md`, `CONTRIBUTING.md` and the issue / PR templates describe the Android port
    (`c6b3257`, `de78a12`, `2767df0`); CI runs on Linux only (§5), the Mac / iOS / Metal jobs and
    `test_ci_toolchain.py` are gone; `test_env_switches` is green (the `DM_GFX_*` rows `jni_android.c`
    sets included) and runs in CI.
    **Remains:** `*.m`, `*.S` only Mach-O uses, `front_*.m`, the iOS tree and IPA packing
    (`scripts/build_ipa_from_nsp.py`, `dm/ios`), `scripts/regress.py` and its baselines,
    `scripts/bug_report.py` (it reads only nxnative's Mac / iPhone logs), the Apple branch of `port.h`,
    the Apple-only parts of `dm/tools` (the rewriter's default target becomes `android`), the 149
    `docs/env_switches.tsv` rows read only by Apple code, `docs/agents/game-patches.md` (generated from the
    profiles' `patches.py` `GENERALIZE` strings, which name the iPhone), comments in the Apple sources and
    `build_ipa_from_nsp.py` that cite removed sections, `dm/games/README.md` and the per-game notes' Mac /
    iPhone wording, the gallery (`docs/images/gallery.tsv`, `dm/tools/docs_gallery.py`: README's folded
    nxnative block with IPA sizes; drop or re-measure on Android) and README's XcodeGen mention. Keep the
    `README.md#how-to-play` anchor (`docs/playing.md`, `docs/agents/06-dev-loop.md` link it).
    `dm/gfx/nvn/nvn_mtl.m` goes last: first retire or re-base the gates that read it (`opcode_map.py`,
    `abi_gaps.py`, the `nvn_mtl.m` line citations in `android.md` and in the tests). Then run
    `dm/tools/tests/test_docs.py` (links, anchors, notes, table rows). The `android_audit` baseline is
    the checklist: it should shrink to 0. `8e050e9` keeps everything removed.
    `fuzz.yml` (nightly) failed on 2026-11-03 and 11-04 with one finding, `zlib.error` in
    `shader_split.py` `monolith_cmp_data` (read from the job's annotations, no sign-in needed); `2880071`
    makes that a declared rejection, and the run of 2026-11-05 is green.
11. **[ALL CLOSED] Independent audit follow-ups** (audit of `f7e190d` / `6dc397b`). Facts still relevant:
    - The guest address space is one memfd mapped `MAP_SHARED` (`dm_guest_as_reserve`); `dm_vm_alias`
      maps an alias at the same file offset (`MAP_SHARED | (to ? MAP_FIXED : 0)`), so NVN virtual pools
      and the write watch work on Android (`dm_memfd_create` is syscall 279 on arm64, 319 on x86_64;
      tested by `test_android_vm_alias.py` and on the device, item 9).
    - Nothing translates on a worker thread (`gfx_async` is hard-wired false; `xbg_submit` translates on
      the submitting thread under `g_sub_mu`), and the origins are captured per submission (§7).
    - `xbg_game_config` is 328 bytes (it gained `instance_api_version`, filled by `vulkan_present.cpp`
      and `smoke.c`); `format_feature_flags2` requires `cfg.instance_api_version >= VK_API_VERSION_1_3`
      and `properties.apiVersion >= VK_API_VERSION_1_3`.
    - `docs/reference/android.md`'s undef_scan and thread-slot entries no longer call the NDK link and
      the Android rewrite pending (items 4, 4a, 9).
12. **The graphics work on the device (3D picture fixed in Run 28, 60 fps in Run 36; the switches and
    the A/B procedure below stay the reference).** Steps 1 to 8 were written while the cause of the 3D
    picture was unknown (it was the sampler descriptor type, Status); their reading of each switch still
    holds, their suspects are closed. The graphics defaults (`jni_android.c`, the Sprint 6 list in
    Status), the present changes (`vulkan_present.cpp`) and the colour-space filter (3b below) are in
    the APK the device runs; which of the defaults matter for the frame rate is not measured one by one.
    To measure:
    1. Build and install the APK (§5; README, *How to play*), run a race, then collect
       `adb logcat -d -s dm > log.txt`.
    2. Read, in the log, the `nativeStartHost: DM_GFX_…` lines (the value in effect for each switch),
       the engine's `NVN texture checks through the dirty tracker=`, `NVN vertex/index cross-frame
       cache=`, `NVN pipeline memo=`, `NVN native BC textures=` and `NVN defer events=` lines, then
       `NVN PERF` for `fps`, `submit_cpu_ms`, `gpu_ms`, `parts_ms_per_frame` (`fence`, `image`, `draw`,
       `snapshot`) and `NVN PERF texdirty tracked/checks/changed`. The `image` scope is the one the
       defaults were meant to remove.
    3. Read `Swapchain: … format= srgb= source_srgb=` once per rebuild: if `source_srgb=1` the present
       fix applies; if it is 0 the 3D colour fault is inside the 3D chain, and the engine's
       `NVN viewfmt image=… view=… nvn=0x38->0x25` and `NVN mutable upgrade …` lines are the next
       evidence (each prints once per distinct pair).
    3b. `vulkan_present.cpp` takes only a surface format in `VK_COLOR_SPACE_SRGB_NONLINEAR_KHR` when the
       device lists one (before: the first-listed format, whatever its colour space; Samsung also lists
       8-bit formats under `DISPLAY_P3_NONLINEAR_EXT`), and logs every
       `Swapchain surface format=<f> colorSpace=<c>` once per rebuild (` (skipped: not sRGB non-linear)`
       on the ones it refuses). Compiled in CI, not measured; a hardening, not a proven cause of the
       picture. Read those lines first: if the chosen format was not the first listed, this was live.
    4. A/B any single switch without a rebuild: the engine reads a marker file from the parent of the
       shader directory (`<game folder>/shaders` → `<game folder>`, and the game folder's parent when
       the game has no `shaders` subdirectory; `MainActivity` passes `<game folder>/shaders`). Write
       `gfx-tex-dirty`, `gfx-vcache`, `gfx-pipe-memo`, `gfx-native-bc`, `gfx-perf-sample`,
       `gfx-defer-events`, `gfx-wb-skip`, `gfx-shader-reuse`, `gfx-upload-prologue`, `gfx-xview-guard`,
       `gfx-ldc-fold`, `gfx-forward-temps`, `gfx-quad-derivatives` or `gfx-warp32` with `0` in it to
       turn that switch off; `gfx-noload` (proven full-overwrite first draws skip the attachment load)
       takes the same `0`. A marker wins over the environment. The full marker list is the `gfx-*`
       names in `xbg_game.cpp` and `vulkan_present.cpp` (`gfx-depth-clip`, `gfx-present-native`,
       `gfx-present-overlap`, `gfx-present-timing` among them). Two take `1` to turn a diagnostic on:
       `gfx-read-preflight` (the engine's default, which the app turns off) and `gfx-alias-invalidate`
       (the 2026-11-03 pool-alias experiments, off by default since 2026-11-04), and `gfx-rt-dedupe`
       (repeated colour slots attached once, 2026-11-04) and `gfx-sampler-match` (sampler compare follows
       the shader, 2026-11-04) and `gfx-cpugpu-refresh` (re-upload a GPU-drawn texture whose guest bytes
       the CPU changed, 2026-11-05) take `1` too.
    5. `scripts/android_gfx_ab.py` does step 4 over `adb`: it writes the marker (`--off` / `--on`),
       reads it back, force-stops and starts `com.nxdroid` (`--no-restart` to skip), and after `--wait`
       seconds (45 by default; start the race by hand meanwhile) saves `--shot <png>` and `--log <txt>`
       (`logcat -d -s dm`); `--clear`, `--clear-all` and `--list` manage the markers; `-s` picks a
       device. `--game-dir` is the folder with `main` (default `/storage/emulated/0/nxdroid/game`,
       `MainActivity`'s default and `prepare_game_android.py`'s `--device-dir`); the script writes the
       marker where the engine reads it, which for a prepared game (no `shaders/` subfolder, the `.xgs`
       next to `main`) is the game folder's **parent**, `/storage/emulated/0/nxdroid/` (the first
       version wrote into the game folder, and that run was not applied). `--list` shows the markers of
       both folders and marks the ones the engine does not read as stale; `--clear-all` clears both.
       Used on the device on 2026-11-03 for the A/B session below.
    6. **The 3D picture (Status) and what to A/B first.** The screenshots (taken before 3b) show wrong
       data in the 3D chain's intermediate targets, not a gamma or swapchain fault (those darken or wash
       out a smooth picture), so 3b is unlikely to fix it. Read, no fault found: `xbg_spirv_temps.cpp`
       (`gfx-forward-temps`) and `xbg_spirv_ldc.cpp` (`gfx-ldc-fold`) keep the module's values;
       `gfx-quad-derivatives` and `gfx-warp32` already default off on Adreno 740-799
       (`xbg_adreno_policy.h`, DEVICE_LOST there) and the profile ships no `gfx-*` marker; `gfx-bright`
       acts only when the host defines `dm_bright_k` above 1.005; `gfx-noload`'s proof
       (`first_draw_covers`, `nvn_cover.h`) requires `w = 1` and `z` in [0, 1] on every vertex, a full
       viewport and scissor, no blend, full colour mask, no discard, single sample. `gfx-noload` stays
       first only because a missed proof leaves undefined tile contents on Adreno, which looks like this
       speckle. Order, one marker at a time with `0`: `gfx-noload`; `gfx-tex-dirty` (a missed guest
       write leaves a stale texture; on Android its write tracking rests on the memfd `dm_vm_alias`,
       item 11); `gfx-wb-skip`, `gfx-upload-prologue`; `gfx-vcache`, `gfx-pipe-memo`, `gfx-native-bc`;
       `gfx-forward-temps`, `gfx-ldc-fold` last. Record here which one changes the picture.
    7. **`gfx-tex-dirty` read (2026-11-03), no fault found.** `get_image` (`xbg_game.cpp`) hashes a
       texture each submission until 4 unchanged checks, then (switch on, pool tracked) write-protects its
       pages and stamps before the 4th hash, and from then on hashes only when `nvn_dirty_since` says a
       page was written after the stamp. `nvn_dirty.c` keeps the BUSY / PROT / NONE order, releases every
       range sharing a faulting page, and treats an untracked range as dirty; host writes that cannot
       fault go through `dm_guest_write_prepare` (`MapMemory`, `UnmapMemory`, `MapPhysicalMemory`). On
       Android the guest block is one `MAP_SHARED` memfd mapping that the host only `mprotect`s, so
       `dm_vm_alias`'s file offset `from - base` is the right page; virtual pools are not registered with
       the tracker, so their textures are hashed every time. Two open points, neither Android-only:
       (a) a write through a virtual-pool alias (`vpool_map`) does not fault on the physical pool's
       protected pages, so a texture of that physical pool would stay stale; whether MK8DX writes texture
       data that way shows in the log's `[nvn] virtual pool … mapped up to` lines; (b) a fault whose write
       bit is read wrong (`dm_uc_fault_write`, the ESR record on bionic) makes `on_fault` refuse it: a
       crash, not a stale texture. Side finding, fixed in code (`432b086`), not measured: unmapped guest
       memory was never returned on Android (`MADV_FREE` fails on the `MAP_SHARED` memfd); `port.h`
       `dm_guest_discard` (Apple: `MADV_FREE`; bionic: `fallocate(FALLOC_FL_PUNCH_HOLE)` on the memfd,
       since the range is `PROT_NONE` by then and `MADV_REMOVE` refuses that) is called by `hle_svc.c`;
       `dm/android/tests/test_vm_alias.c` checks it on Linux in CI (`MADV_FREE` refused, punched pages
       leave the memfd, an alias reads zero). To measure on the device: the app's resident memory after
       the game unmaps (a level change).
    8. **`gfx-wb-skip` and `gfx-upload-prologue` read (2026-11-03), no fault found; two other suspects
       found on the way.** `wb-skip` (`xbg_writeback_policy.h`, `writeback_superseded`) drops an older
       writeback only when a newer pending one covers its whole range, the pool is
       `NVN_MEMORY_POOL_FLAGS_CPU_NO_ACCESS` and no image aliases it; engine reads still get the newest
       result. `upload-prologue` moves a whole upload of an image no command of the submission has used
       into the prologue command buffer, behind an `ALL_COMMANDS` barrier for earlier submissions and with
       its own layout barriers; correct as read. Both move down the A/B order. The two suspects:
       (a) **`invalidate_cpu_range`, changed by the Sprint 6 commit `d33b9df`**: a CPU write that covers
       only part of a GPU-written image is now ignored for that image (before, the image was re-uploaded
       from guest memory, which lost the GPU's contents). Neither is the hardware's behaviour, where the
       write lands in the image's memory; if the game writes part of a texture the GPU rendered (texture
       streaming into a reused render target, a CPU-patched atlas), that write is lost and the texture
       stays stale. The same commit stopped hash-checking depth / stencil images for CPU changes. The log
       says whether it happens: `[YELLOW] Preserving GPU-written image on partial memory pool write`
       (printed the first 5 times). A workaround in AGENTS.md's sense until its cause is known: the root
       fix would apply the written range to the image (or read the image back first). (b) **`DM_GFX_READ_PREFLIGHT=0`**,
       which `jni_android.c` sets (the engine's default is 1): pending GPU writebacks and reports are then
       resolved only for the CPU reads that overlap them (`cpu_access`), not before every draw, dispatch
       and copy. Upstream chose this for Android after the D2R logs on a Redmi K50 Ultra showed no CPU read
       meeting a pending result; MK8DX was never checked. It is turned back on with a marker holding `1`:
       `scripts/android_gfx_ab.py gfx-read-preflight --on`. Updated A/B order: `gfx-noload` off,
       `gfx-read-preflight` on, `gfx-tex-dirty` off, then the rest; and grep the log for the `[YELLOW]` line
       above.

    9. **Device test record (2026-11-03 onwards; append each new run at the end, one bullet per run):**

    - **Build provenance:** the APK previously running on the device was built from an older
      revision, not from the current checkout. Therefore its baseline log is retained only as an
      historical device observation and must not be used to validate `HEAD`. Rebuild and install the
      APK from the current checkout before continuing the A/B session; record the installed commit
      here for every run.
      **Current installation:** APK built and clean-installed on the S23 Ultra from `HEAD=572da85`
      on 2026-11-03; the previous package was removed because its signing key differed.

    - **Baseline (2026-11-03, partial):** no `gfx-*` marker was active. The race log was captured as
      `/tmp/nxdroid-test/00_base.txt`; the screenshot and memory sample were taken after
      `nativeStopHost` and are invalid for visual/memory comparison. The log shows the expected
      Android defaults (`TEX_DIRTY=1`, `VCACHE=1`, `PIPE_MEMO=1`, `NATIVE_BC=1`, `WB_SKIP=1`,
      `UPLOAD_PROLOGUE=1`, `LDC_FOLD=1`, `FORWARD_TEMPS=1`, `READ_PREFLIGHT=0`, `NOLOAD=1`, etc.).
      The swapchain first reported `format=37 srgb=0 source_srgb=0`, then rebuilt with
      `format=43 srgb=1 source_srgb=1`. The log contained the known hybrid-draw `[RED]` line and five
      `[YELLOW] Preserving GPU-written image on partial memory pool write` lines. Performance during
      the captured run ranged from 16.24 to 20.56 FPS, with `gpu_ms` 20.65–25.80 and
      `submit_cpu_ms` 19.02–28.45. No crash or Vulkan device loss was recorded before exit.
      Visual result: not recorded by the agent; the captured PNG is post-exit and unusable.
    - **Baseline follow-up (2026-11-03, `HEAD=572da85`):** valid run with no `gfx-*` marker. The
      screenshot `/tmp/nxdroid-test/00_base_572da85.png` captured the race while the app was alive.
      The 3D scene is still severely corrupted: posterized colours, dense yellow/black/white road
      speckle and black areas/holes; HUD, controls and 2D elements are readable. `source_srgb=1` was
      selected after the initial swapchain rebuild (`format=43`), so this is not explained by the
      non-sRGB initial surface format. The known hybrid-draw `[RED]` line appeared, plus five
      `[YELLOW] Preserving GPU-written image on partial memory pool write` lines. In the race portion,
      performance was roughly 15.90–29.55 FPS, `submit_cpu_ms` 11.95–29.70 and `gpu_ms` 17.22–27.56;
      warm-up/menu samples reached 60 FPS. Memory at capture was about 3.06 GiB PSS, including
      1.91 GiB Graphics. No crash or device loss was recorded.
    - **Clean baseline (2026-11-03, `HEAD=572da85`):** after removing all stale markers from both
      directories, `/tmp/nxdroid-test/00_base_clean.png` and `.txt` were captured with no marker
      files present. The engine reported its normal defaults: `defer events=2`, `vcache=1`,
      `tex-dirty=1`, `native BC=1`, `wb-skip=1`, `pipe-memo=1`, `read-preflight=0` and `noload=1`;
      `source_srgb=1` after swapchain rebuild. The screenshot still shows the corrupted 3D scene
      behind the pause/control overlay, so the fault is reproduced from a genuinely clean state.
      The known hybrid-draw `[RED]` and GPU-written-image `[YELLOW]` lines remain. This is now the
      authoritative baseline for the following single-marker tests.
    - **`gfx-noload=0`, clean run (2026-11-03, `HEAD=572da85`):** only
      `/storage/emulated/0/nxdroid/gfx-noload` was present; the log confirms `noload=0`, while all
      other tested switches retained their defaults. `/tmp/nxdroid-test/01_noload_off_clean.png`
      shows the same posterized/speckled 3D scene with black regions as the clean baseline. Result:
      **no visual change; `gfx-noload` is not the cause**. Race samples were approximately 16.83–26.63
      FPS with `gpu_ms` 13.67–24.55 and `submit_cpu_ms` 17.05–26.40.
    - **`gfx-read-preflight=1`, clean run (2026-11-03, `HEAD=572da85`):** only
      `/storage/emulated/0/nxdroid/gfx-read-preflight` was present; the log confirms
      `CPU reads resolved before each operation=1`. Visual result: **no perceptible improvement**;
      the 3D corruption remains. It caused a substantial performance regression in the captured race:
      `submit_cpu_ms` was roughly 49.81–73.61 ms, FPS 12.48–17.77, with high `sync_wb`/`sync_q`
      counts. Result: **not the visual cause; keep the default `read-preflight=0`**.
    - **`gfx-tex-dirty=0`, clean run (2026-11-03, `HEAD=572da85`):** only
      `/storage/emulated/0/nxdroid/gfx-tex-dirty` was present; the log confirms
      `texture checks through the dirty tracker=0`, with `read-preflight=0` restored. Visual result:
      **no perceptible improvement**; the 3D scene remains corrupted. The known hybrid-draw `[RED]`
      line and five GPU-written-image `[YELLOW]` lines remained. Race performance was broadly in the
      same range, roughly 16–26 FPS in the later captured frames. Result: **not the cause; keep the
      default texture dirty tracking enabled**.
    - **`gfx-wb-skip=0`, clean run (2026-11-03, `HEAD=572da85`):** only
      `/storage/emulated/0/nxdroid/gfx-wb-skip` was present; the log confirms
      `superseded storage writebacks skipped=0`, with `tex-dirty=1` and `read-preflight=0`. Visual
      result: **no perceptible improvement**; the corrupted 3D picture remains. The known hybrid-draw
      `[RED]` and five GPU-written-image `[YELLOW]` lines remained. Race performance was broadly
      unchanged, approximately 15–26 FPS in the later samples. Result: **not the cause; retain
      writeback skipping**.
    - **`gfx-upload-prologue=0`, clean run (2026-11-03, `HEAD=572da85`):** valid log and screenshot
      at `/tmp/nxdroid-test/05_upload_prologue_off_clean_retry.*`; only the upload-prologue marker
      was active, confirmed by `whole uploads ...=0`, while `wb-skip=1`, `tex-dirty=1` and
      `read-preflight=0` remained at defaults. Visual result: **no perceptible improvement**. The
      user perceived slightly better performance; the log shows roughly 19.46–22.06 FPS in the
      later race samples with `submit_cpu_ms` 17.75–21.38 and `gpu_ms` 20.29–22.17, which is not a
      clear improvement over the clean baseline's variable 16–26 FPS range. Result: **no evidence
      this is the 3D cause; performance effect inconclusive**.
    - **`gfx-vcache=0`, clean run (2026-11-03, `HEAD=572da85`):** only
      `/storage/emulated/0/nxdroid/gfx-vcache` was present; the log confirms
      `vertex/index cross-frame cache=0` and all other tested switches remained at defaults. The
      screenshot shows the same severe corruption (black regions, wrong colours and dense road
      speckle), with no visual improvement. Race samples were roughly 17.12–25.67 FPS,
      `submit_cpu_ms` 17.12–25.07 and `gpu_ms` 15.60–22.95. Result: **not the cause**.
    - **`gfx-pipe-memo=0`, clean run (2026-11-03, `HEAD=572da85`):** valid retry at
      `/tmp/nxdroid-test/07_pipe_memo_off_clean_retry.*`; only this marker was active and the log
      confirms `pipeline memo ...=0`. Visual result: **no perceptible improvement**. Race samples
      were roughly 20.40–21.86 FPS, with `submit_cpu_ms` 18.05–19.71 and `gpu_ms` 20.67–23.02.
      Result: **not the cause**.
    - **`gfx-native-bc=0`, clean run (2026-11-03, `HEAD=572da85`):** only
      `/storage/emulated/0/nxdroid/gfx-native-bc` was present; the log confirms `native BC textures=0`
      and the other tested switches remained at defaults. Visual result: **no perceptible improvement**;
      the same corrupted 3D scene remained. Race samples were roughly 22.4–25.6 FPS with
      `submit_cpu_ms` 16.15–18.06 and `gpu_ms` 16.73–20.80. Result: **not the cause**.
    - **`gfx-forward-temps=0`, clean run (2026-11-03, `HEAD=572da85`):** the first capture was
      invalid (black overlay only) and was discarded. The valid retry at
      `/tmp/nxdroid-test/09_forward_temps_off_clean_retry.*` confirms
      `forwarded temporaries=0` with all other tested switches at defaults. Visual result: **no
      improvement**; the same posterized, speckled and black-hole 3D scene remains. Race samples
      were approximately 15.87–16.95 FPS with `submit_cpu_ms` 25.49–28.83 and `gpu_ms` 24.43–25.10.
      Result: **not the cause**.
    - **`gfx-ldc-fold=0`, clean run (2026-11-03, `HEAD=572da85`):** only
      `/storage/emulated/0/nxdroid/gfx-ldc-fold` was present; the log confirms
      `component fold=0` and `forwarded temporaries=1`. The screenshot still shows the same severe
      3D corruption, with no visual improvement. Race samples were approximately 19.51–24.70 FPS,
      `submit_cpu_ms` 17.22–23.14 and `gpu_ms` 16.58–20.52. Result: **not the cause**.
    - **A/B conclusion (2026-11-03, `HEAD=572da85`):** the planned single-switch order is complete:
      `gfx-noload`, `gfx-read-preflight`, `gfx-tex-dirty`, `gfx-wb-skip`, `gfx-upload-prologue`,
      `gfx-vcache`, `gfx-pipe-memo`, `gfx-native-bc`, `gfx-forward-temps` and `gfx-ldc-fold` all
      reproduced the same bad 3D picture. The recurring evidence is the hybrid-draw `[RED]` line and
      the five `[YELLOW] Preserving GPU-written image on partial memory pool write` lines. The next
      investigation should focus on that partial CPU-write/image-preservation path or the known
      hybrid-draw limitation, rather than another performance switch.
    - **Partial-write overlap diagnostic (2026-11-03, instrumented APK):** the valid run is
      `/tmp/nxdroid-test/12_partial_diag_overlap.png` with log
      `/tmp/nxdroid-test/12_partial_diag_overlap.txt`; the log was checked before recording it.
      The new fields show the main warning as a write at `+0x50000` overlapping the first
      `0x50000` bytes of a `0x870000` image allocation, not an interior subresource offset:
      serial `22183`, NVN format `0x3d` (`A2B10G10R10_UNORM_PACK32`), target `1`, flags `0x8`,
      extent `1920x1080x1`, one level and one layer, `uploaded=0`, attachment provenance
      (`site=3340`). The same write also overlaps serial `5904`, a `128x128x1`, 8-level,
      6-layer format `0x29` image with `uploaded=1`. This confirms multiple aliased images
      share the pool range; the preservation branch is handling an aliasing event, not merely
      a simple partial update to one texture. No behavior change was made by the diagnostic.
      All `gfx-*` markers were clear after capture. Next step: trace the pool alias allocation
      and the command that writes `+0x50000` before changing the preservation semantics.
    - **Alias writer identified (2026-11-03):** the valid follow-up capture is
      `/tmp/nxdroid-test/13_alias_trace.png` with log `/tmp/nxdroid-test/13_alias_trace.txt`.
      After filtering the stale lines from the persistent logcat, the new warning reports
      `op=31`, which is `OP_COPY_B2T` (`CopyBufferToTexture`), writing `+0x50000`. It overlaps
      the first `0x50000` bytes of the `1920x1080` format `0x3d` render target and of a second
      aliased `256x256` format `0x29` image. Both have pool offset `0`; the render target has
      `uploaded=0`, while the smaller image has `uploaded=1`. This moves the investigation from
      generic CPU writes to the ordering and invalidation around buffer-to-texture copies.
    - **Invalidation source narrowed (2026-11-03):** the valid capture is
      `/tmp/nxdroid-test/14_invalidation_source.png` with log
      `/tmp/nxdroid-test/14_invalidation_source.txt`. The new `reason` field was `unknown`
      for the fresh warning, so none of the pending/slot/descriptor writeback paths ran.
      With `op=31` and the color format `0x3d`, this is the normal color upload branch of
      `CopyBufferToTexture`; it invalidates the primary image range while the overlap walker
      also sees the aliased GPU-written render target. The next APK labels that call
      `copy-upload-color` to confirm it directly.
    - **Copy-upload source confirmed (2026-11-03):** the valid capture is
      `/tmp/nxdroid-test/15_copy_upload_color.png` with log
      `/tmp/nxdroid-test/15_copy_upload_color.txt`. The fresh lines report
      `reason=copy-upload-color`, `op=31`, and the same `+0x50000` write. Besides the
      `1920x1080` format `0x3d` target, this run found a second aliased `960x540` format
      `0x25` target, both `uploaded=0`. The pool range is therefore reused by render targets
      of different resolutions during `CopyBufferToTexture`; the next experiment should
      isolate whether preserving those GPU-written aliases is the source of the bad picture.
    - **Alias invalidation experiment (2026-11-03):** the valid capture is
      `/tmp/nxdroid-test/16_alias_invalidate_experiment.png` with log
      `/tmp/nxdroid-test/16_alias_invalidate_experiment.txt`. The log confirms five
      `Experimental invalidation of GPU-written alias during color upload` events and no new
      preservation warning for that upload. The screenshot is still visibly corrupted (black
      regions, severe speckling and displaced/incorrect geometry), so invalidating the aliases
      alone is **not a fix**. Keep this change as diagnostic-only; the persistent hybrid-draw
      `[RED]` remains present and the next investigation should connect the invalidated
      render-target contents to the hybrid draw/read path.
    - **Pool reuse pattern identified (2026-11-03):** the valid capture is
      `/tmp/nxdroid-test/17_upload_trace.png` with log
      `/tmp/nxdroid-test/17_upload_trace.txt`. The fresh upload records show the active
      `CopyBufferToTexture` destinations are small dynamic textures (serial `150550`, format
      `0x1`, `512x608`, `0x50000` bytes; and serial `150557`, format `0xd`, `256x304`,
      `0x30000` bytes). Their pool base is simultaneously indexed by stale GPU-written images
      of `1920x1080`, `960x540` and `1280x720`. This is legitimate pool storage reuse, but the
      image index keeps old texture objects alive and the partial-write branch preserves them.
      The root-cause candidate is stale alias registration/lifetime, not a hybrid draw. The
      eventual fix should retire or remove old image aliases when the pool range is reused by
      a new texture, rather than preserving them during the upload.
    - **Reuse trace confirmed (2026-11-03):** the valid capture is
      `/tmp/nxdroid-test/18_pool_reuse.png` with log `/tmp/nxdroid-test/18_pool_reuse.txt`.
      The creation trace shows the pool being reused repeatedly by smaller mip-sized textures:
      `128x128 -> 32x32 -> 16x16 -> 8x8 -> 4x4 -> 2x2`, while the old images remain
      `oldGpu=1 oldUploaded=1`. This confirms that the address-ordered `image_index` is retaining
      stale GPU image objects across legitimate pool reuse. The next code change should fix
      image-index lifetime/retirement at new texture registration; the upload-time experiment
      is insufficient and remains diagnostic only.
    - **Pool-reuse invalidation experiment (2026-11-03):** the valid capture is
      `/tmp/nxdroid-test/19_pool_reuse_fix.png` with log
      `/tmp/nxdroid-test/19_pool_reuse_fix.txt`. The new-registration path invalidated old
      images before pool reuse, and the app continued running, but the screenshot still has
      severe black regions, speckling and displaced geometry. Stale alias state is real but is
      not the sole rendering fault; keep this change experimental, not as the final fix.
    - **Hybrid diagnostic ruled out (2026-11-03):** source inspection of `dm/gfx/vulkan/nvn_vk.c`
      confirms the recurring `[RED] Vulkan replay: hybrid draws are not collected...` line is
      emitted by `mtl_hybrid_stats()`, whose Vulkan implementation always returns zero because
      hybrid pipelines are a Metal-only diagnostic. It does not report an executed draw reading
      zero and cannot explain the picture. Remove it from the rendering-cause shortlist. The
      next investigation should follow the actual texture upload/alias contents used by the
      affected draws.
    - The first attempted `gfx-noload` A/B was invalid: `scripts/android_gfx_ab.py` wrote
      `/sdcard/nxdroid/game/gfx-noload`, but this build passes `/storage/emulated/0/nxdroid/game` as
      the shader directory and the engine's current marker lookup takes its parent,
      `/storage/emulated/0/nxdroid/`. The log confirmed `NVN proven full-overwrite first draws skip the
      color load=1`; discard `/tmp/nxdroid-test/01_noload_off.png` and its log as an unapplied test.
      The script/docs path assumption needs correction before further A/B runs.
    - Next run: `gfx-noload` off, one marker only, written in `/storage/emulated/0/nxdroid/`. The
      result will be compared against this screenshot and baseline log.
    - The corrected-path attempt was also invalid for visual comparison: the automated restart left
      the Argon launcher on screen, so `/tmp/nxdroid-test/01_noload_off_correct.png` captured the
      launcher rather than the game. The marker path was correct, but the launcher\'s `START GAME`
      button must be pressed after each automated restart before entering the race.
    - **`gfx-noload=0` valid run (2026-11-03, `HEAD=572da85`):** marker was applied in the correct
      parent directory and the log confirms `NVN proven full-overwrite first draws skip the color
      load=0`. The screenshot `/tmp/nxdroid-test/01_noload_off_valid.png` shows the same corrupted
      3D rendering as baseline, with no qualitative improvement. The known hybrid-draw `[RED]` line
      and five GPU-written-image `[YELLOW]` lines remained. Race samples ranged roughly 16.18–25.58
      FPS in the captured portion, with later frames at 18.60–21.20 FPS, `gpu_ms` 17.00–26.43 and
      `submit_cpu_ms` 16.00–31.02. Result: **no change; noload is not the cause**.
    - **Test contamination found (2026-11-03):** the parent directory used by the current engine had
      stale markers from earlier runs (`gfx-depth-clip`, `gfx-legacy-waitall`, `gfx-mutable-images`,
      `gfx-nan-minmax`, `gfx-native-bc`, `gfx-no-warm`, `gfx-pipe-skip`, `gfx-read-preflight`,
      `gfx-swap-format` and `gfx-swap-srgb`). The baseline and `gfx-noload=0` run above therefore are
      not clean single-variable experiments, although their logs still prove the requested marker
      value. All markers in both `/storage/emulated/0/nxdroid/` and its `game/` directory were removed
      afterward. Future `--clear-all` calls must use `--no-restart`, then the test marker must be the
      only file present; the clean baseline must be repeated.
    - (The A/B runs of 2026-11-03 are recorded above, out of order: the clean baseline and the ten
      single-switch runs, then the alias tracing, runs 12 to 19; runs 20 onwards follow in order. Each
      bullet: run number, installed commit, the marker, the visual result, the log lines of "How a device
      run is made" step 5 (Status), and whether the run crashed, hung or stuttered.)
    - **Run 20, `gfx-depth-clip=0` (2026-11-04):** valid capture
      `/tmp/nxdroid-test/20_depth_clip_off.png` and log
      `/tmp/nxdroid-test/20_depth_clip_off.txt`. The marker was initially applied in the wrong
      parent by an explicit `--game-dir`; that stale marker was removed, then the correct
      `/storage/emulated/0/nxdroid/gfx-depth-clip=0` was tested. The log confirms
      `NVN depth clip marker off=1`, `VK_EXT_depth_clip_control=1`, and GL near=-w active via
      `negativeOneToOne`. The picture remained severely corrupted; approximately 27.59 FPS,
      `gpu_ms=12.62`, `submit_cpu_ms=14.69`. Result: **not the fix**.
    - **Preparation for run 22 (2026-11-04):** the correct update is
      `/home/cado/Downloads/MK8/Mario Kart 8 Deluxe [0100152000022800][v1507328].nsp`, not the
      0100152000023001 DLC. `nx_extract` merged it with the base XCI and reported title
      `0100152000022000`, display version `4.0.1`, update title `0100152000022000`. The Android
      preparation found `29,651` shaders, generated `29,642` `.xgs` bundles, and left 9 shaders
      without a bundle; the missing list is under the temporary preparation work directory.
      The normal large tar deployment failed with `tar: bad header`, so the validated output was
      staged with direct `adb push`; the active device folder has `xgs_build.txt` with
      `depth_rewrite=0` and `53,262` `.xgs` files. The previous device folder is retained as
      `/storage/emulated/0/nxdroid/game_previous_depth_test` until this run is accepted.
    - **Run 22, no marker and no shader depth rewrite (2026-11-04):** valid capture
      `/tmp/nxdroid-test/22_norewrite.png` and log `/tmp/nxdroid-test/22_norewrite.txt`. The log
      confirms `NVN depth clip marker off=0`, GL near=-w active through
      `VK_EXT_depth_clip_control`, and shader loads with `rewrite=0`. The screenshot still has
      severe black regions, speckling and displaced geometry; it is **not a fix**. Fresh race
      samples ranged from 14.34 to 25.70 FPS (`gpu_ms` 14.79–21.51,
      `submit_cpu_ms` 18.45–41.09). The run also shows the new `[RED] one texture at two colour
      slots` diagnostic and the existing partial-write warnings; the hybrid statistic remains
      only a Vulkan/Metal diagnostic.
    - **Run 21b, `gfx-rt-dedupe=1` (2026-11-04):** valid capture
      `/tmp/nxdroid-test/21b_rt_dedupe.png` and log `/tmp/nxdroid-test/21b_rt_dedupe.txt`.
      The log confirms `NVN repeated colour slots attached once=1`; the duplicate is the
      observed slot pair `3,4`, serial `60186`, format `0x3d`, mip/layer `0/0`, with masks
      `0xf,0`. No non-zero-write dropped-slot warning appeared. The screenshot remains severely
      corrupted, with black regions, speckling and displaced geometry, so matching the Metal
      attachment behavior is **not the fix**. The run reached roughly 19.14--24.51 FPS
      (`gpu_ms` 14.25--21.78, `submit_cpu_ms` 20.98--27.28) after startup, with no crash or
      hang. The marker was cleared after capture.
    - **Run 23, `gfx-alias-invalidate=1` (2026-11-04):** valid capture
      `/tmp/nxdroid-test/23_alias_invalidate.png` and log
      `/tmp/nxdroid-test/23_alias_invalidate.txt`. The log confirms
      `NVN pool-alias invalidation experiment=1`; the same duplicate-colour diagnostic remains
      (`slots=3,4`, masks `0xf,0`). Compared with run 22, the stadium geometry is more complete
      and less displaced, but severe texture speckling, black regions and incorrect shading remain:
      **partial improvement, not fixed**. Fresh samples ranged from 17.12 to 25.68 FPS
      (`gpu_ms` 13.40--22.42, `submit_cpu_ms` 18.56--30.39), with one 6.41 FPS sample during
      the heavy transition and no crash or hang. The marker was cleared after capture.
    - **Run 24, alias invalidation default-on build (2026-11-04):** APK built from the working
      tree and installed after replacing the differently signed package. Capture and log:
      `/tmp/nxdroid-test/24_alias_default.png` and `.txt`. The collector inadvertently wrote
      `gfx-alias-invalidate=0` while trying to remove the marker, so this run did **not** test
      the default-on behavior. The log confirms the marker was read as `0`; disregard the earlier
      conclusion that it confirmed five default-on alias invalidations. The image remains severely
      corrupted. No crash or hang was found.
    - **Run 25, `gfx-alias-invalidate=0` (2026-11-04):** capture and log
      `/tmp/nxdroid-test/25_alias_disabled.png` and `.txt`. The marker was set to `0`; no
      default-on invalidation message appeared. The screenshot remains severely corrupted and
      looks broadly comparable to run 24; the single captures are at different race positions,
      so they do not establish a visual improvement from the default-on change. Samples ranged
      roughly 18.22--29.44 FPS (`gpu_ms` 12.33--21.41, `submit_cpu_ms` 14.15--28.52), not a
      controlled performance comparison. No crash or hang was found. The `0` marker is still
      set on the device and should be cleared before the next test.
    - **Runtime render-target capture limitation (2026-11-04):** `DM_CTL` is started by
      `hle_hid.c` only when `DM_CTL` names a file. Its `texdump` command calls
      `dm_gfx_texdump_next` in `nvn_vk.c`; the Vulkan implementation delegates to
      `xbg_game_capture_frame`, which rejects capture after any submission/draw/dispatch. Thus
      `texdump` requested during an Android race logs `[RED]` and captures nothing. Vulkan's
      `passdump` is also explicitly unimplemented. The current engine capture must be armed before
      `nnMain`, so it cannot target a chosen race frame through the existing runtime control. Next
      diagnostic step: add a reviewed runtime capture request that safely arms the next-present
      frame, or another Android-accessible trigger; do not repeat a `DM_CTL texdump`/`passdump`
      request expecting output until such support exists.
    - **Run 26, clean baseline (2026-11-05, `HEAD=f3a8513`):** valid capture
      `/tmp/nxdroid-test/26_base.png` and log `/tmp/nxdroid-test/26_base.txt` with all markers
      cleared (`scripts/android_gfx_ab.py --clear-all --no-restart`). Fresh install of debug APK
      (`app-debug.apk`, assembled from commit `f3a8513`). The new CPU-write check found two occurrences:
      `[RED] NVN CPU wrote the storage of a GPU-drawn texture after the GPU (the replay keeps the GPU's pixels): serial=196427 fmt=0x3d 1920x1080 layers=1 levels=1 target=1 decoded=0`
      and `serial=197650 fmt=0x25 960x540 layers=1 levels=1 target=1 decoded=0`. The questions left
      open by runs 20 to 25 were answered: `stencil-mode texture read as depth` (none), `sampler compare
      mode does not match` (none), and `nvnDeviceGetInteger item 0x26 before the Vulkan replay is
      initialized` (none; confirms device-backed `NVN_DEVICE_INFO_MAX_VIEWPORTS` operates cleanly).
      The duplicate colour slot diagnostic remained (`slots=3,4`, format `0x3d`, masks `0xf,0`).
      Across 18 race samples, FPS was 7.15--49.80 (mean 23.08), `gpu_ms` 7.71--20.65 (mean 16.76),
      and `submit_cpu_ms` 8.73--114.15 (mean 28.38). Visual result: **3D corruption remains**
      (speckle, black areas, posterized lighting); center crop has 16.5% black pixels. No crash or hang.
    - **Run 27, `gfx-cpugpu-refresh=1` (2026-11-05, `HEAD=f3a8513`):** valid capture
      `/tmp/nxdroid-test/27_cpugpu_refresh.png` and log `/tmp/nxdroid-test/27_cpugpu_refresh.txt`.
      The log confirms `NVN GPU-drawn textures re-uploaded after a CPU write=1 (marker gfx-cpugpu-refresh)`.
      Re-upload was triggered once for the 960x540 target: `[RED] NVN CPU wrote the storage of a
      GPU-drawn texture after the GPU (the replay keeps the GPU's pixels; gfx-cpugpu-refresh re-uploads
      it): serial=316271 fmt=0x25 960x540 layers=1 levels=1 target=1 decoded=0`. Across 26 race
      samples, FPS was 17.48--40.21 (mean 27.22), `gpu_ms` 8.38--22.41 (mean 15.02), and `submit_cpu_ms`
      11.39--28.40 (mean 18.32). Visual result: **no visual improvement; 3D scene remains severely
      corrupted**, with black regions increasing from 16.5% to 25.9% in the center crop due to
      blindly re-uploading guest memory over GPU-rendered data. Result: **`gfx-cpugpu-refresh` is not
      the fix**. All markers cleared after capture (`scripts/android_gfx_ab.py gfx-cpugpu-refresh --clear --no-restart`).
    - **Run 28, RenderDoc 1.47 frame capture and root cause discovery (2026-11-06):** GPU captures
      taken on the Galaxy S23 Ultra Adreno 740 during a live Mario Kart Stadium race (captures `frame2550`,
      `frame2925`, `frame3370`, with frame 2550 saved locally at `/tmp/nxdroid-test/com.nxdroid_2026.11.06_19.53_frame2550.rdc`).
      Pass-by-pass inspection traced the defect to `Colour Pass #6` (lighting/material pass, draw 2425):
      RenderDoc flagged all bound textures (`fp_t_tcb_14`, `fp_t_tcb_8`, `fp_t_tcb_10`) as
      `Image & Sampler | No Resource` in red. Disassembly showed SPIR-V declared `OpTypeSampledImage`
      (type 1, `COMBINED_IMAGE_SAMPLER`), but `.xgs` bundle headers held `type = 2` (`SAMPLED_IMAGE`).
      Root cause: `scripts/prepare_game_android.py` `_inspect_image_type` had a flow control bug that
      forced `desc_type = 2` across all 193,457 texture bindings in the game, causing the engine to bind
      `ii.sampler = VK_NULL_HANDLE`. Adreno 740 hardware sampling without a sampler returned zeroes,
      rendering all textured geometry (road, kart) pitch black. Fixed in `prepare_game_android.py` and
      all 27,869 `.xgs` bundles batch-updated locally in 11.95s. Next: deploy updated `.xgs` shaders to device.
    - **Run 29, race-start crash resolution, visual verification & 60 FPS CPU optimization (2026-11-07):**
      (1) Initial race-start abort: with `type = 1` `.xgs` bundles, clicking OK aborted on `NVN sampler linear filtering unsupported ...`.
      Cause: `sampler_slow` hit unsupported linear filtering and PCF on Adreno 740 for `VK_FORMAT_D32_SFLOAT` (`0x34`),
      `VK_FORMAT_R32_SFLOAT` (`0x2d`), and `VK_FORMAT_R32G32B32A32_SFLOAT` (`0x2e`), and `null_texture` allocated 1x1 dummy depth
      using `0x34`. In addition, persistent pipeline cache files (`/sdcard/nxdroid/vk-pipeline-*.bin`) held descriptor type 2 layouts.
      Resolved in `xbg_game.cpp`: `null_texture` uses NVN `0x32` (`D16` / `X8_D24_UNORM_PACK32`), `sampler_slow` clamps unsupported
      linear/aniso filtering to `VK_FILTER_NEAREST` with a one-time log instead of aborting, and `ImgKey::kind` includes shadow flags
      (`b.flags & 0xffffff00u`).
      (2) Device race verification: with the updated build and cleared caches, clicking OK starts the race cleanly. 3D race rendering
      was confirmed **visually clean and complete** on Galaxy S23 Ultra (Adreno 740), with road, kart, lighting, and textures rendering correctly.
      (3) Frame pacing telemetry (`draws=1095.9/frame`): `gpu_ms = 5.97–8.40 ms` (down from 17–28 ms; GPU has >2x headroom for 60 FPS).
      Framerate was bounded to `24.86–38.44 FPS` (`submit_cpu_ms = 14.95–21.89 ms`) by three CPU bottlenecks:
      - `legacy_waitall`: `legacy_wait_total = 10.23–12.40 ms/frame` (`submits=2.00 waits=2.00`) due to synchronous `vkWaitForFences`.
      - `OP_BARRIER` pass fragmentation: `pass_ends op28 = 72.4/frame`, `passes = 103.1/frame`, `barriers op28 = 249.8/frame` because `OP_BARRIER` unconditionally closed open passes.
      - Descriptor memo drops: `xmemo_drops = 581`, `retire = 3.31 ms/frame` due to false `memo_epoch` and `memo_check_gen` bumps on first-time registrations.
      (4) 60 FPS optimization pack applied in `xbg_game.cpp`:
      - Enabled asynchronous fence retirement (`legacy_waitall = false`, `completion_wait_default = true`) under `#if defined(__OHOS__) || defined(__ANDROID__)`.
      - `OP_BARRIER` now tracks `open_pass.shader_writes` and only splits open render passes when true (matching `nvn_mtl.m:10041`), emitting `full_barrier` outside passes only when `write_seq > barrier_seq`.
      - Sampler registration (`sampler_par_equal`) and texture/image creation only bump `memo_epoch` and `memo_check_gen` when an *existing* registered resource is mutated.
      - Warm pipeline deserialization fix in `warm::build()`: `xbg_graphics_pipeline_key()` serialized 6 words for viewport state (including `negativeOneToOne`), but `warm::build()` read only 5 words, shifting all subsequent words by 4 bytes and failing 100% of pipeline warm-ups (`warm_built=0 warm_failed=974`), causing mid-race `[longframe]` compiles (`pipe_compile=480.7ms`) and false `gfx-pipe-skip` entries. Reading `bool neg11 = r.u() != 0;` and attaching `VkPipelineViewportDepthClipControlCreateInfoEXT` restored precompilation for all 974 pipelines.
      (5) On-screen real-time FPS HUD: `MainActivity.java` queries `NativeBridge.nativeGetPerformanceStats()` (`fps`, `frame_ms`, `gpu_ms`) via a 500 ms handler and renders `mFpsOverlay`, togglable via the HUD FPS chip or persistent preference.
    - **Run 31 telemetry, warm pipeline verification & 60 FPS pacing bottlenecks (2026-11-07):**
      (1) Warm pipeline precompilation verified: live race telemetry (`/tmp/mk8dx_race_perf_run31.log`) confirmed the `warm::build()` `negativeOneToOne` fix succeeded 100%, with `warm_built=1058 warm_failed=0` and zero mid-race pipeline compiles (`created=0 create_ms=0.0`).
      (2) Remaining race bottlenecks: despite `gpu_ms = 6.00–10.28 ms` (>2x headroom for 60 FPS), framerate remained at 28–39 FPS (`25.4–37.8 ms/frame`) due to two CPU serialization and allocation bottlenecks:
      - CPU/GPU serialization in `mtl_wait_acq`: `nvnWindowAcquireTexture` sets `s->fenced = 2; s->fence = mtl_last_fence()`, and `nvnSyncWait` calls `mtl_wait_acq`. In `dm/gfx/vulkan/nvn_vk.c:78`, `mtl_wait_acq` forwarded to `mtl_wait` (`xbg_legacy_wait`), synchronously blocking the guest CPU thread on previous frame fences for 5.1–9.2 ms every frame (`legacy_wait = 5.09–9.24 ms/frame`, `1.00/frame`).
      - Transient render-target churn: MK8DX finalizes and re-initializes ~4–5 transient render targets per frame at identical guest pool addresses (`t->mem`) and descriptors (`t->d`). `xbg_legacy_tex_release_now` immediately retired the `Image`, destroying `VkFramebuffer`, `VkImageView`, and `VkImage` (`retire = 2.01–3.54 ms/frame`, `fb_creates = 4.0–5.0/frame`, `memo_bump[2] = 10,829`) and forcing recreation in `get_image_slow` and `create_pass`.
      (3) Root-cause resolutions:
      - In `dm/gfx/vulkan/nvn_vk.c`, `mtl_wait_acq` now returns `1` immediately without waiting. Present semaphores and FIFO single-queue execution already synchronize presentation and execution; CPU command recording for Frame N+1 can now run concurrently with Frame N GPU execution.
      - In `dm/gfx/vulkan/engine/xbg_game.cpp`, released pool-backed render-target `Image` objects are retained in a bounded `released_images` standby list and re-adopted in `get_image_slow` when re-initialized at the same `t->mem` with identical descriptor, eliminating per-frame framebuffer recreation and descriptor memo invalidation.
    - **Run 32 telemetry confirms steady ~56 FPS; Run 33 crash analysis and stable configuration (2026-11-07):**
      (1) Telemetry validation: live race telemetry (`/tmp/mk8dx_race_perf_run32.log`) proved the `released_images` cache eliminated per-frame render target churn: `retire` dropped from `3.09–3.54 ms/frame` down to `0.05–0.08 ms/frame`, `fb_creates` dropped from `5.00/frame` to `0.00/frame`, `memo_bump[2]` was 0 during steady racing, and `submit_cpu_ms` dropped from `19.76 ms` to `9.13–11.98 ms`, reaching steady ~56 FPS.
      (2) Race-start dip diagnosis: analysis of Run 32 log (line 9941) showed the race-start drop to 41–45 FPS was primarily a one-time 401.8 ms compile hitch from compiling 46 new race-start pipelines (`new pipelines 16 + shader libraries 17, 303.0 ms in all; pipelines_new=46`). These pipelines are now persisted into `/sdcard/nxdroid/vk-pipeline-cache.bin` (9.11 MB) and `/sdcard/nxdroid/vk-pipeline-list.bin` (1.56 MB) and precompiled at startup via `warm::build()`.
      (3) Run 33 crash and reversal of unsafe changes: an experimental test in Run 33 combining `mtl_wait` returning `1`, `upload_prologue = true`, and caching non-render-target textures in `released_images` caused a race-start `SIGSEGV` inside `vulkan.adreno.so` (`offset 0x22c24c`, dereferencing `NULL + 0xb4` in `vkCmdDrawIndexed`). Root causes: bypassing `xbg_legacy_wait` in `mtl_wait` prevented submission flushes and slot fence retirement, while `upload_prologue` and indiscriminate texture retention desynchronized the open render pass state.
      (4) Stable configuration restored: `mtl_wait_acq` returns `1` immediately; `mtl_wait` calls `xbg_legacy_wait(fence, timeout)`; `upload_prologue` remains `false` by default; and `released_images` strictly retains only render-target / GPU-written textures (`t->mem && (!i->second->fb_keys.empty() || i->second->gpu_written)`).
    - **Run 34 telemetry and safe CPU/GPU pipelining in xbg_legacy_wait (2026-11-07):**
      (1) Steady race performance: live telemetry (`/tmp/run34_pid24283.log`) confirmed steady 3D racing ran smoothly at `54.0–57.1 FPS` (`submit_cpu_ms = 7.86–9.10 ms`, `gpu_ms = 6.3–6.5 ms`, `legacy_wait = 0.00 ms`).
      (2) Start-grid serialization diagnosis: during the dense 12-kart start grid (`1,226–1,287 draws/frame`, `79–82 passes`), CPU recording rose to `14.77–15.48 ms` and GPU execution rose to `9.7–10.9 ms`. Because `nvnSyncWait` calls `mtl_wait` on `nvnQueueFenceSync`, `xbg_legacy_wait` blocked in `vkWaitForFences` for `9.13–12.12 ms/frame`, serializing CPU work and GPU completion into `24.6–34.6 ms/frame` (`28.9–35.4 FPS`).
      (3) Safe pipelining resolution: inside `xbg_legacy_wait` in `dm/gfx/vulkan/engine/xbg_game.cpp`, after `retire_done()` retires completed slots and after `submit_slots(false)` flushes any in-progress recording slot to the Vulkan queue, `if (fence <= submitted) return 1;` returns immediately on Android. Because all CPU buffer writes are snapshotted into host-visible stream arenas during `xbg_submit_now` and `recording_slot()` enforces a 2-slot ring backpressure, Frame N+1 CPU recording executes in parallel with Frame N GPU execution, eliminating `legacy_wait_total` without driver crashes.
    - **Run 35 crash and Run 36 locked 60 FPS milestone (2026-11-07):**
      (1) Run 35 unconstrained pipelining crash: an initial `if (fence <= submitted) return 1;` was tested, but when MK8DX issued mid-frame syncs during active recording (`cur.recording && cur.ops`), `submit_slots(false)` forced a mid-frame submission, flipped slots, and broke active render pass state, causing a `SIGSEGV` in `vulkan.adreno.so + 0x22c24c` (`addr = 0xb4`, null subpass state in `vkCmdDrawIndexed`).
      (2) Run 36 safe 1-frame boundary pipelining: in `dm/gfx/vulkan/engine/xbg_game.cpp`:
      `if(t && t->pending && t->covers>=fence && !cur.pending && !(cur.recording && cur.ops)) return 1;`.
      Preconditions: (a) target fence is in-flight on GPU (`t && t->pending && t->covers >= fence`); (b) alternate recording slot is free (`!cur.pending`); (c) at a clean frame boundary (`!(cur.recording && cur.ops)`), preventing any mid-frame submit from splitting render passes. Mid-frame syncs and ring-full conditions fall through to standard synchronous waiting.
      (3) Run 36 measured results (Galaxy S23 Ultra, Adreno 740):
      - **FPS:** 60.01–60.22 FPS locked at race start (dense 12-kart start grid, 1,247 draws/frame).
      - **CPU Submit Time:** 11.90–12.56 ms.
      - **GPU Execution Time:** 9.44–10.08 ms.
      - **Legacy Wait Stall:** 0.00 ms.
      - **Stability:** zero crashes, pipeline caches 100% active.
      - **Persistent keystore:** `~/.android-dm/debug.keystore` mounted to `/android-user` preventing `INSTALL_FAILED_UPDATE_INCOMPATIBLE`.
    - **Run 37, compute dispatch crash after the race start (2026-11-08, fixed in `501c56e`):** with the Run 36
      build, the race crashed after it started with `SIGSEGV` in `vulkan.adreno.so + 0x22c24c` (`addr=0xb4`), this
      time in `vkCmdDispatch`. Reading of the driver (comment in `dm/gfx/vulkan/engine/xbg_adreno_policy.h`): the
      command buffer keeps graphics dirty bits at `[cmd, #0x78]`; a dispatch recorded after draws in the same
      command buffer makes its preparation hook (`0x22aa60`) call `GetSubpassState` (`0x22c6a0`), which returns
      NULL once the pass has ended, and the driver reads `[NULL, #0xb4]`. Fix: `Slot::has_draws` (set by draws and
      masked clears) and, when `xbg_adreno_compute_needs_clean_cmd` (Qualcomm vendor ID `0x5143`), `dispatch()`
      submits the recording slot before a dispatch into a slot with draws; `recording_slot()` also clears an
      `open_pass` left on a reused command buffer. Same offset and fault address as Runs 33 and 35 (Status, Open
      item 2). Log and capture paths are not recorded. Reference: `docs/reference/android.md`, *Adreno 7xx
      crashes in vkCmdDispatch recorded after draws in the same command buffer*.
    - **Run 38, audio crackling (2026-11-08, fixed in `501c56e`):** the log counted 1,400 short callbacks of 2,000
      (16.8 s zero-padded in 44 s) with bursts up to 1,600 frames against a ~960-frame renderer queue. Fix in
      `dm/android/apple_stubs.c`: `AAUDIO_PERFORMANCE_MODE_LOW_LATENCY`, `setFramesPerDataCallback(rate / 200)`
      (240 frames at 48 kHz, one `audren` block), buffer capacity of 8 callbacks, buffer size two bursts (at
      least two callbacks); `NBUF` 4 → 8 in `dm/host/hle_audren.c`. Measured: 0 underruns in 6,000+ callbacks,
      0.0 ms zero-padded, 60 fps racing. Reference: `docs/reference/audio.md`, *AAudio's default buffer duration
      and performance mode on Android*.
    - **Run 39, abort on the course transition (2026-11-08, fixed in `501c56e`):** going on to the second Grand
      Prix course aborted with `FATAL: NVN sampler invalid LOD range/bias result=-4 … bias=-32`. NVN takes a LOD
      bias down to -32; Vulkan requires `|mipLodBias| <= maxSamplerLodBias` (VUID 01079; 15–16 on the Adreno
      740). Fix: `xbg_sampler_from_nvn` (`xbg_sampler.cpp`) clamps the bias to `±max_lod_bias` and the
      anisotropy to `max_anisotropy`. The record of that day calls it resolved; a run through the second course
      after the fix (log, screenshot) is not recorded. Reference:
      `docs/reference/rendering.md`, *Sampler LOD bias and anisotropy beyond Vulkan limits*.

## 9. How to work in this tree

- `AGENTS.md` governs: English everywhere; `[RED] ` prefixes lines that mean something is wrong; a
  game-specific rule only when no general rule works; fix causes, not symptoms; keep game-derived files
  out of the repository. Agents do not commit or push (the owner does) and ask before installing.
- Specialist agents (`.opencode/agents/android-{dev,qa,shaders,upstream}.md`) coordinate
  implementation and quality control.
- On the Linux machine podman is rootless and docker's daemon is down. The local image
  `localhost/dm-android-tools:1` is derived from `dm/android/docker/Dockerfile` by
  `/tmp/opencode/Dockerfile.tools`, which only adds `make`, `git` and `file`.
- `adb` is not in the image: on the Linux machine it was `/tmp/opencode/platform-tools/adb` (Sprints 1–6)
  and `/opt/platform-tools/adb` in the 2026-11-03 session; `scripts/android_gfx_ab.py --adb <path>` takes it. If the phone refuses the
  authorization, revoke USB debugging authorizations and re-accept on the device.
- `xbg_game_initialize` needs neither guest memory nor a shader bundle, so the smoke harness can
  initialize and shut down the engine on any desktop Vulkan driver. A missing shader is fatal through
  an `xbg_fatalf` in `xbg_game.cpp` (search for it).

## 10. Traps, so they are found once

- **An edit to a vendored file without its manifest row turns CI red.** It happened with
  `xbg_game.cpp` in `89dc2dc` and `85031c7`; the commands to run before the commit are in the box at the
  top of this file. `opcode_map.txt` cites line numbers of `xbg_game.cpp`, so it goes stale with any
  edit there that moves lines, and its gate fails right after the provenance gate.
- **`android_vendor.py --write` recomputes the sha256 of existing rows.** Needed for adapted files,
  but "edit a vendored file, run `--write`" hides the edit. The right shape is two hashes per row
  (upstream's and ours) and two checks; not implemented.
- **`dm/gfx/vulkan/engine/SOURCE.json` has stale hashes for five files** (`xbg_game.cpp`,
  `xbg_game.h`, `xbg_game_internal.h`, `xbg_texture.c`, `xbg_texture.h`). Our copies match the pin;
  upstream's own manifest does not. Recorded, not fixed: it is upstream's file.
- **The fork's `OP_COPY_IMAGE_STRIDE` (61) and our `OP_COPY_STRIDE{image=1}` collide in meaning.**
  One case is dead because our writer never emits the fork's op; that "never" is an assumption to
  guard, not to remember.
- **`viewport_n` is a pipeline input** (`PipeMemoKey.viewports`, through `draw_viewports()`): the
  pipeline declares the recorded array for a viewport-selecting shader. Older notes say every pipeline
  declares one viewport; that is no longer true.
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
- **`exec_pages = ok` was measured in the `shell` SELinux domain.** The packaged app (`untrusted_app`)
  has since run on the device (§8 item 9), so executable mappings work there; keep the caveat only for
  a different Android build.
- **The desktop smoke build proves compilation and initialization, not a frame.** `presents=0` is
  correct there: there is no guest and no shader bundle.
- **Stopping the app while the warm-up threads compile pipelines can poison the pipeline blacklist**
  (`gfx-pipe-skip`; it blacklisted 89 pipelines once in Sprint 6): if many pipelines are suddenly skipped, remove the cache files on
  the device. Remove them too after the bundles' descriptor types change: in Run 29 the cached pipelines
  still carried the `SAMPLED_IMAGE` layouts of the bundles before the sampler fix.

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
| What each `DM_GFX_*` switch and `gfx-*` marker does | `docs/env_switches.tsv`, the comments at each switch in `dm/gfx/vulkan/engine/xbg_game.cpp` |
| How the Metal replay does each of the above | `dm/gfx/nvn/nvn_mtl.m` |
| The command-record ABI both readers share | `dm/gfx/nvn/nvn_obj.h` |
