package com.nxdroid;

import android.app.Activity;
import android.content.Intent;
import android.os.Build;
import android.os.Bundle;
import android.view.Display;
import android.view.InputDevice;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.View;
import android.view.Window;
import android.view.WindowManager;

import java.io.File;

/**
 * Main application Activity handling display setup, immersive fullscreen,
 * gamepad/controller routing, and host lifecycle.
 */
public class MainActivity extends Activity {
    public static final long DM_BTN_A = 1L << 0;
    public static final long DM_BTN_B = 1L << 1;
    public static final long DM_BTN_X = 1L << 2;
    public static final long DM_BTN_Y = 1L << 3;
    public static final long DM_BTN_LS = 1L << 4;
    public static final long DM_BTN_RS = 1L << 5;
    public static final long DM_BTN_L = 1L << 6;
    public static final long DM_BTN_R = 1L << 7;
    public static final long DM_BTN_ZL = 1L << 8;
    public static final long DM_BTN_ZR = 1L << 9;
    public static final long DM_BTN_PLUS = 1L << 10;
    public static final long DM_BTN_MINUS = 1L << 11;
    public static final long DM_BTN_LEFT = 1L << 12;
    public static final long DM_BTN_UP = 1L << 13;
    public static final long DM_BTN_RIGHT = 1L << 14;
    public static final long DM_BTN_DOWN = 1L << 15;

    private static final int STICK_MAX = 32767;
    private static final float DEADZONE = 0.15f;

    private GameSurfaceView mSurfaceView;
    private long mButtons = 0;
    private int mLx = 0;
    private int mLy = 0;
    private int mRx = 0;
    private int mRy = 0;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        requestWindowFeature(Window.FEATURE_NO_TITLE);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN
                | WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        applyImmersiveMode();

        configureRefreshRate();

        mSurfaceView = new GameSurfaceView(this);
        setContentView(mSurfaceView);

