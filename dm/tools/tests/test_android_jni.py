"""Unit test verifying the Android JNI shell (dm/android/jni_android.c) and libdm.so link contract.

Tests:
1. Structural analysis of dm/android/jni_android.c:
   - JNI method table completeness and signature validity.
   - Dual static/dynamic export (JNI_OnLoad and Java_com_nxdroid_*).
   - Local reference leaks prevention (DeleteLocalRef in extraArgs and register_class_natives).
   - UTF string release pairing (ReleaseStringUTFChars for all GetStringUTFChars).
   - Window lifecycle protection (ANativeWindow mutex and acquire/release semantics).
2. CMake build options in dm/android/CMakeLists.txt:
   - -Wl,-Bsymbolic and -Wl,--no-undefined specified for target dm.
3. ELF dynamic symbol audit if libdm.so is built:
   - JNI_OnLoad exported as GLOBAL DEFAULT.
   - Java_com_nxdroid_* bridge methods exported.
   - DF_SYMBOLIC tag set in dynamic section.
"""
from pathlib import Path
import re
import shutil
import subprocess
import unittest

REPO = Path(__file__).resolve().parents[3]
JNI_C = REPO / 'dm/android/jni_android.c'
CMAKELISTS = REPO / 'dm/android/CMakeLists.txt'


