#!/usr/bin/env python3
"""Mechanical ABI gap list between this repository's mtl_* layer and the vendored Vulkan adapter.

Both directions, by name and signature, never by eye:

  missing  declared by dm/gfx/nvn/nvn_mtl.h or dm/gfx/nvn/nvn_obj.h, not defined by
           dm/gfx/vulkan/nvn_vk.c (a link error the moment the adapter joins the host)
  extra    defined by dm/gfx/vulkan/nvn_vk.c, declared by neither header (a definition this
           repository's headers do not know about)

Run it with no argument to rewrite abi_gaps.txt; --check fails when abi_gaps.txt is stale.
"""
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[3]
HEADERS = [ROOT / "dm/gfx/nvn/nvn_obj.h", ROOT / "dm/gfx/nvn/nvn_mtl.h"]
ADAPTER = ROOT / "dm/gfx/vulkan/nvn_vk.c"
METAL = ROOT / "dm/gfx/nvn/nvn_mtl.m"
OUTPUT = HERE / "abi_gaps.txt"


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"//[^\n]*", "", text)
    return text


def drop_preprocessor(text: str) -> str:
    return "\n".join("" if line.lstrip().startswith("#") else line for line in text.splitlines())


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def declared(path: pathlib.Path) -> dict:
    """name -> normalised declaration text, for every mtl_* prototype in one header."""
    text = drop_preprocessor(strip_comments(path.read_text(encoding="utf-8", errors="replace")))
    # The headers carry an extern "C" guard so that C++ can include them (the vendored engine does). It is a
    # brace and a token, not a declaration: left in, it would prefix the prototype that follows it and every
    # signature comparison would report the difference.
    text = re.sub(r'extern\s+"C"\s*\{', " ", text)
    text = re.sub(r"(?m)^\s*\}\s*$", " ", text)
    found = {}
    for chunk in text.split(";"):
        match = re.search(r"\b(MTL_\w+|mtl_\w+)\s*\(", chunk)
        if not match:
            continue
        chunk = norm(chunk)
        # A block of typedefs can precede a prototype in the same chunk; keep from the last '}' or the start.
        cut = chunk.rfind("}")
        if cut >= 0:
            chunk = chunk[cut + 1:].strip()
        found.setdefault(match.group(1), chunk)
    return found


def defined(path: pathlib.Path) -> dict:
    """name -> (line number, normalised signature up to the closing paren), for one source file."""
    text = strip_comments(path.read_text(encoding="utf-8", errors="replace"))
    found = {}
    for match in re.finditer(r"\b(mtl_\w+)\s*\(", text):
        name = match.group(1)
        line_start = text.rfind("\n", 0, match.start()) + 1
        prefix = text[line_start:match.start()]
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_ \t\*]*", prefix):
            continue
        depth, i = 0, match.end() - 1
        while i < len(text):
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        rest = text[i + 1:]
        if not rest.lstrip().startswith("{"):
            continue  # a call, not a definition
        found.setdefault(name, (text.count("\n", 0, line_start) + 1, norm(text[line_start:i + 1])))
    return found


def banners(path: pathlib.Path) -> list:
    """(line, banner text) for the section banners of a file, in file order."""
    out = []
    for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if re.fullmatch(r"// -{3,} .+ -{3,}", line.strip()):
            out.append((number, line.strip().strip("-/ ").strip()))
    return out


def metal_section(path: pathlib.Path, name: str, section_banners: list, metal_defs: dict) -> str:
    found = metal_defs.get(name)
    if not found:
        return "not defined in nvn_mtl.m (look for its caller)"
    number = found[0]
    banner = "no section banner"
    for at, text in section_banners:
        if at < number:
            banner = "%s (line %d)" % (text, at)
    return "%s:%d, section %s" % (path.name, number, banner)


def param_types(signature: str) -> str:
    """Signature with parameter names dropped, so only the types are compared."""
    match = re.search(r"\((.*)\)\s*$", signature)
    if not match:
        return signature
    params = []
    depth, current = 0, ""
    for char in match.group(1):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            params.append(current)
            current = ""
        else:
            current += char
    params.append(current)
    types = []
    for param in params:
        param = param.strip()
        # Drop a trailing parameter name: "const uint8_t *handle" -> "const uint8_t *".
        param = re.sub(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*(\[[^\]]*\])?$", "", param).strip()
        types.append(re.sub(r"\s*\*\s*", " *", param))
    return signature[:match.start()] + "(" + ", ".join(types) + ")"


def main(argv) -> int:
    merge = dict(declared(HEADERS[0]))
    for name, signature in declared(HEADERS[1]).items():
        merge.setdefault(name, signature)
    adapter = defined(ADAPTER)
    metal_defs = defined(METAL)
    section_banners = banners(METAL)

    missing = sorted(set(merge) - set(adapter))
    extra = sorted(set(adapter) - set(merge))
    differ = sorted(name for name in set(merge) & set(adapter)
                    if param_types(norm(merge[name])) != param_types(norm(adapter[name][1])))
    renamed = sorted(name for name in set(merge) & set(adapter)
                     if norm(merge[name]) != norm(adapter[name][1]) and name not in differ)

    lines = [
        "# ABI gap between this repository's mtl_* layer and the vendored Vulkan adapter",
        "# Generated by dm/gfx/vk/engine_smoke/abi_gaps.py; do not edit by hand (--check compares).",
        "# Headers scanned: %s" % ", ".join(path.relative_to(ROOT).as_posix() for path in HEADERS),   # POSIX separators: the file is the same on every platform
        "# Adapter scanned: %s" % ADAPTER.relative_to(ROOT).as_posix(),
        "",
        "== missing: declared by a header, not defined by nvn_vk.c (%d)" % len(missing),
    ]
    for name in missing:
        lines.append(merge[name])
        lines.append("  metal: %s" % metal_section(METAL, name, section_banners, metal_defs))
    lines += ["", "== extra: defined by nvn_vk.c, declared by neither header (%d)" % len(extra)]
    for name in extra:
        lines.append(adapter[name][1])
        lines.append("  metal: %s" % metal_section(METAL, name, section_banners, metal_defs))
    lines += ["", "== signatures that differ in their types (callers cannot be swapped): (%d)" % len(differ)]
    for name in differ:
        lines.append("header:  " + merge[name])
        lines.append("adapter: " + adapter[name][1])
    lines += ["", "== same types, different parameter names only (cosmetic): (%d)" % len(renamed)]
    for name in renamed:
        lines.append("header:  " + merge[name])
        lines.append("adapter: " + adapter[name][1])
    text = "\n".join(lines) + "\n"

    if "--check" in argv[1:]:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if current != text:
            print("[RED] abi_gaps: %s is stale; run python3 %s" % (OUTPUT.relative_to(ROOT).as_posix(), pathlib.Path(__file__).name))
            return 1
        print("abi_gaps: up to date (%d missing, %d extra)" % (len(missing), len(extra)))
        return 0
    OUTPUT.write_text(text, encoding="utf-8", newline="\n")   # LF on every platform (--check compares the text after newline translation; the file in git is LF)
    print("abi_gaps: %d missing, %d extra -> %s" % (len(missing), len(extra), OUTPUT.relative_to(ROOT).as_posix()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
