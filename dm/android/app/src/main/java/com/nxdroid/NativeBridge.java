package com.nxdroid;

import android.view.Surface;

/**
 * JNI bridge connecting the Android shell to the native host runtime (libdm.so).
 */
public final class NativeBridge {
    static {
        System.loadLibrary("dm");
    }

    private NativeBridge() {}

    /**
     * Start the host runner thread.
     *
     * @param gameDir   Directory containing unpacked NSO binaries (main, sdk, etc.).
     * @param shaderDir Directory containing translated .xgs shaders or SPIR-V bundle.
     * @param romfsDir  Optional directory or romfs.img image file for guest RomFS.
     * @param saveDir   Optional directory for guest save data and temporary files.
     * @param extraArgs Optional additional command-line arguments.
     * @return true if started successfully, false if already running or failed.
     */
    public static native boolean nativeStartHost(
            String gameDir,
            String shaderDir,
            String romfsDir,
            String saveDir,
            String[] extraArgs
    );

    /**
     * Request host graceful shutdown (sends SIGTERM to the host process).
     */
    public static native void nativeStopHost();

    /**
     * Check if the host execution thread is currently running.
     */
    public static native boolean nativeIsRunning();

    /**
     * Set or update the active native render surface.
     *
     * @param surface Active Android Surface (or null to detach).
     * @param width   Surface width in pixels.
     * @param height  Surface height in pixels.
     */
    public static native void nativeSetSurface(Surface surface, int width, int height);

    /**
     * Notify that the current surface has been destroyed.
     */
    public static native void nativeSurfaceDestroyed();

    /**
     * Notify the host of the display's current or maximum refresh rate in Hz.
     */
    public static native void nativeSetRefreshRate(float hz);

    /**
     * Push multi-touch input points to the guest touchscreen.
     *
     * @param count Number of active touch points (clamped to 0..16).
     * @param ids   Pointers tracking IDs.
     * @param xs    Normalized X coordinates [0.0, 1.0) with origin at top-left.
     * @param ys    Normalized Y coordinates [0.0, 1.0) with origin at top-left.
     */
    public static native void nativeSendTouch(int count, int[] ids, float[] xs, float[] ys);

    /**
     * Set controller state for a specific player (0..7).
     *
     * @param player  Player index (0 = Player 1 / Handheld).
     * @param buttons Bitmask of DM_BTN_* buttons.
     * @param lx      Left stick horizontal axis [-32767, 32767].
     * @param ly      Left stick vertical axis [-32767, 32767].
     * @param rx      Right stick horizontal axis [-32767, 32767].
     * @param ry      Right stick vertical axis [-32767, 32767].
     */
    public static native void nativeSendPad(int player, long buttons, int lx, int ly, int rx, int ry);

    /**
     * Set the connected controllers mask (bit p = Player p+1 connected).
     */
    public static native void nativeSendPadPlayers(int mask);

    /**
     * Set keyboard/touch virtual pad input for Player 1.
     */
    public static native void nativeSendInput(long buttons, int lx, int ly, int rx, int ry);
}
