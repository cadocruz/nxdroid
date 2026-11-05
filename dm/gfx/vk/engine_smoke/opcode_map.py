#!/usr/bin/env python3
"""Command vocabulary map: this host's NVN command records against the vendored Vulkan engine's replay.

dm/gfx/nvn/nvn_obj.h is the master of the record format (dm/gfx/nvn/hle_nvn.c writes it, 93 game
profiles run through it); dm/gfx/vulkan/engine/xbg_game.cpp reads it. The two were written apart, so
the map is derived from the tree rather than from memory:

  opcode, value       parsed from the enum in nvn_obj.h (OP_END..OP_DEPTH_RANGES, then the fork block)
  emitted by          the first writer call (put_hdr / rec / REC / RECN / REC_SNAP) in dm/gfx/nvn/*.c,
                      or "not emitted"
  handler             the first `case <op>:` inside xbg_game.cpp's execute(), or "missing"
  metal               the case inside nvn_mtl.m's mtl_exec (the replay this port replaces), then the
                      section banner of the first handler anywhere in that file
  note                hand-written: what that handler has to do; see payload_mismatch.txt for the ids

A second block lists the ops the vendored fork added to NVN (named OP_XBG_* in nvn_obj.h after this
header's OP_COUNT_, because the fork's own numbers 39..49 are this header's OP_CLEAR_BUF..OP_BIND_TEX1),
what its own HLE recorded them for and whether this host emits anything of the kind.

Run it with no argument to rewrite opcode_map.txt; --check fails when the table is stale, when an op has
no note, when a payload-mismatch id names no heading in payload_mismatch.txt (or the reverse), and when
the payload sizes quoted there no longer match the header.

dm/gfx/vk/engine_smoke/README.md has the commands; docs/reference/android.md the finding.
"""
import os
import pathlib
import re
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[3]
OBJ = ROOT / "dm/gfx/nvn/nvn_obj.h"
NVN_DIR = ROOT / "dm/gfx/nvn"
HLE = NVN_DIR / "hle_nvn.c"
ENGINE = ROOT / "dm/gfx/vulkan/engine/xbg_game.cpp"
METAL = NVN_DIR / "nvn_mtl.m"
OUTPUT = HERE / "opcode_map.txt"
MISMATCH = HERE / "payload_mismatch.txt"

