# nxdroid — Android Landscape Console Home Interface Specification
**Author:** Senior Android UI/UX Architect & Game Console Interface Designer  
**Target Platform:** Android AArch64 (Samsung Galaxy S23 Ultra, Adreno 740, Vulkan 1.3)  
**Mockup Reference:** `dm/android/mockups/mockup_argon.png` (1920x1080 Landscape)

---

## 1. Executive Summary & Vision

`nxdroid` previously launched directly into a black `GameSurfaceView`, expecting ROM files hardcoded in `/sdcard/Android/data/com.nxdroid/files/game`. On Android 11+ (API 30–36), this default folder is:
1. **Inaccessible to standard users** without specialized third-party file managers or root access.
2. **Volatile**: All game ROMs, update NSOs, shader caches, and save files are erased if the app is uninstalled or reinstalled.

This specification defines a **bespoke, modern, console-grade welcome and launcher interface** inspired by the Nintendo Switch Home Menu, Steam Deck OLED (SteamOS), and Android Material You Dark Gaming theme. It brings:
- **User-selected game directory via Android Storage Access Framework (SAF)** with persistent read/write permissions.
- **Discovered games library** with rich metadata, box art thumbnails, engine detection (`NVN` / `OpenGL`), and performance badges.
- **Real-time hardware & engine diagnostic bar** (Snapdragon 8 Gen 2 / Adreno 740 / Vulkan 1.3 / 60 FPS Target).
- **Physical gamepad & touch navigation parity** (Nintendo physical button layout mapping).

---

## 2. Storage Architecture: Custom Game Directory via SAF

### 2.1 The Problem with Hardcoded Paths
```
Traditional path: /sdcard/Android/data/com.nxdroid/files/game/
- Android Scoped Storage blocks access from standard file explorers.
- Data is purged when APK is updated or reinstalled.
- Copying 15 GB+ games requires ADB or PC USB connection.
```

### 2.2 The Solution: Persistent SAF Document Tree
The app prompts the user to select any directory they prefer (e.g. `/sdcard/Games/Switch/` or a high-speed MicroSD card).

#### Implementation:
```java
// 1. Launch Android Storage Access Framework tree picker
Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE);
intent.addFlags(
    Intent.FLAG_GRANT_READ_URI_PERMISSION |
    Intent.FLAG_GRANT_WRITE_URI_PERMISSION |
    Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION |
    Intent.FLAG_GRANT_PREFIX_URI_PERMISSION
);
startActivityForResult(intent, REQUEST_CODE_SAF_TREE);

// 2. Persist permission indefinitely across app reboots
@Override
protected void onActivityResult(int requestCode, int resultCode, Intent data) {
    super.onActivityResult(requestCode, resultCode, data);
    if (requestCode == REQUEST_CODE_SAF_TREE && resultCode == RESULT_OK && data != null) {
        Uri treeUri = data.getData();
        final int takeFlags = data.getFlags() & (
            Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION
        );
        getContentResolver().takePersistableUriPermission(treeUri, takeFlags);
        
        // Save to SharedPreferences
        getSharedPreferences("nxdroid_prefs", MODE_PRIVATE)
            .edit()
            .putString("game_library_uri", treeUri.toString())
            .apply();
            
        // Scan library
        scanGameDirectory(treeUri);
    }
}
```

#### Converting SAF URI to Direct Filesystem Path for Native Runtime:
For standard Linux/AArch64 `open()` calls in `libdm.so`:
- If the directory resides on internal storage (`primary:Games/Switch`), convert via:
  ```java
  String path = "/storage/emulated/0/" + treeUri.getPath().split("primary:")[1];
  ```
- Alternatively, expose file descriptors directly or mount via Android SAF content provider.

---

## 3. UI Layout & Visual Hierarchy (1920x1080 Landscape)

The mockup in `dm/android/mockups/mockup_argon.png` follows a balanced **Dual-Pane Console Architecture**:

