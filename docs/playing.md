# Playing

How to build the app, prepare a game and put both on the device: [README](../README.md#how-to-play).

- **Starting a game:** the app opens on its launcher, which lists the games in its library folder: `nxdroid` in the device's shared storage (`/storage/emulated/0/nxdroid`), whose `game` subfolder is where `scripts/prepare_game_android.py --push` puts a game. A game is a folder with the rewritten `main` module; the launcher takes the library folder itself when it is one, otherwise each subfolder that is. Each game shows its name, publisher, version and title ID (from the `control.nacp` the prepare script copies), its icon, size, shader bundles and RomFS. **Change folder** picks another library folder with the system's folder picker; **Settings** can type a path or go back to the default; the app remembers the folder. **Launch** (or a second tap on the selected game) starts it.
- **One game per APK:** the APK is built for one game (`-PdmGame=<title ID>`, [README](../README.md#how-to-play)), and the launcher marks each game: **Built into this APK** (it starts), **Needs its own APK** (another game: the launcher refuses it and names the build command) or **Title ID unknown** (no `control.nacp`: it asks before trying).
- **Controllers in the launcher:** the D-pad or the left stick moves the selection, A launches, Y rescans the folder, X changes it, + opens the settings, − turns the touch controls on or off, and L / R turn the page (four games a page).
- **Settings:** the performance HUD (FPS, frame time, GPU time) and the touch controls, each on or off and remembered, the library folder, and, on Android 11 and later while the app lacks it, access to all files, which the host needs to read the game (the launcher says so in red until it is granted).
- **Console mode:** the app starts every game in docked (console) mode. Per-game settings do not exist on Android yet ([Settings](settings.md)).
- **Quitting:** press Back during a game and confirm: the game stops and the app closes with it (the host ends the app's process), so unsaved progress is lost. Open the app again to get back to the launcher.
- **Saves** are in the app's internal storage (`save/` in its files folder), not in the game folder.
- **Logs** go to logcat under the tag `dm`; `[RED] ` lines come at error priority. `adb logcat -d -s dm > log.txt` saves them. When something goes wrong, send that file.

## Touch controls

During a game, the on-screen controller shows a left stick, the D-pad, the A, B, X and Y buttons, L, ZL, R, ZR, − and +, and an **L+R** button that presses both at once. There is no on-screen right stick. The **🎮** button at the top centre hides the controls and shows them again. A touch that misses the controls, and every touch while they are hidden, goes to the game's touch screen.

## Controllers

A connected USB or Bluetooth controller works alongside the touch controls, which stay drawn until you hide them with **🎮**. Its buttons map by position, as on a Switch controller: the bottom face button is B, the right one A, the left one Y and the top one X. Both sticks, the D-pad, the shoulder buttons, the triggers (ZL and ZR), the stick clicks, Start (+) and Select (−) work. There is no rumble or motion (gyro) on Android yet.

## Shaders on first sight

Short stutters the first time a new scene appears are normal: the Vulkan engine builds the pipelines a scene needs on the device the first time it sees them, and keeps them in its pipeline cache for the next launch.
