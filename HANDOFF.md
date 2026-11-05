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

## Status at this cut (2026-11-03)

The port is built with NDK r29, packaged as an APK (`com.nxdroid`) and runs on a physical **Samsung
Galaxy S23 Ultra** (Snapdragon 8 Gen 2, Adreno 740, 12 GB RAM, Android 16 / SDK 36, as the probe
measured). The one title run so far is **Mario Kart 8 Deluxe** (`0100152000022000`, update 4.0.1
`[v1507328]`): it boots, plays its menus and videos and races.

- **Native AArch64 execution:** Horizon SVCs and SDK services answered by `dm/host`; NSO modules
  rewritten by `dm/tools/patch_nso.py --target=android`.
- **H.264 video:** `AMediaCodec` in `dm/android/apple_stubs.c`, decoded into an NV12 `CVPixelBufferRef`;
  menu video previews play in real time.
- **Audio:** AAudio output in `dm/android/apple_stubs.c` (48 kHz stereo PCM). AAC through
  `AudioConverter` is still a stub (an AAC track is silent, one `[RED]` line).
- **Front end:** `MainActivity` picks the game folder (default `/storage/emulated/0/nxdroid/game`) and
  starts the game; an on-screen multitouch gamepad (`VirtualControllerOverlayView.java`: left stick,
  D-pad, triggers, face buttons, show/hide toggle) and physical controllers drive it. The Argon launcher
  views (`LauncherOverlayView.java`, `GameScanner.java`) are in the tree but nothing uses them yet.
- **Deployment:** `scripts/prepare_game_android.py` does base + update RomFS extraction, the rewrite,
  shader translation into `.xgs` bundles, the Mii database from emulator user data, and the `adb` push.
