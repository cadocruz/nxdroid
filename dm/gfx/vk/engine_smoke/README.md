# Engine smoke build: the vendored Vulkan engine on a desktop Linux machine

This directory builds `dm/gfx/vulkan/engine` alone on Linux x86_64 (system Vulkan headers, lavapipe
or a real GPU), links it with a 60-line harness that creates the `VkInstance` / device / queue
`xbg_game_config` asks for, and reports the ABI gap between the vendored adapter and this
repository's own `mtl_*` layer. Nothing here is part of a shipped build and the Metal path is not
touched; the engine sources are compiled in place and the one local edit they carry (`xbg_game.cpp`'s
compatibility block, below) is recorded in `dm/tools/android_vendor.tsv`, so
`python3 dm/tools/android_vendor.py --check` stays green.

Measured on 2026-10-28: Ubuntu, GCC 15.2, system Vulkan headers (`VK_HEADER_VERSION` 341), Mesa
26.0.8 lavapipe and an NVIDIA RTX 5060 Ti (proprietary driver, `api 1.4.312`). No NDK, no Android
device, no Mac was used.

## What compiles

`make report` first runs `make headers` (the two shared headers alone, as C and as C++, `-Werror`), then
prints one line per translation unit. The state today (clang 21.1.8 and g++ 15.2):

| Translation units | State |
|---|---|
| The engine's 8 C files | `ok` — needs `-D_GNU_SOURCE` on glibc: `xbg_texture.c:267` calls `pthread_setname_np`, which glibc declares only under `__USE_GNU`. Bionic declares it unconditionally, so this is a harness flag, not a source change |
| The engine's 12 C++ files (`xbg_game.cpp` included) | `ok` with both `clang++ -std=c++17` and `g++ -std=c++17`, no workaround, no `-fpermissive` |
| This repository's `nvn_tex.c`, `nvn_deswizzle.c` | `ok` (the engine calls both; they are linked as they are) |
| `smoke.c`, `host_stubs.c` | `ok` |
| `dm/gfx/nvn/nvn_obj.h`, `nvn_mtl.h` alone | `ok` as C (`gcc` / `clang`, `-Werror`) and as C++ (`g++` / `clang++`, `-Werror`) |

`xbg_game.cpp` includes `dm/gfx/nvn/nvn_obj.h` through `xbg_game_internal.h`'s `extern "C"`, and two
things in this tree did not agree with it. Both are fixed at the cause, and neither needed
`-fpermissive` (which clang does not have):

1. **`nvn_obj.h` was C-only.** Its five helpers (`vbuf_rec`, `bind_buf_rec`, `bind_rec`, `draw_rec`,
   `draw_idx_rec`) returned or assigned a `const void *` as a typed pointer, which C converts implicitly
   and C++ does not. The eight sites now cast explicitly — the record layouts are identical, so the cast
   states what the function already promised; nothing is being silenced. Both headers also carry an
   `extern "C"` guard and a `DM_STATIC_ASSERT` that is `_Static_assert` in C and `static_assert` in C++,
   so the C side is byte-for-byte the same.
2. **`OP_COPY_IMAGE_STRIDE` did not exist here.** `nvn_obj.h`'s enum stops at `OP_BIND_VBUF1` (50) +
   `OP_COUNT_` (51); the fork's enum continued with `OP_COPY_IMAGE_STRIDE` (39) and `OP_COUNT_` (40).
   The fork's nine extension ops (its `OP_COUNT_+1..+9`, i.e. 41..49 there) now have names in this
   header, in a block after `OP_COUNT_`: `OP_XBG_SYNC_WAIT` (52) .. `OP_XBG_TYPED_CLEAR` (60), plus
   `OP_XBG_COPY_IMAGE_STRIDE` (61) and `OP_XBG_PATCH_SIZE` (62). The engine's case labels still read
   `OP_COUNT_+N` — which lands on `OP_XBG_SYNC_WAIT+N`, so the numbering is explicit on both sides — and
   the one name it spells differently is mapped in a single compatibility block at the top of
   `xbg_game.cpp` (`#define OP_COPY_IMAGE_STRIDE OP_XBG_COPY_IMAGE_STRIDE`). Its tessellation case was
   `case OP_COUNT_:`; that is `case OP_XBG_PATCH_SIZE:` now, because 51 is this host's sentinel and no
   command of ours is 51. That block plus that one case label is the whole edit to the vendored file; it
   is recorded in `dm/tools/android_vendor.tsv` and `make check-vendor`-style gates see it as `adapt`.

Warning noise is high: `-Wall -Wextra` gives well over a thousand warnings, mostly
`-Wmissing-field-initializers` and `-Wmisleading-indentation`, because the engine writes `VkX x{S_TYPE};`
and `if(a)b;c;` on one line throughout. None is an error and none is new; the harness drops
`-Wmissing-field-initializers` for its own two files only.

