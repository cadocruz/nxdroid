#!/usr/bin/env python3
"""The vk_probe dump contract as code: `check(text)` lists the ways a dump breaks it (empty means it obeys the contract), so a dump pulled from the S23 is validated
here, on any machine, without the phone or the GPU. dm/gfx/vk/probe prints one fact per line, `key = value`, under `# <section>` headers, and the Android port's
answers come from those facts (is host memory zero-copy, are BC textures there, is the pipeline cache offline, do exec pages work, what is the host page), so a dump
that drifts from the contract quietly removes the evidence a decision rests on.

Run as a script it prints the breaches as `[RED] ` lines and exits 1:
  python3 dm/gfx/vk/probe/tests/test_probe_output.py dm/gfx/vk/probe/tests/fixtures/valid.txt

The contract:
- Sections, each exactly once, in this order: instance, device, extensions, features, limits, memory, formats, external_memory_host, exec_pages, pagesize, verdict.
  A section is the line `# <name>`; nothing else is a header.
- A fact is `<key> = <value>`, one space either side of `=`, inside a section. `;` starts a comment line: `#` marks sections, so a dump says what it is in `;` lines.
- instance: instance_api_version (decoded), instance_extension_count, instance_extension (one extension name per line, sorted ascending).
- device: device_count, then device_selected (the index the dump's answers are about, 0 <= value < device_count), then per device i (0..count-1)
  device.i.name, .device_type, .vendor_id, .device_id, .api_version, .driver_version (decoded: three dot-separated numbers, or four where the vendor encodes a
  fourth), .driver_version_raw (the raw 32-bit value in decimal: it keys the Adreno 740 shader-rewrite gate, so it must not depend on a vendor's decoding),
  .driver_id, .driver_info. # features, # limits, # memory, # formats and # external_memory_host describe the selected device, not every device: one dump is one
  device's answers even when the loader sees several.
- extensions: device_extension, "<name> <specVersion>", sorted ascending by name.
- features: Vulkan feature names in lowerCamelCase, value present|absent (extensions) or true|false (features); any subset.
- limits: Vulkan limit names (lowerCamelCase), decimal, plus timestamp_compute_and_graphics = true|false. The three float limits (timestampPeriod,
  maxSamplerLodBias, maxSamplerAnisotropy) carry three decimals, 1.000. Vulkan's array limits (maxViewportDimensions is uint32_t[2]) take a dotted index,
  maxViewportDimensions.0 = 32768: the contract has no other spelling for them, and `[0]` is not a key.
- memory: memory_heap_count, memory_type_count, then memory_heap.i.size/.flags and memory_type.i.flags/.heap_index for every i below its count.
- formats: VK_FORMAT_ names, value a space-separated subset of sampled storage color depth blit-src blit-dst filter-linear transfer-dst atomic, or none.
- external_memory_host: `absent` alone, or `present` then min_imported_host_pointer_alignment, one host_pointer.<size> per tested size, unaligned_rejected,
  largest_importable (<bytes> or none).
- exec_pages: ok|denied, with exec_pages_errno (the errno of the failed mmap, decimal) only when denied: it separates a SELinux W^X denial from a probe bug.
  pagesize: bytes. verdict: zero_copy ok|copy-only, bc_textures ok|missing, guest_upload_cost none|mirror, pipeline_cache_offline
  ok|recompile, mirror_clamp ok|missing. The verdict must agree with itself: zero_copy = ok exactly when guest_upload_cost = none, copy-only exactly when mirror.
- Deterministic: no ANSI escapes, absolute paths, timestamps or addresses. device.i.driver_info is exempt from the path and timestamp rules: it is the vendor's
  own string and may name a build path or a date, and rejecting a real dump over it would cost the gate its evidence.

This file is the contract's own test: its fixtures are written by hand from the contract above, never from the probe's source, so a probe that prints something else
is reported here instead of being agreed with. No GPU, phone, compiler or game files needed."""
import re, subprocess, sys, pathlib

SECTIONS = ('instance', 'device', 'extensions', 'features', 'limits', 'memory', 'formats', 'external_memory_host', 'exec_pages', 'pagesize', 'verdict')

