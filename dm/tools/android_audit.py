#!/usr/bin/env python3
# Android portability audit: "is this file portable to Android?" as a machine-checkable gate. It scans the C/C++/ObjC/asm of the host that the port moves onto POSIX/bionic
# (dm/host, dm/gfx/nvn) and reports every line that uses something only Apple has, one hit per line and category (a line can hit several categories):
#   apple-api       the Mach kernel and Darwin libc extensions bionic does not have: mach_* (Mach-O symbol decoration _mach_* included, which assembly links against),
#                   <mach/*> and <mach-o/*>, vm_*, os_unfair_lock, dispatch_* (GCD), pthread_[set|get]_qos_class*, sysctl, clonefile, CommonCrypto, <TargetConditionals.h> and
#                   TARGET_OS_* / TARGET_CPU_*, <libkern/*> and sys_icache_invalidate, <os/proc.h> (os_proc_available_memory), and Darwin's ucontext register layout
#                   (_STRUCT_ARM_THREAD_STATE64, ->__ss / ->__ns), which bionic lays out differently
#   objc-framework  Objective-C: an #import/#include of an Apple framework, an @-keyword, or an NS*/CF*/MTL*/... type or id<protocol>. In a .m file the type tokens are
#                   left out: an Objective-C implementation file is Apple-only as a whole (see --summary), and itemising 1,800 MTL lines of nvn_mtl.m adds nothing
#   page-assumption a 16384 / 0x4000 / 1 << 14 / 16 KiB literal on a line that also talks about pages, mmap, mprotect or getpagesize: a host page size written into the
#                   code. Apple's page is 16 KiB, Android's (Galaxy S23 Ultra measured) is 4 KiB. Candidates: the literal is sometimes a guest or device constant that only
#                   looks like a page (an NSO key page, a texture limit), so the listing is for a human to judge, and the baseline is where "judged: not a host page" lives
#   macho-section   Mach-O linker conventions: section("__DATA,swhle"), __TEXT,__text, -sectcreate, and the _-decorated symbols and Mach-O-only directives of a .S file
# Vendored code is another repository's (dm/third_party, dm/gfx/vulkan) and the probes and the engine smoke harness are diagnostics, so they, and anything under a tests/
# directory, are out of scope. --all adds dm/gfx/metal and dm/gfx/vk, so the report still shows what is Apple by design.
# The findings the tree has today are in dm/tools/android_audit_baseline.tsv, keyed by file, category and the sha1 of the whitespace-normalised line (so moving a hit, or
# reformatting the file around it, does not invalidate the baseline). The gate fails on a hit that is not in the baseline and on a baseline row whose hit is gone, so the
# record of what is Apple-specific only shrinks: a new Apple dependency is either made portable, or added deliberately with --write-baseline and its reason in the pull request.
# CI runs:   python3 dm/tools/android_audit.py --check
# By hand:   python3 dm/tools/android_audit.py                 (the hits, grouped by file)
#            python3 dm/tools/android_audit.py --summary       (counts per category, top 10 files)
#            python3 dm/tools/android_audit.py --json          (one JSON object per hit)
#            python3 dm/tools/android_audit.py --all --summary --check
import argparse, hashlib, json, pathlib, re, sys

REPO = pathlib.Path(__file__).resolve().parents[2]
BASELINE = REPO / 'dm/tools/android_audit_baseline.tsv'
HEADER = '# file\tcategory\tsha1\ttext   (dm/tools/android_audit.py; --write-baseline regenerates it, and it should only shrink)\n'
CATS = ('apple-api', 'objc-framework', 'page-assumption', 'macho-section')
ROOTS = ('dm/host', 'dm/gfx/nvn')
ALL_ROOTS = ROOTS + ('dm/gfx/metal', 'dm/gfx/vk')
SUFFIXES = frozenset(('.c', '.h', '.m', '.inc', '.S'))
# Other people's code (vendored), and diagnostics that only exist for a developer: not ours to make portable, and not shipped.
EXCLUDE_DIRS = frozenset(('tests',))
EXCLUDE_PREFIX = ('dm/third_party/', 'dm/gfx/vulkan/', 'dm/gfx/vk/probe/', 'dm/gfx/vk/engine_smoke/')
OBJC_SUFFIX = '.m'

