# The GPU address space on Vulkan (Adreno 740)

How the first Vulkan backend presents the guest's flat 64-bit GPU address space when the driver's largest
single storage descriptor is 128 MiB and the shaders have no `shaderInt64`. Design only: nothing here is
implemented, and no chain, host or engine file was changed.

The short answer is that the flat space is **already gone before the backend sees it**. Every guest global
load and store leaves the translator as a `(storage binding, 32-bit offset)` pair; the 64-bit address never
reaches the GPU. What the backend has to solve is therefore not "address 4 GB" but "place one descriptor so
that the offsets the shader computes land on the right bytes" — 128 MiB of range and 64 bytes of alignment,
per binding, with the shader's own arithmetic unchanged.

## 1. Constraints

Measured on the target (`SM-S918B`, Android 16/SDK 36, `vk_probe` output in `/tmp/opencode/s23-ultra.txt`;
line numbers are that file's).

| Constraint | Value | Consequence for this design |
|---|---|---|
| `maxStorageBufferRange` | `134217728` (128 MiB), line 192 | A descriptor cannot span a 2–4 GB pool. This is the only hard limit that shapes the design |
| `minStorageBufferOffsetAlignment` | `64`, line 190 | A descriptor's offset into its `VkBuffer` must be 64-byte aligned. NVN buffer addresses are not required to be |
| `maxUniformBufferRange` | `65536`, line 193 | Equals NVN's own `NVN_DEVICE_INFO_MAX_UNIFORM_BUFFER_SIZE` (`hle_nvn.c:136`, index `0x3` = 65536), which every game already respects — uniform buffers never hit a range limit |
| NVN uniform buffer alignment | 256 (`hle_nvn.c:136`, index `0x4`) | ≥ 64: plain uniform buffers need no alignment handling at all |
| `maxPerStage/SetDescriptorStorageBuffers` | `16777216`, lines 194–195 | Descriptor *count* is not a limit. A window array would fit; nothing forces one |
| `maxMemoryAllocationSize` | `1073741824` (1 GiB), line 187 | A 1.5 GB or 8 GB pool is 2 or 8 allocations. Allocation boundaries must not be visible to the shader |
| `maxMemoryAllocationCount` | `4294967295`, line 186 | Not a limit |
| `bufferImageGranularity`, `nonCoherentAtomSize` | `1`, `1`, lines 188–189 | No aliasing or flush-granularity padding needed |
| `shaderInt64` | `false`, line 165 | Rules out `PhysicalStorageBuffer64` / buffer device address in shader code (§5, option C) |
| `shaderInt16` | `true`, line 166 | Unrelated, recorded because the translator has a 16-bit path |
| `VK_EXT_external_memory_host` | absent, line 288 | Guest memory cannot be bound. Verdict `zero_copy = copy-only`, `guest_upload_cost = mirror`, lines 294/296: the backend must own a copy of guest memory, so every pool the GPU reads has a *host-side* extent that has to be allocated and (for writes) refreshed |
| `VK_KHR_sparse_*` | absent from the extension list | No sparse binding / sparse residency: a pool cannot be mapped on demand by a page table |
| `subgroupSize` / min / max | `64` / `64` / `128`, lines 222–224 | See §7: the translator's answers are written for 32 today, and the *effective* wave can be 128 |
| `VK_EXT_subgroup_size_control` | present (line 72) | The 64-lane assumption can be pinned per pipeline, which §7 requires |
| `VK_EXT_robustness2` | present, but the dump's `robustness2` means `nullDescriptor` only (`vk_probe.c:518-522`) | Out-of-range storage reads are **unmeasured**, not "zero". `robustBufferAccess` and `robustBufferAccess2` are not printed at all |

## 2. What the chain leaves for the backend

The translator already targets Vulkan: `dmsh_xlate/Program.cs:165` (and 172/178/184) constructs
`new TranslationOptions(TargetLanguage.Spirv, TargetApi.Vulkan)`, and `dmsh_build.py` then runs spirv-cross
on that SPIR-V (`dmsh_build.py:46`, `XC`). So the SPIR-V stage the Android port wants is the step the Apple
build already has; the port keeps it instead of converting it.

Guest addressing is erased in two places, both before SPIR-V emission:

- `InstEmitMemory.cs:512` `Get40BitsAddress` keeps a guest address as two 32-bit operands (low, high). No
  64-bit integer ever appears, which is why `shaderInt64 = false` costs nothing here.
- `Translation/Optimizations/GlobalToStorage.cs` rewrites every `GlobalMemory` operation into a storage
  buffer operation. The base is the *guest address* the game itself stored, read through a reserved constant
  row (`SearchResult.SbCbSlot/SbCbOffset`, `GetBaseAddressCbWithOffset` at :1082), and the index is the
  guest's own offset expression: `offset >> 2` at :441 becomes the word index of the binding. The shader
  never multiplies, adds or compares a 64-bit address; it indexes a binding.

Two paths matter for the backend, and they behave differently:

- **Inline** (`GenerateInlineStorageOp`, :408): one binding, no bounds test. The byte the shader reads is
  `binding base + (guest offset)`. An over-read past the declared NVN size therefore *succeeds* and lands in
  whatever the host bound next — on Metal, the rest of the pool.
- **Multi-target** (`TryGenerateMultiTargetStorageOp`, :643): a pointer that may be one of several buffers.
  Here the shader does check: `offset < size` (:693) with the high word equal (:697), against the
  `(baseLow, baseHigh, size)` triple the host writes. Out of range ⇒ loads read 0, stores are dropped. This
  is also the path that reports `Failed to reserve storage buffer for global memory operation` (:242) when
  no base can be traced, which a full build counts under its `translator …` note lines (`dmsh_build.py:1120`).

The host side of that triple is already the same ABI as Metal: `dmsh_abi.h:24-30` defines
`DMSH_C0_ROW 0x10` (address 64 bits, size 32 bits) at `DMSH_C0_SSBO_<stage> + 0x10·reg`, filled per draw at
`nvn_mtl.m:6661` from the NVN slot's guest address and size. A Vulkan backend fills the same rows and
additionally writes the descriptor. The build already publishes the mapping it needs —
`dmsh_build.reflect()` (`dmsh_build.py:522-575`) turns each SPIR-V binding number into an NVN slot
(`res['sbufs'][i].binding → cb_slot/cb_offset → reg`), and the comment there states it: *"SPIR-V binding
number → c0 offset → NVN storage buffer slot"*. The `msl_name`/`arg_id` fields of that JSON are Metal-only
and simply unused on Vulkan.

## 3. What Metal does today (the behaviour to preserve)

- The binding is **the whole pool**, not the NVN buffer: `mtl_pool_add` (`nvn_mtl.m:517`) creates one
  zero-copy `MTLBuffer` over the pool's page-rounded range and stores `buf.gpuAddress`;
  `mtl_gpu_addr` (:590) returns `off = addr - pool.base` and `gpu = pool.gpu + off`.
- `encode_args_` (`nvn_mtl.m:6635`) writes that absolute GPU address into the argument slot for
  `NVN_RB_SBUFP`; Metal argument buffers hold raw addresses, so there is **no descriptor offset and no
  alignment requirement** anywhere in the Apple path. `QueryHostStorageBufferOffsetAlignment() = 16`
  (`IGpuAccessor.cs:212`) is a value Metal never exercises.
- Consequence: the shader's `base + offset` arithmetic resolves anywhere inside the pool, including past
  the NVN-declared size, and two bindings into one pool read the same bytes because they are the same
  `MTLBuffer`. Both properties must survive the port.

## 4. What the vendored engine solves, and what it does not

`dm/gfx/vulkan/engine/xbg_game.cpp` answers part of this and refuses the rest.

Solved (worth copying):

- Aliasing: storage ranges of a draw are sorted and merged (`:2811-2813`) before anything is bound, and each
  merged range is snapshotted into its own `VkBuffer` (`:2814-2820`), so two NVN bindings that overlap are
  the same allocation and see each other's writes.
- The 64-byte offset rule is enforced rather than assumed: `buffer_offset % minStorageBufferOffsetAlignment
  == 0` (`:2836`), and the snapshot base is padded to that alignment (`:2820`).
- Its driver segment is our ABI: `fill_driver` (`:2499`) writes guest address + u32 size into the c0 rows.

Not solved:

- **No windowing of any kind.** Every storage range must satisfy
  `r.size <= properties.limits.maxStorageBufferRange` (`:2809`) or the draw is rejected outright. The engine's
  answer to the 128 MiB limit is "refuse the game".
- **The pool is not the unit.** A range is copied per draw (`snapshot` / `readback_buffer`), so a 2–4 GB pool
  is out of the question: cost is O(bytes of every bound range, per draw). This works for its own use and is
  not a model this backend can inherit.
- **No buffer device address anywhere** in the engine, and no descriptor indexing used for storage buffers —
  `b.count <= 128` descriptors bound statically per binding (`:2806`).
- The smoke harness on the Mac lies about the limit: `hle_vk.m:272` reports `maxStorageBufferRange = 1 GiB`,
  four times the device's. `engine_smoke` cannot catch this on the Mac; only the probe can.

## 5. Options

Let `B` be the guest address of the NVN storage binding, `P` the base of the pool buffer the backend owns,
and `E` the extent of allocated bytes from `B` (for a pool mirror: `poolEnd - B`; for a per-binding copy:
the declared size).

### A. One descriptor per NVN binding, offset = `B - P`, range = `min(E, 128 MiB)`

- Descriptor offset must be 64-aligned. Two ways to get there:
  - **A1, shader-side**: build the Vulkan job with `QueryHasUnalignedStorageBuffer() = true` and
    `QueryHostStorageBufferOffsetAlignment() = 64`. The lowering exists and is two instructions per global
    access (`GlobalToStorage.cs:322-332`): `maskedBase = B & ~63`, `hostOffset = addr - maskedBase`, so the
    shader's index starts at the 64-aligned base, exactly where the descriptor does. Cost: 1 `AND` +
    1 `SUB` per guest global access, nothing on the Apple builds as long as the answer is a job field.
  - **A2, host-side**: require `B` 64-aligned. Depends on the game's NVN allocator alignment, which nothing
    in NVN promises and nothing here has measured — reject it until measured (§9).
- Range: with a pool mirror, `min(poolEnd - alignedBase, 128 MiB)` keeps in-pool over-reads working as on
  Metal. With a per-binding copy the range is the copied extent and over-reads stop at the copy (and break
  aliasing, §3).
- Per draw: one descriptor write per bound storage buffer. No shader change beyond A1's two ALU ops.
- Breaks when: an access reaches ≥ 128 MiB from the binding base, or `size > 128 MiB`.
- Behaviour, 64 MiB pool: one descriptor, whole pool, exact parity with Metal.
- Behaviour, 2–4 GB pool: descriptor covers 128 MiB from the binding base. Everything else is unchanged,
  because the shader never addresses the pool — only its binding.

### B. 128 MiB windows in a descriptor array

Bind `ceil(E / 128 MiB)` descriptors, index `offset >> 27`, window offset `offset & 0x7FFFFFF`.

- Needs a new SPIR-V pass (or a translator job field) in *every* shader with a storage buffer, hence a chain
  version bump, a full rebuild on Mac and iOS, and re-derived `c1_full.tsv` / `cb_extent.tsv`.
- Per access: 1 shift + 1 AND + a non-uniform index into the descriptor array. Per draw: `ceil(E / 128 MiB)`
  descriptors per slot; a 4 GB pool reached through one binding is 32.
- Requires `shaderStorageBufferArrayNonUniformIndexing` and `runtimeDescriptorArray`, whose feature bits the
  probe does not print (`vk_probe.c:593` prints only `descriptorIndexing`).
- Prior art says this is the shape that faults on this driver: the engine's own subgroup rewrites are a page
  fault on 740–799 (`xbg_adreno_policy.h:22-25`), so a shader-side index into a descriptor array has to be
  measured before anything is built on it (§6).

### C. Buffer device address / `PhysicalStorageBuffer64`

Ruled out, three independent reasons: `PhysicalStorageBuffer` requires the `Int64` capability and
`shaderInt64 = false` (line 165), so the module is invalid; `maxMemoryAllocationSize = 1 GiB` (line 187)
splits a 2–4 GB pool across allocations whose device addresses are not contiguous; and with no
`VK_EXT_external_memory_host` (line 288) those addresses belong to our copies, so a guest→device translation
layer would be needed on top. Nothing in the engine uses it either.

### D. Dynamic offsets

`VK_DESCRIPTOR_TYPE_STORAGE_BUFFER_DYNAMIC` slides a descriptor per draw, but the window is still 128 MiB and
a single invocation may touch two windows of one binding, so it does not solve the case it looks like it
solves. It is also a count-limited descriptor type, unlike the plain one.

### E. Sparse / aliasing the pool at many offsets

No `VK_KHR_sparse_binding`/`sparse_residency` on this device (absent from the extension list) and
`maxMemoryAllocationSize` is 1 GiB, so a pool cannot be given a single device range even conceptually.

| | Chain change | Shader cost | Per-draw cost | 64 MiB pool | 2–4 GB pool | Verdict |
|---|---|---|---|---|---|---|
| A1 | `Program.cs` answers, bumped | 2 ALU per global access | 1 desc/slot | exact | correct to 128 MiB from base | **recommended** |
| A2 | none | none | 1 desc/slot | exact | same, but depends on an unmeasured alignment | accept only if measured |
| B | new SPIR-V pass | shift+mask+array index per access | `ceil(E/128 MiB)` desc/slot | wasteful | "correct" if the driver cooperates | only if A1's cap is hit |
| C | — | — | — | — | — | impossible (`shaderInt64`) |
| D | — | — | 1 desc/slot | exact | fails on two windows per invocation | no |
| E | — | — | — | — | — | unavailable |

## 6. Recommendation

Build **A1 over a pool mirror**: one storage descriptor per NVN binding, offset `(B & ~63) - P`, range
`min(poolEnd - (B & ~63), 128 MiB)`, with the Vulkan job answering `QueryHasUnalignedStorageBuffer() = true`
and `QueryHostStorageBufferOffsetAlignment() = 64`. The c0 rows keep carrying the guest address and the NVN
size exactly as `nvn_mtl.m:6661` writes them, so the shader's own arithmetic and its multi-target range test
are untouched.

Why this and not B:

- The 64-bit space does not need presenting. `GlobalToStorage` already reduced every access to
  (binding, u32 offset); a binding's reach is what must fit in 128 MiB, not the pool.
- The pool mirror is what makes aliasing correct without per-draw merging, and it is the only model that
  reproduces Metal's in-pool over-read. Two NVN bindings into one pool become two offsets into one
  `VkBuffer`, which is also the only way a write through one binding is visible through the other without a
  copy. (Allocating and refreshing that mirror, and tracking dirty pages on Linux without
  `VK_EXT_external_memory_host`, is the memory backend's problem; this document only requires that it is one
  `VkBuffer` per pool, or per aliasing group.)
- A1 keeps Apple bit-identical: the two answers are job fields, the Apple job leaves them at the defaults
  (`false` / `16`), and with the unaligned path off the emitted SPIR-V is byte-for-byte what it is today.
- Cost is 2 integer ops per guest global access on Vulkan only, and zero per-draw work beyond the descriptor
  write that any backend does.

The sequence, when it is implemented: `Program.cs` answers → `python3 dm/gfx/tools/dmsh_chain.py --header`
and commit `dm/gfx/nvn/dmsh_chain.h` → full `dmsh_build.py` run per profile (Mac, and `IOSOUT` for iOS) →
re-derive `c1_full.tsv` / `cb_extent.tsv` → rebuild the host.

## 7. `subgroupSize = 64`

Not part of addressing, but it shares the same translation job and the same "re-decide, do not port" rule.

What is lane-width specific in the chain, today:

- `IGpuAccessor.QueryHostSubgroupSize()` defaults to **32** (`IGpuAccessor.cs:221`) and `dmsh_xlate`'s
  `Accessor` (`Program.cs:29`) does not override it — like it does not override
  `QueryHasUnalignedStorageBuffer` (:167) or `QueryHostStorageBufferOffsetAlignment` (:212). The overrides it
  has are at :114, :115, :124, :125, :127, :130. So every library built today assumes a 32-lane host.
- With 32, each of these takes the "one guest warp = one subgroup" branch, which is false on a 64-lane
  device: `EmitBallot` returns `Ballot(pred, 0)` = lanes 0–31 of the *hardware* subgroup
  (`InstEmitWarp.cs:116-120`); `EmitLoadSubgroupLaneId` returns `gl_SubgroupInvocationID` unmasked
  (`InstEmitMove.cs:173-181`); `GenerateSubgroupShuffleIndex` returns the source lane unmasked
  (`HelperFunctionManager.cs:352-362`). Any guest warp resident in hardware lanes 32–63 then votes, shuffles
  and reads `%laneid` from the wrong lanes — including shaders that only read `S2R SR_LANEID`, with no warp
  op at all.
- With 64, all three take the masked branch: lane `= id & 0x1f`, shuffle index `= (id & 0x60) | src`,
  ballot word chosen by `id & 32` (`InstEmitWarp.cs:121-133`, `HelperFunctionManager.cs:352-362`). That is
  exactly the scheme `xbg_spirv_warp.cpp:1-20` documents for this GPU family.
- **Answer 64, but pin the pipeline to 64.** `minSubgroupSize = 64` and `maxSubgroupSize = 128`
  (lines 223–224) mean the driver may compile a wave128. Shuffles survive that (`0x60` already selects the
  32-group out of four), but the ballot/vote path selects word 0/1 from lanes 64–127 instead of word 2/3, so
  half the wave votes with the other half's bits. Create the pipeline with
  `VkPipelineShaderStageRequiredSubgroupSizeCreateInfo{ requiredSubgroupSize = 64 }` — available, since
  `VK_EXT_subgroup_size_control` is present (line 72).
- Two gaps that decide how far this goes: the probe does not print `supportedSubgroupSizes` (only
  `subgroupSize`/min/max), and it does not print `subgroupStagesSupported`. The second matters because
  `dmsh_build.py:945` runs a Metal-only workaround, `spv_single_lane` (`:813-817`), on **every vertex
  shader** — "Metal has no SIMD-group functions in vertex functions", so the chain rewrites subgroups away
  and hands each lane its own value. Vulkan does have subgroups in vertex shaders when the stage bit is set;
  whether to keep that rewrite (exact, and always-uniform) or use real subgroups is a decision that needs
  the stage bits.
- The engine's two default-off rewrites (`gfx-quad-derivatives`, `gfx-warp32`,
  `xbg_adreno_policy.h:22-25`, page fault + `VK_ERROR_DEVICE_LOST` on 740–799) gate **the engine's own SPIR-V
  rewrites** — `xbg_spirv_quad.cpp:1-7` replaces shuffle-based derivatives with `OpDPdxFine/OpDPdyFine`,
  `xbg_spirv_warp.cpp` remaps lane ids. Our shaders get the equivalent operations from the translator as
  ordinary `OpGroupNonUniform*`; the gate does not transfer, and porting it by analogy would disable a path
  nobody has tested. It has to be measured at 64 lanes (§8).
  One more engine note that does reach us: 750–799 segfault while compiling subgroup instructions placed in
  a *called helper function* (`xbg_adreno_policy.h:49-60`) — and the translator emits exactly that shape
  (`HelperFunctionManager` shuffle/vote helpers). 740 is outside that range, so this is untested work here,
  not a known-bad path.