# One line per op: what the handler in xbg_game.cpp must do. A new opcode cannot enter the map without
# one (the script stops), which is the point: the enum and this vocabulary are the integration's contract.
NOTES = {
    "OP_END": "OK: ends the walk. Our EndRecording writes it (hle_nvn.c:855).",
    "OP_JUMP": "OK: continues at the 64-bit address in the payload (a segment switch).",
    "OP_BEGIN": "OK and never emitted: BeginRecording writes no record (an empty recording is only its END).",
    "OP_CALL": "OK: recurses into the handle with depth+1; our CopyCommands records it.",
    "OP_SIGNAL_EVENT": "OK: writes the guest event, deferred behind its submission when defer_events is on.",
    "OP_REPORT_COUNTER": "OK: timestamp (bottom of pipe), TIMESTAMP_TOP (top of pipe) and samples-passed queries with their writeback; a pipeline statistic is written as counter 0 with one [RED], as nvn_mtl.m writes it.",
    "OP_COPY_B2B": "OK: guest buffer copy (GPU or CPU), 3 x uint64 payload.",
    "OP_UPDATE_UB": "OK: writes n bytes of the payload into the uniform buffer at the recorded address.",
    "OP_SET_RT": "OK: keeps the record (colour/depth view and has_* are read by create_pass).",
    "OP_CLEAR_COLOR": "OK: index/mask/rgba, load action or full-pass triangle.",
    "OP_CLEAR_DS": "OK: depth/stencil with the caller's write masks.",
    "OP_VIEWPORTS": "FIXED in the draw (was P6): writes viewport[first..first+n) of the 16 and keeps viewport_n (highest index set + 1); a draw declares and sets that many viewports and scissors when the vertex / tessellation-evaluation / geometry shader writes ViewportIndex (draw_viewports; multiViewport and the enabled shaderOutputViewportIndex checked, validate_capabilities accepts 57 / 70 / 5254), one otherwise; a viewport mask (5255) is refused with [RED]. The front end enables shaderOutputViewportIndex and calls xbg_game_set_viewport_features (done, not measured on the device); the writer still records SetScissors / SetDepthRanges index 0 only, so a draw selecting viewport 1.. takes viewport 0's scissor and depth range (docs/reference/android.md).",
    "OP_SCISSOR": "OK: viewport 0's scissor (SetScissor, and index 0 of SetScissors).",
    "OP_DEPTH_RANGE": "OK: viewport 0's minDepth / maxDepth (SetDepthRange, and index 0 of SetDepthRanges).",
    "OP_BIND_PROGRAM": "OK structurally (prog_t serial + sd[6]); resolving the stages is the shader sprint's job.",
    "OP_BIND_STATE": "OK: kind selects the state object to copy out of bytes[0x18].",
    "OP_BIND_VATTR": "OK: NVN's BindVertexAttribState(n, states) has no first, so the writer records first = 0 and n <= 16 (hle_nvn.c), which is what the handler requires; the n states replace the table (the Metal replay does the same).",
    "OP_BIND_VSTREAM": "OK: variable-length record, first + n streams.",
    "OP_BIND_VBUF": "OK: variable-length record of NVNbufferRange.",
    "OP_BIND_UBO": "OK: stage/index/address/size.",
    "OP_BIND_SSBO": "OK: stage/index/address/size.",
    "OP_BIND_TEX": "FIXED (was P4): the handle table is tex[6][256] and the bound is 256, so separate textures at 128..255 bind; the slot number is not shifted (the shaders' reflection names 128+).",
    "OP_BIND_SAMP": "OK: slots 0..127, variable count.",
    "OP_STENCIL": "OK: face mask + value/write mask/reference.",
    "OP_POLY_OFFSET": "OK: factor/units/clamp (the clamp needs the depthBiasClamp feature).",
    "OP_DRAW": "FIXED (was P1): reads with draw_rec(), so the fields a compact record does not carry are 0 and not a read past the end of the record; honours instances / base_instance, and ind / mdi_cnt go to draw_indirect(), which reads the arguments at execution.",
    "OP_DRAW_IDX": "FIXED (was P2): reads with draw_idx_rec() (a compact record carries 32 bytes, up to ind, which includes instances and ibuf); ind / mdi_cnt go to draw_indirect().",
    "OP_DISPATCH": "FIXED (was P3): expands ind, reading the three group counts at execution from that address (they are usually written by the GPU earlier in the frame).",
    "OP_BARRIER": "OK in effect; the payload's cache bits are ignored (the handler always records its one full barrier).",
    "OP_SET_TEX_POOL": "OK: copies the dpool_t the address points to.",
    "OP_SET_SAMP_POOL": "OK: copies the dpool_t the address points to.",
    "OP_COPY_B2T": "OK: reads the record's own texture snapshot; region + view honoured.",
    "OP_COPY_STRIDE": "FIXED (was P5): branches on p_copy_stride.image, so an image stride reaches nvn_copy_pitch() as the image stride and not as the row stride.",
    "OP_BLEND_COLOR": "OK: 4 floats into the pipeline's blend constants.",
    "OP_COPY_T2B": "OK: reads the record's own texture snapshot; src holds the destination buffer.",
    "OP_BIND_IMG": "OK: image slots 0..15 (uint64_t img[6][16]).",
    "OP_COPY_T2T": "FIXED (was P7): branches on DM_COPY_RESOLVE, so a Downsample goes to resolve_texture() instead of a vkCmdCopyImage that cannot read a multisampled source.",
    "OP_RESET_COUNTER": "OK: samples-passed reset, closes the open query run; other types ignored (a statistic with one [RED]), as nvn_mtl.m does.",
    "OP_CLEAR_TEX": "OK: record's own snapshot, region, mask, float/uint constant.",
    "OP_CLEAR_BUF": "OK: fill the guest buffer at addr/size with value (Metal: mtl_sub_fill, in submission order).",
    "OP_DEPTH_CLAMP": "OK: a depth clamp toggle; wired to rs.depthClampEnable in the pipeline.",
    "OP_RENDER_COND": "OK: skip following draws/clears while the two counters at addr / addr+16 compare (mode 0/1), or unconditionally (2/3); a field under a pending timestamp report at that exact address is 0, under any other pending report or writeback unknown (drawn), as nvn_mtl.m rc_value (docs/reference/android.md).",
    "OP_FENCE_SYNC": "OK: fence the sync object with the submission that reaches this command (nvn_mtl.m sets fence/fenced at replay).",
    "OP_TF_BIND": "OK: transform-feedback buffer index 0..3 recorded to state.tf.",
    "OP_TF_STATE": "OK: begin/end/pause/resume of transform feedback recorded to state.tf_on.",
    "OP_RAST_DISCARD": "OK: rasterizer discard toggle wired to rs.rasterizerDiscardEnable in the pipeline.",
    "OP_VP_SWIZZLE": "OK: per-viewport clip x/y/z/w source copied to state.vp_sw.",
    "OP_BIND_TEX1": "OK: one combined handle 16 bytes into the record, read with bind_rec() (adds tbase/sbase); do not read it as p_bind_handles.",
    "OP_PRIM_RESTART": "OK: primitive restart on/off + index; wired to ia.primitiveRestartEnable in the pipeline.",
    "OP_BIND_UBO_SMALL": "OK: a 16-byte uniform binding, read with bind_buf_rec(); must not be read as p_bind_buf.",
    "OP_BIND_VBUF1": "OK: one 24-byte vertex buffer binding, read with vbuf_rec().",
    "OP_SCISSORS": "OK: scissors of viewports 1..15 (SetScissors past index 0), n entries (RECN); a draw that declares viewport i sets scissor i. Metal ignores it (index 0 only, as before).",
    "OP_DEPTH_RANGES": "OK: depth ranges of viewports 1..15 (SetDepthRanges past index 0), n entries (RECN); viewport i takes depth range i. Metal ignores it (index 0 only, as before).",
}

