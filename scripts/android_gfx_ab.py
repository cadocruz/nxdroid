#!/usr/bin/env python3
"""A/B one engine switch on the device without rebuilding.

The Vulkan engine reads marker files named gfx-<switch> from the game folder (the folder with `main` and `shaders/`):
a marker whose first character is 0 turns that switch off, anything else turns it on, and a marker wins over the
environment the app sets. This script writes or removes a marker, restarts the app, and can save a screenshot and the
`dm` log so two runs can be compared.

Examples:
    python3 scripts/android_gfx_ab.py gfx-noload --off --shot noload_off.png --log noload_off.txt
    python3 scripts/android_gfx_ab.py gfx-noload --clear            # back to the default
    python3 scripts/android_gfx_ab.py --list                         # markers present on the device

It only uses adb on a connected device; it installs nothing. Exit code is non-zero on any adb failure.
"""
import argparse
import shutil
import subprocess
import sys
import time

# MainActivity's default (Environment.getExternalStorageDirectory() + "/nxdroid/game") and prepare_game_android.py's --device-dir
DEFAULT_GAME_DIR = "/storage/emulated/0/nxdroid/game"
PACKAGE = "com.nxdroid"
ACTIVITY = "com.nxdroid/.MainActivity"


def adb(args, adb_path, serial, binary=False):
    cmd = [adb_path] + (["-s", serial] if serial else []) + args
    res = subprocess.run(cmd, capture_output=True)
    if res.returncode != 0:
        sys.stderr.write("adb failed: %s\n%s\n" % (" ".join(cmd), res.stderr.decode(errors="replace")))
        sys.exit(1)
    return res.stdout if binary else res.stdout.decode(errors="replace")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("marker", nargs="?", help="marker name, for example gfx-noload (see gfx-* in xbg_game.cpp)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--off", action="store_true", help="write the marker with 0 (switch off); the default")
    mode.add_argument("--on", action="store_true", help="write the marker with 1 (switch on)")
    mode.add_argument("--clear", action="store_true", help="remove the marker (back to the default)")
    mode.add_argument("--clear-all", action="store_true", help="remove every gfx-* marker in the game folder")
    mode.add_argument("--list", action="store_true", help="list the gfx-* markers on the device and exit")
    ap.add_argument("--game-dir", default=DEFAULT_GAME_DIR, help="folder with `main` (default %(default)s)")
    ap.add_argument("--adb", default=shutil.which("adb") or "adb", help="path to adb")
    ap.add_argument("-s", "--serial", help="device serial when more than one is attached")
    ap.add_argument("--no-restart", action="store_true", help="do not force-stop and start the app")
    ap.add_argument("--wait", type=int, default=45, help="seconds to wait after the start before the screenshot / log")
    ap.add_argument("--shot", help="save a screenshot (PNG) to this path after --wait seconds")
    ap.add_argument("--log", help="save `logcat -d -s dm` to this path after --wait seconds")
    a = ap.parse_args()

    gd = a.game_dir.rstrip("/")
    if a.list:
        out = adb(["shell", "ls", gd], a.adb, a.serial)
        for name in out.split():
            if name.startswith("gfx-"):
                val = adb(["shell", "head", "-c", "8", "%s/%s" % (gd, name)], a.adb, a.serial).strip()
                print("%s = %r" % (name, val))
        return 0
    if not a.marker and not a.clear_all:
        ap.error("give a marker name (or --list / --clear-all)")

    if a.clear_all:
        adb(["shell", "rm -f %s/gfx-*" % gd], a.adb, a.serial)
        print("removed every gfx-* marker in", gd)
    elif a.clear:
        adb(["shell", "rm", "-f", "%s/%s" % (gd, a.marker)], a.adb, a.serial)
        print("removed", a.marker)
    else:
        value = "1" if a.on else "0"
        adb(["shell", "echo %s > %s/%s" % (value, gd, a.marker)], a.adb, a.serial)
        check = adb(["shell", "cat", "%s/%s" % (gd, a.marker)], a.adb, a.serial).strip()
        if check != value:
            sys.stderr.write("marker readback was %r, expected %r\n" % (check, value))
            return 1
        print("wrote %s = %s in %s" % (a.marker, value, gd))

    if not a.no_restart:
        adb(["shell", "am", "force-stop", PACKAGE], a.adb, a.serial)
        adb(["logcat", "-c"], a.adb, a.serial)
        adb(["shell", "am", "start", "-n", ACTIVITY], a.adb, a.serial)
        print("app restarted; start the race by hand, then wait for the capture")

    if a.shot or a.log:
        print("waiting %d s ..." % a.wait)
        time.sleep(a.wait)
    if a.shot:
        png = adb(["exec-out", "screencap", "-p"], a.adb, a.serial, binary=True)
        with open(a.shot, "wb") as f:
            f.write(png)
        print("screenshot saved to", a.shot)
    if a.log:
        log = adb(["logcat", "-d", "-s", "dm"], a.adb, a.serial)
        with open(a.log, "w", encoding="utf-8") as f:
            f.write(log)
        print("log saved to", a.log)
    return 0


if __name__ == "__main__":
    sys.exit(main())