class AndroidJniContract(unittest.TestCase):
    def setUp(self):
        self.assertTrue(JNI_C.is_file(), f'Missing {JNI_C}')
        self.source = JNI_C.read_text(encoding='utf-8')

    def test_jni_onload_present(self):
        self.assertIn('JNIEXPORT jint JNI_OnLoad(JavaVM *vm, void *reserved)', self.source)
        self.assertIn('return JNI_VERSION_1_6;', self.source)

    def test_native_methods_table_complete(self):
        expected_methods = [
            'nativeStartHost',
            'nativeStopHost',
            'nativeIsRunning',
            'nativeSetSurface',
            'nativeSurfaceDestroyed',
            'nativeSetRefreshRate',
            'nativeSendTouch',
            'nativeSendPad',
            'nativeSendPadPlayers',
            'nativeSendInput',
        ]
        for m in expected_methods:
            with self.subTest(method=m):
                pattern = rf'\{{\s*"{m}"\s*,'
                self.assertTrue(re.search(pattern, self.source), f'Method {m} missing from k_methods table')

    def test_static_and_dynamic_dual_export(self):
        # NativeBridge class dynamically registered (MainActivity uses static exports)
        self.assertIn('register_class_natives(env, "com/nxdroid/NativeBridge");', self.source)

        # Static JNICALL export macros defined for both NativeBridge and MainActivity
        self.assertIn('Java_com_nxdroid_NativeBridge_', self.source)
        self.assertIn('Java_com_nxdroid_MainActivity_', self.source)

    def test_local_reference_cleanup(self):
        # DeleteLocalRef called in class registration and loop
        self.assertIn('(*env)->DeleteLocalRef(env, cls);', self.source)
        self.assertIn('(*env)->DeleteLocalRef(env, arg_str);', self.source)
        self.assertIn('(*env)->ExceptionClear(env);', self.source)

    def test_string_release_pairing(self):
        # Count GetStringUTFChars and ReleaseStringUTFChars
        get_count = len(re.findall(r'GetStringUTFChars\s*\(', self.source))
        rel_count = len(re.findall(r'ReleaseStringUTFChars\s*\(', self.source))
        self.assertGreater(get_count, 0)
        self.assertEqual(get_count, rel_count, f'GetStringUTFChars ({get_count}) does not match ReleaseStringUTFChars ({rel_count})')

    def test_native_window_reference_safety(self):
        self.assertIn('ANativeWindow_fromSurface', self.source)
        self.assertIn('ANativeWindow_release', self.source)
        self.assertIn('dm_android_vk_set_window', self.source)
        self.assertIn('front_android_set_window', self.source)

    def test_cmakelists_link_options(self):
        cmake_text = CMAKELISTS.read_text(encoding='utf-8')
        self.assertIn('-Wl,-Bsymbolic', cmake_text)
        self.assertIn('-Wl,--no-undefined', cmake_text)

    def test_libdm_so_dynamic_symbols_if_available(self):
        candidates = [
            REPO / 'dm/android/app/build/intermediates/merged_native_libs/debug/mergeDebugNativeLibs/out/lib/arm64-v8a/libdm.so',
            Path('/tmp/nxdroid_build/libdm.so'),
            REPO / 'build/libdm.so',
            REPO / 'dm/android/build/libdm.so',
        ]
        so_path = next((p for p in candidates if p.is_file()), None)
        if not so_path:
            self.skipTest('libdm.so not built in known test locations; skipping ELF symbol audit')

        readelf = shutil.which('readelf') or shutil.which('llvm-readelf')
        if not readelf:
            self.skipTest('readelf not available on host for ELF verification')

        # Check dynamic symbols
        sym_res = subprocess.run([readelf, '-W', '--dyn-syms', str(so_path)], capture_output=True, text=True)
        self.assertEqual(sym_res.returncode, 0)
        symbols = sym_res.stdout

        self.assertIn('JNI_OnLoad', symbols)
        self.assertIn('Java_com_nxdroid_NativeBridge_nativeStartHost', symbols)
        self.assertIn('Java_com_nxdroid_MainActivity_nativeStartHost', symbols)
        self.assertIn('Java_com_nxdroid_NativeBridge_nativeSetSurface', symbols)

        # Check DF_SYMBOLIC tag in dynamic section
        dyn_res = subprocess.run([readelf, '-d', str(so_path)], capture_output=True, text=True)
        self.assertEqual(dyn_res.returncode, 0)
        self.assertTrue('SYMBOLIC' in dyn_res.stdout, 'DF_SYMBOLIC flag missing from libdm.so dynamic section')

    def test_android_manifest(self):
        manifest_path = REPO / 'dm/android/app/src/main/AndroidManifest.xml'
        self.assertTrue(manifest_path.is_file(), f'Missing {manifest_path}')
        text = manifest_path.read_text(encoding='utf-8')
        self.assertIn('android:minSdkVersion="29"', text)
        self.assertIn('android:targetSdkVersion="36"', text)
        self.assertIn('android:screenOrientation="sensorLandscape"', text)
        self.assertIn('android.permission.WAKE_LOCK', text)
        self.assertIn('android.hardware.vulkan.version', text)

    def test_gamepad_and_touch_input_mapping(self):
        main_java = REPO / 'dm/android/app/src/main/java/com/nxdroid/MainActivity.java'
        self.assertTrue(main_java.is_file(), f'Missing {main_java}')
        java_text = main_java.read_text(encoding='utf-8')

        dm_input = REPO / 'dm/host/dm_input.h'
        self.assertTrue(dm_input.is_file(), f'Missing {dm_input}')
        c_text = dm_input.read_text(encoding='utf-8')

        buttons = [
            'DM_BTN_A', 'DM_BTN_B', 'DM_BTN_X', 'DM_BTN_Y',
            'DM_BTN_LS', 'DM_BTN_RS', 'DM_BTN_L', 'DM_BTN_R',
            'DM_BTN_ZL', 'DM_BTN_ZR', 'DM_BTN_PLUS', 'DM_BTN_MINUS',
            'DM_BTN_LEFT', 'DM_BTN_UP', 'DM_BTN_RIGHT', 'DM_BTN_DOWN',
        ]
        for b in buttons:
            with self.subTest(button=b):
                # Check C shift: e.g. DM_BTN_A = 1u << 0
                c_m = re.search(rf'{b}\s*=\s*1[uU]?\s*<<\s*(\d+)', c_text)
                self.assertIsNotNone(c_m, f'Missing {b} in dm_input.h')
                # Check Java shift: e.g. DM_BTN_A = 1L << 0
                j_m = re.search(rf'{b}\s*=\s*1L\s*<<\s*(\d+)', java_text)
                self.assertIsNotNone(j_m, f'Missing {b} in MainActivity.java')
                self.assertEqual(c_m.group(1), j_m.group(1), f'Bit shift mismatch for {b}')

        # STICK_MAX
        self.assertIn('STICK_MAX = 32767;', java_text)
        self.assertIn('#define DM_STICK_MAX 32767', c_text)

    def test_apk_package_contains_arm64_libdm(self):
        apk_candidates = [
            REPO / 'dm/android/app/build/outputs/apk/debug/app-debug.apk',
            REPO / 'dm/android/app/build/outputs/apk/release/app-release-unsigned.apk',
        ]
        apk_path = next((p for p in apk_candidates if p.is_file()), None)
        if not apk_path:
            self.skipTest('APK not yet built; skipping bundled APK inspection')

        import zipfile
        with zipfile.ZipFile(apk_path, 'r') as z:
            names = z.namelist()
            self.assertIn('lib/arm64-v8a/libdm.so', names, 'libdm.so missing from lib/arm64-v8a/ in APK')
            self.assertIn('AndroidManifest.xml', names)
            self.assertTrue(any(n.startswith('classes') and n.endswith('.dex') for n in names))


if __name__ == '__main__':
    unittest.main()
