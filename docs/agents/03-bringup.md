# 03 — Host bring-up

## The loop

```bash
python3 scripts/prepare_game_android.py <.nsp or extracted game> --title-id <title ID> --push   # rewrite, shaders, push
# build and install the APK for GAME=<title ID>: README.md, How to play
adb logcat -c                                   # then start the game in com.nxdroid
adb logcat -d -s dm > $W/run/<name>.log
```

`prepare_game_android.py` rewrites every module with `patch_nso.py --target=android` on every run (the loader refuses the default Apple output), builds the shaders and, with `--push`, copies the game folder to the device (`--device-dir`). The app's host writes stdout and stderr to logcat under the tag `dm` (`dm/android/jni_android.c`); `nativeStartHost` sets `DM_ROMFS`, `DM_SAVE`, `DM_TEMP`, the shader map and the graphics defaults, and logs each value it set. Logs may contain non-UTF-8 bytes: use `grep -a` / `LC_ALL=C` when filtering.

## Reading the log

| Marker | Meaning |
|---|---|
| `>>> nnosInitialize`, `>>> nnMain` | Boot stages reached |
| `[RED] …` | Something unimplemented or wrong, printed once per kind. Collect them with `grep -aF "[RED]" log \| sort \| uniq -c` after every run |
| `UNIMPL <name>` | A forced NVN / SDK stub was called |
| `[nvn] frame N: … \| name=count …` | Per-frame NVN call counts (calls made on the frame thread; command buffers recorded elsewhere replay later) |
| `[longframe]` | A long frame, with submit / GPU / pipeline / upload breakdown |
| `memory up to frame N: resident … GPU allocated …` | Memory report of the Metal replay; the Vulkan replay prints none ([05](05-debugging.md#memory-growth)) |
| `NVN PERF … fps= … gpu_ms= …` | The Vulkan engine's frame rate and CPU / GPU time: see [05](05-debugging.md#on-device-diagnostics) |
| `CRASH sig=… pc=… lr=…` + registers + `bt:` + `stack scan` + thread dump | Crash report: see [05](05-debugging.md) |
| `thread 0x10xx 'name' … waits:<state> addr=…` | Thread dump: what each guest thread waits on (`address` = address arbiter, `mutex` = mutex with holder, `condvar`, `sync object`, `running/not waiting` = running); a thread waiting in an SVC also gets a `guest stack:` line, the words on its guest stack that point into a module (its callers when the code keeps no frame pointers) and x19–x28 |

Useful switches: `DM_FS=1` (file opens, and not-found probes), `DM_SVC=1` (memory SVCs and other syscalls), `DM_THR=1` (thread SVCs), `DM_WATCH=<s>` (dump all threads after s seconds), `DM_WATCH_STALL=<s>` (dump when the frame loop stops progressing). The host reads them from its environment; the app sets only what `nativeStartHost` sets, so one of these needs a change there and a rebuild. The graphics switches have marker files instead ([05](05-debugging.md#on-device-diagnostics)).

## Failure catalogue

The failures met so far are filed by subsystem, one entry per mechanism (symptom, cause, fix, the games it was found on): [rewriter](../reference/rewriter.md), [memory and address space](../reference/memory.md), [threads](../reference/threads.md), [services and SDK calls](../reference/services.md), [movies](../reference/movies.md), [audio](../reference/audio.md), [frame rate](../reference/frame-rate.md), [NVN objects](../reference/nvn-objects.md) and [game state](../reference/game-state.md); graphics in [rendering](../reference/rendering.md) and [shaders](../reference/shaders.md). Most new-title failures are one of them in a new form, so search the [symptom index](symptoms.md) for the assertion, `[RED]` text, abort site or visible result first, then read the entry and the game notes it names.

A new finding goes to one place: a general mechanism as an entry in its reference (with a line in the symptom index), a fact about one game in that game's note (`dm/games/<id>/README.md`).
