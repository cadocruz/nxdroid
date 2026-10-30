#!/usr/bin/env python3
# Symbols the Android host would fail to link: names the sources the Android build keeps use, and that nothing in the link set defines. The link is
# -Wl,--no-undefined, so each one is a build break on the NDK; this scan finds them on any machine, without the NDK.
#
# The link set: the sources host_sources.py lists (dm/host/Makefile's SRC and GFX without the .m), the Android sources (front_android.c,
# vulkan_present.cpp, port_android.c, nvn_vk.c, main.c, compat/*.c), the files each of them #includes locally (a .inc included by a kept .c defines
# for the link; one included only by a dropped .m does not), the Vulkan engine (dm/gfx/vulkan), libvpx, and the labels of the three ELF-converted .S
# files. A weak definition counts (the host's own fallbacks: dm_vk_drain, mtl_link_wait_vsync, ...).
# Two questions, as QA's independent scans asked them (undef2.py, inc_scan.py, bare_scan.py):
#   1. declared and used, never defined: every prototype in dm/host and dm/gfx headers (tests, third_party and the engine aside) and in the kept
#      sources (block-scope declarations included, the way hle_nvn.c declares the Metal statistics), called or taken by address in a kept source,
#      with no definition in the link set but a definition somewhere else in the repository (dm/ outside third_party: a .c, .m, .inc or .cpp). The
#      last condition is what separates a dropped definition from the C library (memcpy, pthread_mutex_lock, ...), a macro (LOG, die) or a C++
#      constructor call the heuristic reads as a prototype: none of those is defined by a repository source;
#   2. defined only where the Android build does not look: a non-static function or file-scope variable of a dropped .m, or of a .inc / .h that only
#      a dropped .m includes, whose bare identifier appears in a kept source (a function pointer or a variable use, not only a call).
# Balanced-parenthesis scanning over comment-, string- and preprocessor-stripped text: a definition is `name(...) {`, a prototype `name(...);` whose
# head is a declaration and not a call. Known blind spots: macros are not followed (preprocessor lines are stripped), so a name only a macro
# produces is not seen; a global function pointer defined only in a dropped .m (`T (*name)(...) = ...;`) is not in file_scope()'s definition set.
# A clean run is not a clean link: only names some repository source defines are looked for, so an Apple API a kept source calls and neither
# dm/android/compat nor bionic provides (AudioUnit*, CF*, CVPixelBuffer*, dispatch_*, getsectiondata, malloc_zone_*, mach_vm_* / vm_*,
# thread_policy_*, sysctlbyname, pthread_cond_timedwait_relative_np, ...) is outside this scan; those are compile errors the host bring-up expects.
# Usage: undef_scan.py <host_sources.cmake written by host_sources.py>   exit 1 with one [RED] line per symbol (what, where defined, who uses it),
#        exit 0 with "undef_scan: no undefined symbol" otherwise. dm/android/CMakeLists.txt runs it at configure (a warning there, this exit code in CI).
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
ANDROID = HERE.parent
# Mach-O spellings that the ELF assembler refuses or that fail the ELF link, in a kept C source's inline assembly: .private_extern (ELF: .hidden), .linker_option (no ELF
# equivalent: the library goes on the link line), .weak_definition (ELF: .weak), the Mach-O-only directives (.subsections_via_symbols, .alt_entry, .no_dead_strip,
# .weak_reference, .zerofill, .loh, .tbss, .const_data, .cstring), sym@PAGE / @PAGEOFF and their @GOTPAGE / @GOTPAGEOFF / @TLVPPAGE / @TLVPPAGEOFF forms (ELF: the bare
# symbol / :lo12:, :got: / :got_lo12:, the TLS descriptors), a Mach-O segment,section name (.section __TEXT,__text or section("__DATA,swhle"): ELF sections have one
# name, DM_SECTION), and an _-prefixed C symbol as an operand (ELF symbols carry no underscore) of a branch (b, bl, b.cond, cbz / cbnz, tbz / tbnz), of adrp / adr / ldr
# (ldr x0, =_x included), of .globl / .set or of a data directive (.quad, .xword, .8byte, .long, .int, .4byte, .word). A mnemonic starts a line of the assembly: after a
# blank, a quote or a C string's \n or \t escape (the escape's letter is a word character, so \b alone missed "\nbl _x"); an operand follows blanks, a \t escape or the
# end of one string literal and the start of the next ("bl " "_x"); the symbol may be stringified ("bl _" #name). The .S files are not scanned: asm_elf.py rewrites them.
# port.h defines the DM_ASM_* macros that spell both and is the one place these strings may appear.
_AT = r'(?:(?<![\w.$])|(?<=\\[nt]))'      # where a mnemonic or directive can start
_SP = r'(?:\s|\\t|"\s*")+'                # between a mnemonic and its operand
_CO = r'(?:\s|\\t|"\s*")*,(?:\s|\\t|"\s*")*'   # an operand separator
_SYM = r'_(?:[A-Za-z_]|"\s*#)'             # an _-prefixed symbol, or "_" followed by a stringified name
MACHO_ASM = re.compile(r'\.private_extern\b|\.linker_option\b|\.weak_definition\b'
                       r'|' + _AT + r'\.(?:subsections_via_symbols|alt_entry|no_dead_strip|weak_reference|zerofill|loh|tbss|const_data|cstring)\b'
                       r'|@(?:GOT|TLVP)?PAGE(?:OFF)?\b'
                       r'|\.section' + _SP + r'__[A-Z]+\s*,|\bsection\s*\(\s*"__[A-Z]+\s*,'
                       r'|' + _AT + r'(?:bl?|b\.[a-z]{2}|\.globa?l|\.set|\.quad|\.xword|\.8byte|\.long|\.int|\.4byte|\.word)' + _SP + _SYM
                       + r'|' + _AT + r'(?:adrp?|cbn?z|ldr)' + _SP + r'\w+' + _CO + r'=?' + _SYM
                       + r'|' + _AT + r'tbn?z' + _SP + r'\w+' + _CO + r'#?\w+' + _CO + _SYM)