# Ops whose reader does not match the writer. The id is the heading of its account in payload_mismatch.txt;
# "writer" is right by construction (it is what the games run through).
PAYLOAD = {
    "OP_BARRIER": "P8",
}

# The ops the vendored fork added to NVN: name -> (what its HLE recorded it for, does this host emit the like?).
FORK = {
    "OP_XBG_SYNC_WAIT": ("a GPU-side wait on another sync object at replay time (sync_t fenced/fence were patched by the fork)",
                         "no: nvnCommandBufferWaitSync is a nop here (hle_nvn.c g_nops); our sync is OP_FENCE_SYNC plus the queue wait"),
    "OP_XBG_DISPATCH_INDIRECT": ("DispatchComputeIndirect, the group counts read from guest memory",
                                 "no: we carry the address in OP_DISPATCH.ind (which the engine must expand, P3)"),
    "OP_XBG_DRAW_INDIRECT_COUNT": ("a multi-draw whose count is read from guest memory",
                                   "no: we carry it in OP_DRAW.mdi_cnt / mdi_i (P1)"),
    "OP_XBG_WAIT_EVENT": ("a CPU spin on a guest event value before the following commands",
                          "no: nvnCommandBufferWaitEvent is a nop here; events are replayed by OP_SIGNAL_EVENT"),
    "OP_XBG_DEPTH_BOUNDS": ("SetDepthBounds (VkPipelineDepthStencilStateCreateInfo depth bounds)",
                            "no: SetDepthBounds is a nop here (hle_nvn.c g_nops)"),
    "OP_XBG_RESOLVE": ("Downsample, a multisample resolve",
                       "no: we record it as OP_COPY_T2T with DM_COPY_RESOLVE (the engine must branch on it, P7)"),
    "OP_XBG_DRAW_PLAN": ("a draw the fork planned at recording time (xbg_draw_call), to skip per-frame planning",
                         "no: a fork-side optimisation; we plan at replay"),
    "OP_XBG_DRAW_INDIRECT": ("one indirect draw (the arguments read from guest memory at replay)",
                             "no: ours is OP_DRAW with ind != 0 (P1)"),
    "OP_XBG_TYPED_CLEAR": ("ClearColor with a scalar constant for integer-format targets (xbg_typed_clear)",
                           "no: ClearColori / ClearColorui are recorded as floats in OP_CLEAR_COLOR and converted per attachment type"),
    "OP_XBG_COPY_IMAGE_STRIDE": ("SetCopyImageStride (bytes per layer / depth slice)",
                                 "no: we record it as OP_COPY_STRIDE with p_copy_stride.image = 1 (P5); the engine's own case for this op is dead code under our vocabulary"),
    "OP_XBG_PATCH_SIZE": ("the tessellation patch size (the fork's own OP_COUNT_, its number 40)",
                          "no: SetPatchSize is a nop here (hle_nvn.c g_nops); the patch size comes from the tessellation stage"),
}