# (label, regex): the label names the symbol or construct in --json, so a finding says what to port. Ordered: a line reports the first matching label of a category.
APPLE_API = [
    ('mach', r'\b_?mach_[A-Za-z0-9_]+'),
    ('mach-header', r'#\s*(?:include|import)\s*<mach(?:-o)?/[^>]*>'),
    ('vm', r'\b_?vm_(?:allocate|deallocate|protect|region\w*|recurse\w*|read_overwrite|write_overwrite|page_size|statistics|remap|address_t|size_t|prot_t|machine\w*)'),
    ('mach-o-image', r'\b_mh_execute_header\b'),
    ('section-lookup', r'\bgetsectiondata\b'),
    ('os_unfair_lock', r'\bos_unfair_lock\b'),
    ('dispatch', r'\bdispatch_(?:async|sync|after|once|apply|queue|group|semaphore|source|time\b|data|get_main|get_global|release|retain|set_|qos)'),
    ('qos-class', r'\bpthread_(?:set|get)_qos_class[A-Za-z_]*'),
    ('sysctl', r'\bsysctl\b'),
    ('clonefile', r'\bclonefile\b'),
    ('commoncrypto', r'CommonCrypto|\bCC_(?:SHA1|SHA256|MD5)\b'),
    ('target-conditionals', r'\bTARGET_(?:OS|CPU|IPHONE|SIMULATOR)[A-Z_]*\b|TargetConditionals'),
    ('libkern', r'#\s*(?:include|import)\s*<libkern/[^>]*>|\bsys_(?:i|d)cache_(?:invalidate|flush)\b'),
    ('os-proc', r'#\s*(?:include|import)\s*<os/proc\.h>|\bos_proc_available_memory\b'),
    ('ucontext', r'_STRUCT_ARM_[A-Z0-9_]+|->__ss\b|->__ns\b'),
]
OBJC = [
    ('framework-header', r'#\s*(?:import|include)\s*<(?:Metal|MetalFX|AppKit|UIKit|Foundation|CoreAudio|AudioToolbox|AVFAudio|VideoToolbox|'
                         r'CoreMedia|CoreVideo|GameController|CoreHaptics|IOKit|ImageIO|UniformTypeIdentifiers|QuartzCore|Cocoa|CoreFoundation|objc)/'),
    ('syntax', r'@(?:interface|implementation|protocol|property|synthesize|dynamic|autoreleasepool|try|catch|finally|throw|synchronized|selector|encode|end\b|available|import\b)'),
    # Apple framework types, by name: a bare prefix would also match this tree's own words (NSP, NSLOT, GCreateMalloc, CF as a constant, UINT32_MAX). Add a name when a new one appears.
    ('type', r'\bNS(?:Object|String|Array|MutableArray|Dictionary|MutableDictionary|Number|Error|Data|Set|MutableSet|Range|MakeRange|MaxRange|'
             r'NotFound|BackwardsSearch|Integer|UInteger|TimeInterval|ProcessInfo|UTF8StringEncoding|View|Event|Menu|MenuItem|Application|Window|Bundle|Value)\b'
             r'|\bCF(?:STR|[A-Z][A-Za-z0-9_]*)\b|\bkCF[A-Za-z0-9_]*\b'
             r'|\bMTL[A-Z_][A-Za-z0-9_]*\b'
             r'|\bGC(?:Controller|Motion|Haptics|Synthetic)[A-Za-z0-9_]*\b'
             r'|\bCA[A-Z][a-z][A-Za-z0-9_]*\b'
             r'|\bAV(?:Audio|FAudio|Capture|Sample|Asset|Media|Player|Route)[A-Za-z0-9_]*\b'
             r'|\b(?:CM|CV|VT)[A-Z][a-z][A-Za-z0-9_]*\b'
             r'|\b(?:IOHID|IOSurface|IOReturn|IOKit)[A-Za-z0-9_]*\b'
             r'|\b(?:UIKit|UIView|UIApplication|UIScreen|UTType|MTKView)\b'
             r'|\bid\s*<\s*(?:MTL|NS|CF|id)\w*'),
]
PAGE_CTX = re.compile(r'page|\bpg\b|mmap|mprotect|getpagesize', re.I)
PAGE_LIT = re.compile(r'\b16384\b|\b0x4000\b|\b1\s*<<\s*14\b|\b16\s*K(?:i)?B\b', re.I)
MACHO = [
    ('section', r'__DATA[,_]\w+|__TEXT[,_]\w+|\bsection\s*\(\s*"[^"]+"\s*\)|\bsectcreate\b'),
]
RULES = ([(c, label, re.compile(rx)) for c, table in (('apple-api', APPLE_API), ('objc-framework', OBJC), ('macho-section', MACHO))
          for label, rx in table])


def rel(p): return p.relative_to(REPO).as_posix()
def norm(line): return re.sub(r'\s+', ' ', line).strip()          # reformatting (indentation, tabs, line breaks around a hit are not part of the key)
def digest(text): return hashlib.sha1(text.encode('utf-8', 'replace')).hexdigest()
def shown(text, n=200): return text if len(text) <= n else text[:n] + ' ...'


def walk(roots):
    # The scanned files, sorted: only the shared host and the NVN layer by default, with the vendored and diagnostic trees removed.
    out = []
    for root in roots:
        base = REPO / root
        if not base.is_dir(): continue
        for p in sorted(base.rglob('*')):
            if not p.is_file() or p.suffix not in SUFFIXES: continue
            r = rel(p)
            if r.startswith(EXCLUDE_PREFIX) or EXCLUDE_DIRS & set(pathlib.PurePosixPath(r).parts[:-1]): continue
            out.append((r, p))
    return sorted(out)