VERSION = re.compile(r'\d+\.\d+(?:\.\d+)?')                  # a decoded Vulkan API version
DRIVER_VERSION = re.compile(r'\d+\.\d+\.\d+(?:\.\d+)?')        # decoded, so a driver update shows in the diff; Qualcomm and NVIDIA encode a fourth number
DECIMAL = re.compile(r'\d+')
NUMBER = re.compile(r'(?:0[xX][0-9a-fA-F]+|\d+)')            # an id or a flags mask (an address is longer, see hygiene)
CAMEL = re.compile(r'[a-z][A-Za-z0-9_]*')                    # a Vulkan feature or limit name as Vulkan spells it (textureCompressionASTC_LDR has an underscore)
LIMIT = re.compile(r'[a-z][A-Za-z0-9_]*(?:\.[0-9]+)?')      # a limit, with the dotted index an array limit needs (maxViewportDimensions.0)
KEY = re.compile(r'[A-Za-z0-9_.]+')
NAME = re.compile(r'[A-Za-z][A-Za-z0-9_]*')                  # a driver id, short (qualcomm_proprietary) or VK_DRIVER_ID_QUALCOMM_PROPRIETARY
FORMAT_KEY = re.compile(r'VK_FORMAT_[A-Za-z0-9_]+')          # ASTC's 4x4 and friends are lower case in Vulkan's own name
MEMORY_FLAGS = re.compile(r'[A-Za-z0-9_]+(?: [A-Za-z0-9_]+)*')   # flag names, one or more, space separated
FORMAT_USAGE = ('sampled', 'storage', 'color', 'depth', 'blit-src', 'blit-dst', 'filter-linear', 'transfer-dst', 'atomic')
FLOAT_LIMIT = re.compile(r'\d+\.\d{3}')                    # the limits Vulkan stores as floats, printed with three decimals
FLOAT_LIMITS = ('timestampPeriod', 'maxSamplerLodBias', 'maxSamplerAnisotropy')
RAW_VERSION = 0xFFFFFFFF                                      # VkPhysicalDeviceProperties::driverVersion is 32 bits
FEATURE_VALUE = ('present', 'absent', 'true', 'false')
DEVICE_TYPE = ('cpu', 'discrete_gpu', 'integrated_gpu', 'other', 'virtual_gpu')
EXEC_PAGES = ('ok', 'denied')
VERDICT = {'zero_copy': ('ok', 'copy-only'), 'bc_textures': ('ok', 'missing'), 'guest_upload_cost': ('none', 'mirror'),
           'pipeline_cache_offline': ('ok', 'recompile'), 'mirror_clamp': ('ok', 'missing')}
DEVICE_FIELDS = ('name', 'device_type', 'vendor_id', 'device_id', 'api_version', 'driver_version', 'driver_version_raw', 'driver_id', 'driver_info')
DEVICE_KEY = re.compile(r'device\.(\d+)\.([a-z_]+)')
MEMORY_KEY = re.compile(r'memory_(heap|type)\.(\d+)\.([a-z_]+)')
POINTER_KEY = re.compile(r'host_pointer\.(\d+)')
DRIVER_INFO = re.compile(r'device\.\d+\.driver_info')          # the vendor's own string: exempt from the path and timestamp rules
TIMESTAMP = re.compile(r'\b\d{4}-\d{2}-\d{2}(?!\d)|\b\d{2}:\d{2}:\d{2}(?!\d)')
ADDRESS = re.compile(r'0[xX][0-9a-fA-F]{9,}')                 # a pointer is longer than any VkFlags mask (32 bits)
CONTROL = re.compile(r'[\x00-\x08\x0b\x0e-\x1a\x1c-\x1f\x7f]')   # not tab, LF, FF, CR; ESC is reported on its own
ABSOLUTE = re.compile(r'[A-Za-z]:[\\/]')


def split(text):
    """(breaches found while lexing, [(section name, header line, [(line, key, value)])] in file order). Blank lines, `;` comments and CRLF are tolerated: they
    are transport, not facts."""
    bad, sections, cur = [], [], None
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip('\r')
        if not line.strip() or line.lstrip().startswith(';'): continue
        if line.startswith('#'):
            name = line[1:].strip()
            if line != f'# {name}': bad.append((n, f'section header {line!r} is not "# <name>"'))
            cur = (name, n, [])
            sections.append(cur)
            continue
        if cur is None:
            bad.append((n, f'{line!r} comes before the first section'))
            continue
        key, sep, value = line.partition(' = ')
        if not sep or not KEY.fullmatch(key) or not value.strip():
            bad.append((n, f'{line!r} is not "key = value"'))
            continue
        cur[2].append((n, key, value))
    return bad, sections


def hygiene(n, line, vendor=False):
    """the things that make a dump untrustworthy as evidence: its output of one run must equal any other for the same device. `vendor` says the value is the
    driver's own string (driver_info), which legitimately names a build path or a date, so only the path and timestamp rules are waived for it."""
    out = []
    if '\x1b' in line: out.append((n, f'ANSI escape in {line!r}: a dump is not a terminal'))
    if CONTROL.search(line): out.append((n, f'control character in {line!r}'))
    if not vendor:
        for token in line.split():
            if token.startswith(('/', '~/', '\\\\')) or ABSOLUTE.match(token):
                out.append((n, f'absolute path {token!r}: it names one machine, not the device'))
                break
        if TIMESTAMP.search(line): out.append((n, f'a timestamp in {line!r}: two dumps of one device must differ only by the device'))
    m = ADDRESS.search(line)
    if m: out.append((n, f'an address {m.group(0)!r}: the next run gives another one'))
    return out


def structure(bad, sections):
    """the sections: known, once each, in contract order, none missing"""
    seen, end = [], 0
    for name, n, _ in sections:
        if name not in SECTIONS:
            bad.append((n, f'unknown section "# {name}" (the contract has {" ".join(SECTIONS)})'))
            continue
        i = SECTIONS.index(name)
        if name in seen: bad.append((n, f'section "# {name}" appears twice'))
        elif i < end: bad.append((n, f'# {name} appears after # {SECTIONS[end]}: the contract order is {" ".join(SECTIONS)}'))
        seen.append(name)
        end = max(end, i)
    for name in SECTIONS:
        if name not in seen: bad.append((0, f'section "# {name}" is missing'))


def single(name, entries, bad, repeat=()):
    """{key: (line, value)}, flagging a key used twice: the contract keeps every key once, but for the repeated ones it names"""
    one = {}
    for n, k, v in entries:
        if k in repeat: continue
        if k in one: bad.append((n, f'duplicate key {k!r} in # {name}'))
        else: one[k] = (n, v)
    return one


