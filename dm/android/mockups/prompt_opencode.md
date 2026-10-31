# Prompt for nxdroid Android UI Design

You are designing the welcome/home user interface for `nxdroid`, a native Nintendo Switch game runner on Android AArch64 (currently targeting Samsung Galaxy S23 Ultra, Adreno 740, landscape orientation).

## Context & Needs
1. Currently the app (`com.nxdroid`) immediately opens into a plain black `GameSurfaceView`.
2. The user wants a friendly, beautiful, modern Android welcome screen (tela inicial amigável).
3. Critical requirement from the user:
   - Instead of a hardcoded fixed folder (e.g. `/sdcard/Android/data/...` which users cannot easily access and which gets deleted on app uninstall), the UI MUST allow the user to select their custom game directory (e.g., `/sdcard/Games/Switch/` or SAF folder picker), displaying the current path with a "Change Folder" button.
4. Key elements for this home screen:
   - Game Library Grid/Carousel: displays scanned games found in the directory (box art thumbnail, game title, title ID, file size, status).
   - Quick Start / Action Bar: "Play" button, "Scan / Refresh", "Settings", "Controller Mapping / Touch Overlay".
   - Device & Engine Status Chip: e.g., "S23 Ultra | Snapdragon 8 Gen 2 | Adreno 740 | Vulkan 1.3 (512.676.1) | 60 FPS target".
   - Clean, modern gaming handheld aesthetic (inspired by modern gaming dashboards / Material You dark gaming theme).
   - Designed for landscape orientation (e.g., 1920x1080 or 2340x1080 S23 Ultra ratio).

## Your Mission
1. Propose your UI design concept in detail (layout structure, color palette, navigation hierarchy, interactions).
2. Generate a visual mockup PNG file saved at:
   `dm/android/mockups/mockup_opencode.png`
   Use a Python script (using `PIL` / Pillow) to render a clean, high-resolution (1920x1080), visually detailed and aesthetic wireframe/mockup image showing the exact layout, game cards, folder picker bar, status chip, action buttons, icons/text.
3. Verify that `dm/android/mockups/mockup_opencode.png` exists and is a valid PNG.
4. Output your detailed design description and rationale.
