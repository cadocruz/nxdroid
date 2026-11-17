package com.nxdroid;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.DialogInterface;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.provider.DocumentsContract;
import android.provider.Settings;
import android.util.Log;
import android.view.Display;
import android.view.Gravity;
import android.view.InputDevice;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.view.WindowManager;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.TextView;
import android.widget.Toast;

import java.io.File;
import java.util.List;
import java.util.Locale;

/**
 * The app's one Activity: the launcher (LauncherOverlayView) over the game's surface, the
 * on-screen controller, the performance HUD, physical controller input and the host's lifecycle.
 * The APK is built for one game profile (-PdmGame); the launcher lists every prepared game folder
 * it finds and starts the one this APK was built for.
 */
public class MainActivity extends Activity implements LauncherOverlayView.LauncherEventListener {
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
    private static final float NAV_THRESHOLD = 0.6f;
    private static final int REQUEST_SELECT_FOLDER = 1001;
    private static final String PREF_NAME = "nxdroid_prefs";
    private static final String PREF_LIBRARY_DIR = "library_dir";
    private static final String PREF_GAME_DIR_OLD = "game_dir";   // before the library: one game folder
    private static final String PREF_SHOW_FPS = "show_fps";
    private static final String PREF_TOUCH_CONTROLS = "touch_controls";

    private FrameLayout mRootContainer;
    private GameSurfaceView mSurfaceView;
    private VirtualControllerOverlayView mVirtualController;
    private LauncherOverlayView mLauncher;
    private TextView mFpsOverlay;
    private boolean mShowFps = true;
    private boolean mTouchControls = true;
    private String[] mBuiltGame;

    private final Handler mFpsHandler = new Handler(Looper.getMainLooper());
    private final Runnable mFpsUpdater = new Runnable() {
        @Override
        public void run() {
            if (!NativeBridge.nativeIsRunning()) {
                return;
            }
            float[] stats = NativeBridge.nativeGetPerformanceStats();
            if (stats != null && stats.length >= 3 && mFpsOverlay != null) {
                float fps = stats[0];
                float frameMs = stats[1];
                float gpuMs = stats[2];
                if (gpuMs > 0.0f) {
                    mFpsOverlay.setText(String.format(Locale.US, "%.1f FPS | %.1f ms (GPU: %.1f ms)", fps, frameMs, gpuMs));
                } else {
                    mFpsOverlay.setText(String.format(Locale.US, "%.1f FPS | %.1f ms", fps, frameMs));
                }
            }
            mFpsHandler.postDelayed(this, 500);
        }
    };

    private String mLibraryDir;
    private boolean mInGame = false;