        startHostFromIntent(getIntent());
    }

    private void applyImmersiveMode() {
        View decor = getWindow().getDecorView();
        decor.setSystemUiVisibility(
                View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                | View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                | View.SYSTEM_UI_FLAG_FULLSCREEN
        );
    }

    private void configureRefreshRate() {
        Display display = getWindowManager().getDefaultDisplay();
        float maxHz = display.getRefreshRate();

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            Display.Mode[] modes = display.getSupportedModes();
            if (modes != null) {
                for (Display.Mode mode : modes) {
                    if (mode.getRefreshRate() > maxHz) {
                        maxHz = mode.getRefreshRate();
                    }
                }
            }
        }

        NativeBridge.nativeSetRefreshRate(maxHz);
    }

    private void startHostFromIntent(Intent intent) {
        File ext = getExternalFilesDir(null);
        if (ext == null) {
            ext = getFilesDir();
        }

        String gameDir = intent.hasExtra("gameDir")
                ? intent.getStringExtra("gameDir")
                : new File(ext, "game").getAbsolutePath();

        String shaderDir = intent.hasExtra("shaderDir")
                ? intent.getStringExtra("shaderDir")
                : new File(ext, "shaders").getAbsolutePath();

        String romfsDir = intent.hasExtra("romfsDir")
                ? intent.getStringExtra("romfsDir")
                : new File(ext, "romfs.img").getAbsolutePath();

        String saveDir = intent.hasExtra("saveDir")
                ? intent.getStringExtra("saveDir")
                : new File(getFilesDir(), "save").getAbsolutePath();

        String[] extraArgs = intent.getStringArrayExtra("extraArgs");

        new File(saveDir).mkdirs();
        File gameFolder = new File(gameDir);
        gameFolder.mkdirs();

        File mainNso = new File(gameFolder, "main");
        if (!mainNso.exists()) {
            android.util.Log.i("dm", "Game folder is empty: " + gameDir + " (missing 'main'). Waiting for game files.");
            android.widget.Toast.makeText(this,
                    "nxdroid: Place Switch game files ('main', 'sdk') in:\n" + gameDir,
                    android.widget.Toast.LENGTH_LONG).show();
            return;
        }

        NativeBridge.nativeStartHost(gameDir, shaderDir, romfsDir, saveDir, extraArgs);
    }

    @Override
    protected void onResume() {
        super.onResume();
        applyImmersiveMode();
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        NativeBridge.nativeStopHost();
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        long mapped = mapKeyCodeToButton(keyCode);
        if (mapped != 0) {
            mButtons |= mapped;
            NativeBridge.nativeSendPad(0, mButtons, mLx, mLy, mRx, mRy);
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }

    @Override
    public boolean onKeyUp(int keyCode, KeyEvent event) {
        long mapped = mapKeyCodeToButton(keyCode);
        if (mapped != 0) {
            mButtons &= ~mapped;
            NativeBridge.nativeSendPad(0, mButtons, mLx, mLy, mRx, mRy);
            return true;
        }
        return super.onKeyUp(keyCode, event);
    }

    @Override
    public boolean onGenericMotionEvent(MotionEvent event) {
        if ((event.getSource() & InputDevice.SOURCE_JOYSTICK) == InputDevice.SOURCE_JOYSTICK
                && event.getAction() == MotionEvent.ACTION_MOVE) {

            float rawLx = event.getAxisValue(MotionEvent.AXIS_X);
            float rawLy = event.getAxisValue(MotionEvent.AXIS_Y);
            float rawRx = event.getAxisValue(MotionEvent.AXIS_Z);
            if (rawRx == 0.0f) {
                rawRx = event.getAxisValue(MotionEvent.AXIS_RX);
            }
            float rawRy = event.getAxisValue(MotionEvent.AXIS_RZ);
            if (rawRy == 0.0f) {
                rawRy = event.getAxisValue(MotionEvent.AXIS_RY);
            }

            mLx = filterAxis(rawLx);
            mLy = -filterAxis(rawLy); // Invert Y so up is positive
            mRx = filterAxis(rawRx);
            mRy = -filterAxis(rawRy); // Invert Y so up is positive

            // Hat axes for D-pad fallback
            float hatX = event.getAxisValue(MotionEvent.AXIS_HAT_X);
            float hatY = event.getAxisValue(MotionEvent.AXIS_HAT_Y);

            mButtons &= ~(DM_BTN_LEFT | DM_BTN_RIGHT | DM_BTN_UP | DM_BTN_DOWN);
            if (hatX < -0.5f) mButtons |= DM_BTN_LEFT;
            if (hatX > 0.5f) mButtons |= DM_BTN_RIGHT;
            if (hatY < -0.5f) mButtons |= DM_BTN_UP;
            if (hatY > 0.5f) mButtons |= DM_BTN_DOWN;

            // Trigger axes
            float lt = event.getAxisValue(MotionEvent.AXIS_LTRIGGER);
            if (lt == 0.0f) lt = event.getAxisValue(MotionEvent.AXIS_BRAKE);
            float rt = event.getAxisValue(MotionEvent.AXIS_RTRIGGER);
            if (rt == 0.0f) rt = event.getAxisValue(MotionEvent.AXIS_GAS);

            if (lt > 0.5f) mButtons |= DM_BTN_ZL; else mButtons &= ~DM_BTN_ZL;
            if (rt > 0.5f) mButtons |= DM_BTN_ZR; else mButtons &= ~DM_BTN_ZR;

            NativeBridge.nativeSendPad(0, mButtons, mLx, mLy, mRx, mRy);
            return true;
        }
        return super.onGenericMotionEvent(event);
    }

    private static int filterAxis(float val) {
        if (Math.abs(val) < DEADZONE) {
            return 0;
        }
        return Math.round(val * STICK_MAX);
    }

    private static long mapKeyCodeToButton(int keyCode) {
        switch (keyCode) {
            case KeyEvent.KEYCODE_BUTTON_A:
                return DM_BTN_B; // Nintendo physical layout
            case KeyEvent.KEYCODE_BUTTON_B:
                return DM_BTN_A;
            case KeyEvent.KEYCODE_BUTTON_X:
                return DM_BTN_Y;
            case KeyEvent.KEYCODE_BUTTON_Y:
                return DM_BTN_X;
            case KeyEvent.KEYCODE_BUTTON_L1:
                return DM_BTN_L;
            case KeyEvent.KEYCODE_BUTTON_R1:
                return DM_BTN_R;
            case KeyEvent.KEYCODE_BUTTON_L2:
                return DM_BTN_ZL;
            case KeyEvent.KEYCODE_BUTTON_R2:
                return DM_BTN_ZR;
            case KeyEvent.KEYCODE_BUTTON_THUMBL:
                return DM_BTN_LS;
            case KeyEvent.KEYCODE_BUTTON_THUMBR:
                return DM_BTN_RS;
            case KeyEvent.KEYCODE_BUTTON_START:
                return DM_BTN_PLUS;
            case KeyEvent.KEYCODE_BUTTON_SELECT:
                return DM_BTN_MINUS;
            case KeyEvent.KEYCODE_DPAD_UP:
                return DM_BTN_UP;
            case KeyEvent.KEYCODE_DPAD_DOWN:
                return DM_BTN_DOWN;
            case KeyEvent.KEYCODE_DPAD_LEFT:
                return DM_BTN_LEFT;
            case KeyEvent.KEYCODE_DPAD_RIGHT:
                return DM_BTN_RIGHT;
            default:
                return 0;
        }
    }
}