def missing(name, head, one, keys, bad):
    for k in keys:
        if k not in one: bad.append((head, f'# {name}: {k} is missing'))


def unknown(name, one, ok, bad):
    test = ok if callable(ok) else ok.__contains__
    for k, (n, _) in one.items():
        if not test(k): bad.append((n, f'# {name}: unknown key {k!r}'))


def want(name, one, key, good, bad, why):
    if key in one:
        n, v = one[key]
        if not good(v): bad.append((n, f'# {name}: {key} = {v!r}: want {why}'))


def count(name, one, key, bad):
    """the decimal value of a count key, or None (a non-decimal value is already reported)"""
    if key not in one: return None
    n, v = one[key]
    if not DECIMAL.fullmatch(v): bad.append((n, f'# {name}: {key} = {v!r}: want a decimal')); return None
    return int(v)


def ordered(name, lines, what, bad):
    """repeated lines (line, value) sorted ascending by their first token, without duplicates"""
    names, seen = [], set()
    for n, v in lines:
        k = v.split()[0] if v.split() else v
        if k in seen: bad.append((n, f'# {name}: {what} {k!r} is listed twice'))
        if names and k < names[-1]: bad.append((n, f'# {name}: {what} {k!r} follows {names[-1]!r}: the lines are not sorted ascending'))
        names.append(k)
        seen.add(k)


def instance(name, head, entries, bad):
    one = single(name, entries, bad, repeat=('instance_extension',))
    missing(name, head, one, ('instance_api_version', 'instance_extension_count'), bad)
    unknown(name, one, {'instance_api_version', 'instance_extension_count'}, bad)
    want(name, one, 'instance_api_version', VERSION.fullmatch, bad, 'a decoded version')
    exts = [(n, v) for n, k, v in entries if k == 'instance_extension']
    for n, v in exts:
        if not re.fullmatch(r'VK_[A-Za-z0-9_]+', v): bad.append((n, f'# instance: instance_extension = {v!r}: want one extension name per line'))
    ordered(name, exts, 'instance_extension', bad)
    n = count(name, one, 'instance_extension_count', bad)
    if n is not None and n != len(exts):
        bad.append((one['instance_extension_count'][0], f'# instance: instance_extension_count = {n} but {len(exts)} instance_extension lines'))


def device_value(key, v, bad, n):
    if key.endswith('.device_type'):
        if v.lower().replace('vk_physical_device_type_', '') not in DEVICE_TYPE:
            bad.append((n, f'# device: {key} = {v!r}: want one of {" ".join(DEVICE_TYPE)}'))
    elif key.endswith(('.vendor_id', '.device_id')):
        if not NUMBER.fullmatch(v): bad.append((n, f'# device: {key} = {v!r}: want a number (0x5143)'))
    elif key.endswith('.api_version'):
        if not VERSION.fullmatch(v): bad.append((n, f'# device: {key} = {v!r}: want a decoded version'))
    elif key.endswith('.driver_version'):
        if not DRIVER_VERSION.fullmatch(v): bad.append((n, f'# device: {key} = {v!r}: want a decoded version with three or four numbers'))
    elif key.endswith('.driver_version_raw'):
        if not DECIMAL.fullmatch(v) or int(v) > RAW_VERSION:
            bad.append((n, f'# device: {key} = {v!r}: want the raw 32-bit value in decimal'))
    elif key.endswith('.driver_id'):
        if not (NAME.fullmatch(v) or NUMBER.fullmatch(v)): bad.append((n, f'# device: {key} = {v!r}: want a driver id name or number'))


def device(name, head, entries, bad):
    if not entries: bad.append((head, '# device: the section is empty')); return
    if entries[0][1] != 'device_count':
        bad.append((entries[0][0], f'# device: the section starts with {entries[0][1]!r}: device_count comes first'))
    one = single(name, entries, bad)
    missing(name, head, one, ('device_count', 'device_selected'), bad)
    n = count(name, one, 'device_count', bad)
    if n is not None and n < 1: bad.append((one['device_count'][0], f'# device: device_count = {n}: a dump with no device answers nothing'))
    if entries[0][1] == 'device_count' and 'device_selected' in one and len(entries) > 1 and entries[1][1] != 'device_selected':
        bad.append((one['device_selected'][0], '# device: device_selected comes second, right after device_count'))
    selected = count(name, one, 'device_selected', bad)
    if selected is not None and n and not 0 <= selected < n:
        bad.append((one['device_selected'][0], f'# device: device_selected = {selected}: want one of 0..{n - 1}'))
    groups, first = {}, {}
    for line, k, v in entries:
        if k in ('device_count', 'device_selected'): continue
        m = DEVICE_KEY.fullmatch(k)
        if not m or m.group(2) not in DEVICE_FIELDS: bad.append((line, f'# device: unknown key {k!r}')); continue
        i, field = int(m.group(1)), m.group(2)
        first.setdefault(i, line)
        if n is not None and i >= n: bad.append((line, f'# device: {k} names device {i}, but device_count = {n}'))
        g = groups.setdefault(i, {})
        if field in g: continue                            # a duplicate is already reported by single()
        g[field] = v
        device_value(k, v, bad, line)
    for i in sorted(groups):
        for f in DEVICE_FIELDS:
            if f not in groups[i]: bad.append((first[i], f'# device: device.{i}.{f} is missing'))
    if n is not None and sorted(groups) != list(range(n)):
        bad.append((one['device_count'][0], f'# device: device_count = {n}, but the devices listed are {sorted(groups)}'))