MACHO_ASM_EXEMPT = {REPO / 'dm/host/port.h'}


def cmake_list(name, extra=()):
    """the paths dm/android/CMakeLists.txt lists in set(<name> ...): the same list the build uses, read, not copied"""
    text = re.sub(r'#[^\n]*', '', read(ANDROID / 'CMakeLists.txt'))
    m = re.search(r'set\(%s\s+(.*?)\)' % re.escape(name), text, re.S)
    if not m:
        raise SystemExit('[RED] undef_scan: dm/android/CMakeLists.txt has no set(%s ...) block to read the list from' % name)
    out = []
    for tok in m.group(1).split():
        tok = tok.replace('${CMAKE_CURRENT_SOURCE_DIR}', str(ANDROID)).replace('${DM}', str(REPO / 'dm')).replace('${HOST}', str(REPO / 'dm/host'))
        if '$' in tok:
            raise SystemExit('[RED] undef_scan: %s entry %s uses a CMake variable this scan does not know' % (name, tok))
        out.append(pathlib.Path(tok))
    return out + list(extra)


def android_srcs():
    """set(ANDROID_SRCS ...) plus main.c (the dmhost target)"""
    return cmake_list('ANDROID_SRCS', [REPO / 'dm/host/main.c'])


def uncomment(text):
    """text with its C comments blanked and its string and character literals kept (a "//" inside a string is not a comment), line breaks where they were"""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c in '"\'':
            j = i + 1
            while j < n and text[j] != c and text[j] != '\n': j += 2 if text[j] == '\\' else 1
            out.append(text[i:j + 1]); i = j + 1
        elif text.startswith('//', i):
            j = text.find('\n', i); j = n if j < 0 else j
            out.append(' ' * (j - i)); i = j
        elif text.startswith('/*', i):
            j = text.find('*/', i + 2); j = n if j < 0 else j + 2
            out.append(re.sub(r'[^\n]', ' ', text[i:j])); i = j
        else:
            out.append(c); i += 1
    return ''.join(out)


def macho_asm(paths):
    """[RED] lines for Mach-O assembly spellings in kept C sources and their includes (comments removed, strings kept: the assembly is in them)"""
    out = []
    for p in paths:
        if p in MACHO_ASM_EXEMPT:
            continue
        for n, code in enumerate(uncomment(read(p)).split('\n'), 1):
            m = MACHO_ASM.search(code)
            if m:
                out.append('%s:%d: Mach-O assembly in a kept source: %s (ELF needs the DM_ASM_* spellings of port.h, or no linker option)' % (p.relative_to(REPO).as_posix(), n, m.group(0).strip()))
    return out