### 3.1 Top Global Status & Diagnostic Bar (Height: 62px)
- **Left Branding:**
  - Dual Joy-Con capsule logo (Neon Cyan left pill `#00E5FF`, Neon Crimson right pill `#FF3366`).
  - Title: `nxdroid` (Space Grotesk Bold 26px).
  - Version Chip: `VULKAN AARCH64`.
- **Center Diagnostic Chip:**
  - Highlighting hardware capability: `S23 Ultra · Snapdragon 8 Gen 2 · Adreno 740 · Vulkan 1.3 (512.676.1) · 60 FPS Target`.
  - Emerald status dot indicating Vulkan driver readiness.
- **Right Utilities:**
  - Connected controller indicator: `🎮 DualSense BT` (or Xbox Wireless / On-Screen Touch).
  - Device SoC temperature: `34°C` (Normal / Green).
  - Battery percentage: `94%` with battery glyph.
  - Digital clock: `20:45`.

### 3.2 Game Directory Bar (Height: 86px) — The User's Core Control
- Placed immediately beneath the top bar for maximum visibility.
- **Visuals:** Obsidian slate background with a vibrant 6px Cyan accent bar on the left edge.
- **Details:**
  - Title: `GAME DIRECTORY (STORAGE ACCESS FRAMEWORK · PERSISTENT ACCESS)`
  - Current Path: `/storage/emulated/0/Games/Switch/` (Ubuntu Sans Mono Bold 21px).
  - Subtitle: `Accessible without root · Data preserved on app uninstall · 5 Switch titles discovered`.
- **Interactive Controls:**
  - `[ 📁 Change Folder ]`: Triggers SAF folder picker.
  - `[ 🔄 Rescan Library ]`: Re-indexes the directory for `main`, `sdk`, `.nsp`, `.xci` packages.

### 3.3 Main Content Area (Dual-Pane)
#### A. Left Showcase Pane (Width: 770px) — Selected Game Hero Card
- **Hero Banner:**
  - Full-color cinematic banner featuring custom game illustrations (e.g. *Super Mario Odyssey* with New Donk City night skyline, Power Moon with expressive eyes, and Mario Cappy red cap).
  - Overlay badges: `SELECTED GAME` and `VERIFIED 60 FPS · DOCKED`.
- **Game Title & Metadata:**
  - `Super Mario Odyssey` (Bold 34px).
  - `Nintendo EPD · 3D Platformer · Version 1.3.0 (Base + All DLC)`.
- **Technical Specs 2x2 Grid:**
  - **Title ID:** `010015100B514000`
  - **Package Size:** `5.7 GB (RomFS + Patch NSO)`
  - **Graphics Translator:** `NVN → Vulkan 1.3 (Adreno 740 native)`
  - **Pipeline Cache:** `2,841 Prewarmed (No Stutter)`
- **Primary Action Button:**
  - Giant luminous gradient CTA: `▶ LAUNCH GAME` (Gradient Cyan `#00E5FF` to Electric Blue `#00A3FF`, Height 68px, Obsidian bold text).
- **Secondary Game Controls:**
  - `[ 🎮 Touch Overlay ]`: Customize virtual on-screen buttons.
  - `[ ⚙ Game Settings ]`: Per-game render resolution, 60 FPS cut, and shader compiler flags.
  - `[ 💾 Save Data ]`: Backup and manage save directories.

#### B. Right Pane (Width: 1050px) — Discovered Titles 2x2 Grid
- **Filter Tabs:** `All (5)`, `Favorites (2)`, `Recent (3)`.
- **Search Bar:** Real-time filter by title or Title ID.
- **Game Cards (4 Discovered Titles displayed):**
  1. **Zelda: Tears of the Kingdom** (`0100F2C0115B6000`, 16.3 GB, NVN, 30/60 FPS, Playable) — *Currently focused with Cyan luminous border*.
  2. **Metroid Dread** (`010093801237C000`, 4.2 GB, NVN, 60 FPS Flawless, Playable).
  3. **Balatro** (`0100CD801CE5E000`, 320 MB, OpenGL, 60 FPS Native, Playable).
  4. **Animal Crossing: New Horizons** (`01006F8002326000`, 6.9 GB, NVN, 30 FPS, Playable).