    private long mButtons = 0;
    private int mLx = 0;
    private int mLy = 0;
    private int mRx = 0;
    private int mRy = 0;
    private long mNavDirection = 0;   // the launcher's last stick / hat direction (one move per push)

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        requestWindowFeature(Window.FEATURE_NO_TITLE);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN
                | WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
            setShowWhenLocked(true);
            setTurnScreenOn(true);
        } else {
            getWindow().addFlags(WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED
                    | WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON);
        }

        applyImmersiveMode();
        configureRefreshRate();
        mBuiltGame = NativeBridge.nativeGetBuiltGame();
        loadPreferences();
        buildUiHierarchy();

        // adb / RenderDoc: am start ... --es gameDir <folder> [--ez autoStart true] (HANDOFF.md, How a device run is made)
        Intent intent = getIntent();
        if (intent != null && intent.hasExtra("gameDir")) {
            String gameDir = intent.getStringExtra("gameDir");
            if (gameDir != null && !gameDir.trim().isEmpty()) {
                File dir = new File(gameDir.trim());
                mLibraryDir = GameScanner.isGameFolder(dir) && dir.getParent() != null ? dir.getParent() : dir.getAbsolutePath();
                mLauncher.setLibraryDirectory(mLibraryDir);
                if (intent.getBooleanExtra("autoStart", false)) {
                    startGameSession(dir.getAbsolutePath());
                }
            }
        }
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

    private static String defaultLibraryDir() {
        return new File(Environment.getExternalStorageDirectory(), "nxdroid").getAbsolutePath();
    }

    private void loadPreferences() {
        SharedPreferences prefs = getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE);
        mShowFps = prefs.getBoolean(PREF_SHOW_FPS, true);
        mTouchControls = prefs.getBoolean(PREF_TOUCH_CONTROLS, true);
        String saved = prefs.getString(PREF_LIBRARY_DIR, null);
        if (saved == null) {
            // The folder of the earlier front end was one game's: its parent holds it and any other prepared game
            String old = prefs.getString(PREF_GAME_DIR_OLD, null);
            if (old != null && !old.trim().isEmpty()) {
                File dir = new File(old.trim());
                saved = GameScanner.isGameFolder(dir) && dir.getParent() != null ? dir.getParent() : dir.getAbsolutePath();
                prefs.edit().putString(PREF_LIBRARY_DIR, saved).remove(PREF_GAME_DIR_OLD).apply();
            }
        }
        mLibraryDir = saved != null && !saved.trim().isEmpty() ? saved : defaultLibraryDir();
    }

    private void saveLibraryDir(String path) {
        mLibraryDir = path;
        getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE).edit().putString(PREF_LIBRARY_DIR, path).apply();
        mLauncher.setLibraryDirectory(path);
        rescan();
    }

    private void setPreference(String key, boolean value) {
        getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE).edit().putBoolean(key, value).apply();
    }

    private int dp(int val) {
        return (int) (val * getResources().getDisplayMetrics().density + 0.5f);
    }

    private static GradientDrawable createRoundedDrawable(int fillColor, int strokeColor, int cornerRadiusDp, float density) {
        GradientDrawable gd = new GradientDrawable();
        gd.setColor(fillColor);
        gd.setCornerRadius(cornerRadiusDp * density);
        if (strokeColor != 0) {
            gd.setStroke((int) (1 * density + 0.5f), strokeColor);
        }
        return gd;
    }

    private void buildUiHierarchy() {
        float density = getResources().getDisplayMetrics().density;

        mRootContainer = new FrameLayout(this);
        mRootContainer.setBackgroundColor(Color.BLACK);

        // 1. SurfaceView for native Vulkan presentation
        mSurfaceView = new GameSurfaceView(this);
        mRootContainer.addView(mSurfaceView, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        // 2. On-screen controller
        mVirtualController = new VirtualControllerOverlayView(this);
        mVirtualController.setVisibility(View.GONE);
        mVirtualController.setOnPadStateChangeListener(new VirtualControllerOverlayView.OnPadStateChangeListener() {
            @Override
            public void onPadStateChanged(long buttons, int lx, int ly, int rx, int ry) {
                mButtons = buttons;
                mLx = lx;
                mLy = ly;
                mRx = rx;
                mRy = ry;
                sendPad();
            }
        });
        mRootContainer.addView(mVirtualController, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        // 3. Performance HUD
        mFpsOverlay = new TextView(this);
        mFpsOverlay.setText("FPS: --");
        mFpsOverlay.setTextSize(12);
        mFpsOverlay.setTextColor(0xFF00FF66);
        mFpsOverlay.setTypeface(Typeface.MONOSPACE, Typeface.BOLD);
        mFpsOverlay.setPadding(dp(8), dp(4), dp(8), dp(4));
        mFpsOverlay.setBackground(createRoundedDrawable(0xAA000000, 0x4400FF66, 6, density));
        mFpsOverlay.setClickable(false);
        mFpsOverlay.setFocusable(false);
        mFpsOverlay.setVisibility(View.GONE);
        FrameLayout.LayoutParams fpsParams = new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        fpsParams.gravity = Gravity.TOP | Gravity.END;
        fpsParams.setMargins(0, dp(12), dp(20), 0);
        mRootContainer.addView(mFpsOverlay, fpsParams);

        // 4. Launcher, on top until a game starts
        mLauncher = new LauncherOverlayView(this);
        mLauncher.setListener(this);
        mLauncher.setBuiltGame(mBuiltGame);
        mLauncher.setLibraryDirectory(mLibraryDir);
        mLauncher.setTouchControls(mTouchControls);
        mLauncher.setStorageAccess(hasStorageAccess());
        mRootContainer.addView(mLauncher, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        setContentView(mRootContainer);
        mLauncher.requestFocus();
    }

    private static boolean hasStorageAccess() {
        return Build.VERSION.SDK_INT < Build.VERSION_CODES.R || Environment.isExternalStorageManager();
    }

    private void rescan() {
        mLauncher.setScanning(true);
        GameScanner.scanDirectoryAsync(mLibraryDir, new GameScanner.ScanCallback() {
            @Override
            public void onScanCompleted(String rootPath, List<GameInfo> games) {
                if (rootPath.equals(mLibraryDir)) mLauncher.setGames(games);   // a scan of a folder left meanwhile is dropped
            }
        });
    }

    // ---- LauncherOverlayView.LauncherEventListener ----

    @Override
    public void onChangeFolderRequested() {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE);
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION
                | Intent.FLAG_GRANT_WRITE_URI_PERMISSION
                | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);
        try {
            startActivityForResult(intent, REQUEST_SELECT_FOLDER);
        } catch (Exception e) {
            Toast.makeText(this, "Cannot open the folder picker: " + e.getMessage(), Toast.LENGTH_SHORT).show();
        }
    }

    @Override
    public void onRescanRequested() {
        rescan();
    }

    @Override
    public void onLaunchGame(final GameInfo game) {
        if (game == null) return;
        if (!hasStorageAccess()) {
            new AlertDialog.Builder(this)
                    .setTitle("No access to all files")
                    .setMessage("The host reads the game's files directly, which needs access to all files. Grant it, then launch again.")
                    .setPositiveButton("Open the setting", new DialogInterface.OnClickListener() {
                        @Override
                        public void onClick(DialogInterface dialog, int which) {
                            openAllFilesAccessSetting();
                        }
                    })
                    .setNegativeButton("Cancel", null)
                    .show();
            return;
        }
        switch (mLauncher.status(game)) {
            case LauncherOverlayView.STATUS_OTHER:
                new AlertDialog.Builder(this)
                        .setTitle("This APK runs another game")
                        .setMessage(game.title + " (" + game.titleId + ") needs an APK built for it:\n\n"
                                + "gradle -p dm/android :app:assembleDebug -PdmGame=" + game.titleId
                                + "\n\nThis APK runs " + mLauncher.builtGameText() + ".")
                        .setPositiveButton("OK", null)
                        .show();
                return;
            case LauncherOverlayView.STATUS_UNKNOWN:
                new AlertDialog.Builder(this)
                        .setTitle("Title ID unknown")
                        .setMessage("No control.nacp in " + game.folderPath + " names the game. This APK runs "
                                + mLauncher.builtGameText() + "; any other game will not start. Launch it anyway?")
                        .setPositiveButton("Launch", new DialogInterface.OnClickListener() {
                            @Override
                            public void onClick(DialogInterface dialog, int which) {
                                startGameSession(game.folderPath);
                            }
                        })
                        .setNegativeButton("Cancel", null)
                        .show();
                return;
            default:
                startGameSession(game.folderPath);
        }
    }

    @Override
    public void onSettingsRequested() {
        final boolean needAccess = !hasStorageAccess();
        final String[] items = new String[needAccess ? 5 : 4];
        items[0] = "Performance HUD: " + (mShowFps ? "on" : "off");
        items[1] = "Touch controls in game: " + (mTouchControls ? "on" : "off");
        items[2] = "Type the library folder…";
        items[3] = "Use the default library folder (" + defaultLibraryDir() + ")";
        if (needAccess) items[4] = "Grant access to all files…";
        new AlertDialog.Builder(this)
                .setTitle("Settings")
                .setItems(items, new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface dialog, int which) {
                        switch (which) {
                            case 0:
                                mShowFps = !mShowFps;
                                setPreference(PREF_SHOW_FPS, mShowFps);
                                break;
                            case 1:
                                onTouchControlsToggled();
                                break;
                            case 2:
                                showEditPathDialog();
                                break;
                            case 3:
                                saveLibraryDir(defaultLibraryDir());
                                break;
                            case 4:
                                openAllFilesAccessSetting();
                                break;
                            default:
                                break;
                        }
                    }
                })
                .setNegativeButton("Close", null)
                .show();
    }

    @Override
    public void onTouchControlsToggled() {
        mTouchControls = !mTouchControls;
        setPreference(PREF_TOUCH_CONTROLS, mTouchControls);
        mLauncher.setTouchControls(mTouchControls);
    }

    private void openAllFilesAccessSetting() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) return;
        try {
            Intent intent = new Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION);
            intent.setData(Uri.parse("package:" + getPackageName()));
            startActivity(intent);
        } catch (Exception e) {
            startActivity(new Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION));
        }
    }

    // ---- Library folder ----

    @Override
    @SuppressLint("WrongConstant")
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQUEST_SELECT_FOLDER && resultCode == RESULT_OK && data != null) {
            Uri treeUri = data.getData();
            if (treeUri != null) {
                try {
                    final int takeFlags = data.getFlags()
                            & (Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
                    getContentResolver().takePersistableUriPermission(treeUri, takeFlags);
                } catch (Exception e) {
                    Log.w("dm", "Could not take persistable URI permission: " + e.getMessage());
                }

                String resolvedPath = resolveDocTreePath(treeUri);
                if (resolvedPath != null) {
                    saveLibraryDir(resolvedPath);
                } else {
                    Toast.makeText(this, "This folder has no file path the host can open:\n" + treeUri, Toast.LENGTH_LONG).show();
                }
            }
        }
    }

    private String resolveDocTreePath(Uri treeUri) {
        if (treeUri == null) return null;
        try {
            String docId = DocumentsContract.getTreeDocumentId(treeUri);
            if (docId == null) return null;

            if (docId.startsWith("primary:")) {
                String sub = docId.substring("primary:".length());
                File base = Environment.getExternalStorageDirectory();
                return new File(base, sub).getAbsolutePath();
            }

            String[] parts = docId.split(":", 2);
            if (parts.length == 2) {
                String uuid = parts[0];
                String sub = parts[1];
                File storage = new File("/storage/" + uuid);
                if (storage.exists()) {
                    return new File(storage, sub).getAbsolutePath();
                }
            }
        } catch (Exception e) {
            Log.w("dm", "resolveDocTreePath exception: " + e.getMessage());
        }
        return null;
    }

    private void showEditPathDialog() {
        final EditText input = new EditText(this);
        input.setText(mLibraryDir);
        input.setTextColor(Color.WHITE);
        input.setBackgroundColor(0xFF1E222B);
        input.setPadding(dp(12), dp(12), dp(12), dp(12));
        input.setTextSize(12);
        input.setTypeface(Typeface.MONOSPACE);

        new AlertDialog.Builder(this)
                .setTitle("Library folder")
                .setMessage("The absolute path of a game folder, or of the folder that holds game folders:")
                .setView(input)
                .setPositiveButton("Save", new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface dialog, int which) {
                        String path = input.getText().toString().trim();
                        if (!path.isEmpty()) {
                            saveLibraryDir(path);
                        }
                    }
                })
                .setNegativeButton("Cancel", null)
                .show();
    }

    // ---- Game session ----

    private void startGameSession(String gameDir) {
        File gameFolder = new File(gameDir);
        if (!GameScanner.isGameFolder(gameFolder)) {
            new AlertDialog.Builder(this)
                    .setTitle("No 'main' module")
                    .setMessage("The folder has no 'main' module:\n" + gameDir
                            + "\n\nPrepare the game with scripts/prepare_game_android.py --push, or pick the folder it wrote.")
                    .setPositiveButton("OK", null)
                    .show();
            return;
        }

        File shadersCandidate = new File(gameFolder, "shaders");
        String shaderDir = shadersCandidate.exists() ? shadersCandidate.getAbsolutePath() : gameDir;

        File romfsImg = new File(gameFolder, "romfs.img");
        File romfsFolder = new File(gameFolder, "romfs");
        String romfsDir = romfsImg.exists() ? romfsImg.getAbsolutePath()
                : (romfsFolder.exists() ? romfsFolder.getAbsolutePath() : gameDir);

        File saveFolder = new File(getFilesDir(), "save");
        saveFolder.mkdirs();
        String saveDir = saveFolder.getAbsolutePath();

        mInGame = true;
        mButtons = 0;
        mLx = mLy = mRx = mRy = 0;
        mLauncher.animate().alpha(0f).setDuration(250).withEndAction(new Runnable() {
            @Override
            public void run() {
                if (mInGame) mLauncher.setVisibility(View.GONE);
            }
        }).start();
        mSurfaceView.setVisibility(View.VISIBLE);
        mVirtualController.setVisibility(View.VISIBLE);
        mVirtualController.setControlsVisible(mTouchControls);   // hidden controls keep their toggle button; touches go to the game
        mVirtualController.bringToFront();
        mVirtualController.requestFocus();

        if (mShowFps) {
            mFpsOverlay.setVisibility(View.VISIBLE);
            mFpsOverlay.bringToFront();
            mFpsHandler.removeCallbacks(mFpsUpdater);
            mFpsHandler.postDelayed(mFpsUpdater, 500);
        } else {
            mFpsOverlay.setVisibility(View.GONE);
        }

        if (!NativeBridge.nativeStartHost(gameDir, shaderDir, romfsDir, saveDir, null)) {
            Toast.makeText(this, "The host did not start (see adb logcat -s dm)", Toast.LENGTH_LONG).show();
            stopGameSession();
        }
    }

    /** Back to the launcher. After nativeStopHost the host ends the process within 1.5 s (dm/host/hle_lifecycle.c), so this matters only when the start failed. */
    private void stopGameSession() {
        runOnUiThread(new Runnable() {
            @Override
            public void run() {
                mInGame = false;
                mFpsOverlay.setVisibility(View.GONE);
                mFpsHandler.removeCallbacks(mFpsUpdater);
                mVirtualController.setVisibility(View.GONE);
                mLauncher.animate().cancel();
                mLauncher.setAlpha(1f);
                mLauncher.setVisibility(View.VISIBLE);
                mLauncher.bringToFront();
                mLauncher.requestFocus();
                applyImmersiveMode();
            }
        });
    }

    @Override
    public void onBackPressed() {
        if (NativeBridge.nativeIsRunning()) {
            new AlertDialog.Builder(this)
                    .setTitle("Quit the game?")
                    .setMessage("The game stops and nxdroid closes with it: unsaved progress is lost.")
                    .setPositiveButton("Quit", new DialogInterface.OnClickListener() {
                        @Override
                        public void onClick(DialogInterface dialog, int which) {
                            NativeBridge.nativeStopHost();
                            stopGameSession();
                        }
                    })
                    .setNegativeButton("Keep playing", null)
                    .show();
        } else {
            super.onBackPressed();
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        applyImmersiveMode();
        if (!mInGame) {
            mLauncher.setStorageAccess(hasStorageAccess());
            rescan();   // the folder may have changed while the app was away (a push, a granted permission)
        }
        if (NativeBridge.nativeIsRunning() && mShowFps && mFpsOverlay != null) {
            mFpsOverlay.setVisibility(View.VISIBLE);
            mFpsOverlay.bringToFront();
            mFpsHandler.removeCallbacks(mFpsUpdater);
            mFpsHandler.postDelayed(mFpsUpdater, 500);
        }
    }

    @Override
    protected void onPause() {
        super.onPause();
        mFpsHandler.removeCallbacks(mFpsUpdater);
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        mFpsHandler.removeCallbacks(mFpsUpdater);
        NativeBridge.nativeStopHost();
    }

    // ---- Physical controllers: the launcher before a game, the guest's pad during one ----

    private void sendPad() {
        NativeBridge.nativeSendPad(0, mButtons, mLx, mLy, mRx, mRy);
        NativeBridge.nativeSendInput(mButtons, mLx, mLy, mRx, mRy);
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        long mapped = mapKeyCodeToButton(keyCode);
        if (!mInGame) {
            if (keyCode == KeyEvent.KEYCODE_ENTER || keyCode == KeyEvent.KEYCODE_DPAD_CENTER
                    || keyCode == KeyEvent.KEYCODE_NUMPAD_ENTER) {
                mapped = DM_BTN_A;
            }
            if (mapped != 0 && mLauncher.handleButton(mapped)) return true;
            return super.onKeyDown(keyCode, event);
        }
        if (mapped != 0) {
            mButtons |= mapped;
            sendPad();
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }

    @Override
    public boolean onKeyUp(int keyCode, KeyEvent event) {
        long mapped = mapKeyCodeToButton(keyCode);
        if (!mInGame) {
            return mapped != 0 || super.onKeyUp(keyCode, event);
        }
        if (mapped != 0) {
            mButtons &= ~mapped;
            sendPad();
            return true;
        }
        return super.onKeyUp(keyCode, event);
    }

    @Override
    public boolean onGenericMotionEvent(MotionEvent event) {
        if ((event.getSource() & InputDevice.SOURCE_JOYSTICK) == InputDevice.SOURCE_JOYSTICK
                && event.getAction() == MotionEvent.ACTION_MOVE) {
            if (!mInGame) {
                launcherNavigate(event);
                return true;
            }

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
            mLy = -filterAxis(rawLy);
            mRx = filterAxis(rawRx);
            mRy = -filterAxis(rawRy);

            float hatX = event.getAxisValue(MotionEvent.AXIS_HAT_X);
            float hatY = event.getAxisValue(MotionEvent.AXIS_HAT_Y);

            mButtons &= ~(DM_BTN_LEFT | DM_BTN_RIGHT | DM_BTN_UP | DM_BTN_DOWN);
            if (hatX < -0.5f) mButtons |= DM_BTN_LEFT;
            if (hatX > 0.5f) mButtons |= DM_BTN_RIGHT;
            if (hatY < -0.5f) mButtons |= DM_BTN_UP;
            if (hatY > 0.5f) mButtons |= DM_BTN_DOWN;

            float lt = event.getAxisValue(MotionEvent.AXIS_LTRIGGER);
            if (lt == 0.0f) lt = event.getAxisValue(MotionEvent.AXIS_BRAKE);
            float rt = event.getAxisValue(MotionEvent.AXIS_RTRIGGER);
            if (rt == 0.0f) rt = event.getAxisValue(MotionEvent.AXIS_GAS);

            if (lt > 0.5f) mButtons |= DM_BTN_ZL; else mButtons &= ~DM_BTN_ZL;
            if (rt > 0.5f) mButtons |= DM_BTN_ZR; else mButtons &= ~DM_BTN_ZR;

            sendPad();
            return true;
        }
        return super.onGenericMotionEvent(event);
    }

    /** The left stick or the hat moves the launcher's selection once per push. */
    private void launcherNavigate(MotionEvent event) {
        float x = event.getAxisValue(MotionEvent.AXIS_HAT_X);
        float y = event.getAxisValue(MotionEvent.AXIS_HAT_Y);
        if (Math.abs(x) < 0.5f && Math.abs(y) < 0.5f) {
            x = event.getAxisValue(MotionEvent.AXIS_X);
            y = event.getAxisValue(MotionEvent.AXIS_Y);
        }
        long direction = 0;
        if (Math.abs(x) >= Math.abs(y)) {
            if (x <= -NAV_THRESHOLD) direction = DM_BTN_LEFT;
            else if (x >= NAV_THRESHOLD) direction = DM_BTN_RIGHT;
        } else {
            if (y <= -NAV_THRESHOLD) direction = DM_BTN_UP;
            else if (y >= NAV_THRESHOLD) direction = DM_BTN_DOWN;
        }
        if (direction != 0 && direction != mNavDirection) mLauncher.handleButton(direction);
        mNavDirection = direction;
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
                return DM_BTN_B;
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
