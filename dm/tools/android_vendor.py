#!/usr/bin/env python3
# Provenance gate for the Android Vulkan engine vendored from jhaizhou-ops/d2r-mobile. dm/tools/android_vendor.tsv records, per imported file, the upstream
# repository, the full 40-character commit, its sha256, its license and the local modification (one line, empty for the upstream bytes, "Pending adaptation: ..."
# for a change this repository still owes). The commit is pinned in this file: updating the vendor tree means changing COMMIT/TAG/DATE here, running --write and
# reviewing every changed row.
#   --write    regenerate the manifest from the tree, keeping each existing row's metadata (upstream, commit, license, modifications) and taking every
#              sha256 from the file as it is now; new files get the pin and their directory's license; rows whose file is gone are dropped. An unknown
#              third_party/ directory stops the run so its notice is read before anything is stamped MIT. The output is sorted by path and deterministic.
#   --check    exit 1 with [RED] lines on a sha256 mismatch, a vendored file missing from the manifest, a manifest row whose file is gone, a row outside the
#              vendored roots, a row that names another upstream or commit, a pinned commit that is not 40 hex digits, or a script that lost its execute bit;
#              exit 0 otherwise. CI runs this.
#   --summary  print the number of rows per upstream commit, the adapted files and the license counts.
# Vendored roots are scanned recursively; the single files that do not live in one are listed in FILES.
# Usage: python3 dm/tools/android_vendor.py --check
import argparse, hashlib, re, sys, pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
MANIFEST = REPO / 'dm/tools/android_vendor.tsv'
UPSTREAM = 'https://github.com/jhaizhou-ops/d2r-mobile'
COMMIT = '1e0e7934c9ccdf95494aee5065d1d07ab3cc3918'
TAG = 'v2.1.0'
DATE = '2026-10-28'
ROOTS = ('dm/gfx/vulkan', 'dm/android/compat', 'dm/android/docker')
FILES = ('dm/android/CMakeLists.txt', 'dm/android/front_android.c', 'dm/android/tools/asm_elf.py',
         'dm/android/vulkan_present.cpp', 'dm/android/vulkan_present.h',
         # Upstream added these three to dm/gfx/, a directory that is otherwise ours. They are listed one by one: making
         # dm/gfx/nvn a root would sweep this repository's own headers into a manifest of another repository's files.
         'dm/gfx/nvn/nvn_copy_pitch.h', 'dm/gfx/nvn/nvn_pool_flags_registry.h', 'dm/gfx/xtrace.h')
# The one file that is executable upstream; the sha256 does not cover the mode bit, so --check tests it separately.
EXECUTABLE = ('dm/android/docker/build.sh',)
LICENSES = ('MIT', 'MIT-CMU', 'MIT-OR-Unlicense')
HEADER = ('# path\tupstream\tcommit\tsha256\tlicense\tmodifications   '
          '(dm/tools/android_vendor.py; regenerate with --write, check with --check)\n'
          '# modifications: empty when the bytes are upstream\'s; "Pending adaptation: ..." for a change this repository still owes.\n'
          f'# Pinned: {UPSTREAM} @ {COMMIT} (tag {TAG}, committed {DATE})\n')
SHA = re.compile(r'[0-9a-fA-F]{64}')
COMMIT_RE = re.compile(r'[0-9a-f]{40}')


def rel(path):
    return path.resolve().relative_to(REPO).as_posix()


def license_for(path):
    # The two third-party directories carry their own license, kept beside the files. A new third-party directory must not
    # inherit the engine's MIT by default: --write stops so that its notice is read and named here.
    if '/third_party/bcdec/' in path:
        return 'MIT-OR-Unlicense'
    if '/third_party/pillow_reference/' in path:
        return 'MIT-CMU'
    if '/third_party/' in path:
        raise SystemExit(f'android_vendor: {path}: unknown third-party directory; read its license and add it to license_for and LICENSES')
    return 'MIT'


def vendored():
    # every file the manifest must cover: the recursive roots plus the explicit files, sorted by path
    found = []
    for root in ROOTS:
        base = REPO / root
        if base.is_dir():
            found += [rel(p) for p in base.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name != '.DS_Store']
    for name in FILES:
        path = REPO / name
        if path.is_file():
            found.append(rel(path))
    return sorted(set(found))


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def load():
    # rows in file order and a path -> row map; returns (rows, errors)
    rows, errors = [], []
    if not MANIFEST.exists():
        return rows, [f'{rel(MANIFEST)} does not exist']
    for number, line in enumerate(MANIFEST.read_text(encoding='utf-8').splitlines(), 1):
        if not line or line.startswith('#'):
            continue
        fields = line.split('\t')
        if len(fields) != 6:
            errors.append(f'{rel(MANIFEST)}:{number}: expected 6 tab-separated columns, found {len(fields)}')
            continue
        rows.append(tuple(fields))
    return rows, errors


