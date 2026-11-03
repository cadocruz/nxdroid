# Contributing

Issues and pull requests are welcome. This page says how a change gets in; what the code does and where things are is in [AGENTS.md](AGENTS.md), [docs/development.md](docs/development.md) and, for the state of the Android port, [HANDOFF.md](HANDOFF.md).

## Reporting a problem

Open an issue with the bug report form. It asks for what a problem is traced with: the nxdroid commit, the game's title ID and version, the device and Android version, how the game was prepared and started, the `gfx-*` marker files and environment overrides, and the whole log of the run. The app writes its log to logcat under the tag `dm`: after the run, `adb logcat -d -s dm > log.txt` ([Playing](docs/playing.md)). A screenshot helps for a wrong picture.

`scripts/bug_report.py` collects the logs of nxnative's Mac and iPhone builds; it does not read an Android device yet, so attach the logcat file yourself. Look at it before you attach it: logs carry no game files, but check that no line holds key material.

## Never game files or keys

Never commit or attach game files, keys, title keys or anything extracted from a game: RomFS, code modules, shaders, dumps. Game files and their extractions stay next to the game, outside this repository ([AGENTS.md](AGENTS.md)). Logs, screenshots, title IDs, build IDs and offsets are fine.

## Before you start

- Read [AGENTS.md](AGENTS.md): it lists where to start for each kind of task, and the rules for profiles, per-build knowledge and the shader translation chain. [HANDOFF.md](HANDOFF.md) says what works on Android, what is open, and the commands of the gates.
- A crash, a hang or a wrong picture: search the [symptom index](docs/agents/symptoms.md) for the text in the log first. For the Vulkan replay, the engine's switches can be turned off one at a time without a rebuild (`scripts/android_gfx_ab.py`, HANDOFF.md §8 item 12).
- Another game: follow [Port another game](docs/development.md#port-another-game).
- Prefer a fix that holds for every game to a game-specific rule, and fix a bug at its cause ([AGENTS.md](AGENTS.md)).

## A pull request

- **One change per PR, off `main`.** Rebase on `main` rather than merging it in.
- **Commits.** Each commit message says what changed and why, in plain English sentences, as the history does: the symptom, the cause, the fix, and what was measured or checked.
- **Where findings go.** A fact about one game goes in its note (`dm/games/<id>/README.md`). A general mechanism gets an entry in `docs/reference/<subsystem>.md` (Symptom, Cause, Fix, Found on), followed by `python3 dm/tools/docs_symptoms.py`. A new game takes its profile, its note and its row in the games table ([dm/games/README.md](dm/games/README.md)).
- **The shader chain.** After changing one of its tools, run `python3 dm/gfx/tools/dmsh_chain.py --header` and commit `dm/gfx/nvn/dmsh_chain.h` with the change. Every game's shaders are then rebuilt, so say which games you checked.
- **Tests.** CI runs on Linux on every push and pull request: the Android gates and tool tests, and an NDK build of `dmhost` and `libdm.so`; both must pass ([Continuous integration](docs/development.md#continuous-integration)). Nothing in CI runs on a device: say what you ran on one, with which game.
- **The PR text.** Fill in the template: what and why, what was checked (tests, games, devices), and which docs changed.

## Large changes

- **Agree on the scope first.** Open an issue before writing a change that adds a device class, adds a second implementation of an existing path, or runs to more than about 1,000 lines. A large PR built on an older `main` can rarely be reviewed or merged, however well it was tested.
- **One concern per PR.** A new front end, a device baseline and one game's fixes are separate PRs, each on current `main`.
- **Supported devices:** Android 10 (API 29) or later on arm64-v8a with Vulkan; the port is developed and tested on a Samsung Galaxy S23 Ultra (Adreno 740). Other GPUs (Mali, Xclipse, older Adreno) have driver differences the engine gates by device; supporting one is a change to agree on in an issue first.

## How changes get in

The maintainer reviews every PR. A PR is often taken in as a squashed or reworked commit on `main` that credits its author (`Co-authored-by`), and the PR is then closed rather than merged; that is expected. The maintainer may rebase or rework a PR that conflicts with `main` while taking it in.