## How to run it

```sh
make -C dm/gfx/vk/engine_smoke            # build build/engine_smoke
make -C dm/gfx/vk/engine_smoke report     # headers as C/C++, then per TU: ok, or the first error
make -C dm/gfx/vk/engine_smoke headers    # nvn_obj.h + nvn_mtl.h alone, as C and as C++, -Werror
make -C dm/gfx/vk/engine_smoke map        # regenerate opcode_map.txt; check-map fails when stale
make -C dm/gfx/vk/engine_smoke run        # Mesa lavapipe (VK_ICD_FILENAMES, no window, no surface)
make -C dm/gfx/vk/engine_smoke run-gpu    # the machine's default device; SMOKE_DEVICE=<name> picks one
make -C dm/gfx/vk/engine_smoke gaps       # regenerate abi_gaps.txt; check-gaps fails when stale
```

The harness creates the instance and device itself (Vulkan 1.1, one graphics+compute queue family,
`shaderDrawParameters` enabled when the device has it), creates `build/shader_dir`, and calls
`xbg_game_initialize`, one entry point through `xbg_nvn_get_proc_address`, `xbg_game_get_stats`,
`xbg_game_set_sampler_mirror_clamp_to_edge(VK_FALSE)` and `xbg_game_shutdown`. There is no surface,
no window and no guest. `present` counts calls (the run makes none), `log` prints the engine's own
`NVN ...` lines, `fatal` exits 97 rather than returning. It states its instance version in
`xbg_game_config.instance_api_version` (1.1), so the engine asks the device no 1.2 feature struct even
on a 1.2 loader; with that field present, x86_64 prints `size=328/328`.

## What it produced

Both devices, exit 0:

```
device 0: llvmpipe (LLVM 21.1.8, 256 bits) vendor 0x10005 api 1.4.335   # make run
device 0: NVIDIA GeForce RTX 5060 Ti vendor 0x10de api 1.4.312          # make run-gpu
config: size=328/328 physical=... device=... queue=... family=0 draw_params=1 timeout=1000000000
xbg_game_initialize -> 0
xbg_nvn_get_proc_address("nvnDeviceGetInteger") -> 0x...
  entry point call -> 0, value 7
stats: submissions=0 draws=0 dispatches=0 presents=0 shader_loads=0
xbg_game_shutdown -> 0
log lines=60 presents=0 fatals=0                                        # lavapipe; 63 on the RTX
```

`xbg_game_initialize` also returns 0 with `SMOKE_SHADER_DIR=/nonexistent/...`, i.e. with no shader
directory at all. It never touched a stubbed host function: `host_stubs.c` gives the two symbols no
engine translation unit defines (`nvn_new_serial`, `xbg_record_command`) and neither was reached.

## What initialization actually needs, and what it does not

**Nothing that needs guest memory, and nothing that needs a shader directory.** The only inputs are
a non-NULL `VkPhysicalDevice`, `VkDevice`, `VkQueue`, `shader_directory` string and a non-zero
`fence_timeout_ns` (`xbg_game.cpp:3886`), a queue family with both `GRAPHICS` and `COMPUTE`
(`:3906`) and every feature bit set in `enabled_core` being available (`:3905`). The rest of
initialization is capability logging, marker files under the shader directory (every read is
best-effort; a missing file just leaves the default), a `VkCommandPool`, a `VkPipelineCache` and the
warm-up / async-pool-reset threads. `shader_directory` is only a *prefix*: every consumer appends
`/<key>.xgs`, `/vk-pipeline-cache.bin`, `/spv-override/...` or a marker name.

Shader bundles are needed lazily, at the first program bind, not at initialization:

- `xbg_game.cpp:1980` — `xbg_fatalf("Missing genuine shader bundle %s", path)` in `load_shader`,
  with `path = <shader_directory>/<key>.xgs` and `key` the first 8 bytes of sha256 over the
  program's control section (`xbg_shader_control_key`).
- The bundle must satisfy, in order: 32 bytes ≤ length ≤ 16 MiB (`:1981`), then the header check
  (`:1982`) — `magic == 0x31534758` ("XGS1"), `version == 1`, `stage < 6`, `binding_count <= 256`,
  `input_count <= 16`, `c1_bytes <= 65536`, `spirv_bytes % 4 == 0` — then an exact extent
  (`:1983`): `32 + binding_count * 32 + input_count * 4 + c1_bytes + spirv_bytes == length`,
  laid out as `xbg_shader_header` (8 × u32), `xbg_shader_binding[binding_count]`, `input_count`
  u32 input locations, `c1` bytes, SPIR-V words. Header and binding layout are in `xbg_game.h`.