def write():
    existing = {row[0]: row for row in load()[0]}
    current = vendored()
    rows = []
    changed = 0
    for path in current:
        row = existing.get(path)
        # The metadata is what a row records about where the file came from (upstream, commit, license,
        # modification); the sha256 is always the bytes in the tree, so that --write is the way to record
        # an adapted file and --check stays a real test.
        sha = digest(REPO / path)
        if row:
            if row[3].lower() != sha:
                changed += 1
            rows.append((row[0], row[1], row[2], sha, row[4], row[5]))
        else:
            rows.append((path, UPSTREAM, COMMIT, sha, license_for(path), ''))
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(HEADER + ''.join('\t'.join(row) + '\n' for row in rows), encoding='utf-8')
    dropped = len(set(existing) - set(current))
    adapted = sum(1 for row in rows if row[5])
    print(f'android_vendor: wrote {len(rows)} rows ({adapted} adapted, {changed} sha256 changed) to {rel(MANIFEST)}'
          + (f', dropped {dropped} rows whose file is gone' if dropped else ''))
    return 0


def check():
    rows, errors = load()
    current = vendored()
    if not COMMIT_RE.fullmatch(COMMIT):
        errors.append(f'{rel(MANIFEST)}: pinned commit {COMMIT!r} is not a 40-character commit hash')
    listed = set()
    for path, upstream, commit, sha, license_, note in rows:
        where = path
        if path in listed:
            errors.append(f'{where}: duplicate row')
        listed.add(path)
        if upstream != UPSTREAM:
            errors.append(f'{where}: upstream {upstream} is not the pinned {UPSTREAM}')
        if commit != COMMIT:
            errors.append(f'{where}: commit {commit} is not the pinned {COMMIT}')
        if not SHA.fullmatch(sha):
            errors.append(f'{where}: sha256 {sha!r} is not 64 hexadecimal digits')
        if license_ not in LICENSES:
            errors.append(f'{where}: license {license_!r} is not one of {", ".join(LICENSES)}')
        file = REPO / path
        if not file.is_file():
            errors.append(f'{where}: is in the manifest but the file is gone')
        elif SHA.fullmatch(sha):
            actual = digest(file)
            if actual != sha.lower():
                errors.append(f'{where}: sha256 {actual} does not match the manifest ({sha})')
    if [row[0] for row in rows] != sorted(row[0] for row in rows):
        errors.append(f'{rel(MANIFEST)}: rows are not sorted by path')
    for path in EXECUTABLE:
        file = REPO / path
        if file.is_file() and not (file.stat().st_mode & 0o111):
            errors.append(f'{path}: is executable upstream but has no execute bit here')
    for path in current:
        if path not in listed:
            errors.append(f'{rel(MANIFEST)}: {path} is vendored but not in the manifest (run --write)')
    for path in sorted(listed - set(current)):
        if (REPO / path).is_file():
            errors.append(f'{rel(MANIFEST)}: {path} is outside the vendored roots and files')
    for error in errors:
        print(f'[RED] android_vendor: {error}')
    if errors:
        print(f'android_vendor: {len(errors)} problem(s) in {rel(MANIFEST)}')
        return 1
    print(f'android_vendor: {len(rows)} files match {rel(MANIFEST)} (commit {COMMIT})')
    return 0


def summary():
    rows, errors = load()
    if errors:
        for error in errors:
            print(f'[RED] android_vendor: {error}')
        return 1
    counts = {}
    licenses = {}
    adapted = []
    for path, upstream, commit, sha, license_, note in rows:
        counts[(upstream, commit)] = counts.get((upstream, commit), 0) + 1
        licenses[license_] = licenses.get(license_, 0) + 1
        if note.strip():
            adapted.append(path)
    print(f'android_vendor: {len(rows)} files in {rel(MANIFEST)}')
    for (upstream, commit), n in sorted(counts.items()):
        tag = f' (tag {TAG})' if (upstream, commit) == (UPSTREAM, COMMIT) else ''
        print(f'  {upstream}@{commit}{tag}: {n}')
    print(f'  adapted (a modification is recorded or pending): {len(adapted)}')
    for path in adapted:
        print(f'    {path}')
    print('  licenses: ' + ', '.join(f'{name} {licenses[name]}' for name in sorted(licenses)))
    return 0


def main():
    ap = argparse.ArgumentParser(description='provenance gate for the vendored Android Vulkan engine')
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument('--write', action='store_true', help='regenerate dm/tools/android_vendor.tsv from the tree')
    group.add_argument('--check', action='store_true', help='fail on a hash mismatch, an unlisted file or a stale row')
    group.add_argument('--summary', action='store_true', help='print counts per upstream commit and the adapted files')
    args = ap.parse_args()
    if args.write:
        return write()
    if args.summary:
        return summary()
    return check()


if __name__ == '__main__':
    sys.exit(main())