# Payload shapes the map and payload_mismatch.txt quote: (label, C expression). Compiled against the header
# on every run, so a changed struct cannot leave a stale number in either file.
SIZES = [
    ("sizeof(p_draw)", "sizeof(p_draw)"),
    ("offsetof(p_draw, ind)", "offsetof(p_draw, ind)"),
    ("sizeof(p_draw_idx)", "sizeof(p_draw_idx)"),
    ("offsetof(p_draw_idx, ibuf)", "offsetof(p_draw_idx, ibuf)"),
    ("offsetof(p_draw_idx, ind)", "offsetof(p_draw_idx, ind)"),
    ("sizeof(p_dispatch)", "sizeof(p_dispatch)"),
    ("sizeof(p_bind_handles)", "sizeof(p_bind_handles)"),
    ("offsetof(p_bind_handles, h)", "offsetof(p_bind_handles, h)"),
    ("sizeof(p_bind_tex1)", "sizeof(p_bind_tex1)"),
    ("sizeof(p_copy_stride)", "sizeof(p_copy_stride)"),
    ("sizeof(p_bind_ubo_small)", "sizeof(p_bind_ubo_small)"),
    ("sizeof(p_bind_vbuf1)", "sizeof(p_bind_vbuf1)"),
    ("sizeof(p_viewports)", "sizeof(p_viewports)"),
    ("sizeof(tex_t)", "sizeof(tex_t)"),
]

# A writer is a call that puts a record into command memory. bind_handles() is the one helper that takes the
# op as an argument (bind_handles(c, OP_BIND_TEX, ...) -> RECN(c, op, ...)), so it is a writer call too.
WRITER = re.compile(r"\b(put_hdr|rec|REC|RECN|REC_SNAP|bind_handles)\s*\(")


def strip_comments(text):
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def enum_values(text, start_marker, known=None):
    """name -> value for the enum block that contains start_marker, expressions evaluated left to right."""
    at = text.rindex("enum", 0, text.index(start_marker))
    body = text[text.index("{", at) + 1:text.index("}", at)]
    values, next_value, last = dict(known or {}), 0, None
    for item in body.split(","):
        item = item.strip()
        if not item:
            continue
        name, _, expression = item.partition("=")
        name = name.strip()
        if expression.strip():
            value = eval(expression, {"__builtins__": {}}, dict(values))  # only OP_ names and + - * numbers
            values[name] = int(value)
        else:
            values[name] = next_value
        next_value = values[name] + 1
        last = name
    return values, last


