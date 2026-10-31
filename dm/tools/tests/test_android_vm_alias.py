"""Unit test verifying guest address space reservation and dm_vm_alias on Linux / Android.

Tests:
1. dm_guest_as_reserve: memfd-backed reservation with MAP_SHARED and PROT_NONE.
2. mprotect: transitions pages to PROT_READ | PROT_WRITE.
3. dm_vm_alias (dynamic): creates a second mapping to == NULL with MAP_SHARED.
4. dm_vm_alias (fixed): creates a second mapping to != NULL with MAP_FIXED | MAP_SHARED.
5. Write coherence: writes to guest memory are visible across all alias mappings and vice versa.
6. Independent page protections: modifying VMA protection on source page does not alter alias protection.
7. Out-of-bounds checks: alias requests outside reserved guest AS return NULL with EINVAL.
8. Release: dm_guest_as_release unmaps AS and closes memfd; subsequent alias requests return ENOTSUP.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[3]
TEST_C = REPO / 'dm/android/tests/test_vm_alias.c'


class AndroidVmAlias(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_vm_alias_native_execution(self):
        compiler = shutil.which('clang') or shutil.which('gcc')
        self.assertIsNotNone(compiler, 'clang or gcc required on host to run vm_alias native test')

        out_bin = Path(self.tmp.name) / 'test_vm_alias'
        res = subprocess.run([compiler, '-Wall', '-Wextra', str(TEST_C), '-o', str(out_bin)],
                             capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f'Host compilation failed: {res.stderr}')

        run_res = subprocess.run([str(out_bin)], capture_output=True, text=True)
        self.assertEqual(run_res.returncode, 0, f'Test run failed: {run_res.stderr}')
        self.assertIn('ALL TESTS PASSED', run_res.stdout)

    def test_vm_alias_android_ndk_compilation(self):
        podman = shutil.which('podman')
        if not podman:
            self.skipTest('podman not available for NDK cross-compilation check')

        ndk_clang = '/opt/android-sdk/ndk/29.0.14206865/toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android29-clang'
        cmd = [
            podman, 'run', '--rm', '--userns=keep-id',
            '-v', f'{REPO}:/src:rw',
            '-w', '/src',
            'dm-android-tools:1',
            ndk_clang, '-Wall', '-Wextra', '-c', 'dm/android/tests/test_vm_alias.c',
            '-o', '/tmp/test_vm_alias.o'
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f'NDK compilation failed: {res.stderr}')

    def test_port_android_ndk_compilation(self):
        podman = shutil.which('podman')
        if not podman:
            self.skipTest('podman not available for NDK cross-compilation check')

        ndk_clang = '/opt/android-sdk/ndk/29.0.14206865/toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android29-clang'
        cmd = [
            podman, 'run', '--rm', '--userns=keep-id',
            '-v', f'{REPO}:/src:rw',
            '-w', '/src',
            'dm-android-tools:1',
            ndk_clang, '-c', 'dm/android/port_android.c',
            '-I', 'dm/android',
            '-I', 'dm/host',
            '-I', 'dm/host/tests/memory_profile',
            '-I', 'dm/android/compat/include',
            '-I', 'build/gen',
            '-o', '/tmp/port_android.o'
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f'NDK compilation of port_android.c failed: {res.stderr}')
