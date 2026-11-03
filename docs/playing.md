# Playing

How to build the app, prepare a game and put both on the device: [README](../README.md#how-to-play).

- **Starting a game:** the app opens on its launcher, which shows the game folder: `nxdroid/game` in the device's shared storage (`/storage/emulated/0/nxdroid/game`, where `scripts/prepare_game_android.py --push` puts the game) unless you picked another. **Selecionar Pasta** picks another folder with the system's folder picker, **Digitar Path** takes a typed path, and **Reset (/sdcard)** goes back to the default; the app remembers the folder. The folder needs the rewritten `main` module, and the launcher says whether it found it; `shaders/` and `romfs/` (or a `romfs.img`) go beside it. Tap **INICIAR JOGO / START GAME** to start. On Android 11 and later, while the app lacks access to all files, a banner at the top opens the system setting that grants it.
- **Console mode:** the app starts every game in docked (console) mode. It has no settings screen yet ([Settings](settings.md)).
- **Quitting:** press Back during a game and confirm to stop it and return to the launcher.
- **Saves** are in the app's internal storage (`save/` in its files folder), not in the game folder.
- **Logs** go to logcat under the tag `dm`; `[RED] ` lines come at error priority. `adb logcat -d -s dm > log.txt` saves them. When something goes wrong, send that file.

## Touch controls

During a game, the on-screen controller shows a left stick, the D-pad, the A, B, X and Y buttons, L, ZL, R, ZR, − and +, and an **L+R** button that presses both at once. There is no on-screen right stick. The **🎮** button at the top centre hides the controls and shows them again. A touch that misses the controls, and every touch while they are hidden, goes to the game's touch screen.

## Controllers

A connected USB or Bluetooth controller works alongside the touch controls, which stay drawn until you hide them with **🎮**. Its buttons map by position, as on a Switch controller: the bottom face button is B, the right one A, the left one Y and the top one X. Both sticks, the D-pad, the shoulder buttons, the triggers (ZL and ZR), the stick clicks, Start (+) and Select (−) work. There is no rumble or motion (gyro) on Android yet.

## Shaders on first sight

Short stutters the first time a new scene appears are normal: the Vulkan engine builds the pipelines a scene needs on the device the first time it sees them, and keeps them in its pipeline cache for the next launch.
