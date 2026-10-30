"""dm/tools/android_vendor.py keeps the vendored Android Vulkan tree honest: every imported file has a sha256, the upstream repository and commit, a license
and one line of local modification, and the gate fails on a hash mismatch, a vendored file the manifest does not list, and a manifest row whose file is gone.
These tests run the tool on a synthetic tree in a temporary directory, so they need no network and no upstream checkout."""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch
import tempfile
import unittest
import sys

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / 'dm/tools'))
import android_vendor   # noqa: E402

OTHER_COMMIT = '0' * 40


class Vendor(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name).resolve()
        self.manifest = self.root / 'dm/tools/android_vendor.tsv'
        self.patches = []

    def use(self, roots=('vendor',), files=()):
        self.manifest.parent.mkdir(parents=True, exist_ok=True)
        for root in roots:
            (self.root / root).mkdir(parents=True, exist_ok=True)
        for name, target in (('REPO', self.root), ('MANIFEST', self.manifest), ('ROOTS', tuple(roots)), ('FILES', tuple(files))):
            p = patch.object(android_vendor, name, target)
            p.start()
            self.patches.append(p)
            self.addCleanup(p.stop)

    def write(self, name, text='x\n'):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def run_tool(self, function):
        out = StringIO()
        with redirect_stdout(out):
            rc = function()
        return rc, out.getvalue()

    def test_write_then_check_passes_and_is_deterministic(self):
        self.use()
        self.write('vendor/a.c')
        self.write('vendor/sub/b.h')
        rc, text = self.run_tool(android_vendor.write)
        self.assertEqual(rc, 0)
        self.assertIn('wrote 2 rows', text)
        first = self.manifest.read_text(encoding='utf-8')
        self.assertTrue(first.startswith('#'))
        rows = [line.split('\t') for line in first.splitlines() if not line.startswith('#')]
        self.assertEqual([row[0] for row in rows], ['vendor/a.c', 'vendor/sub/b.h'])
        self.assertEqual(rows[0][1], android_vendor.UPSTREAM)
        self.assertEqual(rows[0][2], android_vendor.COMMIT)
        self.assertEqual(rows[0][4], 'MIT')
        rc, text = self.run_tool(android_vendor.check)
        self.assertEqual(rc, 0, text)
        self.run_tool(android_vendor.write)
        self.assertEqual(self.manifest.read_text(encoding='utf-8'), first)

    def test_hash_mismatch_is_red(self):
        self.use()
        self.write('vendor/a.c')
        self.run_tool(android_vendor.write)
        self.write('vendor/a.c', 'changed\n')
        rc, text = self.run_tool(android_vendor.check)
        self.assertEqual(rc, 1)
        self.assertIn('[RED] android_vendor: vendor/a.c', text)
        self.assertIn('does not match', text)

    def test_unlisted_file_is_red(self):
        self.use()
        self.write('vendor/a.c')
        self.run_tool(android_vendor.write)
        self.write('vendor/new.c')
        rc, text = self.run_tool(android_vendor.check)
        self.assertEqual(rc, 1)
        self.assertIn('[RED] android_vendor:', text)
        self.assertIn('vendor/new.c is vendored but not in the manifest', text)

    def test_stale_row_is_red(self):
        self.use()
        self.write('vendor/a.c')
        self.run_tool(android_vendor.write)
        (self.root / 'vendor/a.c').unlink()
        rc, text = self.run_tool(android_vendor.check)
        self.assertEqual(rc, 1)
        self.assertIn('vendor/a.c: is in the manifest but the file is gone', text)

    def test_write_drops_stale_rows_and_keeps_metadata(self):
        self.use()
        self.write('vendor/a.c')
        self.run_tool(android_vendor.write)
        text = self.manifest.read_text(encoding='utf-8').replace('\tMIT\t', '\tMIT\tadapted locally\n')
        self.manifest.write_text(text, encoding='utf-8')
        self.write('vendor/b.c')
        rc, out = self.run_tool(android_vendor.write)
        self.assertEqual(rc, 0)
        self.assertIn('1 adapted', out)
        rows = {line.split('\t')[0]: line.split('\t') for line in self.manifest.read_text(encoding='utf-8').splitlines() if not line.startswith('#')}
        self.assertEqual(rows['vendor/a.c'][5], 'adapted locally')
        self.assertEqual(rows['vendor/b.c'][5], '')

    def test_write_refreshes_a_changed_sha_and_keeps_the_metadata(self):
        # An adapted file's bytes are no longer upstream's: --write must take the sha256 from the tree (or
        # --check could never pass again) while keeping the provenance and the recorded modification.
        self.use()
        self.write('vendor/a.c')
        self.run_tool(android_vendor.write)
        text = self.manifest.read_text(encoding='utf-8').replace('\tMIT\t', '\tMIT\tadapt: local block\n')
        self.manifest.write_text(text, encoding='utf-8')
        self.write('vendor/a.c', 'changed\n')
        rc, out = self.run_tool(android_vendor.write)
        self.assertEqual(rc, 0)
        self.assertIn('1 sha256 changed', out)
        rows = {line.split('\t')[0]: line.split('\t') for line in self.manifest.read_text(encoding='utf-8').splitlines() if not line.startswith('#')}
        self.assertEqual(rows['vendor/a.c'][3], android_vendor.digest(self.root / 'vendor/a.c'))
        self.assertEqual(rows['vendor/a.c'][5], 'adapt: local block')
        self.assertEqual(rows['vendor/a.c'][1], android_vendor.UPSTREAM)
        rc, out = self.run_tool(android_vendor.check)
        self.assertEqual(rc, 0, out)

    def test_script_that_lost_its_execute_bit_is_red(self):
        self.use()
        path = self.write('vendor/run.sh', '#!/bin/sh\n')
        path.chmod(0o755)
        self.run_tool(android_vendor.write)
        p = patch.object(android_vendor, 'EXECUTABLE', ('vendor/run.sh',))
        p.start()
        self.addCleanup(p.stop)
        rc, out = self.run_tool(android_vendor.check)
        self.assertEqual(rc, 0, out)
        path.chmod(0o644)
        rc, out = self.run_tool(android_vendor.check)
        self.assertEqual(rc, 1)
        self.assertIn('is executable upstream but has no execute bit here', out)

    def test_unknown_third_party_license_stops_write(self):
        self.use()
        self.write('vendor/third_party/newdep/x.h')
        with self.assertRaisesRegex(SystemExit, 'unknown third-party directory'):
            self.run_tool(android_vendor.write)
        self.assertFalse(self.manifest.exists())

    def test_pin_must_be_a_commit_and_not_a_branch(self):
        self.use()
        self.write('vendor/a.c')
        p = patch.object(android_vendor, 'COMMIT', 'main')
        p.start()
        self.addCleanup(p.stop)
        self.run_tool(android_vendor.write)
        rc, out = self.run_tool(android_vendor.check)
        self.assertEqual(rc, 1)
        self.assertIn("pinned commit 'main' is not a 40-character commit hash", out)

    def test_wrong_pin_and_license_are_red(self):
        self.use()
        self.write('vendor/a.c')
        self.run_tool(android_vendor.write)
        text = self.manifest.read_text(encoding='utf-8')
        self.manifest.write_text(text.replace(android_vendor.COMMIT, OTHER_COMMIT).replace('\tMIT\t', '\tGPL-3.0\t', 1), encoding='utf-8')
        rc, out = self.run_tool(android_vendor.check)
        self.assertEqual(rc, 1)
        self.assertIn('commit ' + OTHER_COMMIT + ' is not the pinned', out)
        self.assertIn("license 'GPL-3.0' is not one of", out)

    def test_explicit_files_are_covered(self):
        self.use(roots=(), files=('one.c', 'missing.c'))
        self.write('one.c')
        rc, _ = self.run_tool(android_vendor.write)
        self.assertEqual(rc, 0)
        self.assertIn('one.c', self.manifest.read_text(encoding='utf-8'))
        rc, out = self.run_tool(android_vendor.check)
        self.assertEqual(rc, 0, out)

    def test_summary_counts_commits_adapted_and_licenses(self):
        self.use()
        self.write('vendor/a.c')
        self.write('vendor/engine/third_party/bcdec/b.h')
        self.run_tool(android_vendor.write)
        text = self.manifest.read_text(encoding='utf-8').replace('vendor/a.c\t', 'vendor/a.c\t', 1)
        rows = []
        for line in text.splitlines():
            if line.startswith('#'):
                continue
            fields = line.split('\t')
            if fields[0] == 'vendor/a.c':
                fields[5] = 'adapt pending'
            rows.append('\t'.join(fields))
        header = ''.join(line + '\n' for line in text.splitlines() if line.startswith('#'))
        self.manifest.write_text(header + ''.join(row + '\n' for row in rows), encoding='utf-8')
        rc, out = self.run_tool(android_vendor.summary)
        self.assertEqual(rc, 0, out)
        self.assertIn(f'{android_vendor.UPSTREAM}@{android_vendor.COMMIT}', out)
        self.assertIn(': 2', out)
        self.assertIn('adapted (a modification is recorded or pending): 1', out)
        self.assertIn('vendor/a.c', out)
        self.assertIn('MIT 1, MIT-OR-Unlicense 1', out)


if __name__ == '__main__':
    unittest.main()
