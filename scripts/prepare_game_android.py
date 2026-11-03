#!/usr/bin/env python3
"""
Prepares Nintendo Switch game files for native execution on Android (nxdroid).
- Extracts Base and Update NSP / XCI files using hactool and prod.keys (or accepts an already extracted folder).
- Rewrites AArch64 executable modules (main, sdk, subsdk*) with --target=android and preserves fixups metadata.
- Packs RomFS assets into an indexed, fast-loading 'romfs.img'.
- Detects Title ID and automatically copies profile tables (shader_map.tsv, pso_manifest.tsv, shader_facts.tsv, xbg_game.cfg).
- Extracts NVN Maxwell shaders from ExeFS/RomFS, translates them to SPIR-V via dmsh_xlate, and compiles .xgs bundles (XGS1 format).
- Automatically discovers and imports MiiModel system data (0100000000000802) and saves (userdata.dat) from emulator NANDs (Citron, Eden, Yuzu).
- Optionally builds the Android APK (--build-apk) and installs it to the device (--install-apk).
- Optionally pushes all game assets and saves directly to the connected Android device via ADB (--push).
"""

import argparse
import hashlib
import json
import multiprocessing as mp
import os
import re
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import xml.etree.ElementTree as ET
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = REPO_ROOT / "dm" / "tools"
GFX_TOOLS_DIR = REPO_ROOT / "dm" / "gfx" / "tools"
GAMES_DIR = REPO_ROOT / "dm" / "games"

STAGE_INDEX = {"vs": 0, "hs": 1, "ds": 2, "gs": 3, "ps": 4, "cs": 5}
SSBO_BASE = {"vs": 0x110, "cs": 0x310, "gs": 0x510, "ps": 0x610}


def log(msg):
    print(f"[nxdroid-prep] {msg}")


def check_tool_requirements():
    try:
        import capstone  # noqa: F401
    except ImportError:
        log("ERROR: 'capstone' is required. Install with: pip install capstone")
        sys.exit(1)

    try:
        import lz4.block  # noqa: F401
    except ImportError:
        import ctypes
        import ctypes.util
        import types

        lib_name = ctypes.util.find_library("lz4") or "liblz4.so.1"
        try:
            lib = ctypes.CDLL(lib_name)
            decompress = lib.LZ4_decompress_safe
            decompress.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_int]
            decompress.restype = ctypes.c_int

            class LZ4BlockError(Exception):
                pass

            def lz4_decompress(raw, uncompressed_size=-1):
                buf = ctypes.create_string_buffer(uncompressed_size)
                res = decompress(raw, buf, len(raw), uncompressed_size)
                if res < 0:
                    raise LZ4BlockError("decompression failed")
                return buf.raw[:res]

            lz4_mod = types.ModuleType("lz4")
            lz4_block = types.ModuleType("lz4.block")
            vars(lz4_block).update(decompress=lz4_decompress, LZ4BlockError=LZ4BlockError)   # through vars(): a ModuleType declares no such attributes
            vars(lz4_mod)["block"] = lz4_block
            sys.modules["lz4"] = lz4_mod
            sys.modules["lz4.block"] = lz4_block
        except Exception:
            log("WARNING: lz4 library not found via pip or system CDLL; RomFS decompression may fail.")


def find_hactool(custom_path=None):
    if custom_path:
        p = Path(custom_path).expanduser().resolve()
        if p.exists() and os.access(p, os.X_OK):
            return p
    local_bin = TOOLS_DIR / "bin" / "hactool"
    if local_bin.exists() and os.access(local_bin, os.X_OK):
        return local_bin
    system_bin = shutil.which("hactool")
    if system_bin:
        return Path(system_bin)
    return None