- **2D is right, 3D is not.** The HUD, text and video have correct colours. Two screenshots of Mario
  Kart Stadium taken on 2026-11-03 (the owner's, not in the tree) show the 3D scene posterized, with a
  flat blue sky, hard white edges on buildings, large black holes, colour fringes on letters and dense
  yellow / black / white speckle on the road. Cause open; suspects and the A/B order are in §8 item 12.
  The Sprint 6 notes called the 3D colour fault "resolved"; the fixes listed below (item 2) are real and
  stay in the tree, but they did not make the race scene right.
- `dm/games/0100152000022000/README.md` does not record the Android run yet (`AGENTS.md`: a game counts
  as running on Android only when its note says so).

### Resume from the 2026-11-03 graphics investigation

The diagnostic edits in `dm/gfx/vulkan/engine/xbg_game.cpp` and the test record below were committed in
`89dc2dc` (the pool-reuse invalidation and the `copy-upload-color` branch are experiments, not fixes).
That commit left the vendor row of `xbg_game.cpp` and `opcode_map.txt` stale, so CI's `android-gates`
failed on it; both were brought up to date afterwards. **Any edit to `xbg_game.cpp` needs both:** the
row's LF sha256 in `dm/tools/android_vendor.tsv` (by hand, §10) and `CC=gcc python3
dm/gfx/vk/engine_smoke/opcode_map.py` (it cites the file's line numbers). The latest APK was built from
`89dc2dc`'s tree and installed on the S23 Ultra; the captures and logs are in `/tmp/nxdroid-test/` on
the Linux machine (latest: `19_pool_reuse_fix.png` / `.txt`).

**Next device test, first (2026-11-04): the depth convention is converted twice.**
`scripts/prepare_game_android.py` `_rewrite_depth` writes GL's clip-space z (near = -w) as `[0, w]` into
every vertex shader it packs. The engine, when the game keeps NVN's GL depth mode, also chains
`VK_EXT_depth_clip_control` with `negativeOneToOne` (`xbg_game.cpp` `draw()`, `!game_depth_zero`;
`nvn_vk.c` logs `NVN depth mode near=-w (GL) kept by the game: active via VK_EXT_depth_clip_control`),
which converts the already converted z again: depth becomes `z_ndc / 4 + 0.75` instead of
`z_ndc / 2 + 0.5`. Visibility order barely changes, but depth precision halves (z-fighting: the road
speckle) and every pass that rebuilds a position from depth (deferred lighting, shadows, fog, ambient
occlusion) reads a wrong position (posterized light, black holes). Sprint 6's fix e) only avoids the
double conversion when the marker `gfx-depth-clip` holds `0`; that marker was among the stale ones
removed before the clean baseline, which would explain why the race scene looked "resolved" during
Sprint 6 and broken in every clean run. Not measured. The test: `python3 scripts/android_gfx_ab.py
gfx-depth-clip --off` (the script now finds the engine's marker folder, §8 item 12 step 5), one race,
screenshot and log; and grep the earlier logs for `depth mode` and `depth clip`. If it fixes the picture,
the root fix is to convert once, by the game's runtime depth mode: drop `_rewrite_depth` from the
prepare script (it cannot know the runtime mode; a game that sets near = 0 gets a wrong conversion
from it) and keep the engine's `negativeOneToOne`, which follows `nvnDeviceSetDepthMode`; then prepare
the game again with `--rebuild-shaders`. A device without `VK_EXT_depth_clip_control` would need the
conversion done by the engine at shader load, keyed by the mode, not at packing.

**Prepared in code (2026-11-04), not measured; CI compiles it.**
- `scripts/prepare_game_android.py` no longer applies `_rewrite_depth` by default; `--depth-rewrite`
  turns it back on, only for a device without `VK_EXT_depth_clip_control` (and then with the marker
  `gfx-depth-clip` = `0`). A stamp `xgs_build.txt` beside the bundles records the setting, and bundles
  built with another one (or before the stamp, all of them with the rewrite) are rebuilt on the next
  run without `--rebuild-shaders`. The rewrite also only ever touched stage 0, which would be wrong for
  a game whose last stage before rasterization is a tessellation or geometry shader.
- The two pool-aliasing experiments of `89dc2dc` are off by default, behind the marker
  `gfx-alias-invalidate` = `1` (`xbg_game.cpp`); their log lines stay on. Reason: the textures seen
  over the same storage are live (NVN's `nvnTextureFinalize` reaches the engine as
  `xbg_legacy_tex_release`, which erases and retires the image, so an image still indexed has not been
  finalized): most likely transient render targets sharing a pool range within a frame. Marking them
  for a re-upload from guest memory can fill one with bytes the GPU never wrote, and the runs with the
  experiments on (16 and 19) are the only ones that also showed displaced geometry.

What is established:

- The ten planned single-switch A/B runs (2026-11-03) did not improve the picture; the record is in
  §8 item 12, step 9.
- The recurring partial-write warning comes from `OP_COPY_B2T` (`CopyBufferToTexture`), in the
  `copy-upload-color` path: small dynamic textures (`512x608`, `256x304`) are written into pool ranges
  that GPU-written render targets (`1920x1080`, `960x540`, `1280x720`) also cover. Those images are live
  (finalizing a texture removes its image from the engine), so this is most likely storage the game
  shares between transient targets within a frame, not a stale object left behind (inferred from the
  code, not traced on the device).
- The `[RED] hybrid draws are not collected` line is not a rendering failure: it is the Vulkan stub of
  a Metal-only statistic in `dm/gfx/vulkan/nvn_vk.c` (always zero).
- **Depth-convention test completed (2026-11-04):** `gfx-depth-clip=0` was active in the correct
  marker directory and the fresh log confirms `NVN depth clip marker off=1`,
  `NVN depth clip control ...=1`, and `NVN depth mode near=-w (GL) kept by the game: active via
  VK_EXT_depth_clip_control`. Capture: `/tmp/nxdroid-test/20_depth_clip_off.png`; log:
  `/tmp/nxdroid-test/20_depth_clip_off.txt`. The screenshot remains severely corrupted, with black
  regions, speckle and displaced geometry; this switch alone is **not the fix**. The run measured
  approximately `27.59 fps`, `gpu_ms=12.62`, `submit_cpu_ms=14.69`. Do not repeat this exact test.
- Fixed on 2026-11-04, not run yet: `scripts/prepare_game_android.py`'s RomFS shader scan read only
  files under folders and extensions written for Mario Kart 8 Deluxe (`/Course/`, `/Kart/`, `.bfres`, …),
  a game-specific rule in a general script that never found a shader elsewhere; it now scans every
  RomFS file, as `shader_split.py`'s own main does (the profile's `shader_groups` only name groups).

### Device session of 2026-11-04 (done): step by step

**Done on 2026-11-04: runs 20 to 25 are recorded in §8 item 12 step 9. The next session is the GPU frame
capture further down ("Next device session (2026-11-05)"); keep these steps as the reference for
building, installing, markers and logs.**

Everything here runs on the Linux machine that has `adb`, podman and the phone (S23 Ultra, USB
debugging on). Commands run from the repository root. `ADB` below is the `adb` that machine used on
2026-11-03, `/opt/platform-tools/adb` (§9 names `/tmp/opencode/platform-tools/adb`, an older path):
pass it to the script with `--adb "$ADB"` when `adb` is not on `PATH`. Name every capture with the
next free number in `/tmp/nxdroid-test/` (the 2026-11-03 session used `00` to `19`; start at `20`).

1. **Get the code and check it.** `git pull`, then `git log -1 --oneline`. The checkout must contain the
   2026-11-04 changes: `grep -c alias_invalidate dm/gfx/vulkan/engine/xbg_game.cpp` prints a number
   above 0, and `grep -c DEPTH_REWRITE scripts/prepare_game_android.py` and
   `grep -c "one texture at two colour slots" dm/gfx/vulkan/engine/xbg_game.cpp` too. CI must be green for that
   commit (both jobs of `tests.yml`).
2. **Build the APK** (the game profile is mandatory):
   ```sh
   podman run --rm --userns=keep-id -v "$PWD:/workspace" -w /workspace localhost/dm-android-tools:1 \
       gradle -p dm/android :app:assembleDebug -PdmGame=0100152000022000
   ```
   It writes `dm/android/app/build/outputs/apk/debug/app-debug.apk`.
3. **Install it:** `"$ADB" install -r dm/android/app/build/outputs/apk/debug/app-debug.apk`. If it fails
   with a signature conflict (it did on 2026-11-03), `"$ADB" uninstall com.nxdroid` first. Uninstalling
   deletes the app's private data, the saves in `/data/user/0/com.nxdroid/files/save` among them, but
   not `/storage/emulated/0/nxdroid/`: check afterwards that `"$ADB" shell ls /storage/emulated/0/nxdroid/game`
   still lists `main`, `romfs.img` and the `.xgs` bundles. Record the installed commit in the test record.
4. **Prepare the session:**
   ```sh
   "$ADB" logcat -G 16M
   python3 scripts/android_gfx_ab.py --adb "$ADB" --clear-all --no-restart
   python3 scripts/android_gfx_ab.py --adb "$ADB" --list      # "the engine reads markers from /storage/emulated/0/nxdroid", nothing else
   ```
   Do **not** pass `--game-dir /storage/emulated/0/nxdroid` any more: the 2026-11-03 session needed it
   with the first version of the script; the script now takes the game folder (default
   `/storage/emulated/0/nxdroid/game`) and finds the marker folder itself, and the parent of
   `/storage/emulated/0/nxdroid` would be the wrong folder.
5. **Run 20, the new APK's baseline, no marker** (the pool-alias experiments are now off, so this can
   differ from the 2026-11-03 baseline):
   ```sh
   "$ADB" logcat -c
   "$ADB" shell am force-stop com.nxdroid && "$ADB" shell am start -n com.nxdroid/.MainActivity
   ```
   In the app press **START GAME** (the automated restart stops at the launcher), start a race on
   **Mario Kart Stadium**, keep racing about a minute, then:
   ```sh
   "$ADB" exec-out screencap -p > /tmp/nxdroid-test/20_base_0411.png
   "$ADB" logcat -d -s dm > /tmp/nxdroid-test/20_base_0411.txt
   ```
6. **Run 21, the depth test** (the bundles on the phone still carry the rewrite, so this marker leaves
   one conversion, the shaders'):
   ```sh
   python3 scripts/android_gfx_ab.py --adb "$ADB" gfx-depth-clip --off --wait 120 \
       --shot /tmp/nxdroid-test/21_depthclip_off.png --log /tmp/nxdroid-test/21_depthclip_off.txt
   ```
   Within the 120 s: press START GAME and race. Then
   `python3 scripts/android_gfx_ab.py --adb "$ADB" gfx-depth-clip --clear --no-restart`.
7. **Check the logs of runs 20 and 21 before anything else** (`grep` each file):
   - `NVN depth clip control (VK_EXT_depth_clip_control)=1`: the device has the extension.
   - `NVN depth mode near=-w (GL) kept by the game: active via VK_EXT_depth_clip_control`: MK8DX keeps
     the GL mode, so the engine converts. Its absence means the game sets near = 0: then the engine
     never converted, and the shaders' rewrite alone was the wrong one; go to step 8 regardless.
   - `NVN depth clip marker off=0` in run 20 and `=1` in run 21: the marker was read.
   - `NVN pool-alias invalidation experiment=0` in both.
   - `[RED] NVN one texture at two colour slots`, `[RED] NVN stencil-mode texture read as depth` and
     `[RED] NVN sampler compare mode does not match the shader` (diagnostics added on 2026-11-04, the
     first five of each): each present makes it suspect 1, 2 or 3 of "If the depth test does not fix it"
     below. Copy them into the test record. `NVN repeated colour slots attached once=0` and
     `NVN sampler depth compare follows the shader=0` must be there too (the markers of steps 7b and 7c,
     off).
7b. **Run 21b, only if run 20's log has `[RED] NVN one texture at two colour slots`:** the fix is in the
   APK behind a marker. With no other marker set:
   ```sh
   python3 scripts/android_gfx_ab.py --adb "$ADB" gfx-rt-dedupe --on --wait 120        --shot /tmp/nxdroid-test/21b_rt_dedupe.png --log /tmp/nxdroid-test/21b_rt_dedupe.txt
   python3 scripts/android_gfx_ab.py --adb "$ADB" gfx-rt-dedupe --clear --no-restart
   ```
   Its log must say `NVN repeated colour slots attached once=1`; a `[RED] NVN colour slot … repeats slot …
   with write mask …` line means a dropped slot really had writes. If 21b fixes the picture, try it once
   more together with the depth marker (`gfx-depth-clip --off` and `gfx-rt-dedupe --on`, both set) to
   see whether both faults were present.
7c. **Run 21c, only if run 20's log has `[RED] NVN sampler compare mode does not match the shader`:** the
   same way with `gfx-sampler-match --on` (files `21c_sampler_match.*`), then `--clear --no-restart`. Its
   log must say `NVN sampler depth compare follows the shader=1`; a
   `[RED] NVN sampler compare enabled … LEQUAL assumed` line means a compare the game's sampler did not
   enable got an assumed function (note it: if shadows look inverted, LEQUAL was the wrong guess).
   - `[YELLOW] Preserving GPU-written image`, every `[RED]`, `NVN PERF` (fps, `gpu_ms`,
     `submit_cpu_ms`), `Swapchain`.
8. **Run 22, the packing without the rewrite** (do it when run 21 looks right, and also when the game
   turned out to set near = 0 in step 7): prepare the game again with the current script and push it.
   ```sh
   python3 scripts/prepare_game_android.py <base game .nsp or .xci> --title-id 0100152000022000 \
       [-u <update .nsp>] [-k <prod.keys>] --push
   ```
   Same input, keys and tools as the last preparation (it needs `hactool`, `prod.keys`, `capstone` in
   its Python and `dotnet` or podman for `dmsh_xlate`). Since 2026-11-04 it scans **every** RomFS file
   for shaders (before: only Mario Kart's folders and a few extensions), so the scan takes longer and may
   find shaders the earlier packs missed: record its `Total unique shaders identified: N` and compare it
   with the earlier preparation's count if that log still exists. Its log must say `Shader bundles were built with
   other settings than 'depth_rewrite=0': rebuilding them`, and `"$ADB" shell cat
   /storage/emulated/0/nxdroid/game/xgs_build.txt` must print `depth_rewrite=0`. Read the end of its
   shader section too: since 2026-11-04 it counts what it loses instead of dropping it silently
   (`[RED] N of M shaders have no bundle: … not translated …, … failed to pack; the list is
   <work>/xlate_work/missing_shaders.tsv`, `[RED] the shader translator exited with …`, and a `WARNING`
   for RomFS asset files it could not scan). Copy those lines into the test record; any shader without a
   bundle is a candidate cause of a wrong draw (before, the translator's exit status was ignored and a
   failed translation or packing left no trace). Then, with no marker
   (`--list` empty), race again as in step 5 and save `22_norewrite.png` / `.txt`. Run 22 must look
   like run 21.
9. **Optional, only if runs 20 to 22 all stay wrong:** run 23 with `gfx-alias-invalidate --on` (the
   2026-11-03 experiments) to check whether they change anything; clear it afterwards.
10. **Bring back** every `.png` and `.txt` of runs 20 to 23, one line per run saying how the 3D scene
    looked (same as the 2026-11-03 baseline, better, correct, worse) and anything else seen (crash,
    hang, stutter; after a crash also `"$ADB" logcat -d -b crash > /tmp/nxdroid-test/<n>_crash.txt`),
    and append the results to the test record in §8 item 12 step 9, one bullet per run, with the
    installed commit, the marker, the visual result and the log lines of step 7.
11. **What the results mean:** run 21 or 22 right → the double conversion was the cause; keep the new
    packing default, drop the marker, record it in `docs/reference/android.md` (Symptom, Cause, Fix,
    Found on) and in the MK8DX note, and run `python3 dm/tools/docs_symptoms.py`. Runs 21 and 22 wrong
    → it was not the cause (keep the new default anyway: one conversion is right in every mode); go on
    with "If the depth test does not fix it" below.

### Next device session (2026-11-05): capture one race frame with a GPU debugger

The 2026-11-04 session (runs 20 to 25, §8 item 12 step 9) ruled out the double depth conversion, the
re-pack without the rewrite and the repeated colour slots; only the pool-alias invalidation changed the
picture (geometry more complete, speckle and black areas left). Guessing switch by switch has run its
course. The engine cannot capture a chosen race frame itself (`DM_CTL texdump` / `passdump` do nothing
on the Vulkan replay, the record above), so the next step is a GPU frame capture with **RenderDoc**
(preferred) or **Android GPU Inspector (AGI)**: either records one whole frame and shows every render
pass, draw, render target and texture, so the first pass whose output is already wrong names the
faulty stage. The menu names below are from memory of those tools and may differ slightly by version.

**First, two short runs that need no new tool (2026-11-05):** the build of this session's commit
logs, by default, `[RED] NVN CPU wrote the storage of a GPU-drawn texture after the GPU` (the first 20).
The reason, read in `xbg_game.cpp` `get_image_slow`: once an image is marked GPU-drawn (`gpu_written`),
the engine never looks at its guest bytes again (the CPU-coherent pool hashing and the dirty tracker
skip it), and the replay never writes a render target back to guest memory, so a change of those bytes
is the game's CPU (or a host copy) writing them after the GPU; on the Switch the texture shows those
bytes, here it keeps the old drawing. The alias path of `get_image_slow` makes it reachable: a new
texture object over the storage of a drawn one, with the same description, shares its image and its
`gpu_written`. This fits the only change that helped (run 23, the pool-alias invalidation) and pool
storage MK8DX shares between transient render targets and textures. Run A: no marker, a race, log and
screenshot (`26_base.*`); count the `[RED] NVN CPU wrote …` lines and note their formats and sizes.
Run B, if run A has any: `android_gfx_ab.py --adb "$ADB" gfx-cpugpu-refresh --on --wait 120 --shot
/tmp/nxdroid-test/27_cpugpu_refresh.png --log /tmp/nxdroid-test/27_cpugpu_refresh.txt`, then
`--clear --no-restart`; its log must say `NVN GPU-drawn textures re-uploaded after a CPU write=1`. The
marker re-uploads such an image from guest memory: right when the CPU rewrote the whole texture, wrong
where it rewrote only part of one the GPU drew. If run B fixes or improves the picture, the capture is
still worth doing to see which textures they are, but the cause is found. Record both runs in §8 item
12 step 9.

**Before:** installing either tool on the Linux machine needs the owner's go-ahead (`AGENTS.md`: ask
before downloading or installing). The APK must be the debug build (`assembleDebug`, debuggable), from
current `main`, installed as in the 2026-11-04 session's steps 2 and 3. Clear every marker first
(`android_gfx_ab.py --adb "$ADB" --clear-all --no-restart`, then `--list` empty), so the frame shows the
default build. A capture makes that one frame very slow; that is expected.

**RenderDoc (preferred):**

1. Download the Linux build from renderdoc.org (a `.tar.gz`), unpack it, run `bin/qrenderdoc`.
2. In the replay-context selector at the bottom left of the window (it starts as "Local"), pick the
   phone (found through `adb`); the first time, RenderDoc installs its own server app on the phone.
3. **Launch Application** tab: executable `com.nxdroid`, activity `com.nxdroid/.MainActivity`; **Launch**.
   The app starts with RenderDoc's layer.
4. On the phone press **START GAME**, start a race on **Mario Kart Stadium**, and while the broken 3D
   picture is on screen press **Trigger Capture** in the connected-app tab. Take two or three captures
   at different moments of the race.
5. Open a capture (double-click). Replay runs on the phone and shows on the PC.
   - **Event Browser:** the frame's passes and draws, in order.
   - **Texture Viewer:** for the selected event, the render targets it writes (Outputs) and the textures
     it reads (Inputs).
   - **Pipeline State:** formats, depth / stencil state and samplers of the selected draw.

**AGI (alternative):**

1. Download the Linux release from `github.com/google/agi`, run `agi` (it uses the system `adb`).
2. **Capture a new trace**: the phone, application `com.nxdroid`, type **Vulkan** (frame capture);
   **Start and duration**: manual start, 1 frame.
3. **Run**: AGI starts the app; press START GAME, start the race, then **Start** in AGI's window.
4. Open the `.gfxtrace`: the command list on the left, and for each render pass its attachments,
   textures and pipeline state.

**If the tool cannot inject its layer** (the app starts without it, or no capture appears), point the
app at the GPU debug layers by hand, and undo it afterwards:

```sh
"$ADB" shell settings put global enable_gpu_debug_layers 1
"$ADB" shell settings put global gpu_debug_app com.nxdroid
# afterwards
"$ADB" shell settings delete global enable_gpu_debug_layers
"$ADB" shell settings delete global gpu_debug_app
```

**What to find in the frame:** the **first** render pass whose output is already wrong, walking the
frame in order. Mario Kart 8 Deluxe renders roughly: shadow maps, the G-buffer (colour / albedo, normals,
depth, often several targets in one pass; the 1920x1080 format `0x3d` target at slots 3 and 4 found on
2026-11-04 is one of them), lighting, transparent objects and effects, then post-processing (bloom,
tonemap, the 32x32x32 colour-correction LUT) and the 2D layout. If the G-buffer targets are right and
the lit image is wrong, the fault is in lighting (or the shadow maps it reads); if the G-buffer is
already speckled, the fault is in the geometry pass (its inputs: textures, vertex data, uniform data).
For the first wrong pass, note: its event number, its render targets' formats and sizes, the shaders'
keys if the tool shows the SPIR-V module names, and which input texture or buffer already looks wrong.

**Bring back:** for each capture, PNGs of the main render targets at the end of each stage (Texture
Viewer, **Save Texture**), at least: a shadow map, every G-buffer target, the lit image before post,
and the final image; the event number and name of the first wrong pass with a screenshot of its Pipeline
State; and the capture file itself (`.rdc` or `.gfxtrace`) kept on the Linux machine (it can be hundreds of
MB; opening it on another machine needs the same tool there). Record the session in §8 item 12 step 9 as
before (run number, installed commit, tool and version, what the first wrong pass is).

### If the depth test does not fix it: the next suspects (2026-11-04, read, not measured)

A review of how NVN formats reach Vulkan, against `nvn_mtl.m` (the replay that ran these games right),
found **no wrong format** on Mario Kart 8 Deluxe's path: `0x1` R8, `0xd` RG8, `0x25` RGBA8, `0x29`
RGBA16F, `0x3d` RGB10A2 (`A2B10G10R10_UNORM_PACK32`, red in the low bits), `0x3f` R11G11B10F, the depth
formats (D24 kept as D24, closer to the Switch than Metal's D32F) and the BC table all match; views take
another format only when the game asks, at the same size; clears and blend states map one to one. It
found Metal-only fixes the Vulkan engine does not have, ranked:

1. **One texture at two colour slots** (verified by reading). `nvn_mtl.m` attaches the same level /
   layer only once (`rt_dup_slot`, ~3159): Breath of the Wild's G-buffer passes attach a buffer twice
   with the second slot's write mask 0, and on Apple's tiling GPU the copy stored later (loaded, never
   written) overwrote the drawn one and blacked out the whole 3D picture. Mario Kart 8 Deluxe runs on the
   same Nintendo engine family (sead / agl), and Adreno also renders in tiles. The Vulkan engine attaches
   both (`xbg_game.cpp`, the attachment loop after `targets[]` is filled). The log line
   `[RED] NVN one texture at two colour slots` says whether the game does it (with both slots' write
   masks). Fix if it does: attach a repeated level / layer once and leave the later slot unused
   (`VK_ATTACHMENT_UNUSED`), as Metal does, and say in red when the dropped slot has a non-zero mask.
   **Written on 2026-11-04, behind the marker `gfx-rt-dedupe` = `1`** (off by default until a device run
   shows the case: step 7b of the next session). The render pass with the unused slot is another render
   pass, so its pipelines never mix with the undeduplicated ones.
2. **Stencil-mode textures read as depth** (verified by reading). The writer records
   `nvnTextureViewSetDepthStencilMode` / `nvnTextureBuilderSetDepthStencilMode` (`view_t.dsmode`,
   `tex_t.stencil`), and `nvn_mtl.m` binds a stencil-only view (~4137; reading depth instead striped
   Pokémon Legends: Z-A's lit picture); nothing in `dm/gfx/vulkan` reads it, so a deferred lighting pass
   that tests stencil bits tests bits of the depth value instead (speckle, holes, hard edges). The log
   line `[RED] NVN stencil-mode texture read as depth` says whether the game does it. A fix is more than
   an aspect flag: a stencil view returns integers, and the translated shader declares a float texture
   (Metal hands the raw bits through; the Vulkan equivalent needs a check of what the SPIR-V declares).
3. **Shadow samplers not matched to the shader** (inferred). `compareEnable` comes only from the NVN
   sampler (`xbg_sampler.cpp`), never checked against the binding's shadow flag (`b.flags` bit 14);
   Vulkan leaves a compare sampler on a plain fetch (and the reverse) undefined, where Metal ignored the
   compare function. Could give hard black / white edges. Logged since 2026-11-04:
   `[RED] NVN sampler compare mode does not match the shader` (that bit 14 marks a depth-compare sampler
   is read from the null-texture code, which picks a depth format for it; not confirmed elsewhere).
   **Written on 2026-11-04, behind the marker `gfx-sampler-match` = `1`** (off by default): where the two
   disagree, the sampler's compare follows the shader; a compare the NVN sampler did not enable takes its
   compare function if usable, else `LEQUAL` (an assumption, said in red). Step 7c tests it.
4. Lower likelihood here (none of these formats is in Mario Kart 8 Deluxe's race log). **Written on
   2026-11-05, default on, not measured on the device** (`xbg_game.cpp`, `nvn_no_alpha`, `packed16_pick`
   and the swizzle in `Image::view`, checked by a harness of the extracted code on the Windows machine):
   - Alpha 1: every format `nvn_fmt_mtl.c` marks without alpha (`0x37`, `0x3a`, `0x41`, `0x45`,
     `0x6d`-`0x78`, `0x96`, `0x99`, `0x9b`; it was `0x37` and `0x6d` only), composed with the game's
     swizzle as `nvn_mtl.m` `tex_by_id` does (~4127): a channel the swizzle points at alpha reads 1, and a
     swizzled alpha (`(1 1 1 R)`) keeps what the game asked; before, alpha was forced to 1 over it.
   - 16-bit packed formats by bit: `0x3c` RGB565 → `B5G6R5_UNORM_PACK16` (red in the low bits, as Echoes
     of Wisdom's RGB565 hearts showed on Metal), `0x96` BGR5 → `A1R5G5B5` (it was R5G6B5, the wrong field
     widths), `0x98` A1BGR5 → `R5G5B5A1`. Where the device lacks `B5G6R5` or `R5G5B5A1` (sampled, colour
     attachment, transfer), the old format is kept with one `[RED] NVN format %#x: the device has no
     Vulkan format …` line. `0x3a` RGB5 / `0x3b` RGB5A1 need `A1B5G5R5_PACK16` (`VK_KHR_maintenance5`, not
     enabled): they take `A1R5G5B5` (`0x3a` was R5G6B5) and say `[RED] NVN format RGB5 / RGB5A1` once,
     red and blue still swapped. Mostly 2D: a wrong colour in a menu or a font is where it would show.
   - Still open: min / max sampler reduction dropped by `xbg_sampler_from_nvn` (an SDK this old probably
     does not use it).

The two `[RED]` lines are in the APK of this session's commit, so run 20's log already answers 1 and 2.

### Device fixes and measurements (Sprint 6)

1. **Vertical banding ("venetian blinds"), resolved.** 16 vertical columns of alternating brightness.
   Cause: `ANativeWindow_setBuffersGeometry(active, 1920, 1080)` made Qualcomm's display processor
   decimate non-integer columns (the panel is portrait; the window is 1544x720 landscape). Fix in
   `dm/android/vulkan_present.cpp`: `present_native = false` (the swapchain stays at the window's size;
   a `gfx-present-native` marker other than `0` turns the old path back on) and the present blit uses
   `VK_FILTER_LINEAR` when the format supports it.
2. **3D colour fixes (in the tree; the 3D picture is still wrong, above):**
   a) **3D LUT view bounds:** `xbg_game.cpp` `Image::view()` passed `layerCount = depth` (32) for MK8DX's
      32x32x32 colour-correction LUT (`agl::env::ColorCorrection`), violating
      `VUID-VkImageViewCreateInfo-imageViewType-04973`; a 3D view now takes `base_layer = 0`,
      `layer_cnt = 1`.
   b) **Render targets reset by CPU writes to their pool:** a small CPU write into a pool that also holds
      render targets ran `invalidate_cpu_range()`, which cleared `gpu_written` / `uploaded` and made a
      later `get_image(..., true)` upload stale guest memory over the target. `gpu_written` is now kept
      on partial CPU writes.
   c) **Poisoned pipeline blacklist (`gfx-pipe-skip`):** stopping the app while warm-up threads compiled
      left in-flight markers, and `pipeguard::load()` blacklisted 89 pipelines. The poisoned cache files
      were removed on the device (an operational fix: stopping mid-compile can do it again).
   d) **Texture view swizzle:** `registered_texture_equal` / `register_texture_record` compare
      `view->set_swizzle` and `view->swz`, so differently swizzled views no longer alias.
   e) **Depth clip control:** the `gfx-depth-clip` marker check keeps `VK_EXT_depth_clip_control`
      (`negativeOneToOne`) from applying the depth rewrite twice: `prepare_game_android.py` already bakes
      `z = 0.5 * z + 0.5 * w` into every vertex shader.
   Measured after them, on the **track preview cards** (not the race scene): 256 levels per channel and
   over 21,000 distinct colours.
3. **Frame rate.** The Sprint 6 notes report, on the S23 Ultra, `fps = 53.67`, `gpu_ms = 7.96`,
   `submit_cpu_ms = 6.66`, `present_cpu_ms = 0.48`, against 12–19 fps with `gpu_ms` 19.5 and
   `submit_cpu_ms` 58 before (`docs/reference/android.md`, *Every `DM_GFX_*` switch the engine documents
   for Android was unset*). The changes credited:
   a) at least three swapchain images (`ci.minImageCount = max(3, minImageCount)`, `vulkan_present.cpp`;
      four on OHOS), against SurfaceFlinger fence stalls;
   b) the graphics defaults that `nativeStartHost()` (`dm/android/jni_android.c`) sets before the host
      starts, each logged with its value in effect, an existing environment value or a `gfx-*` marker
      winning: `TEX_DIRTY=1`, `VCACHE=1`, `PIPE_MEMO=1`, `ASYNC_POOL_RESET=1`, `PERF_SAMPLE=0`,
      `NATIVE_BC=1`, `DEFER_EVENTS=2`, `WB_SKIP=1`, `SHADER_REUSE=1`, `UPLOAD_PROLOGUE=1`,
      `XVIEW_GUARD=1`, `LDC_FOLD=1`, `FORWARD_TEMPS=1`, `QUAD_DERIVATIVES=1`, `WARP32=1`,
      `READ_PREFLIGHT=0`, `NOLOAD=1` (all `DM_GFX_*`);
   c) the vertex/index cache (~1,364 hits a frame) and the pipeline memo (~800 draws a frame).
   **Unverified:** which build and which defaults the 53.67 fps run had is not recorded, and
   `android.md` still says the defaults are not measured. Re-measure with §8 item 12 step 2.

### Device test session of 2026-11-03 (done): how the A/B runs are made

**Done on 2026-11-03; the results are in §8 item 12 step 9 and the next session is above.** Kept as the
reference for an A/B session; use the script's current behaviour (it finds the marker folder itself) and
`--clear-all --no-restart` before a baseline. One session, on a
machine with `adb` and the phone connected (USB debugging on), with the APK built from current `main`
installed (§5) and Mario Kart 8 Deluxe prepared in `/storage/emulated/0/nxdroid/game`. Each run below
is one race start on **Mario Kart Stadium**, the track of the 2026-11-03 screenshots, held for about a
minute. The background of each step is in §8 item 12.

1. **Make the log buffer large enough** (the default drops the early lines a race pushes out), and keep
   it for the session: `adb logcat -G 16M`.
2. **Baseline, no marker:**
   ```sh
   python scripts/android_gfx_ab.py --clear-all
   python scripts/android_gfx_ab.py --list                 # must print nothing
   adb logcat -c
   ```
   Start the game from the app, start the race, wait a minute, then:
   ```sh
   adb exec-out screencap -p > 00_base.png
   adb logcat -d -s dm > 00_base.txt
   adb shell dumpsys meminfo com.nxdroid > 00_base_mem.txt
   ```
3. **One switch at a time**, in this order (§8 item 12 steps 6 and 8). The script writes the marker,
   restarts the app and saves the screenshot and the log after `--wait` seconds: start the game and
   the race by hand within that time.
   ```sh
   python scripts/android_gfx_ab.py gfx-noload          --off --wait 120 --shot 01_noload_off.png    --log 01_noload_off.txt
   python scripts/android_gfx_ab.py gfx-noload          --clear --no-restart
   python scripts/android_gfx_ab.py gfx-read-preflight  --on  --wait 120 --shot 02_preflight_on.png  --log 02_preflight_on.txt
   python scripts/android_gfx_ab.py gfx-read-preflight  --clear --no-restart
   python scripts/android_gfx_ab.py gfx-tex-dirty       --off --wait 120 --shot 03_texdirty_off.png  --log 03_texdirty_off.txt
   python scripts/android_gfx_ab.py gfx-tex-dirty       --clear --no-restart
   ```
   Then, the same way, each of `gfx-wb-skip`, `gfx-upload-prologue`, `gfx-vcache`, `gfx-pipe-memo`,
   `gfx-native-bc`, `gfx-forward-temps` and `gfx-ldc-fold` with `--off` (files `04_…` to `10_…`).
   Clear each marker before the next, so only one is ever set. Stop early if one run gives a correct
   3D picture, and run that one twice to be sure.
4. **If the game folder is not the default** (picked in the launcher), add `--game-dir <folder>` to
   every `android_gfx_ab.py` line; `--list` shows the markers it sees there.
5. **Memory** (the `dm_guest_discard` fix): `adb shell dumpsys meminfo com.nxdroid` once in a race and
   once after going back to the menu and starting another track (`11_mem_race.txt`, `12_mem_after.txt`).
6. **Bring back** the folder with every `.png` and `.txt`, and one line per run saying what the 3D scene
   looked like (same as the baseline, better, correct, worse) and anything else seen (a crash, a hang,
   a stutter). If the app crashed, also `adb logcat -d -b crash > crash.txt`.

What is read first in the logs: the `nativeStartHost: DM_GFX_…` lines and the engine's `(marker gfx-…)`
lines (which value each switch had), `Swapchain surface format= colorSpace=` and `Swapchain: … srgb=
source_srgb=` (§8 item 12 steps 3 and 3b), `[YELLOW] Preserving GPU-written image on partial memory
pool write` (step 8a), `[nvn] virtual pool … mapped up to` (step 7a), every `[RED]` line, and `NVN PERF`
(fps, `gpu_ms`, `submit_cpu_ms`, `parts_ms_per_frame`).

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

The dump is a device artifact, not in the repository; regenerate it with the probe (§5) and put any
new fact in `docs/reference/android.md`, not here.

## 4. What is in the tree

| Path | What it is | State |
|---|---|---|
| `dm/gfx/vulkan/` (85 tracked files) | the vendored Vulkan engine and its `nvn_vk.c` adapter | pinned, adapted (12 handlers in `xbg_game.cpp`, 27 entry points in `nvn_vk.c`, the Sprint 6 fixes) |
| `dm/android/` | the bionic compatibility layer (`compat/`), build environment (`docker/`, `CMakeLists.txt`, Gradle), `front_android.c` (our `front.h`), `vulkan_present.cpp`, `jni_android.c`, `port_android.c`, `apple_stubs.c` (+ `apple_stubs/include`), `app/` (Java), `tools/`, `tests/` (`test_device_bionic.c`, `test_vm_alias.c`), `mockups/` | NDK r29 build of `dmhost` and `libdm.so`, both run on the device; CI compiles them |
| `dm/tools/android_vendor.py` + `.tsv` | provenance gate: 108 rows, 13 adapted | green in CI; on a Windows checkout read §10 |
| `dm/gfx/vk/probe/` | the device capability probe (`vk_probe.c`, Makefile with desktop and `android` targets, output contract in `tests/test_probe_output.py`) | run on the device, 0 breaches |
| `dm/gfx/vk/engine_smoke/` | out-of-tree harness: compiles the vendored engine against **our** headers and initializes it; the generated `opcode_map.txt` / `abi_gaps.txt` and `payload_mismatch.txt` | green on desktop (llvmpipe, RTX 5060 Ti); not in CI |
| `dm/gfx/vk/address_space.md` | the 64-bit address space decision | written, not reviewed by hand |
| `dm/host/port.h` | the host's platform layer: Apple inline, bionic in `dm/android/port_android.c` | compiled with the NDK, runs on the device |
| `dm/android/tools/{host_sources,undef_scan}.py`, `dm/tools/tests/test_{thread_slots,android_undef_scan,android_jni,android_vm_alias,launcher_settings,env_switches}.py` | source-list expander, undefined-symbol and Mach-O assembly gate, and the Android tool tests | green in CI |
| `dm/tools/android_audit.py` + baseline + tests | "is this file portable to Android?"; the baseline only shrinks | 760 hits in 38 files |
| `scripts/prepare_game_android.py` | prepares a game folder for the device and can push it, build and install the APK | in use |
| `scripts/android_gfx_ab.py` | A/B one engine switch over `adb` without a rebuild (§8 item 12 step 5) | syntax-checked only |
| `.github/workflows/tests.yml` | CI: `android-gates` and `android-build`, Linux | green and blocking since `94d3ee4` |
| `README.md`, `CONTRIBUTING.md`, `AGENTS.md`, `.github` templates | describe the Android port; README's game gallery is folded below the Android games section and labelled as nxnative's Mac / iPhone builds | current |
| `docs/reference/android.md` | the vendored engine reference: pin, gate, device, Adreno gates, ABI gaps, licensing, the Android findings | current, with the stale lines named in §8 item 11 |
| `.opencode/agents/android-{dev,qa,shaders,upstream}.md` | the four specialist agents this work was coordinated through | in use |

## 5. Gates, and the exact commands

Run these before believing anything. CI (`.github/workflows/tests.yml`, GitHub's Linux runners) runs
them on every push to `main` and every pull request: `android-gates` (provenance, both vocabularies,
the audit, the symptom index, the four engine source checks, the tool tests below) and `android-build`
(NDK `ndk;29.0.14206865` through `sdkmanager`, `GAME=0100152000022000`, configure, then
`cmake --build … --target dmhost dm`). Both are green and blocking since `94d3ee4`. CI never runs the
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

# the APK (in the same image), then install it
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
- **Open:** the GL depth mode (near = -w) has no Vulkan entry point; a game that keeps it gets one
  `[RED]` at its first submission and near = 0 depth. (Android writes the GL rewrite into every vertex
  shader's SPIR-V instead: Status item 2e.)

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
   - **[DONE 2026-11-05, not measured on the device]** `NVN_DEVICE_INFO_MAX_VIEWPORTS` comes from the
     device: `nvnDeviceGetInteger` asks the replay (`mtl_device_integer`, `nvn_mtl.h`; `nvn_vk.c` →
     `xbg_device_integer`, `multiViewport ? min(16, maxViewports) : 1`); the Tegra table's 16 is left
     only before the Vulkan replay is up (`[RED] nvnDeviceGetInteger item 0x26 before the Vulkan replay is
     initialized`, which a device log should not show).
   - **[DONE 2026-11-05, not measured on the device]** `SetScissors` / `SetDepthRanges` keep every
     index: index 0 as before (`OP_SCISSOR` / `OP_DEPTH_RANGE`), 1..15 in the new `OP_SCISSORS` /
     `OP_DEPTH_RANGES` records (`OP_COUNT_` is 53, the `OP_XBG_*` block 54..64, the capture layout says
     `ops 53`), and a draw that declares viewport *i* sets scissor and depth range *i*. A range past 16
     is refused with `[RED] SetScissors first=… n=…: outside NVN's 16 viewports`. The Metal replay skips
     the new records (index 0 only, as before). Checked by a harness of the extracted writer and by the
     gates; CI's NDK build is the first compile.
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
8. **[DONE] The app shell.** `dm/android/jni_android.c` (JNI registration, stdout/stderr to logcat tag
   `dm`, host start/stop, surface, refresh rate, touch and pad input, the graphics defaults of Status
   item 3b; tested by `test_android_jni.py`) and `dm/android/app/` (Gradle: compileSdk 36, minSdk 29,
   targetSdk 36, arm64-v8a, NDK 29.0.14206865, `-DGAME=`; package `com.nxdroid`). `MainActivity`'s own
   folder picker and the virtual gamepad run on the device. Default game folder:
   `/storage/emulated/0/nxdroid/game`. **Open:** the Argon launcher (`LauncherOverlayView.java`,
   `GameScanner.java`, spec `dm/android/mockups/design_spec_argon.md`: hero card, title grid) is written
   but not wired into `MainActivity` (nothing references it); the help text in `MainActivity.java` (~426)
   is Portuguese, against `AGENTS.md`'s English rule.
   **Argon assessment (2026-11-03, read only; the owner deferred the work until after the device
   graphics tests):** the view draws the spec's top bar, hero card, 4-slot grid and footer, but its data
   is fake (four placeholder games added in `init`, title from the folder name, title ID falling back to
   `010015100B514000`, API / fps / prewarm counts from folder-name substrings, size "5.7 GB", fixed
   "Vulkan 1.3" / "S23 Ultra" / "v0.1.0-alpha", every card "Playable"); `control.nacp` and `icon.jpg`,
   which `prepare_game_android.py` copies, are read by nothing; its default folder is
   `/storage/emulated/0/Games/Switch/`; it has touch only (no key handling), no fade, no paging past 4
   games. Two limits of the architecture: the APK is built for one profile (`-DGAME`), so a library can
   start only that game (a JNI getter for the built title ID is needed to mark the others); and stopping
   a game ends the app's process (`nativeStopHost` → SIGTERM → `_exit(0)`, `hle_lifecycle.c`), so there
   is no return to the launcher without moving the host to a separate process. Estimate to wire it in
   with real data, gamepad navigation, the built-game check and English strings: 400-500 lines, 12-20 h,
   most of it checkable only on the device. CI does not compile the Java (`android-build` builds the
   native targets only): a Gradle `assembleDebug` job would be the first step.
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
12. **The graphics work on the device (open, needs a build and a log).** The graphics defaults
    (`jni_android.c`, Status item 3b), the present changes (`vulkan_present.cpp`, Status items 1 and 3a)
    and the colour-space filter (3b below) are committed and compiled in CI (`android-build`); none is
    measured on the device since. To measure:
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
      single-switch runs, then the alias tracing, runs 12 to 19. Next: runs 20 onwards of the 2026-11-04
      session, "Next device session" near the top. Each bullet: run number, installed commit, the
      marker, the visual result, the step 7 log lines, and whether the run crashed, hung or stuttered.)
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
  (`gfx-pipe-skip`, Status item 2c): if many pipelines are suddenly skipped, remove the cache files on
  the device.

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