def extensions(name, head, entries, bad):
    lines = []
    for n, k, v in entries:
        if k != 'device_extension': bad.append((n, f'# extensions: unknown key {k!r}')); continue
        parts = v.split()
        if len(parts) != 2 or not DECIMAL.fullmatch(parts[1]):
            bad.append((n, f'# extensions: device_extension = {v!r}: want "<name> <specVersion as a decimal>"')); continue
        lines.append((n, v))
    ordered(name, lines, 'device_extension', bad)


def features(name, head, entries, bad):
    one = single(name, entries, bad)
    for k, (n, v) in one.items():
        if not CAMEL.fullmatch(k): bad.append((n, f'# features: {k!r} is not a Vulkan feature name (lowerCamelCase, as Vulkan spells it)'))
        if v not in FEATURE_VALUE: bad.append((n, f'# features: {k} = {v!r}: want present, absent, true or false'))


def limits(name, head, entries, bad):
    if not entries: bad.append((head, '# limits: the section is empty'))
    one = single(name, entries, bad)
    for k, (n, v) in one.items():
        if k == 'timestamp_compute_and_graphics':
            if v not in ('true', 'false'): bad.append((n, f'# limits: {k} = {v!r}: want true or false'))
        elif k in FLOAT_LIMITS:
            if not FLOAT_LIMIT.fullmatch(v): bad.append((n, f'# limits: {k} = {v!r}: want a float with three decimals (1.000)'))
        elif not LIMIT.fullmatch(k):
            bad.append((n, f'# limits: {k!r} is not a Vulkan limit name (maxViewportDimensions, or maxViewportDimensions.0 for an array)'))
        elif not DECIMAL.fullmatch(v):
            bad.append((n, f'# limits: {k} = {v!r}: want a decimal'))


def memory(name, head, entries, bad):
    one = single(name, entries, bad)
    missing(name, head, one, ('memory_heap_count', 'memory_type_count'), bad)
    heaps = count(name, one, 'memory_heap_count', bad)
    types = count(name, one, 'memory_type_count', bad)
    groups, first = {}, {}
    for line, k, v in entries:
        if k in ('memory_heap_count', 'memory_type_count'): continue
        m = MEMORY_KEY.fullmatch(k)
        kind, index, field = (m.group(1), int(m.group(2)), m.group(3)) if m else (None, None, None)
        if not m or field not in (('size', 'flags') if kind == 'heap' else ('flags', 'heap_index')):
            bad.append((line, f'# memory: unknown key {k!r}')); continue
        total = heaps if kind == 'heap' else types
        if total is not None and index >= total: bad.append((line, f'# memory: {k} names {kind} {index}, but there are {total}'))
        first.setdefault((kind, index), line)
        g = groups.setdefault((kind, index), {})
        if field in g: continue
        g[field] = v
        if field == 'size' and not DECIMAL.fullmatch(v): bad.append((line, f'# memory: {k} = {v!r}: want bytes as a decimal'))
        if field == 'flags' and not MEMORY_FLAGS.fullmatch(v): bad.append((line, f'# memory: {k} = {v!r}: want flag names'))
        if field == 'heap_index':
            if not DECIMAL.fullmatch(v): bad.append((line, f'# memory: {k} = {v!r}: want a decimal'))
            elif heaps is not None and int(v) >= heaps: bad.append((line, f'# memory: {k} = {v}: the dump has {heaps} heaps'))
    for (kind, index), fields in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        total = heaps if kind == 'heap' else types
        if total is not None and index >= total: continue
        for f in ('size', 'flags') if kind == 'heap' else ('flags', 'heap_index'):
            if f not in fields: bad.append((first[(kind, index)], f'# memory: memory_{kind}.{index}.{f} is missing'))
    for kind, total in (('heap', heaps), ('type', types)):
        if total is not None and sorted(i for k, i in groups if k == kind) != list(range(total)):
            bad.append((one[f'memory_{kind}_count'][0], f'# memory: memory_{kind}_count = {total}, but the {kind}s listed are '
                        f'{sorted(i for k, i in groups if k == kind)}'))


def formats(name, head, entries, bad):
    if not entries: bad.append((head, '# formats: the section is empty'))
    one = single(name, entries, bad)
    for k, (n, v) in one.items():
        if not FORMAT_KEY.fullmatch(k): bad.append((n, f'# formats: {k!r} is not a VK_FORMAT_ name')); continue
        if v == 'none': continue
        tokens = v.split()
        if not all(t in FORMAT_USAGE for t in tokens) or len(set(tokens)) != len(tokens):
            bad.append((n, f'# formats: {k} = {v!r}: want a space-separated subset of {" ".join(FORMAT_USAGE)}, or none'))


