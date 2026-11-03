# 06 — The developer loop: which tool when, and before a pull request

One page for people and agents: the tools this repository has for building, running, debugging, measuring and checking a change, when to use which, and what a pull request needs. It links to where each tool is described instead of repeating it. Game files, keys, builds and runs stay outside the repository ([AGENTS.md](../../AGENTS.md)).

## 1. Build and run on the device

| Step | Tool | Details |
|---|---|---|
| Prepare a game | `python3 scripts/prepare_game_android.py <.nsp, .xci or extracted game folder> --title-id <id>` (`-u <update>`, `-k <prod.keys>`, `--rebuild-shaders`, `--push`, `--device-dir`) | Base and update extraction, the rewriter with `--target=android`, shader translation into `.xgs` bundles, system data; `--push` copies the game folder over `adb`. [README, How to play](../../README.md#how-to-play) |
| Build and install the APK | `gradle -p dm/android :app:assembleDebug -PdmGame=<id>` in the `dm-android-tools:1` podman image, then `adb install -r dm/android/app/build/outputs/apk/debug/app-debug.apk` (or the script's `--build-apk` / `--install-apk`) | [README, How to play](../../README.md#how-to-play) |
| Rebuild only the host | `cmake -S dm/android -B build/android/<id> -DGAME=<id> …` and `cmake --build build/android/<id> --target dmhost` in the same image | [HANDOFF.md](../../HANDOFF.md) §5 |
| Read the log | `adb logcat -d -s dm` | [05, On-device diagnostics](05-debugging.md#on-device-diagnostics) |
| Run with scripted input | `DM_KEYS` (button presses at fixed seconds or frames), `DM_CTL` (presses and dumps while it runs); on Android a switch is set in `nativeStartHost` | [05, Scripted input](05-debugging.md#scripted-input-and-thread-scheduling) |

A new title starts from the [checklist](README.md#checklist-for-a-new-title) and [03](03-bringup.md).

## 2. When something is wrong

1. Search the [symptom index](symptoms.md) for the `[RED]` line, abort text or what you see; it leads to the reference entry and the games it was found on.
2. Crashes: the host's `CRASH sig=…` report, Ghidra / objdump on the rewritten modules: [05](05-debugging.md#reading-a-crash-report).
3. Hangs and threads: `DM_WATCH=<s>` / `DM_WATCH_STALL=<s>` dump every thread ([03, Reading the log](03-bringup.md#reading-the-log)); `DM_THR=1`, `DM_SVC=1`, `DM_FS=1` log thread SVCs, memory SVCs and file opens; `DM_HITCH_DUMP` dumps the guest threads during a hitch ([05](05-debugging.md#scripted-input-and-thread-scheduling)); `DM_HLECOUNT=<file>` counts every HLE function and SVC the game called.
4. Guest state without a debugger: `DM_PROBE` and its watch and heap variants ([05](05-debugging.md#probes-without-a-debugger-dm_probe)).
5. Wrong picture: A/B the Vulkan engine's `gfx-*` markers one at a time with `scripts/android_gfx_ab.py --shot`, and read the `Swapchain` lines ([05, On-device diagnostics](05-debugging.md#on-device-diagnostics)); the method for a glitch that comes and goes is in [05, Intermittent rendering glitches](05-debugging.md#intermittent-rendering-glitches). The Metal replay's dump switches are listed in [04](04-graphics.md#7-diagnostic-switches-host).
6. Slow frames: the `[longframe]` lines, the hitch dump (`DM_HITCH_DUMP`) and the engine's `NVN PERF` lines: [05, GPU time on the device](05-debugging.md#gpu-time-on-the-device).
7. Memory and address space: [05, Memory growth](05-debugging.md#memory-growth).
8. Shaders: `DM_NVN_SHDUMP` (programs missing from the map), `prepare_game_android.py --rebuild-shaders` after a translator or profile change.
9. On the device: the `dm` logcat tag, the `nativeStartHost` lines and the marker files ([05, On-device diagnostics](05-debugging.md#on-device-diagnostics)).
10. Game updates and fixed addresses: `dm/tools/nso_fnmap.py`, `nso_syms.py`, `insn_census.py`, `sdis.py`, `nso2elf.py` ([Tools](../development.md#tools-dmtools)).

## 3. Measuring

There is no benchmark harness for Android: `scripts/bench.py` and `scripts/regress.py` drive the Mac build only. Measure with the engine's `NVN PERF` lines (`fps`, `gpu_ms`, `submit_cpu_ms`, `parts_ms_per_frame`) over the same scene, change one switch at a time with `scripts/android_gfx_ab.py`, and compare runs interleaved: scene, temperature and clock move the numbers between runs ([05, On-device diagnostics](05-debugging.md#on-device-diagnostics)).

## 4. Which games a change can reach: `regress.py impact`

`python3 scripts/regress.py impact <base>..<head>` (or one commit) maps a change to the names in the profiles' usage manifests (`dm/games/<id>/usage.tsv`: the features of each game's translated shaders, and the NVN functions, HLE functions and SVCs one run of its route called): the functions around its changed lines, followed through the host's callers to the NVN entry points and HLE functions they serve, and the rules of `dm/tools/impact_map.tsv`. It lists the games that use what the change touches, those reached only through a broad rule (every game of the API), and the profiles without a manifest as unknown. It reads only git and the committed manifests, so it needs neither game files nor a device: the report is printed, and written as `impact.md` and `impact.json` to `--out`. A changed file no rule maps is listed: add a rule for it.

## 5. Continuous integration

`.github/workflows/tests.yml` runs on every push to `main` and every pull request, on Linux: the `HANDOFF.md` §5 gates and the Android tool tests (`android-gates`, which must stay green), and an NDK compile of `dmhost` and `libdm.so` (`android-build`, advisory until its first green run); nothing runs on a device ([Continuous integration](../development.md#continuous-integration)). `.github/workflows/fuzz.yml` fuzzes the file parsers nightly from synthetic seeds; a change to a parser in `romfs.py`, `nacp.py`, `shader_split.py` or `uepak.py` can run its harness locally (`dm/tools/fuzz/fuzz_<parser>.py --time 300`).

## 6. Before you open a pull request

By what the change touches (the largest that applies):

- **Docs only:** `python3 -m unittest dm/tools/tests/test_docs.py`; after a change to `docs/reference`, `python3 dm/tools/docs_symptoms.py`; after editing `docs/images/gallery.tsv`, `python3 dm/tools/docs_gallery.py` (also resolves conflicts inside README's generated gallery).
- **A Python tool or script** (`scripts/`, the tools under `dm/`): the ratchet `lint-python.yml` runs, ruff and pyright with no new finding: `<venv>/bin/python3 dm/tools/lint_python.py`, from a venv with `.github/requirements/lint.txt` installed, kept on the drive of the NSP folders, not in the home folder ([Continuous integration](../development.md#continuous-integration)). The system Python has neither tool, and the check stops at a `[RED]` line there: that is not a pass. A generated page (`docs_*.py`) is compared in CI on a clean checkout, so it must not read untracked or git-ignored files such as `dm/host/gen`.
- **One game's profile or note** (`dm/games/<id>/`): the Python tool tests; `prepare_game_android.py --rebuild-shaders` for that game after a change to its shader inputs; the game on the device, with its `NVN PERF` numbers when the change is about speed; the finding in the game's note ([AGENTS.md](../../AGENTS.md)).
- **The host, the engine or the tools** (`dm/host`, `dm/gfx`, `dm/android`, `dm/tools`, `scripts`): everything above, the gates of [HANDOFF.md](../../HANDOFF.md) §5 (`android_vendor.py --check`, the `engine_smoke` build and runs, `opcode_map.py --check`, `abi_gaps.py --check`, `android_audit.py --check`, their tests and the engine source checks), `python3 scripts/regress.py impact main..HEAD` to see which games it reaches, the NDK build, and a run on the device of the games it reaches that you have. Name the games you ran and why you chose them: the others are unchecked.