def find_prod_keys(custom_path=None):
    if custom_path:
        p = Path(custom_path).expanduser().resolve()
        if p.exists():
            return p
    home = Path.home()
    candidates = [
        home / ".switch" / "prod.keys",
        home / ".local" / "share" / "citron" / "keys" / "prod.keys",
        home / ".local" / "share" / "eden" / "keys" / "prod.keys",
        home / ".local" / "share" / "yuzu" / "keys" / "prod.keys",
        home / ".local" / "share" / "ryujinx" / "system" / "prod.keys",
        home / ".config" / "yuzu" / "keys" / "prod.keys",
        home / ".config" / "citron" / "keys" / "prod.keys",
        home / ".config" / "eden" / "keys" / "prod.keys",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def find_nand_candidates(custom_path=None):
    dirs = []
    if custom_path:
        p = Path(custom_path).expanduser().resolve()
        if p.exists() and p.is_dir():
            dirs.append(p)
    home = Path.home()
    standard = [
        home / ".local" / "share" / "citron" / "nand",
        home / ".local" / "share" / "eden" / "nand",
        home / ".local" / "share" / "yuzu" / "nand",
        home / ".local" / "share" / "ryujinx" / "bis",
        home / ".config" / "yuzu" / "nand",
        home / ".config" / "citron" / "nand",
        home / ".config" / "eden" / "nand",
    ]
    for s in standard:
        if s.exists() and s.is_dir() and s not in dirs:
            dirs.append(s)
    return dirs


def detect_title_id(inp, work_dir=None, explicit_id=None):
    if explicit_id:
        tid = explicit_id.strip().upper()
        if len(tid) == 16:
            if tid.endswith("800"):
                tid = tid[:-3] + "000"
            return tid

    candidates = [str(inp.name), str(inp)]
    if work_dir and work_dir.exists():
        for xml in work_dir.glob("**/*.cnmt.xml"):
            try:
                tree = ET.parse(xml)
                root = tree.getroot()
                tid = root.findtext("Id") or root.findtext("TitleId")
                if tid and len(tid.strip()) == 16:
                    tid = tid.strip().upper()
                    if tid.endswith("800"):
                        tid = tid[:-3] + "000"
                    return tid
            except Exception:
                pass

    for text in candidates:
        m = re.search(r"\[(0100[0-9a-fA-F]{12})\]", text)
        if m:
            tid = m.group(1).upper()
            if tid.endswith("800"):
                tid = tid[:-3] + "000"
            return tid
        m2 = re.search(r"\b(0100[0-9a-fA-F]{12})\b", text)
        if m2:
            tid = m2.group(1).upper()
            if tid.endswith("800"):
                tid = tid[:-3] + "000"
            return tid

    return None


def rewrite_modules(exefs_dir, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    patch_script = TOOLS_DIR / "patch_nso.py"
    if not patch_script.exists():
        log(f"ERROR: Cannot find {patch_script}")
        sys.exit(1)

    modules = []
    candidates = ["main", "sdk"] + [f"subsdk{i}" for i in range(10)]
    for candidate in candidates:
        p = exefs_dir / candidate
        if p.exists() and p.is_file():
            modules.append((p, candidate))

    if not modules:
        for p in exefs_dir.glob("*.nso"):
            modules.append((p, p.stem))

    if not modules:
        log(f"WARNING: No executable modules found in {exefs_dir}")
        return

    for mod_path, mod_name in modules:
        log(f"Rewriting module '{mod_name}' for Android Bionic (--target=android)...")
        cmd = [
            sys.executable,
            str(patch_script),
            str(mod_path),
            str(out_dir),
            mod_name,
            "--target=android",
        ]
        res = subprocess.run(cmd, env={**os.environ, "PYTHONPATH": str(TOOLS_DIR)})
        if res.returncode != 0:
            log(f"ERROR rewriting {mod_name} (code {res.returncode})")
            sys.exit(res.returncode)

        patched_bin = out_dir / f"{mod_name}.patched.bin"
        final_dest = out_dir / mod_name
        if patched_bin.exists():
            shutil.copy2(patched_bin, final_dest)
            log(f"  ✓ Created ready module: {final_dest.name}")

        fixups_tsv = out_dir / f"{mod_name}.fixups.tsv"
        fixups_alt = out_dir / f"{mod_name}.fixups"
        if fixups_tsv.exists() and not fixups_alt.exists():
            try:
                shutil.copy2(fixups_tsv, fixups_alt)
            except Exception:
                pass


def pack_romfs(romfs_dir, out_img):
    romfs_script = TOOLS_DIR / "romfs_image.py"
    if not romfs_script.exists():
        log(f"ERROR: Cannot find {romfs_script}")
        sys.exit(1)

    log(f"Packing RomFS assets from {romfs_dir} -> {out_img}...")
    cmd = [
        sys.executable,
        str(romfs_script),
        str(romfs_dir),
        str(out_img),
    ]
    res = subprocess.run(cmd, env={**os.environ, "PYTHONPATH": str(TOOLS_DIR)})
    if res.returncode != 0:
        log(f"ERROR packing RomFS (code {res.returncode})")
        sys.exit(res.returncode)
    log(f"  ✓ RomFS image ready: {out_img.name} ({out_img.stat().st_size / (1024*1024):.1f} MB)")


def copy_profile_tables(title_id, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    if not title_id:
        return
    profile_dir = GAMES_DIR / title_id
    if not profile_dir.exists():
        log(f"Notice: Profile directory {profile_dir} not present; skipping profile table copy.")
        return

    tables = [
        "shader_map.tsv",
        "pso_manifest.tsv",
        "shader_facts.tsv",
        "pso_pairs.tsv",
        "shader_pairs.tsv",
        "game.tsv",
        "xbg_game.cfg",
    ]
    copied = 0
    for t in tables:
        src = profile_dir / t
        if src.exists():
            shutil.copy2(src, out_dir / t)
            copied += 1

    # Also copy any gfx-* marker files
    for marker in profile_dir.glob("gfx-*"):
        if marker.is_file():
            shutil.copy2(marker, out_dir / marker.name)
            copied += 1

    # Create default xbg_game.cfg if none existed
    cfg_file = out_dir / "xbg_game.cfg"
    if not cfg_file.exists():
        with open(cfg_file, "w") as f:
            f.write(f"# nxdroid game profile\ntitle_id = {title_id}\n")
        copied += 1

    log(f"  ✓ Copied {copied} profile config/table files for {title_id}")


def inspect_nca_dir(nca_dir, hactool_bin, keys_path):
    prog_nca = None
    ctrl_nca = None
    xml_files = list(nca_dir.glob("*.cnmt.xml"))

    if xml_files:
        try:
            tree = ET.parse(xml_files[0])
            root = tree.getroot()
            for content in root.findall("Content"):
                ctype = content.find("Type")
                cid = content.find("Id")
                if ctype is not None and cid is not None:
                    if ctype.text in ("Program", "Patch"):
                        target = nca_dir / f"{cid.text}.nca"
                        if target.exists():
                            prog_nca = target
                    elif ctype.text == "Control":
                        target = nca_dir / f"{cid.text}.nca"
                        if target.exists():
                            ctrl_nca = target
        except Exception:
            pass

    if not prog_nca:
        largest_nca = None
        largest_sz = 0
        for nca in nca_dir.glob("*.nca"):
            if nca.name.endswith(".cnmt.nca"):
                continue
            sz = nca.stat().st_size
            if sz > largest_sz:
                largest_sz = sz
                largest_nca = nca
        prog_nca = largest_nca

    if not ctrl_nca:
        for nca in nca_dir.glob("*.nca"):
            if nca != prog_nca and 400 * 1024 <= nca.stat().st_size <= 15 * 1024 * 1024:
                ctrl_nca = nca
                break

    return prog_nca, ctrl_nca


def extract_container(archive_path, target_dir, hactool_bin, keys_path):
    target_dir.mkdir(parents=True, exist_ok=True)
    ext = archive_path.suffix.lower()
    is_xci = ext in (".xci", ".xcz")

    if is_xci:
        cmd = [
            str(hactool_bin),
            "--disablekeywarns",
            "-k", str(keys_path),
            "-t", "xci",
            f"--securedir={target_dir}",
            str(archive_path),
        ]
    else:
        cmd = [
            str(hactool_bin),
            "--disablekeywarns",
            "-k", str(keys_path),
            "-t", "pfs0",
            f"--pfs0dir={target_dir}",
            str(archive_path),
        ]

    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        log(f"ERROR: hactool container extraction failed for {archive_path.name}:\n{res.stderr or res.stdout}")
        sys.exit(1)


def extract_archive(base_file, update_file, work_dir, hactool_bin, keys_path):
    work_dir.mkdir(parents=True, exist_ok=True)
    nca_base_dir = work_dir / "ncas_base"
    log(f"Extracting base archive: {base_file.name}...")
    extract_container(base_file, nca_base_dir, hactool_bin, keys_path)
    base_prog, base_ctrl = inspect_nca_dir(nca_base_dir, hactool_bin, keys_path)

    if not base_prog:
        log("ERROR: Could not find Program NCA in base archive.")
        sys.exit(1)
    log(f"Found Base Program NCA: {base_prog.name} ({base_prog.stat().st_size / (1024*1024):.1f} MB)")

    upd_prog = None
    upd_ctrl = None
    if update_file and update_file.exists():
        nca_upd_dir = work_dir / "ncas_upd"
        log(f"Extracting update archive: {update_file.name}...")
        extract_container(update_file, nca_upd_dir, hactool_bin, keys_path)
        upd_prog, upd_ctrl = inspect_nca_dir(nca_upd_dir, hactool_bin, keys_path)
        if upd_prog:
            log(f"Found Update Program NCA: {upd_prog.name} ({upd_prog.stat().st_size / (1024*1024):.1f} MB)")

    exefs_dir = work_dir / "exefs"
    romfs_dir = work_dir / "romfs"
    ctrl_dir = work_dir / "control"
    exefs_dir.mkdir(parents=True, exist_ok=True)
    romfs_dir.mkdir(parents=True, exist_ok=True)
    ctrl_dir.mkdir(parents=True, exist_ok=True)

    if upd_prog:
        log(f"Extracting ExeFS with hactool (--basenca={base_prog.name})...")
        subprocess.run([
            str(hactool_bin),
            "--disablekeywarns",
            "-k", str(keys_path),
            f"--basenca={base_prog}",
            f"--exefsdir={exefs_dir}",
            str(upd_prog),
        ], stdout=subprocess.DEVNULL, check=True)

        log(f"Extracting merged RomFS with hactool (--basenca={base_prog.name})...")
        subprocess.run([
            str(hactool_bin),
            "--disablekeywarns",
            "-k", str(keys_path),
            f"--basenca={base_prog}",
            f"--romfsdir={romfs_dir}",
            str(upd_prog),
        ], stdout=subprocess.DEVNULL, check=True)
    else:
        log(f"Extracting ExeFS from base {base_prog.name}...")
        subprocess.run([
            str(hactool_bin),
            "--disablekeywarns",
            "-k", str(keys_path),
            f"--exefsdir={exefs_dir}",
            str(base_prog),
        ], stdout=subprocess.DEVNULL, check=True)

        log(f"Extracting RomFS from base {base_prog.name}...")
        subprocess.run([
            str(hactool_bin),
            "--disablekeywarns",
            "-k", str(keys_path),
            f"--romfsdir={romfs_dir}",
            str(base_prog),
        ], stdout=subprocess.DEVNULL, check=True)

    chosen_ctrl = upd_ctrl or base_ctrl
    if chosen_ctrl and chosen_ctrl.exists():
        log(f"Extracting Control metadata from {chosen_ctrl.name}...")
        subprocess.run([
            str(hactool_bin),
            "--disablekeywarns",
            "-k", str(keys_path),
            f"--romfsdir={ctrl_dir}",
            str(chosen_ctrl),
        ], stdout=subprocess.DEVNULL)

    return exefs_dir, romfs_dir, ctrl_dir


# --- Shader Extraction and Compilation Engine ---

def _scan_blob_worker(item):
    img_path, start, length, rel = item
    out_file = []
    try:
        import shader_split
        with open(img_path, "rb") as f:
            f.seek(start)
            blob = f.read(length)
        shader_split.scan_blob(blob, rel, out_file)
    except Exception:
        pass
    results = []
    for entry in out_file:
        name, st, ctl, code = entry
        import shader_split
        skey = shader_split.skey(ctl, code)
        ctl_key = hashlib.sha256(ctl[:0x880]).hexdigest()[:16]
        results.append((skey, st, ctl, code, ctl_key))
    return results


def _rewrite_depth(words):
    bound = words[3]
    per_vertex_struct = None
    per_vertex_var = None
    float_type = None
    int_type = None

    i = 5
    while i < len(words):
        w = words[i]
        wc = w >> 16
        op = w & 0xFFFF
        if not wc:
            break
        if op == 72 and wc >= 5:
            if words[i + 2] == 0 and words[i + 3] == 11 and words[i + 4] == 0:
                per_vertex_struct = words[i + 1]
        elif op == 71 and wc >= 4:
            if words[i + 2] == 11 and words[i + 3] == 0:
                per_vertex_var = ("var", words[i + 1])
        elif op == 22 and wc == 3 and words[i + 2] == 32:
            float_type = words[i + 1]
        elif op == 21 and wc == 4 and words[i + 2] == 32:
            int_type = words[i + 1]
        i += wc

    if not per_vertex_struct and not per_vertex_var:
        return words

    ptr_output_struct = None
    ptr_output_float = None
    i = 5
    while i < len(words):
        w = words[i]
        wc = w >> 16
        op = w & 0xFFFF
        if not wc:
            break
        if op == 32 and wc == 4 and words[i + 2] == 3:
            if per_vertex_struct and words[i + 3] == per_vertex_struct:
                ptr_output_struct = words[i + 1]
            if float_type and words[i + 3] == float_type:
                ptr_output_float = words[i + 1]
        if op == 59 and wc >= 4 and words[i + 3] == 3:
            if ptr_output_struct and words[i + 1] == ptr_output_struct:
                per_vertex_var = ("struct", words[i + 2])
        i += wc

    if not per_vertex_var or not float_type:
        return words

    new_types_consts = []
    if not int_type:
        int_type = bound
        bound += 1
        new_types_consts.append([21 | (4 << 16), int_type, 32, 1])
    if not ptr_output_float:
        ptr_output_float = bound
        bound += 1
        new_types_consts.append([32 | (4 << 16), ptr_output_float, 3, float_type])

    c_0 = bound; bound += 1
    c_2 = bound; bound += 1
    c_3 = bound; bound += 1
    c_half = bound; bound += 1

    new_types_consts.append([43 | (4 << 16), int_type, c_0, 0])
    new_types_consts.append([43 | (4 << 16), int_type, c_2, 2])
    new_types_consts.append([43 | (4 << 16), int_type, c_3, 3])
    new_types_consts.append([43 | (4 << 16), float_type, c_half, 0x3F000000])

    first_func_idx = 5
    while first_func_idx < len(words):
        if (words[first_func_idx] & 0xFFFF) == 54:
            break
        first_func_idx += words[first_func_idx] >> 16

    ptr_z = bound; bound += 1
    ptr_w = bound; bound += 1
    val_z = bound; bound += 1
    val_w = bound; bound += 1
    half_z = bound; bound += 1
    half_w = bound; bound += 1
    new_z = bound; bound += 1

    instrs = []
    if per_vertex_var[0] == "struct":
        instrs.append([65 | (6 << 16), ptr_output_float, ptr_z, per_vertex_var[1], c_0, c_2])
        instrs.append([65 | (6 << 16), ptr_output_float, ptr_w, per_vertex_var[1], c_0, c_3])
    else:
        instrs.append([65 | (5 << 16), ptr_output_float, ptr_z, per_vertex_var[1], c_2])
        instrs.append([65 | (5 << 16), ptr_output_float, ptr_w, per_vertex_var[1], c_3])

    instrs.append([61 | (4 << 16), float_type, val_z, ptr_z])
    instrs.append([61 | (4 << 16), float_type, val_w, ptr_w])
    instrs.append([133 | (5 << 16), float_type, half_z, val_z, c_half])
    instrs.append([133 | (5 << 16), float_type, half_w, val_w, c_half])
    instrs.append([129 | (5 << 16), float_type, new_z, half_z, half_w])
    instrs.append([62 | (3 << 16), ptr_z, new_z])

    flat_instrs = [w for ins in instrs for w in ins]
    flat_types = [w for ins in new_types_consts for w in ins]
    new_words = words[:first_func_idx] + flat_types + words[first_func_idx:]

    ret_idx = len(new_words) - 1
    while ret_idx >= 5:
        if (new_words[ret_idx] & 0xFFFF) == 253:
            break
        ret_idx -= 1

    if ret_idx < 5:
        return words
    final_words = new_words[:ret_idx] + flat_instrs + new_words[ret_idx:]
    final_words[3] = bound
    return final_words


def _decode_tex_handle(handle, cbuf_slot, is_image):
    tb = (cbuf_slot & 0xFFFF) if cbuf_slot >= 0 else 2
    sb = ((cbuf_slot >> 16) - 1) if cbuf_slot >= 0 and (cbuf_slot >> 16) else tb
    o0 = handle & 0x3FFF
    o1 = (handle >> 14) & 0x3FFF
    ty = handle >> 28

    def slot_from_word(w, base, cb):
        byte_off = w * 4
        if cb == 2 and byte_off >= base and (byte_off - base) % 8 == 0:
            return (byte_off - base) // 8
        return None

    words = [o0] + ([o1] if ty else [])
    if is_image:
        img_s = next(
            (slot_from_word(x, 0x120, tb) for x in words if 0x120 <= x * 4 < 0x120 + 8 * 8 and slot_from_word(x, 0x120, tb) is not None),
            None,
        )
        return (img_s if img_s is not None else 0), 0xFFFFFFFF

    tw = [o0] if ty == 3 else words
    t_slot = next((slot_from_word(x, 0x20, tb) for x in tw if slot_from_word(x, 0x20, tb) is not None and x * 4 < 0x168), None)
    if t_slot is None:
        t_slot = next((128 + s for x in tw if (s := slot_from_word(x, 0x168, tb)) is not None and x * 4 < 0x568), None)

    s_slot = next((slot_from_word(x, 0x568, sb) for x in words if x * 4 >= 0x568 and slot_from_word(x, 0x568, sb) is not None), None) if ty != 3 else None
    if ty == 3:
        s_slot = (handle >> 14) & 0x3FFF
    if ty == 0:
        s_slot = 0xFFFFFFFF

    return (t_slot if t_slot is not None else 0), (s_slot if s_slot is not None else 0xFFFFFFFF)


def _parse_spirv_resources(words):
    var_binding = {}
    var_builtin = set()
    var_location = {}
    types = {}
    vars_by_id = {}

    i = 5
    while i < len(words):
        w = words[i]
        wc = w >> 16
        op = w & 0xFFFF
        if not wc:
            break
        if op == 71 and wc >= 4:
            target = words[i + 1]
            dec = words[i + 2]
            val = words[i + 3]
            if dec == 33:
                var_binding[target] = val
            elif dec == 30:
                var_location[target] = val
            elif dec == 11:
                var_builtin.add(target)
        elif op in (21, 22, 23, 25, 27, 28, 32):
            types[words[i + 1]] = (op, words[i:i + wc])
        elif op == 59 and wc >= 4:
            vars_by_id[words[i + 2]] = (words[i + 1], words[i + 3])
        i += wc

    return var_binding, var_location, var_builtin, types, vars_by_id


def _inspect_image_type(types, type_id):
    curr = type_id
    count = 1
    while curr in types:
        op, w = types[curr]
        if op == 32:
            curr = w[3]
        elif op == 28:
            curr = w[2]
        elif op == 27:
            curr = w[2]
            break
        elif op == 25:
            break
        else:
            break

    is_sampled_image = False
    if curr in types and types[curr][0] == 27:
        is_sampled_image = True
        curr = types[curr][1][2]

    if curr not in types or types[curr][0] != 25:
        flags = (1 << 31) | (1 << 8)
        return (1 if is_sampled_image else 2), count, flags

    w = types[curr][1]
    sampled_type = w[2]
    dim = w[3] & 7
    depth = 1 if w[4] == 1 else 0
    array = 1 if w[5] != 0 else 0
    ms = 1 if w[6] != 0 else 0
    sampled = w[7]
    image_format = w[8] if len(w) > 8 else 0
    access = w[9] if len(w) > 9 else -1

    scalar = 0
    if sampled_type in types:
        sop, sw = types[sampled_type]
        if sop == 21:
            scalar = 1 if sw[3] == 1 else 2
        elif sop == 22:
            scalar = 0

    rw_flags = 0
    if image_format == 0:
        if access == 0:
            rw_flags = 2
        elif access == 1:
            rw_flags = 1
        elif access == 2:
            rw_flags = 3
        else:
            rw_flags = 1 if sampled == 2 else 0

    flags = (1 << 31) | (dim << 8) | (array << 12) | (ms << 13) | (depth << 14) | (scalar << 16) | rw_flags
    if sampled == 2:
        desc_type = 5 if dim == 5 else 3
    elif is_sampled_image or sampled == 1:
        desc_type = 4 if dim == 5 else (1 if is_sampled_image else 2)
    else:
        desc_type = 1

    return desc_type, count, flags


def _sanitize_spirv_words(words):
    if len(words) < 5 or words[0] != 0x07230203:
        return words
    has_fp64 = False
    has_interlock = False
    i = 5
    while i < len(words):
        w = words[i]
        cnt = w >> 16
        op = w & 0xFFFF
        if not cnt or i + cnt > len(words):
            break
        if op == 22 and cnt >= 3 and words[i + 2] == 64:
            has_fp64 = True
        elif op in (5364, 5365):
            has_interlock = True
        i += cnt

    out_words = words[:5]
    i = 5
    while i < len(words):
        w = words[i]
        cnt = w >> 16
        op = w & 0xFFFF
        if not cnt or i + cnt > len(words):
            break
        drop = False
        if op == 17:
            cap = words[i + 1]
            if cap == 10 and not has_fp64:
                drop = True
            elif cap == 5378 and not has_interlock:
                drop = True
        elif op == 10:
            name_bytes = b"".join(struct.pack("<I", words[i + j]) for j in range(1, cnt))
            name = name_bytes.split(b"\x00")[0].decode("ascii", "replace")
            if name == "SPV_EXT_fragment_shader_interlock" and not has_interlock:
                drop = True
        if not drop:
            out_words.extend(words[i:i + cnt])
        i += cnt
    return out_words


def build_xgs_bundle(skey, stage_str, spv_bytes, res_json, c1_bytes):
    stage = STAGE_INDEX[stage_str]
    stage_offset = stage * 64 if stage < 5 else 0

    words = list(struct.unpack(f"<{len(spv_bytes)//4}I", spv_bytes))
    words = _sanitize_spirv_words(words)

    inputs = []
    if stage == 0:
        var_binding, var_location, var_builtin, types, vars_by_id = _parse_spirv_resources(words)
        for var_id, (ptr_type, st_class) in vars_by_id.items():
            if st_class == 1:
                if var_id in var_location and var_id not in var_builtin:
                    loc = var_location[var_id]
                    if loc < 16 and loc not in inputs:
                        inputs.append(loc)
        inputs.sort()
        words = _rewrite_depth(words)

    if stage_offset > 0:
        i = 5
        while i < len(words):
            w = words[i]
            wc = w >> 16
            op = w & 0xFFFF
            if not wc:
                break
            if op == 71 and wc >= 4 and words[i + 2] == 33:
                words[i + 3] += stage_offset
            i += wc

    var_binding, var_location, var_builtin, types, vars_by_id = _parse_spirv_resources(words)
    binding_to_var = {b: var_id for var_id, b in var_binding.items()}
    bindings = []

    # 1. Support buffer
    bindings.append({
        "binding": 0 + stage_offset,
        "type": 6,
        "count": 1,
        "bytes": 1392,
        "source": 1,
        "slot": 0,
        "sampler_slot": 0xFFFFFFFF,
        "flags": 0,
    })

    # 2. Constant buffers
    for cb in res_json.get("cbufs", []):
        orig_b = cb["binding"]
        b = orig_b + stage_offset
        slot = cb["slot"]
        if slot == 0:
            source, slot_val, b_bytes = 5, 0, 0x1000
        elif slot == 1:
            source, slot_val, b_bytes = 4, 0, len(c1_bytes)
        elif slot == 2:
            source, slot_val, b_bytes = 6, 0, 0x1000
        elif 3 <= slot <= 16:
            source, slot_val, b_bytes = 2, slot - 3, 65536
        else:
            continue

        bindings.append({
            "binding": b,
            "type": 6,
            "count": 1,
            "bytes": b_bytes,
            "source": source,
            "slot": slot_val,
            "sampler_slot": 0xFFFFFFFF,
            "flags": 0,
        })

    # 3. Storage buffers
    for sb in res_json.get("sbufs", []):
        orig_b = sb["binding"]
        b = orig_b + stage_offset
        cb_slot = sb.get("cb_slot", -1)
        cb_offset = sb.get("cb_offset", 0)
        if cb_slot == 0:
            off = cb_offset * 4
            if stage_str == "cs" and 0x210 <= off < 0x310:
                source = 2
                slot_val = (off - 0x210) // 16
            else:
                source = 3
                ssbo_base = SSBO_BASE.get(stage_str, 0x110)
                slot_val = (off - ssbo_base) // 16
        else:
            source = 3
            slot_val = sb.get("slot", 0)

        bindings.append({
            "binding": b,
            "type": 7,
            "count": 1,
            "bytes": 0,
            "source": source,
            "slot": max(0, slot_val),
            "sampler_slot": 0xFFFFFFFF,
            "flags": 0,
        })

    # 4. Textures and images
    for group, is_img in ((res_json.get("textures", []), False), (res_json.get("images", []), True)):
        for t in group:
            orig_b = t["binding"]
            b = orig_b + stage_offset
            var_id = binding_to_var.get(b)
            if var_id and var_id in vars_by_id:
                desc_type, count, flags = _inspect_image_type(types, vars_by_id[var_id][0])
            else:
                desc_type = 3 if is_img else 1
                count = t.get("array", 1)
                flags = (1 << 31) | (1 << 8)

            t_slot, s_slot = _decode_tex_handle(t.get("handle", 0), t.get("cbuf_slot", -1), is_img)
            bindings.append({
                "binding": b,
                "type": desc_type,
                "count": max(1, count),
                "bytes": 0,
                "source": 8 if is_img else 7,
                "slot": t_slot,
                "sampler_slot": s_slot,
                "flags": flags,
            })

    bindings.sort(key=lambda x: x["binding"])
    final_spv = struct.pack(f"<{len(words)}I", *words)

    hdr = struct.pack(
        "<8I",
        0x31534758,  # 'XGS1'
        1,
        stage,
        len(bindings),
        len(inputs),
        len(c1_bytes),
        len(final_spv),
        0,
    )
    bind_bytes = b"".join(
        struct.pack(
            "<8I",
            b["binding"], b["type"], b["count"], b["bytes"],
            b["source"], b["slot"], b["sampler_slot"], b["flags"],
        ) for b in bindings
    )
    input_bytes = b"".join(struct.pack("<I", loc) for loc in inputs)
    return hdr + bind_bytes + input_bytes + c1_bytes + final_spv


def extract_and_build_shaders(title_id, exefs_dir, romfs_img, romfs_dir, out_dir, work_dir, rebuild_shaders=False):
    log("=== Extracting and Compiling Shaders ===")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_xgs_dir = out_dir

    # Check for existing .xgs bundles in work_dir or profile
    prebuilt_candidates = [
        work_dir / "generated_xgs",
        work_dir / "shaders",
        GAMES_DIR / title_id / "shaders" if title_id else None,
    ]
    for pc in prebuilt_candidates:
        if pc and pc.exists() and not rebuild_shaders:
            existing = list(pc.glob("*.xgs"))
            if len(existing) > 10:
                log(f"Found {len(existing)} prebuilt .xgs shaders in {pc}. Copying...")
                for x in existing:
                    dest = out_xgs_dir / x.name
                    if not dest.exists():
                        shutil.copy2(x, dest)
                log(f"  ✓ Copied prebuilt shaders into {out_xgs_dir}")
                return

    sys.path.insert(0, str(TOOLS_DIR))
    sys.path.insert(0, str(GFX_TOOLS_DIR))
    if title_id:
        os.environ["DM_GAME"] = title_id

    try:
        import romfs
        import shader_split
    except Exception as e:
        log(f"Notice: shader_split / romfs tools could not be loaded ({e}); skipping offline shader compilation.")
        return

    facts = {}
    facts_candidates = [
        out_dir / "shader_facts.tsv",
        GAMES_DIR / title_id / "shader_facts.tsv" if title_id else None,
    ]
    for fc in facts_candidates:
        if fc and fc.exists():
            with open(fc, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split("\t")
                    if len(parts) >= 2:
                        try:
                            facts[parts[0]] = json.loads(parts[1])
                        except Exception:
                            pass
            break

    found_shaders = {}
    main_path = exefs_dir / "main"
    if main_path.exists():
        try:
            main_img = shader_split.nso_image(str(main_path))
            out_main = []
            shader_split.scan_blob(main_img, "main", out_main)
            for item in out_main:
                name, st, ctl, code = item
                skey = shader_split.skey(ctl, code)
                ctl_key = hashlib.sha256(ctl[:0x880]).hexdigest()[:16]
                found_shaders[skey] = (st, ctl, code, ctl_key)
            log(f"  ✓ Scanned ExeFS main: {len(out_main)} shaders found")
        except Exception as e:
            log(f"Notice: Main NSO shader scan note: {e}")

    # Scan RomFS
    romfs_files = set()
    shmap = out_dir / "shader_map.tsv"
    if shmap.exists():
        with open(shmap, encoding="utf-8") as f:
            for line in f:
                if line.startswith("#"):
                    continue
                parts = line.strip().split("\t")
                if len(parts) >= 5:
                    fp = parts[4].split("#")[0]
                    if fp != "main":
                        if ".sarc/" in fp:
                            fp = fp.split(".sarc/")[0] + ".sarc"
                        romfs_files.add(fp.rstrip("/"))

    img = None
    if romfs_img and romfs_img.exists():
        try:
            img = romfs.Image(str(romfs_img))
        except Exception:
            img = None

    if img:
        targets = ("/Course/", "/RaceCommon/", "/UI/", "/Driver/", "/Kart/", "/Item/", "/Obj/", "/Effect/", "/Common/", "/UI3D/")
        exts = (".ptcl", ".sharcb", ".sarc", ".szs", ".bfsha", ".bnsh", ".bfres")

        def walk_tree(k, path=""):
            a, b, _, _, t, _ = img.entry(k)
            if t:
                yield path, k
            else:
                for name, child_k in img.children(k):
                    subpath = f"{path}/{name}" if path else f"/{name}"
                    yield from walk_tree(child_k, subpath)

        for p, _ in walk_tree(0):
            if any(p.startswith(t) for t in targets) or any(p.endswith(ext) for ext in exts):
                romfs_files.add(p)

        scan_items = []
        for rel in sorted(romfs_files):
            try:
                k_entry = img.find(rel.lstrip("/"))
                if k_entry is None:
                    continue
                start, length = img.entry(k_entry)[:2]
                scan_items.append((str(romfs_img), start, length, rel))
            except Exception:
                pass

        if scan_items:
            log(f"Scanning {len(scan_items)} RomFS asset files for shaders...")
            ctx = mp.get_context("fork")
            workers = min(os.cpu_count() or 8, 16)
            with ProcessPoolExecutor(max_workers=workers, mp_context=ctx) as pool:
                for res_list in pool.map(_scan_blob_worker, scan_items, chunksize=8):
                    for skey, st, ctl, code, ctl_key in res_list:
                        found_shaders[skey] = (st, ctl, code, ctl_key)

    log(f"Total unique shaders identified: {len(found_shaders)}")
    if not found_shaders:
        return

    xlate_work = work_dir / "xlate_work"
    code_dir = xlate_work / "code"
    spv_out_dir = xlate_work / "spv"
    code_dir.mkdir(parents=True, exist_ok=True)
    spv_out_dir.mkdir(parents=True, exist_ok=True)

    jobs = []
    c1_map = {}
    for skey, (st, ctl, code, ctl_key) in found_shaders.items():
        res_file = spv_out_dir / f"{skey}.res.json"
        spv_file = spv_out_dir / f"{skey}.spv"
        c1o, c1t = struct.unpack_from("<2I", ctl, 0x700)
        c1 = code[c1o:c1t]
        c1_map[skey] = c1

        skey_xgs = out_xgs_dir / f"{skey}.xgs"
        ctl_xgs = out_xgs_dir / f"{ctl_key}.xgs"
        if skey_xgs.exists() and ctl_xgs.exists() and not rebuild_shaders:
            continue

        if res_file.exists() and spv_file.exists():
            continue

        code_bin = code[0x30:] if st != "cs" else (code[0x100:] if code[:4] == b"\x79\x56\x34\x12" else code)
        code_path = code_dir / f"{skey}.bin"
        with open(code_path, "wb") as cf:
            cf.write(code_bin)

        job = {
            "key": skey,
            "stage": st,
            "code": str(code_path),
            "c1": c1.hex(),
            "debug": False,
            "reduced": True,
        }
        if skey in facts:
            job.update(facts[skey])
        jobs.append(job)

    if jobs:
        jobs_file = xlate_work / "jobs.json"
        with open(jobs_file, "w") as jf:
            json.dump(jobs, jf)

        dll_path = GFX_TOOLS_DIR / "dmsh_xlate" / "bin" / "Debug" / "net10.0" / "dmsh_xlate.dll"
        if not dll_path.exists():
            dll_path = GFX_TOOLS_DIR / "dmsh_xlate_bin" / "dmsh_xlate.dll"

        log(f"Translating {len(jobs)} shaders to SPIR-V...")
        cmd = None
        if shutil.which("dotnet"):
            cmd = ["dotnet", str(dll_path), str(jobs_file), str(spv_out_dir)]
        elif shutil.which("podman"):
            cmd = [
                "podman", "run", "--rm",
                "-v", f"{REPO_ROOT}:/workspace",
                "-v", f"{work_dir}:{work_dir}",
                "-w", "/workspace",
                "mcr.microsoft.com/dotnet/sdk:10.0-preview",
                "dotnet", f"/workspace/{dll_path.relative_to(REPO_ROOT)}",
                str(jobs_file), str(spv_out_dir),
            ]
        elif shutil.which("docker"):
            cmd = [
                "docker", "run", "--rm",
                "-v", f"{REPO_ROOT}:/workspace",
                "-v", f"{work_dir}:{work_dir}",
                "-w", "/workspace",
                "mcr.microsoft.com/dotnet/sdk:10.0-preview",
                "dotnet", f"/workspace/{dll_path.relative_to(REPO_ROOT)}",
                str(jobs_file), str(spv_out_dir),
            ]

        if cmd:
            subprocess.run(cmd, stdout=subprocess.DEVNULL)
        else:
            log("WARNING: Neither dotnet nor podman/docker found; skipping SPIR-V compilation.")

    log("Packing .xgs bundles...")
    built = 0
    for skey, (st, ctl, code, ctl_key) in found_shaders.items():
        res_file = spv_out_dir / f"{skey}.res.json"
        spv_file = spv_out_dir / f"{skey}.spv"
        if not res_file.exists() or not spv_file.exists():
            continue

        skey_path = out_xgs_dir / f"{skey}.xgs"
        ctl_path = out_xgs_dir / f"{ctl_key}.xgs"
        if skey_path.exists() and ctl_path.exists() and not rebuild_shaders:
            built += 1
            continue

        try:
            with open(res_file, encoding="utf-8") as rf:
                res_json = json.load(rf)
            with open(spv_file, "rb") as sf:
                spv_bytes = sf.read()
            c1 = c1_map.get(skey, b"")
            bundle = build_xgs_bundle(skey, st, spv_bytes, res_json, c1)
            with open(skey_path, "wb") as bf:
                bf.write(bundle)
            with open(ctl_path, "wb") as bf:
                bf.write(bundle)
            built += 1
        except Exception:
            pass

    log(f"  ✓ {built} .xgs shader bundles ready in {out_xgs_dir}")


def import_system_data_and_saves(title_id, out_dir, nand_dirs, hactool_bin, keys_path):
    log("=== System Data and Save Import ===")
    # 1. System Data: MiiModel (0100000000000802)
    sysdata_dir = out_dir / "sysdata" / "0100000000000802"
    sysdata_dir.mkdir(parents=True, exist_ok=True)
    existing_sys = list(sysdata_dir.glob("*.dat"))

    if len(existing_sys) >= 4:
        log(f"  ✓ Found existing MiiModel sysdata in {sysdata_dir}")
    elif hactool_bin and keys_path:
        found_mii_nca = None
        for nand in nand_dirs:
            reg_dir = nand / "system" / "Contents" / "registered"
            if not reg_dir.exists():
                continue
            for nca in reg_dir.glob("*.nca"):
                # MiiModel PublicData RomFS NCA is ~5-6 MB
                if 4 * 1024 * 1024 <= nca.stat().st_size <= 8 * 1024 * 1024:
                    res = subprocess.run(
                        [str(hactool_bin), "--disablekeywarns", "-k", str(keys_path), str(nca)],
                        capture_output=True, text=True,
                    )
                    if "0100000000000802" in res.stdout and "RomFS" in res.stdout:
                        found_mii_nca = nca
                        break
            if found_mii_nca:
                break

        if found_mii_nca:
            log(f"Extracting MiiModel system data from {found_mii_nca.name}...")
            subprocess.run([
                str(hactool_bin),
                "--disablekeywarns",
                "-k", str(keys_path),
                f"--romfsdir={sysdata_dir}",
                str(found_mii_nca),
            ], stdout=subprocess.DEVNULL)
            log(f"  ✓ MiiModel system data extracted into {sysdata_dir}")
        else:
            log("Notice: MiiModel (0100000000000802) system NCA not found in emulator NANDs.")

    # 2. Save data import
    save_dest = out_dir / "save" / "userdata.dat"
    if save_dest.exists():
        log(f"  ✓ Save file already in output: {save_dest}")
    elif title_id:
        found_save = None
        for nand in nand_dirs:
            user_save_dir = nand / "user" / "save"
            if not user_save_dir.exists():
                continue
            for save in user_save_dir.glob(f"**/{title_id}/**/userdata.dat"):
                if save.exists() and save.stat().st_size > 0:
                    found_save = save
                    break
            if found_save:
                break

        if found_save:
            save_dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(found_save, save_dest)
            log(f"  ✓ Imported save data ({found_save.stat().st_size} bytes): {found_save.name} -> {save_dest}")
        else:
            log(f"Notice: No existing emulator save found for {title_id}.")


def build_apk(title_id):
    log("=== Building Android APK ===")
    game_arg = f"-PdmGame={title_id}" if title_id else ""
    apk_out = REPO_ROOT / "dm" / "android" / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"

    if shutil.which("gradle"):
        cmd = ["gradle", "-p", "dm/android", ":app:assembleDebug"]
        if game_arg:
            cmd.append(game_arg)
        log(f"Running host gradle: {' '.join(cmd)}")
        res = subprocess.run(cmd, cwd=str(REPO_ROOT))
        if res.returncode != 0:
            log(f"ERROR: Gradle build failed with code {res.returncode}")
            sys.exit(res.returncode)
    elif shutil.which("podman"):
        cmd = [
            "podman", "run", "--rm", "--userns=keep-id",
            "-v", f"{REPO_ROOT}:/src",
            "-w", "/src",
            "dm-android-tools:1",
            "gradle", "-p", "dm/android", ":app:assembleDebug",
        ]
        if game_arg:
            cmd.append(game_arg)
        log("Running container gradle build via podman...")
        res = subprocess.run(cmd)
        if res.returncode != 0:
            log(f"ERROR: Podman gradle build failed with code {res.returncode}")
            sys.exit(res.returncode)
    elif shutil.which("docker"):
        cmd = [
            "docker", "run", "--rm",
            "--user", f"{os.getuid()}:{os.getgid()}",
            "-v", f"{REPO_ROOT}:/src",
            "-w", "/src",
            "dm-android-tools:1",
            "gradle", "-p", "dm/android", ":app:assembleDebug",
        ]
        if game_arg:
            cmd.append(game_arg)
        log("Running container gradle build via docker...")
        res = subprocess.run(cmd)
        if res.returncode != 0:
            log(f"ERROR: Docker gradle build failed with code {res.returncode}")
            sys.exit(res.returncode)
    else:
        log("ERROR: Neither gradle, podman nor docker found to build the APK.")
        sys.exit(1)

    if apk_out.exists():
        log(f"  ✓ APK built successfully: {apk_out} ({apk_out.stat().st_size / (1024*1024):.1f} MB)")
    else:
        log(f"WARNING: Gradle completed but {apk_out} was not found.")


def install_apk(adb_path=None, device_id=None):
    if not adb_path:
        adb_path = shutil.which("adb") or "/tmp/opencode/platform-tools/adb"
    apk_path = REPO_ROOT / "dm" / "android" / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
    if not apk_path.exists():
        log(f"ERROR: APK not found at {apk_path}. Run with --build-apk first.")
        return

    adb_cmd = [str(adb_path)]
    if device_id:
        adb_cmd.extend(["-s", device_id])

    log(f"Installing APK on Android device ({apk_path.name})...")
    res = subprocess.run(adb_cmd + ["install", "-r", "-d", str(apk_path)])
    if res.returncode == 0:
        log("  ✓ APK installed successfully!")
    else:
        log(f"ERROR: adb install failed (code {res.returncode})")


def push_to_device(game_folder, target_remote_dir, adb_path=None, device_id=None):
    if not adb_path:
        adb_path = shutil.which("adb") or "/tmp/opencode/platform-tools/adb"
    if not Path(adb_path).exists():
        log("ADB not found. Cannot push to device.")
        return

    adb_cmd = [str(adb_path)]
    if device_id:
        adb_cmd.extend(["-s", device_id])

    dest_on_phone = target_remote_dir.rstrip("/")
    log(f"Preparing deployment to smartphone at {dest_on_phone}...")
    subprocess.run(adb_cmd + ["shell", "mkdir", "-p", dest_on_phone])

    # 1. Fast stream / tar deployment for files (to transfer thousands of shaders in seconds)
    with tempfile.TemporaryDirectory() as td:
        tar_path = Path(td) / "game_deploy.tar"
        log("Packaging game assets into temporary transfer archive...")
        with tarfile.open(tar_path, "w") as tar:
            for item in game_folder.iterdir():
                if item.name == "save":
                    continue
                tar.add(item, arcname=item.name)

        remote_tar = "/data/local/tmp/game_deploy.tar"
        log(f"Pushing archive ({tar_path.stat().st_size / (1024*1024):.1f} MB) -> {remote_tar}...")
        subprocess.run(adb_cmd + ["push", str(tar_path), remote_tar], check=True)
        log("Extracting assets on device...")
        subprocess.run(adb_cmd + ["shell", f"tar -xf {remote_tar} -C {dest_on_phone} && rm -f {remote_tar}"], check=True)
        log("  ✓ Game files deployed to smartphone!")

    # 2. Push save data if present
    save_file = game_folder / "save" / "userdata.dat"
    if save_file.exists():
        log("Pushing save file to app private storage...")
        remote_tmp_save = "/data/local/tmp/userdata.dat"
        subprocess.run(adb_cmd + ["push", str(save_file), remote_tmp_save], check=True)
        subprocess.run(adb_cmd + ["shell", "run-as com.nxdroid mkdir -p /data/user/0/com.nxdroid/files/save"], check=True)
        subprocess.run(adb_cmd + ["shell", f"run-as com.nxdroid cp {remote_tmp_save} /data/user/0/com.nxdroid/files/save/userdata.dat"], check=True)
        subprocess.run(adb_cmd + ["shell", f"rm -f {remote_tmp_save}"])
        log("  ✓ Save data deployed into com.nxdroid private storage!")


def main():
    check_tool_requirements()

    parser = argparse.ArgumentParser(
        description="Prepare Nintendo Switch games for nxdroid (Android AArch64 native execution)"
    )
    parser.add_argument("input", help="Extracted game directory, or .nsp / .xci file")
    parser.add_argument("-u", "--update", help="Update .nsp / .xci file (or auto-detected from folder)")
    parser.add_argument("-o", "--out", help="Output directory for prepared game (default: ./prepared_games/<name>)")
    parser.add_argument("-k", "--keys", help="Path to prod.keys (default: auto-detected from emulator dirs)")
    parser.add_argument("--nand", help="Custom path to emulator NAND directory")
    parser.add_argument("--title-id", help="Explicit base title ID (e.g. 0100152000022000)")
    parser.add_argument("--rebuild-shaders", action="store_true", help="Force rebuilding .xgs shaders even if already present")
    parser.add_argument("--build-apk", action="store_true", help="Build the nxdroid Android APK for this game profile")
    parser.add_argument("--install-apk", action="store_true", help="Install the built APK via ADB to connected device")
    parser.add_argument("--push", action="store_true", help="Push prepared folder directly to connected Android phone via ADB")
    parser.add_argument("--device-dir", default="/storage/emulated/0/nxdroid/game",
                        help="Target directory on Android phone (default: /storage/emulated/0/nxdroid/game)")
    parser.add_argument("--device", help="Specific ADB device serial (e.g. RQCX808VH9K)")
    parser.add_argument("--adb", help="Custom path to adb binary")

    args = parser.parse_args()
    inp = Path(args.input).resolve()
    if not inp.exists():
        log(f"ERROR: Input path does not exist: {inp}")
        sys.exit(1)

    update_file = Path(args.update).resolve() if args.update else None
    if not update_file and inp.is_file():
        # Look for sibling update file
        for sibling in inp.parent.glob("*.nsp"):
            if sibling != inp and ("update" in sibling.name.lower() or "[v" in sibling.name.lower() or "800]" in sibling.name):
                update_file = sibling
                log(f"Auto-detected update file: {update_file.name}")
                break

    game_stem = re.sub(r"[^A-Za-z0-9_-]", "", inp.stem.replace(" ", "_"))
    out_dir = Path(args.out).resolve() if args.out else Path.cwd() / "prepared_games" / game_stem
    out_dir.mkdir(parents=True, exist_ok=True)

    log("=== nxdroid Game Preparation ===")
    log(f"Input:   {inp.name}")
    if update_file:
        log(f"Update:  {update_file.name}")
    log(f"Output:  {out_dir}")

    work_dir = (inp.parent if inp.is_file() else inp) / f"{game_stem}-work"

    # Case 1: Folder
    if inp.is_dir():
        exefs_dir = inp / "exefs" if (inp / "exefs").exists() else inp
        romfs_dir = inp / "romfs" if (inp / "romfs").exists() else None
        romfs_img = inp / "romfs.img"
        ctrl_dir = inp / "control" if (inp / "control").exists() else inp

        title_id = detect_title_id(inp, work_dir, args.title_id)
        log(f"Game Title ID: {title_id or 'Unknown'}")

        rewrite_modules(exefs_dir, out_dir)

        dest_romfs_img = out_dir / "romfs.img"
        if romfs_dir and romfs_dir.exists():
            pack_romfs(romfs_dir, dest_romfs_img)
        elif romfs_img.exists():
            shutil.copy2(romfs_img, dest_romfs_img)
            log(f"  ✓ Copied existing romfs.img ({dest_romfs_img.stat().st_size / (1024*1024):.1f} MB)")

        for f in ctrl_dir.glob("*.nacp"):
            shutil.copy2(f, out_dir / "control.nacp")
        for f in ctrl_dir.glob("icon*.dat"):
            shutil.copy2(f, out_dir / "icon.jpg")
            break

        copy_profile_tables(title_id, out_dir)
        extract_and_build_shaders(title_id, exefs_dir, dest_romfs_img, romfs_dir, out_dir, work_dir, args.rebuild_shaders)

        hactool = find_hactool()
        keys = find_prod_keys(args.keys)
        nand_dirs = find_nand_candidates(args.nand)
        import_system_data_and_saves(title_id, out_dir, nand_dirs, hactool, keys)

    # Case 2: Archive (.nsp, .xci)
    else:
        hactool = find_hactool()
        if not hactool:
            log("ERROR: 'hactool' binary not found. Build it with gcc in dm/tools/bin/hactool")
            sys.exit(1)

        keys = find_prod_keys(args.keys)
        if not keys:
            log("ERROR: 'prod.keys' not found. Specify with -k <path> or place in ~/.switch/prod.keys")
            sys.exit(1)
        log(f"Using keys from: {keys}")

        exefs_dir, romfs_dir, ctrl_dir = extract_archive(inp, update_file, work_dir, hactool, keys)

        title_id = detect_title_id(inp, work_dir, args.title_id)
        log(f"Game Title ID: {title_id or 'Unknown'}")

        rewrite_modules(exefs_dir, out_dir)
        dest_romfs_img = out_dir / "romfs.img"
        pack_romfs(romfs_dir, dest_romfs_img)

        for f in ctrl_dir.glob("*.nacp"):
            shutil.copy2(f, out_dir / "control.nacp")
        for f in ctrl_dir.glob("icon*.dat"):
            shutil.copy2(f, out_dir / "icon.jpg")
            break

        copy_profile_tables(title_id, out_dir)
        extract_and_build_shaders(title_id, exefs_dir, dest_romfs_img, romfs_dir, out_dir, work_dir, args.rebuild_shaders)

        nand_dirs = find_nand_candidates(args.nand)
        import_system_data_and_saves(title_id, out_dir, nand_dirs, hactool, keys)

    if args.build_apk:
        build_apk(title_id)

    if args.install_apk:
        install_apk(args.adb, args.device)

    log(f"\nPreparation complete! Game files ready in:\n  {out_dir}")
    log(f"Target path on phone:\n  {args.device_dir.rstrip('/')}/")

    if args.push:
        push_to_device(out_dir, args.device_dir, args.adb, args.device)


if __name__ == "__main__":
    main()