def external_memory_host(name, head, entries, bad):
    if not entries: bad.append((head, '# external_memory_host: the section is empty')); return
    if entries[0][1] != 'external_memory_host':
        bad.append((entries[0][0], f'# external_memory_host: the section starts with {entries[0][1]!r}: external_memory_host comes first'))
    one, pointers = {}, []
    for n, k, v in entries:
        m = POINTER_KEY.fullmatch(k)
        if m: pointers.append((n, int(m.group(1)), v)); continue
        if k in one: bad.append((n, f'duplicate key {k!r} in # {name}'))
        else: one[k] = (n, v)
    state = one.get('external_memory_host', (head, None))[1]
    unknown(name, one, {'external_memory_host', 'min_imported_host_pointer_alignment', 'unaligned_rejected', 'largest_importable'}, bad)
    if 'external_memory_host' not in one: bad.append((head, '# external_memory_host: external_memory_host is missing'))
    elif state not in ('absent', 'present'):
        bad.append((one['external_memory_host'][0], f'# external_memory_host: external_memory_host = {state!r}: want absent or present'))
    elif state == 'absent':
        for n, k, _ in entries:
            if k != 'external_memory_host': bad.append((n, f'# external_memory_host: absent, so {k} has no meaning here'))
    else:
        missing(name, head, one, ('min_imported_host_pointer_alignment', 'unaligned_rejected', 'largest_importable'), bad)
        count(name, one, 'min_imported_host_pointer_alignment', bad)
        want(name, one, 'unaligned_rejected', ('true', 'false').__contains__, bad, 'true or false')
        want(name, one, 'largest_importable', lambda v: v == 'none' or bool(DECIMAL.fullmatch(v)), bad, 'bytes as a decimal, or none')
        if not pointers: bad.append((head, '# external_memory_host: present, but no host_pointer.<size> line was tested'))
        sizes = set()
        for n, size, v in pointers:
            if size in sizes: bad.append((n, f'# external_memory_host: host_pointer.{size} is tested twice'))
            sizes.add(size)
            if not NUMBER.fullmatch(v): bad.append((n, f'# external_memory_host: host_pointer.{size} = {v!r}: want the memory type mask'))


def exec_pages(name, head, entries, bad):
    one = single(name, entries, bad)
    missing(name, head, one, ('exec_pages',), bad)
    unknown(name, one, {'exec_pages', 'exec_pages_errno'}, bad)
    want(name, one, 'exec_pages', EXEC_PAGES.__contains__, bad, ' or '.join(EXEC_PAGES))
    if 'exec_pages_errno' in one:
        n, v = one['exec_pages_errno']
        if not DECIMAL.fullmatch(v): bad.append((n, f'# exec_pages: exec_pages_errno = {v!r}: want the errno as a decimal'))
        if one.get('exec_pages', (head, None))[1] == 'ok':
            bad.append((n, '# exec_pages: exec_pages_errno follows exec_pages = ok: an errno means the mmap was denied'))


def pagesize(name, head, entries, bad):
    one = single(name, entries, bad)
    missing(name, head, one, ('pagesize',), bad)
    unknown(name, one, {'pagesize'}, bad)
    want(name, one, 'pagesize', lambda v: bool(DECIMAL.fullmatch(v)) and int(v) > 0 and not int(v) & (int(v) - 1), bad,
         'the host page in bytes, a power of two')


def verdict(name, head, entries, bad):
    one = single(name, entries, bad)
    missing(name, head, one, tuple(VERDICT), bad)
    unknown(name, one, set(VERDICT), bad)
    for k, good in VERDICT.items():
        want(name, one, k, good.__contains__, bad, ' or '.join(good))
    # The two answers are one fact: host memory is either importable (zero copy, no mirror) or it is not (mirror). A verdict that contradicts itself after the
    # evidence above it is what this contract exists to catch, so it is reported with both values named.
    zc, gu = (one.get(k, (head, None))[1] for k in ('zero_copy', 'guest_upload_cost'))
    if zc in VERDICT['zero_copy'] and gu in VERDICT['guest_upload_cost'] and (zc == 'ok') != (gu == 'none'):
        bad.append((one['guest_upload_cost'][0], f'# verdict: zero_copy = {zc} contradicts guest_upload_cost = {gu}: '
                                                  f'zero_copy ok goes with guest_upload_cost none, copy-only with mirror'))


VALIDATORS = {'instance': instance, 'device': device, 'extensions': extensions, 'features': features, 'limits': limits, 'memory': memory,
              'formats': formats, 'external_memory_host': external_memory_host, 'exec_pages': exec_pages, 'pagesize': pagesize, 'verdict': verdict}


def check(text):
    """the ways a dump breaks the contract, in line order (24: an address); empty means it obeys it. The result depends on the text alone: same dump, same list."""
    bad, sections = split(text)
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip('\r')
        if line.strip() and not line.lstrip().startswith(';'):
            bad += hygiene(n, line, vendor=bool(DRIVER_INFO.fullmatch(line.partition(' = ')[0])))
    structure(bad, sections)
    done = set()
    for name, head, entries in sections:
        if name in SECTIONS and name not in done:
            done.add(name)
            VALIDATORS[name](name, head, entries, bad)
    return [f'line {n}: {m}' if n else m for n, m in sorted(bad)]


FIXTURES = pathlib.Path(__file__).resolve().parent / 'fixtures'
# The invalid fixtures, one class of breach each, and the message that must be in it: a fixture whose breaches change fails here instead of passing quietly.
INVALID = {
    'invalid_missing_verdict.txt': ('section "# verdict" is missing',),
    'invalid_out_of_order.txt': ('# pagesize appears after # verdict',),
    'invalid_unknown_key.txt': ("# device: unknown key 'device.0.queue_count'",),
    'invalid_hygiene.txt': ('a timestamp in', "absolute path '/data/local/tmp/vk_probe.txt'"),
}


def read(name):
    return (FIXTURES / name).read_text(encoding='utf-8')


VALID = read('valid.txt')