KEYWORDS = {'if', 'for', 'while', 'switch', 'sizeof', 'return', 'do', 'catch', '__attribute__', 'defined', '_Static_assert', 'static_assert',
            'alignof', '_Alignof', 'typeof', '__typeof__', 'decltype', 'case', 'else', 'new', 'delete', 'throw'}
NAME = re.compile(r'\b([A-Za-z_]\w*)\s*\(')
INCLUDE = re.compile(r'^\s*#\s*(?:include|import)\s*"([^"]+)"', re.M)
MIN_BARE = 4   # a bare identifier shorter than this is too common to attribute


def strip(text):
    text = re.sub(r'/\*.*?\*/', ' ', text, flags=re.S)
    text = re.sub(r'//[^\n]*', '', text)
    text = re.sub(r'"(?:\\.|[^"\\\n])*"', '""', text)
    text = re.sub(r"'(?:\\.|[^'\\\n])*'", "''", text)
    text = re.sub(r'^\s*#.*?(?<!\\)$', '', text, flags=re.M | re.S)   # preprocessor lines, #define bodies included
    return text


def read(path):
    return path.read_text(encoding='utf-8', errors='replace')


def close(text, i):
    # text[i] == '(' -> index after the matching ')', or -1 when a statement boundary comes first
    depth = 0
    for j in range(i, min(len(text), i + 4000)):
        c = text[j]
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
            if depth == 0:
                return j + 1
        elif c in ';{}':
            return -1
    return -1


def after(text, j):
    # skip blanks, __attribute__((...)), noexcept(...), const / noexcept / override
    while True:
        j = re.compile(r'\s*').match(text, j).end()
        m = re.compile(r'(__attribute__|noexcept)\s*(?=\()').match(text, j)
        if m:
            k = close(text, m.end())
            if k < 0:
                return j
            j = k
            continue
        m = re.compile(r'(const|noexcept|override)\b').match(text, j)
        if m:
            j = m.end()
            continue
        return j


def scan(text):
    """(definitions, prototypes) of one stripped source"""
    defs, protos = set(), set()
    for m in NAME.finditer(text):
        name = m.group(1)
        if name in KEYWORDS:
            continue
        k = close(text, m.end() - 1)
        if k < 0:
            continue
        j = after(text, k)
        if j < len(text) and text[j] == '{':
            defs.add(name)
        elif j < len(text) and text[j] == ';':
            start = max(text.rfind(';', 0, m.start()), text.rfind('{', 0, m.start()), text.rfind('}', 0, m.start())) + 1
            head = text[start:m.start()]
            if re.search(r'[=()\[\]]|\breturn\b|\bstatic\b|\btypedef\b|->|\.', head) or not re.search(r'[A-Za-z_]', head):
                continue   # a call, not a declaration
            protos.add(name)
    return defs, protos


def file_scope(text):
    """non-static functions and variables defined at column 0 of one stripped dropped source: what a kept source could still name"""
    functions = {m.group(1) for m in re.finditer(r'^(?!static\b)(?!\s)[A-Za-z_][\w \t\*]*?\b([A-Za-z_]\w*)\s*\(', text, re.M)} & scan(text)[0]
    variables = {m.group(1) for m in re.finditer(r'^(?!static\b)(?!typedef\b)(?!extern\b)(?!return\b)[A-Za-z_][\w \t\*]*?\b([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*(?:=|;)', text, re.M)}
    return functions | variables


def local_includes(path, seen):
    """the files path #includes with quotes, recursively, that exist under the repository"""
    out = []
    for name in INCLUDE.findall(read(path)):
        target = (path.parent / name).resolve()
        if target in seen or not target.is_file() or REPO not in target.parents:
            continue
        seen.add(target)
        out.append(target)
        out += local_includes(target, seen)
    return out