- So a real host integration needs (a) a shader directory of genuine bundles produced offline, or
  (b) a replacement for `load_shader` that takes the SPIR-V the DMSH chain already produces. Which
  one is the Android port's decision, not this sprint's.

## The ABI gap, mechanically

`abi_gaps.txt` (generated by `abi_gaps.py --check` in CI terms) parses both sides. Counts today:

- **27 `mtl_*` entry points** are declared by `dm/gfx/nvn/nvn_obj.h` + `nvn_mtl.h` and not defined by
  `dm/gfx/vulkan/nvn_vk.c`, each with the `nvn_mtl.m` section that implements it on Metal: 12 of the
  29 `nvn_mtl.h` declares, and 15 that only `nvn_obj.h` declares (`mtl_ab_gpu`, `mtl_cpu_tex_count`,
  `mtl_link_rate`, `mtl_link_stalled`, `mtl_link_tick`, `mtl_link_wait_ticks`, `mtl_pkg_edge_skips`,
  `mtl_present_test_stall`, `mtl_reg_image`, `mtl_snap_acquire_wait`, `mtl_snap_on`, `mtl_sub_fill`,
  `mtl_tex_cpu_written`, `mtl_tex_gpu_owned`, `mtl_tex_init`). An earlier count of 13 took
  `nvn_mtl.h`'s list plus `mtl_present_wait`, which the adapter does define (`nvn_vk.c:83`), and
  missed the fifteen.
- `dm/gfx/vulkan/nvn_vk.c` also defines `mtl_*` functions neither header declares (`abi_gaps.txt`,
  "extra": 12 at the import, two of them D2R-specific (`mtl_ui_ghost`, `mtl_ui_ghost_rect`); 29 now
  that the adapter answers `hle_nvn.c`'s statistics calls). Inert for linking, but the first twelve
  mean the two sides were written against different headers.
- **One signature differs in its types**: `int mtl_link_wait_tick(int vsyncs, uint64_t timeout_ns)`
  here, `int mtl_link_wait_tick(uint64_t timeout)` in the adapter — the caller's `vsyncs` argument
  would land in `timeout`.

### Command vocabulary: the engine reads the fork's records, not ours

This is not a symbol gap and it does not show up until a command is replayed, but it is the item
that decides the shape of the integration. Two generated files carry it; `make map` rewrites them
and `python3 dm/gfx/vk/engine_smoke/opcode_map.py --check` fails when either drifts from the tree
(the enum, the dispatch in `xbg_game.cpp`, the writers in `dm/gfx/nvn/*.c` and the payload sizes
quoted below are all read, not remembered):

- `opcode_map.txt` — one row per op: value, the writer call that emits it (`not emitted` when no
  game reaches it), the `case` in `xbg_game.cpp`'s `execute()` (`missing` when it falls into
  `default:`), the `nvn_mtl.m` case and section banner that implements it on Metal, a payload id,
  and what the handler must do. Today: **51 ops, 51 handled, 0 missing, 1 payload-mismatched**,
  plus **11 fork-only rows** in a second block.
- `payload_mismatch.txt` — the one op both sides implement but read differently, `P8` (barrier
  cache bits, benign), with the writer line, the reader line, which side is right (the writer:
  `hle_nvn.c` is what 93 profiles record through and what games size with
  `GetCommandMemoryUsed`), the fix and what breaks. The seven that were fixed (`P1`–`P5`, `P7`,
  and `P6`, the viewport array) are recorded in `opcode_map.txt`'s note column instead, with the
  reason.

What the counts say, in the order it will hurt:

1. **Twelve ops have no handler.** `OP_CLEAR_BUF`(39), `OP_DEPTH_CLAMP`(40), `OP_RENDER_COND`(41),
   `OP_FENCE_SYNC`(42), `OP_TF_BIND`(43), `OP_TF_STATE`(44), `OP_RAST_DISCARD`(45),
   `OP_VP_SWIZZLE`(46), `OP_BIND_TEX1`(47), `OP_PRIM_RESTART`(48), `OP_BIND_UBO_SMALL`(49),
   `OP_BIND_VBUF1`(50). Each reaches `xbg_fatalf("NVN opcode %u ... not implemented")` at
   `xbg_game.cpp:3839` — a loud stop, not silent corruption. `opcode_map.txt` names the Metal
   section that implements each (`mtl_exec` at `nvn_mtl.m:10034` for rasterizer discard, the
   `mtl_sub_fill`/submission-order path for `OP_CLEAR_BUF`, …), so a handler is a port, not a
   design. The state for half of them (`depth_clamp`, `rast_discard`, `restart_on/index`, `vp_sw`,
   `render_cond_skip`, `tf_on`, `tf[4]`) is declared, in `PipeMemoKey` where it changes a pipeline,
   and set by nothing yet.
