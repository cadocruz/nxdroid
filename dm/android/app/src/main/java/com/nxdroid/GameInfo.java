package com.nxdroid;

import java.io.File;

/**
 * Metadata and runtime state for a detected Switch title in the library.
 */
public class GameInfo {
    public final String title;
    public final String titleId;
    public final String folderPath;
    public final String sizeStr;
    public final String apiType;
    public final int targetFps;
    public final boolean playable;
    public final int prewarmedShaders;

    public GameInfo(String title, String titleId, String folderPath, String sizeStr,
                    String apiType, int targetFps, boolean playable, int prewarmedShaders) {
        this.title = title;
        this.titleId = titleId;
        this.folderPath = folderPath;
        this.sizeStr = sizeStr;
        this.apiType = apiType;
        this.targetFps = targetFps;
        this.playable = playable;
        this.prewarmedShaders = prewarmedShaders;
    }

    public File getMainFile() {
        File main = new File(folderPath, "main");
        if (main.exists()) return main;
        File mainNso = new File(folderPath, "main.nso");
        if (mainNso.exists()) return mainNso;
        return main;
    }

    public File getRomFsFile() {
        File img = new File(folderPath, "romfs.img");
        if (img.exists()) return img;
        File dir = new File(folderPath, "romfs");
        if (dir.exists()) return dir;
        return img;
    }
}