def main():
    if len(sys.argv) != 2:
        raise SystemExit('usage: undef_scan.py <host_sources.cmake>')
    cmake = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')
    kept = [pathlib.Path(p) for p in re.findall(r'"([^"]+\.(?:c|cpp))"', cmake)] + android_srcs()
    kept = [p.resolve() for p in kept if p.exists()]
    kept_text = {p: strip(read(p)) for p in kept}
    seen = set(kept)
    kept_includes = []
    for p in kept:
        kept_includes += local_includes(p, seen)
    # the link set's definitions: kept sources and what they include, the engine, compat, libvpx, the .S labels
    link = set()
    for text in kept_text.values():
        link |= scan(text)[0]
    for p in kept_includes:
        link |= scan(strip(read(p)))[0]
    for root in (REPO / 'dm/gfx/vulkan', ANDROID / 'compat', REPO / 'dm/third_party/libvpx'):
        for p in [*root.rglob('*.c'), *root.rglob('*.cpp'), *root.rglob('*.cc')]:
            link |= scan(strip(read(p)))[0]
    for s in cmake_list('ASM_IN'):   # the .S files asm_elf.py converts (dm/android/CMakeLists.txt)
        if s.exists():
            t = read(s)
            link |= {n.lstrip('_') for n in re.findall(r'^\s*([A-Za-z_]\w*):', t, re.M)} | {n.lstrip('_') for n in re.findall(r'\.globa?l\s+(\w+)', t)}
    # the dropped sources: every .m of dm/host and dm/gfx outside tests, plus what only they include
    dropped = sorted(p for root in (REPO / 'dm/host', REPO / 'dm/gfx') for p in root.rglob('*.m') if 'tests' not in p.parts)
    dropped_only = []
    for m in dropped:
        dropped_only += [p for p in local_includes(m, seen) if p not in kept_includes]
    dropped_defs = {}
    for p in dropped + dropped_only:
        for name in file_scope(strip(read(p))):
            dropped_defs.setdefault(name, p)

    found = []
    # 1. declared and used, never defined in the link set, defined somewhere in the repository
    declared = set()
    headers = [p for d in ('dm/host', 'dm/gfx') for p in (REPO / d).rglob('*.h')
               if 'tests' not in p.parts and 'third_party' not in p.parts and 'engine' not in p.parts]
    for p in headers:
        declared |= scan(strip(read(p)))[1]
    for text in kept_text.values():
        declared |= scan(text)[1]
    repo_defined = set(dropped_defs)
    for p in (REPO / 'dm').rglob('*'):
        if p.suffix in ('.c', '.m', '.inc', '.cpp') and 'third_party' not in p.parts and p.resolve() not in kept_text and p.is_file():
            repo_defined |= scan(strip(read(p)))[0]
    for name in sorted((declared & repo_defined) - link):
        use = re.compile(r'\b%s\s*\(|&\s*%s\b' % (re.escape(name), re.escape(name)))
        users = [p.name for p, text in kept_text.items() if use.search(text)]
        if users:
            where = dropped_defs.get(name)
            found.append('%s (declared, defined %s) <- %s' % (name, where.relative_to(REPO).as_posix() if where else 'nowhere in the link set', ', '.join(users)))
    # 2. defined only in a dropped file, named bare in a kept one (a function pointer, a variable)
    for name, where in sorted(dropped_defs.items()):
        if name in link or len(name) < MIN_BARE or any(name in line for line in found):
            continue
        bare = re.compile(r'\b%s\b' % re.escape(name))
        users = [p.name for p, text in kept_text.items() if bare.search(text)]
        if users:
            found.append('%s (defined only in %s) <- %s' % (name, where.relative_to(REPO).as_posix(), ', '.join(users)))
    # 3. Mach-O assembly spellings in a kept source or one of its includes (the ELF assembler or the link would refuse them)
    asm_found = macho_asm(kept + kept_includes)
    for line in found:
        print('[RED] undef_scan: ' + line)
    for line in asm_found:
        print('[RED] undef_scan: ' + line)
    if found or asm_found:
        print('undef_scan: %d symbol(s) the Android build uses and does not define, %d Mach-O assembly line(s)' % (len(found), len(asm_found)))
        return 1
    print('undef_scan: no undefined symbol, no Mach-O assembly (%d kept sources and %d of their includes; %d dropped .m with %d includes of their own)'
          % (len(kept), len(kept_includes), len(dropped), len(dropped_only)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