2. **Six payload readers were fixed here, and the fix is guarded.** `P1`/`P2` (a compact draw record
   is 24 / 32 bytes; the reader now goes through `draw_rec` / `draw_idx_rec` and treats the fields
   the writer did not store as 0), `P3` (indirect dispatch reads its group counts at execution),
   `P4` (256 texture slots), `P5` (image stride), `P7` (a `Downsample` resolves instead of
   copying). The compact draw lengths are pinned in `nvn_obj.h`
   (`DM_REC_DRAW_COMPACT` / `DM_REC_DRAW_IDX_COMPACT` and the assertions next to `draw_rec`), so
   moving a field inside `p_draw` fails the build instead of a game's first draw.
3. **One remains.** `P8` is benign: the reader's one full barrier is stronger than the bits ask
   for. `P6` is handled in the draw: the handler writes `viewport[first..first+n)`, and a draw
   declares and sets the recorded array when its vertex / tessellation-evaluation / geometry shader
   writes `ViewportIndex` (one viewport otherwise); the path is not reachable end to end until the
   front end enables `shaderOutputViewportIndex` and the writer records per-viewport scissors, and
   a viewport mask is refused (the multiview fan-out is open; see `docs/reference/android.md`).
4. **Eleven fork-only rows** in the second block of `opcode_map.txt`: the engine's nine extension
   ops and its `OP_COPY_IMAGE_STRIDE` / `OP_COUNT_`. They are named `OP_XBG_*` in `nvn_obj.h` after
   our `OP_COUNT_` (52..62, this sprint), each row saying what the fork recorded it for and what
   this host emits instead (`OP_DISPATCH.ind` for its indirect dispatch, `OP_DRAW.mdi_cnt/mdi_i` for
   its multi-draw, `OP_COPY_T2T | DM_COPY_RESOLVE` for its resolve, `OP_COPY_STRIDE` with
   `image = 1` for its `OP_COPY_IMAGE_STRIDE`, `g_nops` for the rest). Our host emits none of them,
   so a handler for each is not on the integration's critical path; the engine's `case` bodies are.

## The one thing that most constrains the host integration

The 27 missing `mtl_*` entry points are mechanical host work. The constraint is that the vendored
engine is a *replayer of the fork's command records*, and this repository's HLE writes a newer
record set. The two headers and the vocabulary now agree on paper (the enum carries the fork's
names, `xbg_game.cpp` compiles against `nvn_obj.h` with no workaround, and `opcode_map.txt` /
`payload_mismatch.txt` are checked by `--check`), which leaves the actual port: add the 12 handlers
or stop emitting those ops, and port the readers for the open payload ids (`opcode_map.txt` gives
each the `nvn_mtl.m` case to port). Only then can the 27 `mtl_*` functions and the `xbg_*` host surface be
filled in. Until that is decided, an Android build compiles and initializes but dies at the first
`DrawArrays`, `ClearBuffer`, `DepthClamp` or per-slot descriptor bind.

## Not run here

No NDK, no arm64 device, no Adreno driver, no Android surface/swapchain, no guest memory, no
genuine `.xgs` bundle, no pipeline creation, no draw. The engine initializes and shuts down; whether
its replay produces a correct picture on an Adreno 740 is untouched by this sprint. The two Adreno
gates in `docs/reference/android.md` are compile-time paths only (and the SPIRV-Tools one is
compiled out here — `XBG_HAVE_SPIRV_OPT` is not defined, so the log line "NVN helper inlining is not
built into this package" is what a build without SPIRV-Tools says).

## Files

| File | What it is |
|---|---|
| `Makefile` | Builds the engine's 24 TUs plus 4 harness/repository TUs into `build/engine_smoke`; `report`, `headers`, `run`, `run-gpu`, `map`, `check-map`, `gaps`, `check-gaps`, `clean` |
| `report.sh` | The per-TU loop `make report` runs; reports every unit with no workaround in the flags |
| `smoke.c` | The harness: instance, device, `xbg_game_config`, initialize, one proc address, shutdown |
| `host_stubs.c` | The two host symbols no engine TU defines (`nvn_new_serial`, `xbg_record_command`) |
| `abi_gaps.py`, `abi_gaps.txt` | The mechanical `mtl_*` gap in both directions, with the `nvn_mtl.m` section for each name |
| `opcode_map.py`, `opcode_map.txt` | The command vocabulary: every op of `nvn_obj.h` with its writer, its handler (or `missing`), its Metal case, a payload id and what the handler must do; `--check` re-derives it from the tree |
| `payload_mismatch.txt` | `P1`..`P8`: the ops both sides implement but read differently, with writer line, reader line, correct side, fix and what breaks first |