def body_of(text, signature):
    """Source of one function, found by its signature line and closed by brace counting."""
    start = text.index(signature)
    depth = 0
    for i in range(text.index("{", start), len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return start, text[start:i]
    raise SystemExit(f"opcode_map: unterminated function {signature!r}")


def line_of(text, offset):
    return text.count("\n", 0, offset) + 1


def case_line(text, offset, name):
    match = re.search(r"case\s+%s\s*:" % name, text[offset:])
    return offset + match.start() if match else None


def case_line_fork(text, offset, number):
    match = re.search(r"case\s+OP_COUNT_\s*\+\s*%d\s*:" % number, text[offset:])
    return offset + match.start() if match else None


def writer(name):
    """First call in dm/gfx/nvn/*.c that writes this op into command memory."""
    pattern = re.compile(r"\b%s(?![A-Za-z0-9_])" % name)
    for path in sorted(NVN_DIR.glob("*.c")):
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            code = strip_comments(line)
            if pattern.search(code) and WRITER.search(code):
                return "%s:%d" % (path.relative_to(ROOT).as_posix(), number)
    return "not emitted"


def banners(text):
    out = []
    for number, line in enumerate(text.splitlines(), 1):
        if re.fullmatch(r"// -{3,} .+ -{3,}", line.strip()):
            out.append((number, line.strip().strip("-/ ").strip()))
    return out


def section(banner_list, line):
    found = "no section banner"
    for at, text in banner_list:
        if at < line:
            found = "%s (line %d)" % (text, at)
    return found


def payload_sizes():
    """Compile and run the sizeof probe for the structs both files quote."""
    # Included through the same paths the engine uses, so the numbers are the engine's numbers.
    source = "#include <stdio.h>\n#include <stddef.h>\n#include \"nvn_obj.h\"\nint main(void){\n"
    for label, expression in SIZES:
        source += '  printf("%s=%%zu\\n", (size_t)(%s));\n' % (label, expression)
    source += "  return 0;\n}\n"
    compiler = os.environ.get("CC", "cc")
    include = ["-I" + str(ROOT / "dm/gfx/nvn"), "-I" + str(ROOT / "dm/gfx/nvn/include"), "-I" + str(ROOT / "dm/gfx")]
    with tempfile.TemporaryDirectory() as folder:
        binary = pathlib.Path(folder) / "sizes"
        run = subprocess.run([compiler, "-std=gnu11", *include, "-x", "c", "-", "-o", str(binary)],
                             input=source, capture_output=True, text=True)
        if run.returncode:
            raise SystemExit("opcode_map: cannot compile the sizeof probe with %s:\n%s" % (compiler, run.stderr))
        probe = subprocess.run([str(binary)], capture_output=True, text=True)
    if probe.returncode:
        raise SystemExit("opcode_map: the sizeof probe failed")
    return [line for line in probe.stdout.splitlines() if line]


def table():
    header = strip_comments(OBJ.read_text(encoding="utf-8", errors="replace"))
    ops, last = enum_values(header, "OP_END")
    assert last == "OP_COUNT_", last
    ours = [(name, value) for name, value in sorted(ops.items(), key=lambda item: item[1]) if value < ops["OP_COUNT_"]]
    fork_ops, _ = enum_values(header, "OP_XBG_SYNC_WAIT", ops)
    fork = [(name, value) for name, value in sorted(fork_ops.items(), key=lambda item: item[1]) if name.startswith("OP_XBG_")]

    engine = ENGINE.read_text(encoding="utf-8", errors="replace")
    engine_at, engine_body = body_of(engine, "void execute(const uint8_t *pc,unsigned depth,uint64_t &budget)")
    metal = METAL.read_text(encoding="utf-8", errors="replace")
    metal_at, metal_body = body_of(metal, "void mtl_exec(const uint8_t *p)")
    metal_banners = banners(metal)

    rows, missing, mismatched = [], [], []
    for name, value in ours:
        if name not in NOTES:
            raise SystemExit("opcode_map: %s has no note: say what the handler must do" % name)
        handler = case_line(engine_body, 0, name)
        where = "xbg_game.cpp:%d" % line_of(engine, engine_at + handler) if handler is not None else "missing"
        if handler is None:
            missing.append(name)
        if name in PAYLOAD:
            mismatched.append(name)
        replay = case_line(metal_body, 0, name)
        first = re.search(r"case\s+%s\s*:" % name, metal)
        if replay is not None:
            replay_line = line_of(metal, metal_at + replay)
            if first is not None and line_of(metal, first.start()) != replay_line:
                where_metal = "nvn_mtl.m:%d, first case %d (%s)" % (replay_line, line_of(metal, first.start()),
                                                                   section(metal_banners, line_of(metal, first.start())))
            else:
                where_metal = "nvn_mtl.m:%d (%s)" % (replay_line, section(metal_banners, replay_line))
        else:
            where_metal = "missing"
        rows.append((name, value, writer(name), where, where_metal, PAYLOAD.get(name, ""), NOTES[name]))

    fork_rows = []
    for name, value in fork:
        if name not in FORK:
            raise SystemExit("opcode_map: fork op %s has no entry in FORK" % name)
        fork_rows.append((name, value, FORK[name][0], FORK[name][1]))

    numbers = {name: value for name, value in ops.items()}
    for name, value in fork:
        numbers[name] = value

    lines = [
        "# Command vocabulary: this host's NVN records (dm/gfx/nvn/nvn_obj.h, written by dm/gfx/nvn/hle_nvn.c)",
        "# against the vendored Vulkan engine's replay (dm/gfx/vulkan/engine/xbg_game.cpp, execute()).",
        "# Generated by dm/gfx/vk/engine_smoke/opcode_map.py; do not edit by hand (--check compares).",
        "# The writer is the ground truth (93 game profiles run through it); a row whose reader disagrees with it",
        "# carries a payload id here and its account in payload_mismatch.txt.",
        "# Columns: opcode, value, writer (dm/gfx/nvn/*.c, 'not emitted'), handler in xbg_game.cpp execute()",
        "#          ('missing' = falls into the default xbg_fatalf), Metal replay (the case in nvn_mtl.m's mtl_exec,",
        "#          then the first case anywhere in that file and its section banner), payload id, what the handler",
        "#          must do.",
        "# This host: %d ops, %d handled, %d missing, %d payload-mismatched." %
        (len(ours), len(ours) - len(missing), len(missing), len(mismatched)),
        "",
        "== this host's ops (OP_END..OP_DEPTH_RANGES): %d" % len(ours),
        "\t".join(("opcode", "value", "emitted by", "handler", "metal", "payload", "note")),
    ]
    for name, value, where, where_engine, where_metal, payload, note in rows:
        lines.append("\t".join((name, str(value), where, where_engine, where_metal, payload or "-", note)))
    lines += [
        "",
        "== the vendored fork's own ops (OP_XBG_* in nvn_obj.h, after this host's OP_COUNT_): %d" % len(fork),
        "\t".join(("opcode", "value", "the fork records it for", "this host emits the like?")),
    ]
    for name, value, why, need in fork_rows:
        lines.append("\t".join((name, str(value), why, need)))
    lines += [
        "",
        "== payload sizes quoted above and in payload_mismatch.txt (compiled against nvn_obj.h, so a changed",
        "== struct cannot leave a stale number): %d" % len(SIZES),
    ]
    sizes = payload_sizes()
    lines += sizes
    text = "\n".join(lines) + "\n"

    if "--check" in sys.argv[1:]:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if current != text:
            print("[RED] opcode_map: %s is stale; run python3 %s" % (OUTPUT.relative_to(ROOT), pathlib.Path(__file__).name))
            return 1
        if not MISMATCH.exists():
            print("[RED] opcode_map: %s is missing" % MISMATCH.relative_to(ROOT))
            return 1
        account = MISMATCH.read_text(encoding="utf-8")
        headings = set(re.findall(r"^== (P\d+) ", account, re.M))
        ids = set(PAYLOAD.values())
        if headings != ids:
            print("[RED] opcode_map: payload ids %s in the table, %s accounted for in payload_mismatch.txt"
                  % (sorted(ids), sorted(headings)))
            return 1
        quoted = dict(re.findall(r"(sizeof\([a-z_]+\)|offsetof\([a-z_]+, [a-z_]+\))=(\d+)", account))
        probe = dict(line.split("=", 1) for line in sizes)
        stale = {name: (value, probe.get(name)) for name, value in quoted.items() if probe.get(name) != value}
        if stale:
            print("[RED] opcode_map: payload_mismatch.txt quotes sizes the header no longer has: %s"
                  % ", ".join("%s=%s (now %s)" % (name, value, probe.get(name)) for name, (value, _) in sorted(stale.items())))
            return 1
        print("opcode_map: up to date (%d ops: %d handled, %d missing, %d payload-mismatched; %d fork-only)"
              % (len(ours), len(ours) - len(missing), len(missing), len(mismatched), len(fork)))
        return 0
    OUTPUT.write_text(text, encoding="utf-8", newline="\n")   # LF on every platform; the file in git is LF
    print("opcode_map: %d ops (%d handled, %d missing, %d payload-mismatched), %d fork-only -> %s"
          % (len(ours), len(ours) - len(missing), len(missing), len(mismatched), len(fork), OUTPUT.relative_to(ROOT).as_posix()))
    return 0


if __name__ == "__main__":
    sys.exit(table())
