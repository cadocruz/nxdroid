# Handoff: running this host on Android (nxdroid)

This file is the state of the Android port at a cut in the work, written so that the next
session (or person) can continue without re-deriving anything. It is not a design document: the
design lives in `dm/gfx/vk/address_space.md` and `docs/reference/android.md`, and the per-op detail
in `dm/gfx/vk/engine_smoke/opcode_map.txt` and `payload_mismatch.txt`. This file says **where the
work stands, what is broken, what to do next, and how to run it**.

The repository points to remote `origin git@github.com:cadocruz/nxdroid.git`.
The repository is initialized with a clean single commit on `main` and the working tree is clean. Commit
with proper descriptive messages following repository conventions.

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
| Zero-copy | **not available**; mirror is the baseline | `VK_EXT_external_memory_host` is absent on the Adreno 740. The only remaining route is to allocate pool memory *as* an `AHardwareBuffer` and import it — unmeasured, see §8 item 8 |

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
| `dm/android/` (compat, docker, front end, CMake) | the vendored bionic compatibility layer and build environment | imported; `CMakeLists.txt` and `front_android.c` carry *pending adaptation* notes |
| `dm/tools/android_vendor.py` + `.tsv` | provenance gate: 108 rows, 4 adapted | green |
| `dm/gfx/vk/probe/` | the device capability probe: `vk_probe.c`, a Makefile with a desktop and an `android` target, a frozen output contract in `tests/test_probe_output.py` | built and run on the device, 0 breaches |
| `dm/gfx/vk/engine_smoke/` | the out-of-tree harness that compiles the vendored engine against **our** headers and initializes it, plus the two generated vocabulary reports and `README.md` | green on desktop (llvmpipe + RTX 5060 Ti) |
| `dm/gfx/vk/address_space.md` | the 64-bit-address-space decision | written, unreviewed by hand |
| `dm/tools/android_audit.py` + baseline + tests | "is this file portable to Android?", with a baseline that only shrinks | green; 832 hits in 44 files |
| `docs/reference/android.md` | the vendored engine reference: pin, gate, device, Adreno gates, ABI gaps, licensing | current |
| `.opencode/agents/android-{dev,qa,shaders,upstream}.md` | the four specialist agents this work was coordinated through | in use / active |

## 5. Gates, and the exact commands

Run these before believing anything:

```sh
# vendored provenance: 108 files, 4 adapted
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

# docs, vendor gate, audit, probe contract
/home/cado/.venv/bin/python -m pytest dm/tools/tests/test_docs.py \
    dm/tools/tests/test_android_vendor.py dm/tools/tests/test_android_audit.py \
    dm/gfx/vk/probe/tests/test_probe_output.py -q
python3 dm/tools/docs_symptoms.py    # after any docs/reference edit
```

The system `python3` has no pytest; use `/home/cado/.venv/bin/python -m pytest`. The full
`dm/tools/tests` suite is **not** green on this machine and was not before this work: five modules
fail to import (`/usr/lib/libproc.dylib`, a macOS-only dependency) and the fuzz corpus needs
`lz4`, which the venv does not have. Those are environment gaps, not regressions — but say so
rather than claiming the suite passes.

Building and running on the device:

```sh
# toolchain image (derived from dm/android/docker/Dockerfile, adding make, git, file)
podman run --rm --userns=keep-id -v "$PWD:/src:rw" -w /src dm-android-tools:1 \
    make -C dm/gfx/vk/probe android NDK=/opt/android-sdk/ndk/29.0.14206865

ADB=/tmp/opencode/platform-tools/adb          # 37.0.1; the device is RQCX808VH9K
$ADB push dm/gfx/vk/probe/vk_probe_android /data/local/tmp/vk_probe
$ADB shell chmod 755 /data/local/tmp/vk_probe && $ADB shell /data/local/tmp/vk_probe > /tmp/opencode/s23-ultra.txt
python3 dm/gfx/vk/probe/tests/test_probe_output.py /tmp/opencode/s23-ultra.txt   # must print "valid"
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

Current counts (`opcode_map.py --check`): **51 ops, 51 handled, 0 missing, 2 payload-mismatched**
(`P6`, a multi-viewport record, refused on purpose; `P8`, barrier cache bits, benign), 11
fork-only. `abi_gaps.py --check`: **0 `mtl_*` entry points missing, 0 signature mismatches, 12 extra**.
`android_audit.py --summary`: **832 hits in 44 files** — 433 `objc-framework`, 379 `apple-api`,
12 `page-assumption`, 8 `macho-section` (gate `--check` is green).

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
- **4 KiB page fix in host probe:** comment regex trigger resolved, audit baseline reduced to 832 hits.
- **Still open:** `P6` (n > 1 viewports).

The `dm/tools/android_vendor.tsv` rows for `xbg_game.cpp` and `nvn_vk.c` are updated and clean.

## 8. What to do next, in order

1. **[DONE] The 12 missing handlers** — all 12 implemented and verified by QA in `xbg_game.cpp`.
2. **`P6` n > 1** — a viewport array as dynamic state, a pipeline built for the count, and
   `VK_KHR_multiview` only where the record wants one pass over several viewports. `P8` (barrier
   cache bits) is benign: the reader's single full barrier is stronger, so record that and leave it.
3. **[DONE] The 27 missing `mtl_*` entry points.** Implemented in `dm/gfx/vulkan/nvn_vk.c`.
4. **Host bring-up**: `dm/host` on bionic, with the audit as the checklist. Replace Apple-only
   APIs (`clonefile`, QoS, Mach absolute time, CommonCrypto) using `dm/android/compat/`.
5. **Wire it into a build**: Generalize `dm/android/CMakeLists.txt` and `front_android.c` for any game
   profile (`game.tsv` -> `game_profile.h`), replacing the D2R-specific headers (`dm_vault_tab.h`, etc.).
6. **Probe v2, the last chance for zero-copy**: `vkGetPhysicalDeviceExternalBufferProperties` for
   opaque-fd and AHB, plus a real 64 MiB `AHardwareBuffer` import and a shader write through it. If
   that works, pools can be allocated in AHB memory from the start and the mirror's copy tax
   disappears; if it does not, the mirror stands and `nvn_dirty.c`'s page tracking is the
   performance-critical path (4 KiB pages match the device exactly).
7. **`address_space.md` §8's experiment** if the 128 MiB cap turns out to matter: it needs a SPIR-V
   shader the tree cannot currently produce (`dmsh_xlate_bin` is Mach-O and `dotnet` is not
   installed here), so first get one translated shader from a Mac build.

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
  shader is `xbg_game.cpp:1980-1983`.

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
- **`viewport_n` is not in the pipeline memo key and must not be**: the pipeline declares one
  dynamic viewport whatever the record's count. If step 4 of §8 lands, that changes.
- **`exec_pages = ok` was measured in the `shell` SELinux domain.** The app runs in
  `untrusted_app`; treat it as indicative until a packaged app maps an executable page.
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