def broken(old, new, times=1):
    """the valid fixture with one thing changed; the change must apply exactly `times` times, or the test is testing nothing"""
    assert VALID.count(old) == times, f'{old!r} appears {VALID.count(old)} times, the test expects {times}'
    return VALID.replace(old, new)


def cli(*paths):
    return subprocess.run([sys.executable, str(pathlib.Path(__file__).resolve()), *map(str, paths)], capture_output=True, text=True)


def test_valid_fixture_obeys_the_contract():
    assert check(VALID) == []


def test_crlf_and_comments_are_transport_not_facts():
    assert check(VALID.replace('\n', '\r\n')) == []
    assert check('\r\n' + VALID + '\r\n\r\n') == []


def test_invalid_fixtures_breach_exactly_what_they_name():
    for name, wanted in INVALID.items():
        found = check(read(name))
        assert len(found) == len(wanted), f'{name}: {found}'
        for message, w in zip(found, wanted): assert w in message, f'{name}: {message!r} does not mention {w!r}'


def test_every_fixture_has_a_test():
    # no orphan fixture: one added here without a row above would never run
    assert {p.name for p in FIXTURES.iterdir()} == {'valid.txt'} | set(INVALID)


def test_missing_section():
    lines = VALID.splitlines()
    found = check('\n'.join(lines[:lines.index('# verdict')]))
    assert found == ['section "# verdict" is missing'], found


def test_section_out_of_order():
    moved = broken('# pagesize\npagesize = 4096\n', '')
    found = check(moved + '# pagesize\npagesize = 4096\n')
    assert len(found) == 1 and '# pagesize appears after # verdict' in found[0], found


def test_duplicate_section():
    found = check(VALID + '# pagesize\npagesize = 4096\n')
    assert len(found) == 1 and 'section "# pagesize" appears twice' in found[0], found


def test_unknown_section_and_malformed_header():
    found = check(broken('# features\n', '# device_info\n# features\n'))
    assert len(found) == 1 and 'unknown section "# device_info"' in found[0], found
    found = check(broken('# features\n', '#features\n'))
    assert len(found) == 1 and 'is not "# <name>"' in found[0], found


def test_unknown_key():
    found = check(broken('instance_extension_count = 2\n', 'instance_extension_count = 2\ninstance_layer_count = 0\n'))
    assert len(found) == 1 and "unknown key 'instance_layer_count'" in found[0], found


def test_duplicate_key():
    found = check(broken('timestamp_compute_and_graphics = true\n', 'timestamp_compute_and_graphics = true\nmaxImageDimension2D = 16384\n'))
    assert len(found) == 1 and "duplicate key 'maxImageDimension2D' in # limits" in found[0], found


def test_bad_enum_value():
    for old, new in (('device.0.device_type = integrated_gpu', 'device.0.device_type = gpu_on_a_phone'),
                     ('exec_pages = denied', 'exec_pages = sometimes'),
                     ('zero_copy = ok', 'zero_copy = most-of-the-time'),
                     ('geometryShader = true', 'geometryShader = yes'),
                     ('external_memory_host = present', 'external_memory_host = maybe')):
        found = check(broken(old + '\n', new + '\n'))
        assert len(found) == 1 and 'want' in found[0], f'{new}: {found}'


def test_driver_version_may_have_three_or_four_numbers():
    for value in ('512.744.1', '580.178.4.0'):
        assert check(broken('device.0.driver_version = 24.1.0', f'device.0.driver_version = {value}')) == [], value
    for value in ('24.1', '24', '580.178.4.0.1', '512.744.1-rc1'):
        found = check(broken('device.0.driver_version = 24.1.0', f'device.0.driver_version = {value}'))
        assert len(found) == 1 and 'three or four numbers' in found[0], f'{value}: {found}'


def test_driver_version_raw_is_required_and_decimal():
    # the integer the Adreno 740 gates are keyed on: required, decimal, 32 bits
    found = check(broken('device.0.driver_version_raw = 2435551488\n', ''))
    assert len(found) == 1 and 'device.0.driver_version_raw is missing' in found[0], found
    for value in ('0x912c8100', '2435551488.0', '4294967296'):
        found = check(broken('device.0.driver_version_raw = 2435551488', f'device.0.driver_version_raw = {value}'))
        assert len(found) == 1 and 'raw 32-bit value in decimal' in found[0], f'{value}: {found}'
    assert check(broken('device.0.driver_version_raw = 2435551488', 'device.0.driver_version_raw = 4294967295')) == []


def test_device_selected_is_required_and_in_range():
    found = check(broken('device_selected = 0\n', ''))
    assert len(found) == 1 and 'device_selected is missing' in found[0], found
    for value in ('1', '7', '-1'):
        found = check(broken('device_selected = 0', f'device_selected = {value}'))
        assert len(found) == 1 and 'device_selected' in found[0], f'{value}: {found}'


def test_device_selected_comes_right_after_device_count():
    moved = broken('device_selected = 0\n', '').replace('device.0.name = fixture_device\n',
                                                         'device.0.name = fixture_device\ndevice_selected = 0\n')
    found = check(moved)
    assert len(found) == 1 and 'device_selected comes second' in found[0], found


