# Front ends

A graphical app that prepares games, keeps a library of them or starts them can be a project of its own that builds on nxdroid. This page lists what such an app can rely on today: how it prepares a game, how it starts one in the Android app, and the settings list each game's profile defines. When a front end needs more, the piece it needs is an issue or a small PR here.

- [Preparing a game](#preparing-a-game)
- [Starting a game](#starting-a-game)
- [The settings list](#the-settings-list)
- [What a front end cannot see yet](#what-a-front-end-cannot-see-yet)

## Preparing a game

`scripts/prepare_game_android.py <input>` prepares one game, from an extracted game folder or a `.nsp` / `.xci` file: it extracts the base and its update, rewrites the modules for Android, packs the RomFS into `romfs.img` and compiles the shaders, into the folder `-o` names. `--push` copies the result to the device over ADB (`--device-dir`, by default `/storage/emulated/0/nxdroid/game`); `--build-apk` and `--install-apk` build and install the app for the game's profile. `--help` lists the other options. It writes its progress as text meant for people.

## Starting a game

The app is `com.nxdroid`, and its activity `com.nxdroid/.MainActivity` (`scripts/android_gfx_ab.py` starts it with `adb shell am start -n com.nxdroid/.MainActivity`). Two intent extras start a game from outside the launcher: the string `gameDir` sets the game folder, which the app also keeps as its launcher's folder, and the boolean `autoStart`, when true, starts the game at once. The folder holds what the launcher expects there ([Playing](playing.md)): the rewritten `main` beside the other modules, `shaders/`, and `romfs/` or `romfs.img`. The app passes no settings to the host: it sets the host's environment itself (`dm/android/jni_android.c`), console mode among it.

## The settings list

`dm/games/settings.py` writes the settings a game supports, as `launcher.json`, from `dm/games/settings.tsv`, whose header describes the rows ([Settings](settings.md) says what each one does). Today only the legacy Apple packing runs it (`dm/ios/tools/build_ipa.sh`, `dm/mac/pack_app.py`); the Android app neither carries nor reads the list yet. Breath of the Wild's list, shortened:

```json
{"schema": 1, "game": "01007EF00011E000", "settings": [
 {"env": "DM_FPS_TARGET", "kind": "choice", "section": "Game", "label": "Frame rate", "note": "…", "default": "60",
  "options": [["30", "30 fps"], ["60", "60 fps"]], "level": "basic"},
 {"env": "DM_RENDER_SCALE", "kind": "range", "section": "Game", "label": "Render scale", "note": "…", "default": "1.0", "min": 0.5, "max": 1.0, "step": 0.05},
 {"env": "DM_FPS_HOLD", "kind": "toggle", "section": "Performance", "label": "Hold frames when late", "note": "…", "default": "on", "on": "on", "off": "off"}
]}
```

- `env`: the environment switch the setting sets. `kind`: `choice` (one of `options`, each `[value, label]`), `range` (a number from `min` to `max` in `step`s) or `toggle` (`on` or `off`, the values the switch takes).
- `section`: the heading the row goes under, today `Game`, `Controls` or `Performance`. Sections come in the order of their first rows, and rows in the order to show them. A new section may appear in schema 1: a reader draws a section it does not know like the others, under its name.
- `default`: the tested default for the platform the list was written for ([Tested defaults](settings.md#tested-defaults)), with profile defaults resolved for its game. A front end that keeps only the choices that differ from it lets a newer build's tested defaults reach the player.
- `base` (optional, render scale only): `{"docked": [w, h], "handheld": [w, h]}`, the 3D views' size that the scale multiplies, so a front end can show 0.75 as 1200×675 docked. It comes from the game's profile (`render_base`), and only some games have it.
- `level` (optional): `basic` marks a setting to show first, for a front end that shows a short list and puts the rest behind a second step. Without it, the front end decides.
- `needs` (optional): `<VAR>=<value>` makes the row a sub-setting of the row that sets `<VAR>`, drawn only while that row has that value (Rumble strength only while rumble is on). A row naming a variable the list does not have stays drawn.
- An app without the file has no settings to offer: start it as it is.

**Compatibility.** [launcher.schema.json](launcher.schema.json) describes the file as a JSON Schema, so a front end can check it and generate its types from it. `schema` is 1, and schema 1 grows only by optional fields: a reader ignores fields it does not know, draws sections it does not know, and a field never changes its meaning. A new `kind` would be schema 2, since a reader cannot draw a kind it does not know. A list written before the field existed has no `schema` and is 1. In `settings.tsv`, the optional fields come from the last column, `meta` (`key=value` pairs separated by `;`); a new key is added in `settings.py`'s `META`, here and in the schema together, and `test_launcher_settings.py` fails when the three disagree.

## What a front end cannot see yet

While a game runs, the host says what happens only in its log (logcat, tag `dm`), as text meant for people, red lines included. A front end that reads the log to show these would break when a line's wording changes. Events a program can read (one JSON object per line) would be the next piece of this interface; until then, treat log lines as diagnostics, not as an interface.