## 8. The experiment

One probe answers everything §5 leaves open, and it decides between A and B. A compute shader, not built
yet, run through the same chain and the same probe harness (`dm/gfx/vk/probe`) once the Vulkan path exists.

Setup: one `VkBuffer` of 256 MiB in memory type 4 (device local + host visible + coherent), each 4 KiB page
filled with a pattern derived from its page index, so a wrong window is identifiable, not just wrong.

Test 1 — windowing works at all (decides option B):
`layout(set=0, binding=0) buffer W { uint w[]; } win[2];` with the two elements bound at offset 0 and
128 MiB of that buffer, and each invocation indexing `win[off >> 27].w[(off & 0x7FFFFFF) >> 2]` for a
disjoint offset per lane. Expected: every page's checksum matches. Rules B out if the pipeline fails to
build, faults (kgsl page fault / `VK_ERROR_DEVICE_LOST`, the failure mode `xbg_adreno_policy.h` documents), or
any lane reads the other window.

Test 2 — divergence inside a wave64 (the same, but decisive): the same loop with the index chosen per lane so
that lanes 0–31 read window 0 and lanes 32–63 read window 1 in one wave. Expected: both halves correct. A
result where lanes 32–63 read window 0 means the array index was hoisted as uniform — B is then only usable
with one window per wave, which is not a design.