def detect(path, line):
    # [(category, label, matched text)] of one line, at most one per category (the line is the unit); in a .m file the ObjC type tokens are the file, not the line.
    hits, done = [], set()
    for cat, label, rx in RULES:
        if cat in done: continue
        m = rx.search(line)
        if not m: continue
        if label == 'type' and path.endswith(OBJC_SUFFIX): continue          # the whole .m file is Objective-C (see --summary)
        hits.append((cat, label, m.group(0).strip()))
        done.add(cat)
    m = PAGE_LIT.search(line) if PAGE_CTX.search(line) else None
    if m: hits.append(('page-assumption', 'page-literal', m.group(0)))
    return sorted(hits)


def scan(roots):
    # Hits keyed by (file, category, sha1 of the normalised line): identical lines of one file and category collapse into one row and one baseline entry.
    hits = {}
    for path, p in walk(roots):
        for n, line in enumerate(p.read_text(errors='replace').split('\n'), 1):
            text = norm(line)
            for cat, label, match in detect(path, line):
                hits.setdefault((path, cat, digest(text)), {'path': path, 'line': n, 'category': cat, 'match': match, 'text': text})
    return sorted(hits.values(), key=lambda h: (h['path'], h['line'], h['category']))


def load():
    base = {}
    if BASELINE.exists():
        for line in BASELINE.read_text().split('\n'):
            if not line or line.startswith('#'): continue
            path, cat, sha, text = line.split('\t', 3)
            base[(path, cat, sha)] = text
    return base


def write(base):
    BASELINE.parent.mkdir(parents=True, exist_ok=True)
    rows = [f'{path}\t{cat}\t{sha}\t{shown(text)}\n' for (path, cat, sha), text in sorted(base.items())]
    BASELINE.write_text(HEADER + ''.join(rows))


def main():
    ap = argparse.ArgumentParser(description='Android portability audit of dm/host and dm/gfx/nvn (what only Apple has)')
    ap.add_argument('--all', action='store_true', help='also scan dm/gfx/metal and dm/gfx/vk, for the report (the baseline covers the default roots)')
    ap.add_argument('--json', action='store_true', help='one JSON object per hit')
    ap.add_argument('--summary', action='store_true', help='counts per category and the top 10 files')
    ap.add_argument('--check', action='store_true', help='fail on a hit not in the baseline and on a baseline row with no hit')
    ap.add_argument('--write-baseline', action='store_true', help='regenerate the baseline (it should only shrink)')
    args = ap.parse_args()
    if args.all and (args.check or args.write_baseline):
        print('android_audit: --all does not apply to --check or --write-baseline: the baseline is the default roots', file=sys.stderr)
    hits = scan(ALL_ROOTS if args.all and not (args.check or args.write_baseline) else ROOTS)
    cur = {(h['path'], h['category'], digest(h['text'])): h['text'] for h in hits}
    line_of = {(h['path'], h['category'], h['text']): h['line'] for h in hits}

    if args.write_baseline:
        before = set(load())
        write(cur)
        added, removed = len(set(cur) - before), len(before - set(cur))
        print(f'android_audit: wrote {len(cur)} hits to {rel(BASELINE)} ({added} added, {removed} removed)')
        return 0
    if args.check:
        base = load()
        new = [(k, v) for k, v in cur.items() if k not in base]
        stale = [(k, v) for k, v in base.items() if k not in cur]
        for (path, cat, _), text in new:
            print(f'[RED] android_audit: {path}:{line_of[(path, cat, text)]}: {cat}: not in the baseline: {shown(text, 160)}')
        for (path, cat, _), text in stale:
            print(f'[RED] android_audit: {path}: {cat}: in the baseline, no longer in the code: {shown(text, 160)}')
        print(f'android_audit: {len(hits)} hits, {len(base)} in the baseline, {len(new)} new, {len(stale)} gone'
              + ('' if not (new or stale) else ' (make a new hit portable, or add it deliberately with --write-baseline, which also drops the gone rows)'))
        return 1 if new or stale else 0
    if args.json:
        for h in hits: print(json.dumps(h))
        return 0
    if args.summary:
        per = {}
        for h in hits: per[h['path']] = per.get(h['path'], 0) + 1
        print(f'android_audit: {len(hits)} hits in {len(per)} files')
        for c in CATS: print(f'  {c:<16}{sum(1 for h in hits if h["category"] == c):>6}')
        print('files:')
        for path, n in sorted(per.items(), key=lambda kv: (-kv[1], kv[0]))[:10]: print(f'  {n:>6} {path}')
        return 0
    prev = None
    for h in hits:
        if prev is not None and h['path'] != prev: print()
        prev = h['path']
        print(f'{h["path"]}:{h["line"]}: {h["category"]}: {h["text"]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
