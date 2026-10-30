# nxdroid

nxdroid is an Android-only port of [nxnative](https://github.com/seedds/nxnative), which runs Nintendo Switch games natively: the game's own AArch64 code runs, rewritten only where the platform requires it, on a host that answers Horizon's SVCs and the SDK's services (`dm/host`). The Switch's graphics (NVN) are replayed on Vulkan. The target device is a Samsung Galaxy S23 Ultra (Adreno 740). It is not an emulator, and nothing from any game is in this repository. The project is not affiliated with Nintendo or any game publisher.

## Status

**The Android port has not been built or run.** No NDK build has been done, and nothing has run on a device. No game is known to run on Android. What exists:

- The host and the game profiles from nxnative, with the Apple-only calls moved behind `dm/host/port.h` and bionic implementations in `dm/android/port_android.c`. These were read and syntax-checked only; no arm64 compile of the host files has been done.
- A vendored Vulkan replay engine and its adapter (`dm/gfx/vulkan`), imported from [d2r-mobile](https://github.com/jhaizhou-ops/d2r-mobile) at a pinned commit. Its Vulkan device requirements were measured on the S23 Ultra with a probe, and the engine was compiled and initialized out of tree on desktop machines. No game frame has been drawn with it.
- A CMake build for the host (`dm/android/CMakeLists.txt`), configured only with a desktop toolchain.

The state in detail, with the open items and what is unverified, is in [HANDOFF.md](HANDOFF.md) and [docs/reference/android.md](docs/reference/android.md).

Android is the only target. The Mac and iOS builds are not kept: the Apple code (Metal, the iOS app, the Mac app, the IPA packing scripts) is still in the tree and is to be removed, so parts of the documentation still describe it.

## How the Android build is structured

The build is `dm/android/CMakeLists.txt`:

- **One game per build.** `-DGAME=<title id>` picks the profile in `dm/games/<id>/`, as `GAME=` does for `make -C dm/host`. There is no default: without it the configure stops and lists the profiles. `DM_GAMES_DIR` points it at a profile outside the repository.
- **Target.** `arm64-v8a` only, with `ANDROID_PLATFORM` 29 or later (the configure stops below it). The Android NDK is required; `dm/android/docker/` pins one build environment (NDK 29.0.14206865).
- **Sources.** The host sources are read from `dm/host/Makefile`. The graphics layer is `dm/gfx/vulkan` in place of the Metal replay (`dm/gfx/nvn/nvn_mtl.m`), presented through `dm/android/vulkan_present.cpp`.
- **Output.** The target is `dmhost`. The app shell (`jni_android.c`, the Java activity, touch input, Gradle) does not exist yet, so there is no APK.

The configure and build commands are in [HANDOFF.md](HANDOFF.md#5-gates-and-the-exact-commands); they have not been run with an NDK.

## How to play

There are no Android instructions yet: packing a game for Android, installing it and its controls are pending until a build exists. The Mac and iOS instructions (the IPA packing script, sideloading) are not valid for this port and are not repeated here.

## Open

- The NDK configure and build, and the compile errors the host files are expected to give on bionic.
- The app shell: the JNI entry, the activity, touch input, packaging.
- Graphics for the Vulkan and OpenGL games: `dm/gfx/vk/hle_vk.m` and `dm/gfx/gl/hle_gl.m` are Metal code, so a game that renders through them has no graphics layer on Android yet.
- Guest memory: the Adreno 740 has no `VK_EXT_external_memory_host`, so the replay mirrors guest memory. Whether an `AHardwareBuffer` route can avoid the copy is not measured.
- Shaders: the Adreno 740 limits a storage-buffer binding to 128 MiB and has no 64-bit integers in shaders; [the address-space decision](dm/gfx/vk/address_space.md) is written and not tested on a device.
- Audio and movie decoding: the Apple audio and video APIs are stubs that log a `[RED]` line, so a game is silent where it uses AAC and shows black frames for AVC movies; no Android backend is designed.
- Several viewports in one draw, and the other items listed in [the Android reference](docs/reference/android.md).

## Games

The profiles are the games nxnative supports; see the [per-game notes](dm/games/README.md#games) for each game's build, SDK, engine and graphics API. Those notes and the screenshots and sizes below come from the Mac and iPhone builds of nxnative. They say nothing about Android: none of these games has been run on Android.

The size under each game is its IPA size on iOS; "60 fps with 1.2.0" marks a game that nxnative runs at 60 fps (30 on the Switch) with that update.

<!-- gallery: written by dm/tools/docs_gallery.py from docs/images/gallery.tsv; change the table, then run it -->
<table>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/mario-kart-8-deluxe.jpg" width="256" alt="Mario Kart 8 Deluxe"><br><sub><b>Mario Kart 8 Deluxe</b><br>~11.9 GB · no Mii heads</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/mario-vs-donkey-kong.jpg" width="256" alt="Mario vs. Donkey Kong"><br><sub><b>Mario vs. Donkey Kong</b><br>~1.6 GB</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/paper-mario-the-thousand-year-door.jpg" width="256" alt="Paper Mario: The Thousand-Year Door"><br><sub><b>Paper Mario: The Thousand-Year Door</b><br>~5 GB · 60 fps with 1.0.1</sub></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/super-mario-3d-world.jpg" width="256" alt="Super Mario 3D World + Bowser's Fury"><br><sub><b>Super Mario 3D World + Bowser's Fury</b><br>~3 GB</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/super-mario-bros-wonder.jpg" width="256" alt="Super Mario Bros. Wonder"><br><sub><b>Super Mario Bros. Wonder</b><br>~4 GB</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/super-mario-galaxy.jpg" width="256" alt="Super Mario Galaxy"><br><sub><b>Super Mario Galaxy</b><br>~3 GB</sub></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/super-mario-galaxy-2.jpg" width="256" alt="Super Mario Galaxy 2"><br><sub><b>Super Mario Galaxy 2</b><br>~3 GB</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/super-mario-odyssey.jpg" width="256" alt="Super Mario Odyssey"><br><sub><b>Super Mario Odyssey</b><br>~6 GB</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/zelda-breath-of-the-wild.jpg" width="256" alt="The Legend of Zelda: Breath of the Wild"><br><sub><b>The Legend of Zelda: Breath of the Wild</b><br>~16 GB · 60 fps with 1.9.0</sub></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/zelda-links-awakening.jpg" width="256" alt="The Legend of Zelda: Link's Awakening"><br><sub><b>The Legend of Zelda: Link's Awakening</b><br>~6 GB</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/zelda-tears-of-the-kingdom.jpg" width="256" alt="The Legend of Zelda: Tears of the Kingdom"><br><sub><b>The Legend of Zelda: Tears of the Kingdom</b><br>~17 GB · 60 fps with 1.4.3</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/13-sentinels.jpg" width="256" alt="13 Sentinels: Aegis Rim"><br><sub><b>13 Sentinels: Aegis Rim</b><br>~5 GB</sub></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/absolum.jpg" width="256" alt="Absolum"><br><sub><b>Absolum</b><br>~2 GB</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/ace-attorney-investigations.jpg" width="256" alt="Ace Attorney Investigations Collection"><br><sub><b>Ace Attorney Investigations Collection</b><br>~7 GB</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/advance-wars-1-2-re-boot-camp.jpg" width="256" alt="Advance Wars 1+2: Re-Boot Camp"><br><sub><b>Advance Wars 1+2: Re-Boot Camp</b><br>~7.1 GB</sub></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/ai-the-somnium-files.jpg" width="256" alt="AI: THE SOMNIUM FILES"><br><sub><b>AI: THE SOMNIUM FILES</b><br>~8.3 GB</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/ai-the-somnium-files-nirvana-initiative.jpg" width="256" alt="AI: THE SOMNIUM FILES - nirvanA Initiative"><br><sub><b>AI: THE SOMNIUM FILES - nirvanA Initiative</b><br>~11.6 GB</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/animal-crossing-new-horizons.jpg" width="256" alt="Animal Crossing: New Horizons"><br><sub><b>Animal Crossing: New Horizons</b><br>~10.5 GB</sub></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/animal-well.png" width="256" alt="ANIMAL WELL"><br><sub><b>ANIMAL WELL</b><br>~54 MB</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/astral-chain.png" width="256" alt="ASTRAL CHAIN"><br><sub><b><a href="dm/games/01007300020FA000/README.md">ASTRAL CHAIN</a></b><br>~9.7 GB · 60 fps target with 1.0.1</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/balatro.jpg" width="256" alt="Balatro"><br><sub><b>Balatro</b><br>~82 MB · played by touch</sub></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/ball-x-pit.jpg" width="256" alt="BALL x PIT"><br><sub><b>BALL x PIT</b><br>~1.1 GB</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/bayonetta.jpg" width="256" alt="Bayonetta"><br><sub><b>Bayonetta</b><br>~8.8 GB</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/bayonetta-2.jpg" width="256" alt="Bayonetta 2"><br><sub><b>Bayonetta 2</b><br>~12.5 GB</sub></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/bayonetta-3.jpg" width="256" alt="Bayonetta 3"><br><sub><b>Bayonetta 3</b><br>~14.2 GB</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/big-brain-academy-brain-vs-brain.jpg" width="256" alt="Big Brain Academy: Brain vs. Brain"><br><sub><b>Big Brain Academy: Brain vs. Brain</b><br>~0.8 GB</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/brain-memory-training-academy.jpg" width="256" alt="Brain Memory Training Academy"><br><sub><b>Brain Memory Training Academy</b><br>~0.1 GB</sub></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/captain-toad-treasure-tracker.jpg" width="256" alt="Captain Toad: Treasure Tracker"><br><sub><b>Captain Toad: Treasure Tracker</b><br>~2 GB</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/catherine-full-body.jpg" width="256" alt="Catherine: Full Body"><br><sub><b>Catherine: Full Body</b><br>~14 GB</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/celeste.jpg" width="256" alt="Celeste"><br><sub><b>Celeste</b><br>~0.9 GB</sub></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/cuphead.jpg" width="256" alt="Cuphead"><br><sub><b>Cuphead</b><br>~5 GB</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/dark-souls-remastered-creation.jpg" width="256" alt="DARK SOULS: REMASTERED"><br><sub><b>DARK SOULS: REMASTERED</b><br>~4 GB · 60 fps with 1.0.3</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/digimon-story-cyber-sleuth.jpg" width="256" alt="Digimon Story Cyber Sleuth: Complete Edition"><br><sub><b>Digimon Story Cyber Sleuth: Complete Edition</b><br>~5 GB</sub></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/donkey-kong-country-tropical-freeze.jpg" width="256" alt="Donkey Kong Country: Tropical Freeze"><br><sub><b>Donkey Kong Country: Tropical Freeze</b><br>~7.3 GB</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/dragon-quest-vii-reimagined.jpg" width="256" alt="DRAGON QUEST VII Reimagined"><br><sub><b>DRAGON QUEST VII Reimagined</b><br>~5.9 GB</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/dragon-quest-xi-s.jpg" width="256" alt="DRAGON QUEST XI S: Echoes of an Elusive Age – Definitive Edition"><br><sub><b>DRAGON QUEST XI S: Echoes of an Elusive Age – Definitive Edition</b><br>~15 GB · 60 fps with 1.0.4</sub></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/final-fantasy-resonance.jpg" width="256" alt="FINAL FANTASY RESONANCE"><br><sub><b>FINAL FANTASY RESONANCE</b><br>~10 GB · 60 fps with 1.0.1</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/final-fantasy-tactics.jpg" width="256" alt="FINAL FANTASY TACTICS - The Ivalice Chronicles"><br><sub><b>FINAL FANTASY TACTICS - The Ivalice Chronicles</b><br>~11 GB</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/fire-emblem-engage.jpg" width="256" alt="Fire Emblem Engage"><br><sub><b>Fire Emblem Engage</b><br>~15 GB · 60 fps with 2.0.0</sub></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/fire-emblem-three-houses.jpg" width="256" alt="Fire Emblem: Three Houses"><br><sub><b>Fire Emblem: Three Houses</b><br>~13 GB · 60 fps with 1.2.0</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/ghost-trick-phantom-detective.jpg" width="256" alt="Ghost Trick: Phantom Detective"><br><sub><b>Ghost Trick: Phantom Detective</b><br>~3 GB</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/the-great-ace-attorney-chronicles.jpg" width="256" alt="The Great Ace Attorney Chronicles"><br><sub><b>The Great Ace Attorney Chronicles</b><br>~4 GB</sub></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/hades.jpg" width="256" alt="Hades"><br><sub><b>Hades</b><br>~4 GB</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/hades-ii.jpg" width="256" alt="Hades II"><br><sub><b>Hades II</b><br>~4 GB</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/hollow-knight-silksong.jpg" width="256" alt="Hollow Knight: Silksong"><br><sub><b>Hollow Knight: Silksong</b><br>~6.4 GB</sub></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/hyrule-warriors-age-of-calamity.jpg" width="256" alt="Hyrule Warriors: Age of Calamity"><br><sub><b>Hyrule Warriors: Age of Calamity</b><br>~15 GB · 60 fps with 1.3.0</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/kirby-and-the-forgotten-land.jpg" width="256" alt="Kirby and the Forgotten Land"><br><sub><b>Kirby and the Forgotten Land</b><br>~6.4 GB</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/luigis-mansion-3.jpg" width="256" alt="Luigi's Mansion 3"><br><sub><b>Luigi's Mansion 3</b><br>~7.5 GB · 60 fps with 1.4.0</sub></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/metroid-dread.jpg" width="256" alt="Metroid Dread"><br><sub><b>Metroid Dread</b><br>~5 GB</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/monster-hunter-rise.jpg" width="256" alt="Monster Hunter Rise"><br><sub><b>Monster Hunter Rise</b><br>~22 GB · 60 fps with 16.0.2</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/monster-train-2.jpg" width="256" alt="Monster Train 2"><br><sub><b>Monster Train 2</b><br>~1.6 GB · 60 fps with 1.1.1</sub></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/octopath-traveler.jpg" width="256" alt="OCTOPATH TRAVELER"><br><sub><b>OCTOPATH TRAVELER</b><br>~3.6 GB</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/octopath-traveler-0.jpg" width="256" alt="Octopath Traveler 0"><br><sub><b>Octopath Traveler 0</b><br>~4 GB · 60 fps with 1.0.5</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/octopath-traveler-ii.jpg" width="256" alt="Octopath Traveler II"><br><sub><b>Octopath Traveler II</b><br>~5.9 GB · 60 fps with 1.1.1</sub></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/patricks-parabox.jpg" width="256" alt="Patrick's Parabox"><br><sub><b>Patrick's Parabox</b><br>~0.2 GB</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/persona-5-royal.jpg" width="256" alt="Persona 5 Royal"><br><sub><b>Persona 5 Royal</b><br>~14.9 GB</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/pikmin-4.jpg" width="256" alt="Pikmin 4"><br><sub><b>Pikmin 4</b><br>~10.8 GB</sub></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/pokemon-brilliant-diamond.jpg" width="256" alt="Pokémon Brilliant Diamond"><br><sub><b>Pokémon Brilliant Diamond</b><br>~4.6 GB · 60 fps with 1.3.0</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/pokemon-legends-z-a.jpg" width="256" alt="Pokémon Legends: Z-A"><br><sub><b>Pokémon Legends: Z-A</b><br>~6 GB</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/pokemon-scarlet.png" width="256" alt="Pokémon Scarlet"><br><sub><b>Pokémon Scarlet</b><br>~7.0 GB</sub></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/pokemon-sword.jpg" width="256" alt="Pokémon Sword"><br><sub><b>Pokémon Sword</b><br>~12.4 GB</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/pokemon-shield.jpg" width="256" alt="Pokémon Shield"><br><sub><b>Pokémon Shield</b><br>~12.4 GB</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/portal.jpg" width="256" alt="Portal"><br><sub><b>Portal</b><br>~2.6 GB</sub></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/raging-loop.jpg" width="256" alt="Raging Loop"><br><sub><b>Raging Loop</b><br>~0.9 GB</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/rhythm-heaven-groove.jpg" width="256" alt="Rhythm Heaven Groove"><br><sub><b>Rhythm Heaven Groove</b><br>~3 GB</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/romance-of-the-three-kingdoms-8-remake.jpg" width="256" alt="ROMANCE OF THE THREE KINGDOMS 8 REMAKE"><br><sub><b>ROMANCE OF THE THREE KINGDOMS 8 REMAKE</b><br>~16.8 GB · controller only</sub></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/sea-of-stars.jpg" width="256" alt="Sea of Stars"><br><sub><b>Sea of Stars</b><br>~5.1 GB</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/shin-megami-tensei-v-vengeance.jpg" width="256" alt="SHIN MEGAMI TENSEI V: Vengeance"><br><sub><b>SHIN MEGAMI TENSEI V: Vengeance</b><br>~14.6 GB · 60 fps with 1.0.3</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/stardew-valley.jpg" width="256" alt="Stardew Valley"><br><sub><b>Stardew Valley</b><br>~0.6 GB</sub></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/steins-gate-reboot.jpg" width="256" alt="STEINS;GATE RE:BOOT"><br><sub><b>STEINS;GATE RE:BOOT</b><br>~6 GB</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/super-smash-bros-ultimate.jpg" width="256" alt="Super Smash Bros. Ultimate"><br><sub><b>Super Smash Bros. Ultimate</b><br>~17.5 GB · offline</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/taiko-risshiden-v-dx.jpg" width="256" alt="Taiko Risshiden V DX"><br><sub><b>Taiko Risshiden V DX</b><br>~3.3 GB · Japanese · played by touch</sub></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/unicorn-overlord.jpg" width="256" alt="Unicorn Overlord"><br><sub><b>Unicorn Overlord</b><br>~4 GB</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/yoshis-crafted-world.jpg" width="256" alt="Yoshi's Crafted World"><br><sub><b><a href="dm/games/01006000040C2000/README.md">Yoshi's Crafted World</a></b><br>~6.1 GB</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/nier-automata.png" width="256" alt="NieR:Automata The End of YoRHa Edition"><br><sub><b>NieR:Automata The End of YoRHa Edition</b><br>~10.9 GB · 60 fps with 1.0.3</sub></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/zelda-echoes-of-wisdom.jpg" width="256" alt="The Legend of Zelda: Echoes of Wisdom"><br><sub><b>The Legend of Zelda: Echoes of Wisdom</b><br>~7.8 GB</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/donkey-kong-country-returns-hd.png" width="256" alt="Donkey Kong Country Returns HD"><br><sub><b>Donkey Kong Country Returns HD</b><br>~11.6 GB</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/mario-rabbids-sparks-of-hope.jpg" width="256" alt="Mario + Rabbids Sparks of Hope"><br><sub><b>Mario + Rabbids Sparks of Hope</b><br>~9.8 GB</sub></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/xenoblade-chronicles-2.jpg" width="256" alt="Xenoblade Chronicles 2"><br><sub><b>Xenoblade Chronicles 2</b><br>~17.1 GB</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/xenoblade-chronicles-3.jpg" width="256" alt="Xenoblade Chronicles 3"><br><sub><b>Xenoblade Chronicles 3</b><br>~19.2 GB</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/final-fantasy-crystal-chronicles.jpg" width="256" alt="FINAL FANTASY CRYSTAL CHRONICLES Remastered Edition"><br><sub><b>FINAL FANTASY CRYSTAL CHRONICLES Remastered Edition</b></sub></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/return-of-the-obra-dinn.png" width="256" alt="Return of the Obra Dinn"><br><sub><b><a href="dm/games/010032E00E6E2000/README.md">Return of the Obra Dinn</a></b><br>~0.9 GB</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/blasphemous-2.png" width="256" alt="Blasphemous 2"><br><sub><b><a href="dm/games/010040801A4C8000/README.md">Blasphemous 2</a></b><br>~1.5 GB</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/silver-pines.jpg" width="256" alt="Silver Pines"><br><sub><b><a href="dm/games/0100D5B026844000/README.md">Silver Pines</a></b></sub></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/blasphemous.jpg" width="256" alt="Blasphemous"><br><sub><b><a href="dm/games/0100698009C6E000/README.md">Blasphemous</a></b><br>~0.9 GB</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/final-fantasy-x-x2-hd-remaster.jpg" width="256" alt="FINAL FANTASY X/X-2 HD Remaster"><br><sub><b><a href="dm/games/0100BC300CB48000/README.md">FINAL FANTASY X/X-2 HD Remaster</a></b><br>~26.5 GB</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/mario-rabbids-kingdom-battle.jpg" width="256" alt="Mario + Rabbids Kingdom Battle"><br><sub><b><a href="dm/games/010067300059A000/README.md">Mario + Rabbids Kingdom Battle</a></b><br>~5 GB</sub></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/persona-4-golden.jpg" width="256" alt="Persona 4 Golden"><br><sub><b><a href="dm/games/010062B01525C000/README.md">Persona 4 Golden</a></b></sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/xenoblade-chronicles-definitive-edition.jpg" width="256" alt="Xenoblade Chronicles: Definitive Edition"><br><sub><b><a href="dm/games/0100FF500E34A000/README.md">Xenoblade Chronicles: Definitive Edition</a></b><br>~13.2 GB</sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/pokemon-legends-arceus.jpg" width="256" alt="Pokémon Legends: Arceus"><br><sub><b><a href="dm/games/01001F5010DFA000/README.md">Pokémon Legends: Arceus</a></b><br>~4.2 GB</sub></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/super-mario-party-jamboree.jpg" width="256" alt="Super Mario Party Jamboree"><br><sub><b><a href="dm/games/0100965017338000/README.md">Super Mario Party Jamboree</a></b></sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/cult-of-the-lamb.jpg" width="256" alt="Cult of the Lamb"><br><sub><b><a href="dm/games/01002E7016C46000/README.md">Cult of the Lamb</a></b></sub></td>
<td align="center" valign="top" width="33%"><img src="docs/images/paper-mario-the-origami-king.jpg" width="256" alt="Paper Mario: The Origami King"><br><sub><b><a href="dm/games/0100A3900C3E2000/README.md">Paper Mario: The Origami King</a></b></sub></td>
</tr>
</table>
<!-- end of gallery -->

### For developers

<sub>[Android port state](HANDOFF.md) · [Android reference](docs/reference/android.md) · [How it works](docs/development.md) · [Game notes](dm/games/README.md#games) · [Bring-up and debugging](docs/agents/README.md) · [Front ends](docs/frontends.md) · [Contributing](CONTRIBUTING.md)</sub>

Part of that documentation (`docs/development.md`, `docs/playing.md`, `docs/frontends.md`) describes the Mac and iOS builds.

### Acknowledgements

<sub>nxdroid is a port of **[nxnative](https://github.com/seedds/nxnative)**, which started from **[d2r-mobile](https://github.com/jhaizhou-ops/d2r-mobile)** (MIT), which developed this native-execution approach for Diablo II: Resurrected: its NSO rewriter, Horizon host, NVN-on-Metal layer and iOS app shell. The Vulkan replay engine and the bionic compatibility layer in this repository are vendored from d2r-mobile. [nx2apk](https://github.com/ghostyshell/nx2apk) is a reference for the same approach on Android. The project also builds on **Ryujinx** (MIT; its shader translator, in `dm/third_party/ryujinx` with [a few fixes](dm/third_party/ryujinx/README.md), and a reference for system services), **[Atmosphère](https://github.com/Atmosphere-NX/Atmosphere)** (Horizon's synchronization semantics), **yuzu** (Maxwell encodings, kernel cross-checks), **[LibHac](https://github.com/Thealexbarney/LibHac)** and **hactool** (reading NSPs), **[SPIRV-Cross](https://github.com/KhronosGroup/SPIRV-Cross)** and **[glslang](https://github.com/KhronosGroup/glslang)** (shaders), **deko3d** (zlib; texture layout sizes), **libvpx**, **stb_vorbis**, the **Vulkan headers** and **NVIDIA FLIP** ([licenses](dm/third_party/README.md)), and **Capstone**, **lz4**, **fontTools** and **XcodeGen** in the build.</sub>

### License

<sub>MIT ([LICENSE](LICENSE)). Third-party code keeps its own license ([dm/third_party](dm/third_party/README.md)).</sub>