Test 3 — the out-of-range answer (decides how badly A fails at its cap): a single descriptor with
`range = 128 MiB` at offset 0, and reads at `off = 128 MiB ± 4`, `+ 4 KiB`, `+ 64 MiB`. Record what comes
back (0 / the neighbouring bytes / a fault). This is the only way to know what a shader that over-reads past
its window does on this driver, because the probe's `robustness2` is `nullDescriptor` only and neither
`robustBufferAccess` nor `robustBufferAccess2` is in the dump.

Test 4 — 64-lane subgroup sanity, in the same dispatch: a ballot and a shuffle that must not cross a 32-lane
boundary, run in a pipeline created with `requiredSubgroupSize = 64`. Confirms the §7 pin and shows whether
the translator's 64-lane SPIR-V compiles on this compiler at all.

Not in this experiment: crossing a 1 GiB *allocation* boundary. 256 MiB does not reach one; a 1.5 GB class
pool would need a third buffer and a second `vkAllocateMemory`, and that belongs with the memory backend.

Cheap prerequisite, no device: while the pool mirror is being built, count per NVN storage slot the maximum
`size` ever bound and the maximum `size + offset` ever reached from one base over a Mac session of the five
local games. That number, not an argument, says whether A's 128 MiB cap is ever approached.

## 9. What is not settled

