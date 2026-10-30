"""dm/tools/android_audit.py is the gate on "what only Apple has" in the C/ObjC host the Android port moves onto POSIX/bionic: it finds the Mach and Darwin
libc APIs, the Objective-C frameworks, the 16 KiB host page and the Mach-O linker sections, and the baseline it keeps may only shrink.
These tests run the tool on synthetic trees in a temporary directory, so they need no game files, no Apple SDK and no network."""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch
import json
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / 'dm/tools'))
import android_audit   # noqa: E402

APPLE = 'dm/host/apple.c'
OBJC = 'dm/host/objc.h'
PAGE = 'dm/host/page.c'
MACHO = 'dm/host/macho.c'


class Audit(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.baseline = self.root / 'dm/tools/android_audit_baseline.tsv'
        (self.root / 'dm/tools').mkdir(parents=True)
        for name, target in (('REPO', self.root), ('BASELINE', self.baseline),
                             ('ALL_ROOTS', android_audit.ROOTS + ('dm/gfx/metal',))):
            p = patch.object(android_audit, name, target)
            p.start()
            self.addCleanup(p.stop)

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def run_tool(self, *args):
        out = StringIO()
        with patch.object(sys, 'argv', ['android_audit.py', *args]), redirect_stdout(out):
            rc = android_audit.main()
        return rc, out.getvalue()

    def tree(self):
        self.write(APPLE, 'void f(void) {\n    mach_absolute_time();\n    os_unfair_lock_lock(&l);\n}\n')
        self.write(OBJC, '#import <Metal/Metal.h>\nstatic CAMetalLayer *layer;\n')
        self.write(PAGE, '#define HOST_PAGE 0x4000   /* mprotect granularity */\n')
        self.write(MACHO, '__attribute__((used, section("__DATA,swhle"))) static int ent;\n')

    def categories(self):
        rc, text = self.run_tool('--json')
        self.assertEqual(rc, 0)
        return {(h['path'], h['category']) for h in map(json.loads, text.splitlines())}

    def test_each_category_is_detected(self):
        self.tree()
        found = self.categories()
        self.assertIn((APPLE, 'apple-api'), found)
        self.assertIn((APPLE, 'apple-api'), found)
        self.assertIn((OBJC, 'objc-framework'), found)
        self.assertIn((PAGE, 'page-assumption'), found)
        self.assertIn((MACHO, 'macho-section'), found)
        self.assertEqual({c for _, c in found}, set(android_audit.CATS))

    def test_one_hit_per_line_and_category(self):
        # two Apple APIs on one line are one hit: the line is the unit, so the baseline stays one row per line
        self.write(APPLE, 'uint64_t t = mach_absolute_time(); vm_size_t n = 0;\n')
        rc, text = self.run_tool('--json')
        hits = [json.loads(line) for line in text.splitlines()]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]['category'], 'apple-api')

    def test_objc_type_tokens_are_not_itemised_in_a_m_file(self):
        # one .m file is Objective-C as a whole; itemising its 1,800 MTL lines would bury the findings that matter
        self.write('dm/host/impl.m', '#import <Metal/Metal.h>\n@implementation X\n- (void)f { NSString *s = @"x"; }\n@end\n')
        cats = {h['category'] for h in map(json.loads, self.run_tool('--json')[1].splitlines())}
        self.assertEqual(cats, {'objc-framework'})
        rc, text = self.run_tool('--json')
        self.assertEqual(len(text.splitlines()), 3)          # the #import and the two @-keywords, not NSString

    def test_whitespace_normalisation_keeps_the_baseline_valid(self):
        self.assertEqual(android_audit.norm('  a\t b   c \n'), 'a b c')
        self.write(APPLE, 'void f(void) {\n    mach_absolute_time();\n}\n')
        self.assertEqual(self.run_tool('--write-baseline')[0], 0)
        self.write(APPLE, 'void f(void) {\n\t\tmach_absolute_time();\n}\n')   # reindented: the key is the normalised line
        rc, text = self.run_tool('--check')
        self.assertEqual(rc, 0, text)
        self.assertIn('0 new, 0 gone', text)

    def test_check_passes_with_the_baseline_it_wrote(self):
        self.tree()
        self.assertEqual(self.run_tool('--write-baseline')[0], 0)
        rc, text = self.run_tool('--check')
        self.assertEqual(rc, 0, text)
        self.assertNotIn('[RED]', text)

    def test_a_new_hit_fails_the_check(self):
        self.write(APPLE, 'void f(void) { mach_absolute_time(); }\n')
        self.assertEqual(self.run_tool('--write-baseline')[0], 0)
        self.write(APPLE, 'void f(void) { mach_absolute_time(); }\nvoid g(void) { dispatch_async(q, ^{}); }\n')
        rc, text = self.run_tool('--check')
        self.assertEqual(rc, 1)
        red = [l for l in text.splitlines() if l.startswith('[RED] android_audit:')]
        self.assertEqual(len(red), 1, text)
        self.assertIn(f'{APPLE}:2: apple-api: not in the baseline', red[0])
        self.assertIn('1 new, 0 gone', text)

    def test_a_baseline_row_whose_hit_is_gone_fails_the_check(self):
        self.write(APPLE, 'void f(void) { mach_absolute_time(); }\n')
        self.assertEqual(self.run_tool('--write-baseline')[0], 0)
        self.write(APPLE, 'void f(void) { gettimeofday(0, 0); }\n')
        rc, text = self.run_tool('--check')
        self.assertEqual(rc, 1)
        self.assertIn('[RED] android_audit:', text)
        self.assertIn(f'{APPLE}: apple-api: in the baseline, no longer in the code', text)
        self.assertIn('0 new, 1 gone', text)

    def test_exclusions_and_all(self):
        for path in ('dm/third_party/v.c', 'dm/gfx/vulkan/w.c', 'dm/gfx/vk/probe/p.c', 'dm/gfx/vk/engine_smoke/s.c',
                     'dm/host/tests/t.c', 'dm/gfx/nvn/tests/t.c'):
            self.write(path, 'void f(void) { mach_absolute_time(); }\n')
        self.write('dm/host/notes.md', 'mach_absolute_time()\n')          # not a compiled extension
        self.write('dm/host/kept.c', 'void f(void) { mach_absolute_time(); }\n')
        self.write('dm/gfx/metal/only_with_all.m', 'void f(void) { dispatch_async(q, 0); }\n')
        self.assertEqual(self.categories(), {('dm/host/kept.c', 'apple-api')})
        rc, text = self.run_tool('--all', '--json')
        self.assertEqual({h['path'] for h in map(json.loads, text.splitlines())},
                         {'dm/host/kept.c', 'dm/gfx/metal/only_with_all.m'})

    def test_summary_and_json_agree_and_output_is_deterministic(self):
        self.tree()
        self.assertEqual(self.run_tool('--json')[1], self.run_tool('--json')[1])
        self.assertEqual(self.run_tool()[1], self.run_tool()[1])
        hits = [json.loads(l) for l in self.run_tool('--json')[1].splitlines()]
        self.assertEqual([(h['path'], h['line'], h['category']) for h in hits],
                         sorted((h['path'], h['line'], h['category']) for h in hits))
        summary = self.run_tool('--summary')[1]
        self.assertIn(f'android_audit: {len(hits)} hits in 4 files', summary)
        for cat in android_audit.CATS:
            self.assertIn(cat, summary)
            self.assertEqual(sum(1 for h in hits if h['category'] == cat),
                             int(next(l for l in summary.splitlines() if l.strip().startswith(cat)).split()[-1]))

    def test_json_objects_carry_path_line_category_and_text(self):
        self.write(APPLE, 'void f(void) { mach_absolute_time(); }\n')
        hits = [json.loads(l) for l in self.run_tool('--json')[1].splitlines()]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]['path'], APPLE)
        self.assertEqual(hits[0]['line'], 1)
        self.assertEqual(hits[0]['category'], 'apple-api')
        self.assertEqual(hits[0]['text'], 'void f(void) { mach_absolute_time(); }')
        self.assertIn('mach_', hits[0]['match'])


if __name__ == '__main__':
    unittest.main()