def test_two_devices_with_the_second_selected():
    last = 'device.0.driver_info = fixture_driver\n'
    more = ''.join(line.replace('device.0.', 'device.1.') + '\n' for line in VALID.splitlines() if line.startswith('device.0.'))
    text = broken('device_count = 1', 'device_count = 2').replace('device_selected = 0', 'device_selected = 1')
    assert check(text.replace(last, last + more)) == []
    found = check(text.replace('device_selected = 1', 'device_selected = 2').replace(last, last + more))
    assert len(found) == 1 and 'device_selected = 2: want one of 0..1' in found[0], found


def test_ansi_escape():
    found = check(broken('device.0.driver_info = fixture_driver', 'device.0.driver_info = \x1b[31mfixture_driver\x1b[0m'))
    assert len(found) == 1 and 'ANSI escape' in found[0], found


def test_absolute_path():
    found = check(broken('device.0.name = fixture_device\n', 'device.0.name = fixture_device /data/local/tmp/vk_probe.txt\n'))
    assert len(found) == 1 and "absolute path '/data/local/tmp/vk_probe.txt'" in found[0], found


def test_timestamp():
    found = check(broken('device.0.name = fixture_device\n', 'device.0.name = fixture_device 2026-10-28T19:40:00\n'))
    assert len(found) == 1 and 'a timestamp in' in found[0], found


def test_driver_info_keeps_the_vendor_text():
    # VkPhysicalDeviceDriverProperties::driverInfo is the vendor's string: Mesa's names its build path, some drivers a date
    text = broken('device.0.driver_info = fixture_driver',
                  'device.0.driver_info = Mesa 25.0.3 (git-abc123) built in /home/builder/mesa at 2026-10-28T19:40:00')
    assert check(text) == []
    found = check(broken('device.0.name = fixture_device\n', 'device.0.name = fixture /home/builder/mesa 2026-10-28T19:40:00\n'))
    assert len(found) == 2, found
    assert any('absolute path' in f for f in found) and any('a timestamp in' in f for f in found), found


def test_address():
    found = check(broken('device.0.driver_info = fixture_driver', 'device.0.driver_info = fixture_driver 0x7fa3c4d2e000'))
    assert len(found) == 1 and "'0x7fa3c4d2e000'" in found[0], found


def test_unsorted_device_extensions():
    found = check(broken('device_extension = VK_EXT_external_memory_host 1\ndevice_extension = VK_EXT_robustness2 1\n',
                         'device_extension = VK_EXT_robustness2 1\ndevice_extension = VK_EXT_external_memory_host 1\n'))
    assert len(found) == 1 and 'are not sorted ascending' in found[0], found


def test_unsorted_instance_extensions():
    found = check(broken('instance_extension = VK_KHR_get_physical_device_properties2\ninstance_extension = VK_KHR_portability_enumeration\n',
                         'instance_extension = VK_KHR_portability_enumeration\ninstance_extension = VK_KHR_get_physical_device_properties2\n'))
    assert len(found) == 1 and 'instance_extension' in found[0] and 'sorted' in found[0], found


def test_line_before_the_first_section():
    found = check('pagesize = 4096\n' + VALID)
    assert found == ["line 1: 'pagesize = 4096' comes before the first section"], found


def test_a_line_that_is_not_key_value():
    found = check(broken('maxImageDimension2D = 16384\n', 'maxImageDimension2D=16384\n'))
    assert len(found) == 1 and 'is not "key = value"' in found[0], found


def test_counts_must_match_the_lines():
    found = check(broken('instance_extension_count = 2', 'instance_extension_count = 4'))
    assert len(found) == 1 and 'instance_extension_count = 4 but 2 instance_extension lines' in found[0], found
    found = check(broken('memory_type.0.heap_index = 0', 'memory_type.0.heap_index = 9'))
    assert len(found) == 1 and 'the dump has 2 heaps' in found[0], found


def test_memory_must_describe_every_index():
    found = check(broken('memory_heap.1.flags = host_visible\n', ''))
    assert len(found) == 1 and 'memory_heap.1.flags is missing' in found[0], found
    found = check(broken('memory_heap_count = 2', 'memory_heap_count = 3'))
    assert len(found) == 1 and 'memory_heap_count = 3, but the heaps listed are [0, 1]' in found[0], found


def test_formats_value_tokens():
    found = check(broken('VK_FORMAT_BC3_UNORM_BLOCK = sampled transfer-dst', 'VK_FORMAT_BC3_UNORM_BLOCK = sampled wobble'))
    assert len(found) == 1 and "want a space-separated subset" in found[0], found


def test_feature_key_is_a_vulkan_name():
    for key in ('16bitStorage', 'ext.VK_KHR_x', 'GeometryShader'):
        found = check(broken('geometryShader = true', f'{key} = true'))
        assert len(found) == 1 and 'Vulkan feature name' in found[0], f'{key}: {found}'
    # Vulkan's own field spelling keeps its underscore: textureCompressionASTC_LDR is not a typo
    assert check(broken('geometryShader = true', 'textureCompressionASTC_LDR = true')) == []


def test_array_limits_take_a_dotted_index():
    assert check(broken('maxImageDimension2D = 16384', 'maxViewportDimensions.0 = 32768\nmaxViewportDimensions.1 = 32768')) == []
    found = check(broken('maxImageDimension2D = 16384', 'maxViewportDimensions[0] = 32768'))
    assert len(found) == 1 and 'is not "key = value"' in found[0], found


