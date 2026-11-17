package com.nxdroid;

import android.graphics.Bitmap;

import java.io.File;
import java.util.Locale;

/**
 * One prepared game folder found by {@link GameScanner}: what scripts/prepare_game_android.py writes
 * (the rewritten modules with 'main' among them, the .xgs shader bundles, romfs.img or romfs/,
 * control.nacp and icon.jpg). Every field comes from the folder; a field the folder does not have
 * is null, 0 or false.
 */
public final class GameInfo {
    /** The game name from control.nacp, or the folder name when there is no readable control.nacp. */
    public final String title;
    /** The publisher from control.nacp, or null. */
    public final String publisher;
    /** The display version from control.nacp (e.g. "4.0.1"), or null. */
    public final String displayVersion;
    /** The 16-hex-digit title ID (control.nacp's save data owner, else a 16-hex-digit folder name part), or null. */
    public final String titleId;
    public final String folderPath;
    /** Bytes of every file in the folder and its subfolders. */
    public final long sizeBytes;
    /** Translated shader bundles (.xgs) in the folder and its shaders/ subfolder. */
    public final int shaderBundles;
    /** "romfs.img", "romfs/" or null when the folder has neither. */
    public final String romfs;
    /** icon.jpg decoded at a small size, or null. */
    public final Bitmap icon;

    public GameInfo(String title, String publisher, String displayVersion, String titleId, String folderPath,
                    long sizeBytes, int shaderBundles, String romfs, Bitmap icon) {
        this.title = title;
        this.publisher = publisher;
        this.displayVersion = displayVersion;
        this.titleId = titleId;
        this.folderPath = folderPath;
        this.sizeBytes = sizeBytes;
        this.shaderBundles = shaderBundles;
        this.romfs = romfs;
        this.icon = icon;
    }

    public File getFolder() {
        return new File(folderPath);
    }

    public String sizeText() {
        if (sizeBytes <= 0) return "-";
        double gib = sizeBytes / (1024.0 * 1024.0 * 1024.0);
        if (gib >= 1.0) return String.format(Locale.US, "%.1f GB", gib);
        return String.format(Locale.US, "%.0f MB", sizeBytes / (1024.0 * 1024.0));
    }

    /** True when this game's title ID is one of the IDs the APK was built for (NativeBridge.nativeGetBuiltGame). */
    public boolean matches(String[] builtGame) {
        if (titleId == null || builtGame == null) return false;
        if (builtGame.length > 0 && titleId.equalsIgnoreCase(builtGame[0])) return true;
        return builtGame.length > 2 && titleId.equalsIgnoreCase(builtGame[2]);
    }
}