- **The size distribution is unmeasured.** No run of the local games has recorded, per draw, the extent of
  each NVN storage binding or how far from the binding base the shader actually indexes. Until it does, "A is
  enough" is a prediction, not a measurement. It fails silently: the inline path has no bounds test
  (`GlobalToStorage.cs:408-445`), so an access past 128 MiB is out of range of the descriptor with nothing in
  the shader to notice.
- **Guest alignment of NVN binding addresses** is unmeasured. A1 makes this irrelevant; A2 depends on it.
- **Out-of-range storage reads** on this driver are unknown (test 3), so the failure *mode* of A's cap is
  unknown too.
- **No live SPIR-V was inspected for this document.** `dotnet` is not installed here and
  `dm/gfx/tools/dmsh_xlate_bin` is a Mach-O universal binary, so nothing on this machine can produce or
  disassemble a translated shader; there are no `.spv` files in the tree. Every claim above is read from the
  translator's and host's sources with `file:line`, not from a diff. The first thing the implementer should
  produce is that diff: one shader translated with the Vulkan job, then
  `spirv-dis | grep -E 'OpDecorate .* (Binding|DescriptorSet)|OpTypeInt 64'` — the second half proves
  `shaderInt64 = false` is safe for that shader, and `spirv-val --target-env vulkan1.3` with the device's
  features proves the module is even loadable.