def test_float_limits_carry_three_decimals():
    for key in FLOAT_LIMITS:
        assert check(broken('maxImageDimension2D = 16384', f'maxImageDimension2D = 16384\n{key} = 15.000')) == [], key
    for value in ('1', '1.0', '1.0000', '52.5'):
        found = check(broken('maxImageDimension2D = 16384', f'maxImageDimension2D = 16384\ntimestampPeriod = {value}'))
        assert len(found) == 1 and 'three decimals' in found[0], f'{value}: {found}'
    # the float set is by key: a float anywhere else is still not a decimal limit
    found = check(broken('maxImageDimension2D = 16384', 'maxImageDimension2D = 16384.000'))
    assert len(found) == 1 and 'want a decimal' in found[0], found


def test_pagesize_is_a_power_of_two():
    for value in ('4097', '4 KiB', '0'):
        found = check(broken('pagesize = 4096', f'pagesize = {value}'))
        assert len(found) == 1 and 'pagesize' in found[0], f'{value}: {found}'


def test_external_memory_host_absent_is_alone():
    found = check(broken('external_memory_host = present\n', 'external_memory_host = absent\n'))
    assert found and all('absent, so ' in f for f in found), found
    assert any('min_imported_host_pointer_alignment' in f for f in found), found


def test_external_memory_host_present_needs_its_facts():
    found = check(broken('host_pointer.4096 = 0x00000006\nhost_pointer.65536 = 0x00000006\n', ''))
    assert len(found) == 1 and 'present, but no host_pointer.<size> line was tested' in found[0], found
    found = check(broken('unaligned_rejected = true\n', ''))
    assert len(found) == 1 and 'unaligned_rejected is missing' in found[0], found
    found = check(broken('host_pointer.4096 = 0x00000006', 'host_pointer.4096 = six'))
    assert len(found) == 1 and 'want the memory type mask' in found[0], found


def verdict_with(zero, upload):
    text = broken('zero_copy = ok', f'zero_copy = {zero}')
    assert text.count('guest_upload_cost = none') == 1
    return text.replace('guest_upload_cost = none', f'guest_upload_cost = {upload}')


def test_exec_pages_errno_only_when_denied():
    assert check(broken('exec_pages_errno = 13\n', '')) == []          # optional on a denied mmap
    found = check(broken('exec_pages = denied', 'exec_pages = ok'))
    assert len(found) == 1 and 'exec_pages_errno follows exec_pages = ok' in found[0], found
    found = check(broken('exec_pages_errno = 13', 'exec_pages_errno = EACCES'))
    assert len(found) == 1 and 'want the errno as a decimal' in found[0], found


def test_verdict_must_agree_with_itself():
    assert check(verdict_with('copy-only', 'mirror')) == []
    for zero, upload in (('ok', 'mirror'), ('copy-only', 'none')):
        found = check(verdict_with(zero, upload))
        assert len(found) == 1 and 'contradicts' in found[0], found
        assert f'zero_copy = {zero}' in found[0] and f'guest_upload_cost = {upload}' in found[0], found


def test_empty_text_reports_every_section():
    found = check('')
    assert len(found) == len(SECTIONS) and all('is missing' in f for f in found), found


def test_truncated_dump_is_caught():
    # the earlier vk_probe died with SIGSEGV and its dump ended mid-line at "VK_FORMAT_BC", exactly on a 16 KiB flush boundary
    text = VALID[:VALID.index('VK_FORMAT_BC3_UNORM_BLOCK = sampled transfer-dst') + len('VK_FORMAT_BC3_UNORM_BLOCK = sampled trans')]
    found = check(text)
    assert len(found) == 5, found
    for name in ('external_memory_host', 'exec_pages', 'pagesize', 'verdict'):
        assert f'section "# {name}" is missing' in found, (name, found)
    assert any("VK_FORMAT_BC3_UNORM_BLOCK = 'sampled trans'" in f for f in found), found


def test_result_is_a_list_of_strings_in_line_order():
    found = check(read('invalid_hygiene.txt'))
    assert isinstance(found, list) and all(isinstance(f, str) for f in found)
    lines = [int(f[len('line '):f.index(':')]) for f in found if f.startswith('line ')]
    assert lines == sorted(lines), found


def test_check_is_deterministic():
    for text in (VALID, read('invalid_hygiene.txt'), check.__doc__ or '', broken('exec_pages = denied', 'exec_pages = sometimes')):
        assert check(text) == check(text)


def test_script_exits_zero_on_a_valid_dump():
    r = cli(FIXTURES / 'valid.txt')
    assert r.returncode == 0 and r.stdout.strip().endswith('valid'), r.stdout + r.stderr


def test_script_prints_every_breach_as_a_red_line_and_exits_one():
    for name in INVALID:
        first, second = cli(FIXTURES / name), cli(FIXTURES / name)
        assert first.returncode == 1, name
        assert first.stdout == second.stdout, f'{name}: the same dump gave two reports'
        lines = first.stdout.splitlines()
        assert lines and all(line.startswith('[RED] ') for line in lines), f'{name}: {lines}'


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit('usage: test_probe_output.py <dump>...   (the vk_probe dump contract: prints each breach as a [RED] line, exit 1 when there is one)')
    rc = 0
    for arg in sys.argv[1:]:
        try: text = pathlib.Path(arg).read_text(encoding='utf-8', errors='replace')
        except OSError as e:
            print(f'[RED] {arg}: {e}'); rc = 1; continue
        found = check(text)
        for m in found: print(f'[RED] {arg}: {m}')
        if found: rc = 1
        else: print(f'{arg}: valid')
    sys.exit(rc)