- Each card features:
  - Custom game cover art header with distinctive thematic styling.
  - Engine tag (`NVN` or `OpenGL`).
  - Target framerate badge (`60 FPS Flawless`, `30 / 60 FPS`).
  - Title, Title ID, and File Size.
  - `● Playable` emerald status dot.
  - `[ ▶ Select ]` button for instant preview switch.

### 3.4 Console Footer Bar (Height: 58px)
- **Gamepad Navigation Shortcuts:**
  - `(A) Launch Game`
  - `(X) Game Config`
  - `(Y) Scan Folder`
  - `(+) Global Settings`
  - `(L) Prev Tab`
  - `(R) Next Tab`
- **Build stamp:** `nxdroid v0.1.0-alpha · AArch64 Host Runtime`.

---

## 4. Color Palette & Typography Tokens

| Token | Hex / RGB | Usage |
|---|---|---|
| `BG_OBSIDIAN` | `#0A0D14` / `(10, 13, 20)` | Screen background (OLED true black power saving) |
| `SURFACE_0` | `#0E121B` / `(14, 18, 27)` | Header & Footer bars |
| `SURFACE_1` | `#131926` / `(19, 25, 38)` | Sub-panels & cards |
| `SURFACE_CARD` | `#121824` / `(18, 24, 36)` | Game card containers |
| `CYAN_NEON` | `#00E5FF` / `(0, 229, 255)` | Primary brand accent, Joy-Con Left, Focus rings, Launch CTA |
| `CRIMSON_NEON` | `#FF3366` / `(255, 51, 102)` | Secondary brand accent, Joy-Con Right, Warning badges |
| `GREEN_EMERALD` | `#10B981` / `(16, 185, 129)` | Verified playable status, 60 FPS optimal indicator |
| `BORDER_SUBTLE` | `#232E44` / `(35, 46, 68)` | Default card and panel outlines |
| `TEXT_PRIMARY` | `#F8FAFC` / `(248, 250, 252)`| Headings, game titles, primary buttons |
| `TEXT_SECONDARY` | `#A0AFC8` / `(160, 175, 200)`| Metadata, subheadings, secondary labels |
| `TEXT_MUTED` | `#64748B` / `(100, 116, 139)`| Caption labels, version stamps |

---

## 5. Android Implementation Architecture

### 5.1 View Stack Structure (`MainActivity.java`)
Instead of `setContentView(mSurfaceView)` immediately during `onCreate`:

```
MainActivity (Activity)
└── RootFrameLayout (FrameLayout, MatchParent)
    ├── GameSurfaceView (Z-Order: 0, MATCH_PARENT)
    │   └── Native Vulkan presentation queue
    └── LauncherOverlayView (Z-Order: 1, MATCH_PARENT)
        ├── TopDiagnosticBar
        ├── FolderSelectorBar
        ├── DualPaneWorkspace
        │   ├── HeroFeaturedCard
        │   └── LibraryRecyclerView (2x2 Grid)
        └── ConsoleFooterBar
```

### 5.2 Launch Transition Lifecycle
1. User browses library on `LauncherOverlayView`.
2. User taps `[ ▶ LAUNCH GAME ]` or presses `(A)` on gamepad.
3. `LauncherOverlayView` animates alpha `1.0 -> 0.0` over 250ms with `AccelerateDecelerateInterpolator`.
4. `NativeBridge.nativeStartHost(gameDir, shaderDir, romfsDir, saveDir, extraArgs)` is triggered.
5. `GameSurfaceView` receives the first Vulkan frame presentation.
6. When user presses `Back` or `Home` gesture:
   - Host execution pauses via `NativeBridge.nativeStopHost()` or guest pause signal.
   - `LauncherOverlayView` animates back into view.

---

## 6. Verification and Output
- **Mockup File:** `dm/android/mockups/mockup_argon.png`
- **Resolution:** 1920 × 1080 pixels (8-bit RGB PNG)
- **Generator Script:** `dm/android/mockups/render_argon.py`
