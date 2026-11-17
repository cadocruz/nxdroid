package com.nxdroid;

import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.LinearGradient;
import android.graphics.Paint;
import android.graphics.Rect;
import android.graphics.RectF;
import android.graphics.Shader;
import android.graphics.Typeface;
import android.os.BatteryManager;
import android.os.Build;
import android.util.AttributeSet;
import android.view.Display;
import android.view.InputDevice;
import android.view.MotionEvent;
import android.view.View;
import android.view.WindowManager;

import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;

/**
 * The launcher (the Argon design, dm/android/mockups/design_spec_argon.md): a status bar, the library
 * folder, the selected game's card and a 2x2 grid of the games found, paged by four. Everything it
 * shows comes from the device, the scanned folders (GameScanner) and the game this APK was built for
 * (NativeBridge.nativeGetBuiltGame). It is drawn on a Canvas and driven by touch and by a gamepad
 * through {@link #handleButton(long)} (Switch button positions, MainActivity's DM_BTN_* bits).
 */
public class LauncherOverlayView extends View {

    public interface LauncherEventListener {
        void onChangeFolderRequested();
        void onRescanRequested();
        void onLaunchGame(GameInfo game);
        void onSettingsRequested();
        void onTouchControlsToggled();
    }

    /** Whether the APK can start a game: built for it, built for another game, or the folder names no title ID. */
    public static final int STATUS_BUILT = 0;
    public static final int STATUS_OTHER = 1;
    public static final int STATUS_UNKNOWN = 2;

    private static final int PAGE = 4;
    private static final long TICK_MS = 2000;

    // Colour tokens of the Argon specification (section 4)
    private static final int COLOR_BG = Color.rgb(10, 13, 20);
    private static final int COLOR_SURFACE_0 = Color.rgb(14, 18, 27);
    private static final int COLOR_SURFACE_1 = Color.rgb(19, 25, 38);
    private static final int COLOR_SURFACE_CARD = Color.rgb(18, 24, 36);
    private static final int COLOR_CYAN = Color.rgb(0, 229, 255);
    private static final int COLOR_CRIMSON = Color.rgb(255, 51, 102);
    private static final int COLOR_GREEN = Color.rgb(16, 185, 129);
    private static final int COLOR_AMBER = Color.rgb(255, 196, 0);
    private static final int COLOR_BORDER = Color.rgb(35, 46, 68);
    private static final int COLOR_TEXT_PRIMARY = Color.rgb(248, 250, 252);
    private static final int COLOR_TEXT_SECONDARY = Color.rgb(160, 175, 200);
    private static final int COLOR_TEXT_MUTED = Color.rgb(100, 116, 139);

    private LauncherEventListener mListener;
    private String mLibraryDir = "";
    private final List<GameInfo> mGames = new ArrayList<>();
    private int mSelected = 0;
    private boolean mScanning = false;
    private boolean mStorageAccess = true;
    private boolean mTouchControls = true;
    private String[] mBuiltGame;
    private String mVersionName = "";

    private String mDeviceModel = "";
    private String mSocInfo = "";
    private String mRefreshRate = "";
    private String mLiveTime = "";
    private String mLiveBattery = "";
    private String mLiveTemp = "";
    private String mLiveGamepad = "Touch";
    private long mLastMetricsCheck = 0;

    private final Paint mPaint = new Paint(Paint.ANTI_ALIAS_FLAG | Paint.FILTER_BITMAP_FLAG);
    private final RectF mRectF = new RectF();
    private final Rect mSrc = new Rect();

    private final RectF mBtnChangeFolder = new RectF();
    private final RectF mBtnRescan = new RectF();
    private final RectF mBtnLaunch = new RectF();
    private final RectF mBtnTouch = new RectF();
    private final RectF mBtnSettings = new RectF();
    private final RectF mBtnPrevPage = new RectF();
    private final RectF mBtnNextPage = new RectF();
    private final List<RectF> mCardBounds = new ArrayList<>();

    private final Runnable mTicker = new Runnable() {
        @Override
        public void run() {
            if (getVisibility() == VISIBLE) invalidate();
            postDelayed(this, TICK_MS);
        }
    };

    public LauncherOverlayView(Context context) {
        super(context);
        init();
    }

    public LauncherOverlayView(Context context, AttributeSet attrs) {
        super(context, attrs);
        init();
    }

    private void init() {
        setFocusable(true);
        setFocusableInTouchMode(true);
        setClickable(true);
        detectHardwareInfo();
        try {
            mVersionName = getContext().getPackageManager()
                    .getPackageInfo(getContext().getPackageName(), 0).versionName;
        } catch (Exception ignored) {
            mVersionName = "";
        }
    }

    // ---- State from MainActivity ----

    public void setListener(LauncherEventListener listener) {
        mListener = listener;
    }

    public void setBuiltGame(String[] builtGame) {
        mBuiltGame = builtGame;
        invalidate();
    }

    public void setLibraryDirectory(String path) {
        mLibraryDir = path != null ? path : "";
        invalidate();
    }

    public void setScanning(boolean scanning) {
        mScanning = scanning;
        invalidate();
    }

    public void setStorageAccess(boolean granted) {
        mStorageAccess = granted;
        invalidate();
    }

    public void setTouchControls(boolean on) {
        mTouchControls = on;
        invalidate();
    }

    /** Replaces the list; the selection stays on the same folder when it is still there, else on a game this APK can start. */
    public void setGames(List<GameInfo> games) {
        String keep = getSelectedGame() != null ? getSelectedGame().folderPath : null;
        mGames.clear();
        if (games != null) mGames.addAll(games);
        mSelected = 0;
        int built = -1;
        for (int i = 0; i < mGames.size(); i++) {
            if (mGames.get(i).folderPath.equals(keep)) {
                built = i;
                break;
            }
            if (built < 0 && status(mGames.get(i)) == STATUS_BUILT) built = i;
        }
        if (built >= 0) mSelected = built;
        mScanning = false;
        invalidate();
    }

    public GameInfo getSelectedGame() {
        if (mGames.isEmpty()) return null;
        if (mSelected < 0 || mSelected >= mGames.size()) mSelected = 0;
        return mGames.get(mSelected);
    }

    public int status(GameInfo game) {
        if (game == null || game.titleId == null) return STATUS_UNKNOWN;
        return game.matches(mBuiltGame) ? STATUS_BUILT : STATUS_OTHER;
    }

    /** The built game's name and ID, for messages ("Mario Kart 8 Deluxe (0100152000022000)"). */
    public String builtGameText() {
        if (mBuiltGame == null || mBuiltGame.length < 2) return "an unknown game";
        return mBuiltGame[1] + " (" + mBuiltGame[0] + ")";
    }

    // ---- Gamepad navigation ----

    /** One button press (MainActivity.DM_BTN_*, Switch positions); true when the launcher used it. */
    public boolean handleButton(long button) {
        int n = mGames.size();
        if (button == MainActivity.DM_BTN_A) {
            if (mListener != null && getSelectedGame() != null) mListener.onLaunchGame(getSelectedGame());
            return true;
        } else if (button == MainActivity.DM_BTN_Y) {
            if (mListener != null) mListener.onRescanRequested();
            return true;
        } else if (button == MainActivity.DM_BTN_X) {
            if (mListener != null) mListener.onChangeFolderRequested();
            return true;
        } else if (button == MainActivity.DM_BTN_PLUS) {
            if (mListener != null) mListener.onSettingsRequested();
            return true;
        } else if (button == MainActivity.DM_BTN_MINUS) {
            if (mListener != null) mListener.onTouchControlsToggled();
            return true;
        }
        if (n == 0) return false;
        int target = navigate(mSelected, n, button);
        if (target < 0) return false;
        if (target != mSelected) {
            mSelected = target;
            invalidate();
        }
        return true;
    }

    /**
     * The selection after a direction or page button, in a two-column grid paged by four; the same
     * index when the move would leave the list; -1 when the button does not move the selection.
     */
    static int navigate(int selected, int count, long button) {
        int target;
        if (button == MainActivity.DM_BTN_LEFT) {
            target = selected - 1;
        } else if (button == MainActivity.DM_BTN_RIGHT) {
            target = selected + 1;
        } else if (button == MainActivity.DM_BTN_UP) {
            target = selected - 2;
        } else if (button == MainActivity.DM_BTN_DOWN) {
            target = selected + 2;
            if (target >= count && (count - 1) / 2 > selected / 2) target = count - 1;   // the row below is shorter
        } else if (button == MainActivity.DM_BTN_L || button == MainActivity.DM_BTN_ZL) {
            target = (selected / PAGE - 1) * PAGE;
        } else if (button == MainActivity.DM_BTN_R || button == MainActivity.DM_BTN_ZR) {
            target = (selected / PAGE + 1) * PAGE;
        } else {
            return -1;
        }
        return target >= 0 && target < count ? target : selected;
    }

    // ---- Device facts ----

    private void detectHardwareInfo() {
        mDeviceModel = Build.MODEL != null ? Build.MODEL : "";
        if (Build.MANUFACTURER != null && !mDeviceModel.toLowerCase(Locale.ROOT)
                .startsWith(Build.MANUFACTURER.toLowerCase(Locale.ROOT))) {
            mDeviceModel = Build.MANUFACTURER + " " + mDeviceModel;
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S && Build.SOC_MODEL != null
                && !Build.SOC_MODEL.isEmpty() && !Build.UNKNOWN.equals(Build.SOC_MODEL)) {
            mSocInfo = (Build.SOC_MANUFACTURER != null && !Build.UNKNOWN.equals(Build.SOC_MANUFACTURER)
                    ? Build.SOC_MANUFACTURER + " " : "") + Build.SOC_MODEL;
        } else if (Build.HARDWARE != null) {
            mSocInfo = Build.HARDWARE;
        }
        WindowManager wm = (WindowManager) getContext().getSystemService(Context.WINDOW_SERVICE);
        if (wm != null && wm.getDefaultDisplay() != null) {
            Display display = wm.getDefaultDisplay();
            float hz = display.getRefreshRate();
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M && display.getSupportedModes() != null) {
                for (Display.Mode m : display.getSupportedModes()) hz = Math.max(hz, m.getRefreshRate());
            }
            mRefreshRate = Math.round(hz) + " Hz";
        }
    }

    private void refreshSystemMetrics() {
        long now = System.currentTimeMillis();
        if (now - mLastMetricsCheck < TICK_MS - 100) return;
        mLastMetricsCheck = now;
        mLiveTime = new SimpleDateFormat("HH:mm", Locale.getDefault()).format(new Date());
        try {
            Intent battery = getContext().registerReceiver(null, new IntentFilter(Intent.ACTION_BATTERY_CHANGED));
            if (battery != null) {
                int level = battery.getIntExtra(BatteryManager.EXTRA_LEVEL, -1);
                int scale = battery.getIntExtra(BatteryManager.EXTRA_SCALE, -1);
                int state = battery.getIntExtra(BatteryManager.EXTRA_STATUS, -1);
                boolean charging = state == BatteryManager.BATTERY_STATUS_CHARGING
                        || state == BatteryManager.BATTERY_STATUS_FULL;
                if (level >= 0 && scale > 0) {
                    mLiveBattery = Math.round(level * 100f / scale) + "%" + (charging ? " +" : "");
                }
                int tenths = battery.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, Integer.MIN_VALUE);
                if (tenths != Integer.MIN_VALUE) mLiveTemp = Math.round(tenths / 10f) + "°C";
            }
        } catch (Exception ignored) {
            // no battery facts on this device
        }
        String pad = null;
        for (int id : InputDevice.getDeviceIds()) {
            InputDevice dev = InputDevice.getDevice(id);
            if (dev == null || dev.isVirtual()) continue;
            int s = dev.getSources();
            if ((s & InputDevice.SOURCE_GAMEPAD) == InputDevice.SOURCE_GAMEPAD
                    || (s & InputDevice.SOURCE_JOYSTICK) == InputDevice.SOURCE_JOYSTICK) {
                pad = dev.getName();
                break;
            }
        }
        mLiveGamepad = pad != null ? pad : "Touch";
    }

    @Override
    protected void onAttachedToWindow() {
        super.onAttachedToWindow();
        removeCallbacks(mTicker);
        postDelayed(mTicker, TICK_MS);
    }

    @Override
    protected void onDetachedFromWindow() {
        removeCallbacks(mTicker);
        super.onDetachedFromWindow();
    }

    // ---- Drawing ----

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        float w = getWidth();
        float h = getHeight();
        if (w <= 0 || h <= 0) return;
        refreshSystemMetrics();
        canvas.drawColor(COLOR_BG);

        float padX = Math.max(16f, w * 0.02f);
        float topBarH = Math.max(dp(40), h * 0.08f);
        float folderH = Math.max(dp(48), h * 0.11f);
        float footerH = Math.max(dp(32), h * 0.06f);
        float folderY1 = topBarH + h * 0.012f;
        float folderY2 = folderY1 + folderH;
        float mainY1 = folderY2 + h * 0.015f;
        float mainY2 = h - footerH - h * 0.012f;

        drawTopBar(canvas, w, topBarH, padX);
        drawLibraryBar(canvas, w, folderY1, folderY2, padX);
        drawPanes(canvas, w, mainY1, mainY2, padX);
        drawFooter(canvas, w, h, footerH, padX);
    }

    private void drawTopBar(Canvas canvas, float w, float barH, float padX) {
        fill(canvas, 0, 0, w, barH, 0, COLOR_SURFACE_0);
        float midY = barH * 0.5f;

        float pillW = barH * 0.22f, pillH = barH * 0.55f;
        mPaint.setColor(COLOR_CYAN);
        mRectF.set(padX, midY - pillH / 2, padX + pillW, midY + pillH / 2);
        canvas.drawRoundRect(mRectF, pillW / 2, pillW / 2, mPaint);
        mPaint.setColor(COLOR_CRIMSON);
        mRectF.set(padX + pillW + 4, midY - pillH / 2, padX + 2 * pillW + 4, midY + pillH / 2);
        canvas.drawRoundRect(mRectF, pillW / 2, pillW / 2, mPaint);

        float x = padX + 2 * pillW + 14;
        text(canvas, "nxdroid", x, midY + barH * 0.15f, barH * 0.42f, COLOR_TEXT_PRIMARY, true);
        x += mPaint.measureText("nxdroid") + 12;
        mPaint.setTextSize(barH * 0.24f);
        float badgeW = mPaint.measureText("VULKAN AARCH64") + 20;
        fill(canvas, x, midY - barH * 0.22f, x + badgeW, midY + barH * 0.22f, 8, COLOR_SURFACE_1);
        text(canvas, "VULKAN AARCH64", x + 10, midY + barH * 0.08f, barH * 0.24f, COLOR_CYAN, true);
        float leftEnd = x + badgeW + 16;

        // Right: clock, battery, temperature, controller (right to left)
        float size = barH * 0.28f;
        float rx = w - padX;
        rx = rightText(canvas, mLiveTime, rx, midY + barH * 0.1f, size, COLOR_TEXT_PRIMARY) - 24;
        rx = rightText(canvas, mLiveBattery, rx, midY + barH * 0.1f, size, COLOR_TEXT_PRIMARY) - 24;
        rx = rightText(canvas, mLiveTemp, rx, midY + barH * 0.1f, size, COLOR_GREEN) - 24;
        mPaint.setTextSize(size);
        String pad = fit(mLiveGamepad, w * 0.14f);
        rx = rightText(canvas, pad, rx, midY + barH * 0.1f, size, COLOR_TEXT_SECONDARY) - 24;

        // Centre: device, SoC, display rate
        float chipX1 = leftEnd, chipX2 = rx;
        if (chipX2 > chipX1 + dp(80)) {
            float chipH = barH * 0.60f;
            mRectF.set(chipX1, midY - chipH / 2, chipX2, midY + chipH / 2);
            mPaint.setStyle(Paint.Style.FILL);
            mPaint.setColor(COLOR_SURFACE_1);
            canvas.drawRoundRect(mRectF, chipH / 2, chipH / 2, mPaint);
            stroke(canvas, mRectF, chipH / 2, COLOR_BORDER, 1.2f);
            mPaint.setColor(COLOR_GREEN);
            canvas.drawCircle(chipX1 + chipH * 0.5f, midY, chipH * 0.1f, mPaint);
            String diag = mDeviceModel + "  ·  " + mSocInfo + "  ·  " + mRefreshRate;
            mPaint.setTextSize(barH * 0.25f);
            text(canvas, fit(diag, chipX2 - chipX1 - chipH * 1.3f), chipX1 + chipH, midY + barH * 0.09f,
                    barH * 0.25f, COLOR_TEXT_PRIMARY, false);
        }
        mPaint.setColor(COLOR_BORDER);
        mPaint.setStrokeWidth(1);
        canvas.drawLine(0, barH, w, barH, mPaint);
    }

    private void drawLibraryBar(Canvas canvas, float w, float y1, float y2, float padX) {
        float h = y2 - y1;
        mRectF.set(padX, y1, w - padX, y2);
        fill(canvas, mRectF, 10, COLOR_SURFACE_1);
        stroke(canvas, mRectF, 10, COLOR_BORDER, 1.2f);
        fill(canvas, padX, y1, padX + 6, y2, 3, COLOR_CYAN);

        float btnH = h * 0.6f;
        float btnY1 = y1 + (h - btnH) / 2;
        float btnText = btnH * 0.38f;
        mPaint.setTextSize(btnText);
        float rescanW = mPaint.measureText("Rescan (Y)") + btnH;
        mBtnRescan.set(w - padX - 12 - rescanW, btnY1, w - padX - 12, btnY1 + btnH);
        button(canvas, mBtnRescan, "Rescan (Y)", btnText, COLOR_SURFACE_CARD, COLOR_BORDER, COLOR_TEXT_PRIMARY);
        float changeW = mPaint.measureText("Change folder (X)") + btnH;
        mBtnChangeFolder.set(mBtnRescan.left - 10 - changeW, btnY1, mBtnRescan.left - 10, btnY1 + btnH);
        button(canvas, mBtnChangeFolder, "Change folder (X)", btnText, COLOR_SURFACE_CARD, COLOR_CYAN, COLOR_CYAN);

        float tx = padX + 20;
        float maxW = mBtnChangeFolder.left - tx - 16;
        text(canvas, "GAME LIBRARY", tx, y1 + h * 0.28f, h * 0.17f, COLOR_CYAN, true);
        mPaint.setTypeface(Typeface.MONOSPACE);
        mPaint.setTextSize(h * 0.27f);
        String path = fit(mLibraryDir, maxW);
        mPaint.setColor(COLOR_TEXT_PRIMARY);
        canvas.drawText(path, tx, y1 + h * 0.60f, mPaint);

        String sub;
        int color = COLOR_TEXT_MUTED;
        if (!mStorageAccess) {
            sub = "No access to all files: the host cannot read the game folders. Open Settings (+) to grant it.";
            color = COLOR_CRIMSON;
        } else if (mScanning) {
            sub = "Scanning…";
        } else {
            sub = mGames.size() + (mGames.size() == 1 ? " game" : " games") + " found  ·  this APK runs "
                    + builtGameText();
        }
        mPaint.setTextSize(h * 0.16f);
        text(canvas, fit(sub, maxW), tx, y1 + h * 0.86f, h * 0.16f, color, false);
    }

    private void drawPanes(Canvas canvas, float w, float y1, float y2, float padX) {
        float avail = w - 2 * padX;
        float heroW = Math.max(dp(260), avail * 0.38f);
        float heroX1 = padX, heroX2 = padX + heroW;
        drawHero(canvas, heroX1, heroX2, y1, y2);
        drawGrid(canvas, heroX2 + 14, w - padX, y1, y2);
    }

    private void drawHero(Canvas canvas, float x1, float x2, float y1, float y2) {
        float paneH = y2 - y1;
        mRectF.set(x1, y1, x2, y2);
        fill(canvas, mRectF, 12, COLOR_SURFACE_1);
        stroke(canvas, mRectF, 12, COLOR_BORDER, 1.2f);
        GameInfo g = getSelectedGame();
        float cx = x1 + 18;
        float textW = x2 - x1 - 36;

        float artH = paneH * 0.30f;
        mRectF.set(x1, y1, x2, y1 + artH);
        mPaint.setShader(new LinearGradient(x1, y1, x2, y1 + artH, Color.rgb(0, 90, 120),
                Color.rgb(20, 24, 38), Shader.TileMode.CLAMP));
        canvas.drawRoundRect(mRectF, 12, 12, mPaint);
        mPaint.setShader(null);

        if (g == null) {
            float y = y1 + artH + paneH * 0.10f;
            text(canvas, mScanning ? "Scanning the library…" : "No game found", cx, y, paneH * 0.06f,
                    COLOR_TEXT_PRIMARY, true);
            if (!mScanning) {
                String[] lines = {
                        "A game is a folder with the rewritten 'main' module, as",
                        "scripts/prepare_game_android.py --push writes it.",
                        "Put it in this folder or in a subfolder of it,",
                        "or press Change folder (X) to pick the folder that holds it."};
                for (String line : lines) {
                    y += paneH * 0.055f;
                    mPaint.setTextSize(paneH * 0.036f);
                    text(canvas, fit(line, textW), cx, y, paneH * 0.036f, COLOR_TEXT_SECONDARY, false);
                }
            }
            drawHeroButtons(canvas, cx, x2 - 18, y2, paneH, false);
            return;
        }

        float iconSize = artH - 24;
        if (g.icon != null) {
            mRectF.set(cx, y1 + 12, cx + iconSize, y1 + 12 + iconSize);
            bitmap(canvas, g.icon, mRectF);
        }
        float tagX = g.icon != null ? cx + iconSize + 16 : cx;
        String[] st = statusText(g);
        int stColor = statusColor(g);
        mPaint.setTextSize(paneH * 0.034f);
        float tagW = mPaint.measureText(st[0]) + 24;
        fill(canvas, tagX, y1 + 16, tagX + tagW, y1 + 16 + paneH * 0.065f, 6, COLOR_SURFACE_0);
        text(canvas, st[0], tagX + 12, y1 + 16 + paneH * 0.045f, paneH * 0.034f, stColor, true);

        float y = y1 + artH + paneH * 0.08f;
        mPaint.setTextSize(paneH * 0.06f);
        mPaint.setTypeface(Typeface.DEFAULT_BOLD);
        text(canvas, fit(g.title, textW), cx, y, paneH * 0.06f, COLOR_TEXT_PRIMARY, true);
        y += paneH * 0.05f;
        String by = (g.publisher != null ? g.publisher : "Unknown publisher")
                + (g.displayVersion != null ? "  ·  version " + g.displayVersion : "");
        mPaint.setTextSize(paneH * 0.035f);
        text(canvas, fit(by, textW), cx, y, paneH * 0.035f, COLOR_TEXT_SECONDARY, false);

        float col2 = x1 + (x2 - x1) * 0.52f;
        float row1 = y + paneH * 0.075f;
        spec(canvas, cx, row1, "TITLE ID", g.titleId != null ? g.titleId : "unknown", paneH);
        spec(canvas, col2, row1, "SIZE", g.sizeText(), paneH);
        float row2 = row1 + paneH * 0.10f;
        spec(canvas, cx, row2, "SHADER BUNDLES", String.format(Locale.US, "%,d", g.shaderBundles), paneH);
        spec(canvas, col2, row2, "ROMFS", g.romfs != null ? g.romfs : "missing", paneH);
        mPaint.setTextSize(paneH * 0.032f);
        text(canvas, fit(st[1], textW), cx, row2 + paneH * 0.105f, paneH * 0.032f, stColor, false);

        drawHeroButtons(canvas, cx, x2 - 18, y2, paneH, status(g) != STATUS_OTHER);
    }

    private void drawHeroButtons(Canvas canvas, float left, float right, float y2, float paneH, boolean launchable) {
        float launchH = paneH * 0.12f;
        float launchY = y2 - paneH * 0.25f;
        mBtnLaunch.set(left, launchY, right, launchY + launchH);
        if (launchable) {
            mPaint.setShader(new LinearGradient(mBtnLaunch.left, mBtnLaunch.top, mBtnLaunch.right, mBtnLaunch.bottom,
                    COLOR_CYAN, Color.rgb(0, 140, 255), Shader.TileMode.CLAMP));
            canvas.drawRoundRect(mBtnLaunch, 10, 10, mPaint);
            mPaint.setShader(null);
        } else {
            fill(canvas, mBtnLaunch, 10, COLOR_SURFACE_CARD);
            stroke(canvas, mBtnLaunch, 10, COLOR_BORDER, 1.2f);
        }
        centered(canvas, "▶  LAUNCH  (A)", mBtnLaunch, launchH * 0.38f, launchable ? COLOR_BG : COLOR_TEXT_MUTED, true);

        float subY = mBtnLaunch.bottom + paneH * 0.025f;
        float subH = paneH * 0.08f;
        float half = (right - left - 10) / 2;
        mBtnTouch.set(left, subY, left + half, subY + subH);
        button(canvas, mBtnTouch, "Touch controls: " + (mTouchControls ? "on" : "off") + " (−)", subH * 0.40f,
                COLOR_SURFACE_CARD, COLOR_BORDER, COLOR_TEXT_PRIMARY);
        mBtnSettings.set(left + half + 10, subY, right, subY + subH);
        button(canvas, mBtnSettings, "Settings (+)", subH * 0.40f, COLOR_SURFACE_CARD, COLOR_BORDER, COLOR_TEXT_PRIMARY);
    }

    private void spec(Canvas canvas, float x, float y, String label, String value, float paneH) {
        text(canvas, label, x, y, paneH * 0.028f, COLOR_TEXT_MUTED, true);
        text(canvas, value, x, y + paneH * 0.045f, paneH * 0.038f, COLOR_TEXT_PRIMARY, false);
    }

    private void drawGrid(Canvas canvas, float left, float right, float top, float bottom) {
        mCardBounds.clear();
        float gap = 12;
        float colW = (right - left - gap) / 2;
        float rowH = (bottom - top - gap) / 2;
        int first = (mSelected / PAGE) * PAGE;
        for (int slot = 0; slot < PAGE; slot++) {
            int i = first + slot;
            float cx = left + (slot % 2) * (colW + gap);
            float cy = top + (slot / 2) * (rowH + gap);
            RectF card = new RectF(cx, cy, cx + colW, cy + rowH);
            mCardBounds.add(card);
            fill(canvas, card, 10, COLOR_SURFACE_CARD);
            boolean selected = i == mSelected && i < mGames.size();
            stroke(canvas, card, 10, selected ? COLOR_CYAN : COLOR_BORDER, selected ? 2.5f : 1.2f);
            if (i >= mGames.size()) continue;

            GameInfo g = mGames.get(i);
            float artH = rowH * 0.50f;
            mRectF.set(cx + 8, cy + 8, cx + colW - 8, cy + artH);
            mPaint.setShader(new LinearGradient(cx, cy, cx + colW, cy + artH, Color.rgb(30, 60, 100),
                    Color.rgb(20, 24, 34), Shader.TileMode.CLAMP));
            canvas.drawRoundRect(mRectF, 8, 8, mPaint);
            mPaint.setShader(null);
            if (g.icon != null) {
                float s = artH - 24;
                mRectF.set(cx + 20, cy + 16, cx + 20 + s, cy + 16 + s);
                bitmap(canvas, g.icon, mRectF);
            }

            float textW = colW - 24;
            mPaint.setTextSize(rowH * 0.085f);
            mPaint.setTypeface(Typeface.DEFAULT_BOLD);
            text(canvas, fit(g.title, textW), cx + 12, cy + artH + rowH * 0.13f, rowH * 0.085f, COLOR_TEXT_PRIMARY, true);
            String line = (g.titleId != null ? g.titleId : "title ID unknown") + "  ·  " + g.sizeText();
            mPaint.setTextSize(rowH * 0.065f);
            text(canvas, fit(line, textW), cx + 12, cy + artH + rowH * 0.25f, rowH * 0.065f, COLOR_TEXT_SECONDARY, false);
            int color = statusColor(g);
            mPaint.setColor(color);
            float dotY = cy + rowH - rowH * 0.12f;
            canvas.drawCircle(cx + 18, dotY - rowH * 0.02f, rowH * 0.018f, mPaint);
            mPaint.setTextSize(rowH * 0.065f);
            text(canvas, fit(statusText(g)[0], textW - 24), cx + 30, dotY, rowH * 0.065f, color, false);
        }
    }

    private void drawFooter(Canvas canvas, float w, float h, float footerH, float padX) {
        float y = h - footerH;
        fill(canvas, 0, y, w, h, 0, COLOR_SURFACE_0);
        mPaint.setColor(COLOR_BORDER);
        mPaint.setStrokeWidth(1);
        canvas.drawLine(0, y, w, y, mPaint);
        float textY = y + footerH * 0.64f;
        float size = footerH * 0.36f;

        String stamp = "nxdroid " + mVersionName;
        float rx = rightText(canvas, stamp, w - padX, textY, size, COLOR_TEXT_MUTED) - 24;

        int pages = Math.max(1, (mGames.size() + PAGE - 1) / PAGE);
        mBtnPrevPage.setEmpty();
        mBtnNextPage.setEmpty();
        if (pages > 1) {
            float bh = footerH * 0.7f, by = y + (footerH - bh) / 2;
            mBtnNextPage.set(rx - bh * 1.6f, by, rx, by + bh);
            button(canvas, mBtnNextPage, "R ▶", size, COLOR_SURFACE_CARD, COLOR_BORDER, COLOR_TEXT_PRIMARY);
            rx = rightText(canvas, "Page " + (mSelected / PAGE + 1) + " of " + pages, mBtnNextPage.left - 12, textY,
                    size, COLOR_TEXT_SECONDARY) - 12;
            mBtnPrevPage.set(rx - bh * 1.6f, by, rx, by + bh);
            button(canvas, mBtnPrevPage, "◀ L", size, COLOR_SURFACE_CARD, COLOR_BORDER, COLOR_TEXT_PRIMARY);
            rx = mBtnPrevPage.left - 24;
        }
        mPaint.setTextSize(size);
        String keys = "(A) Launch   (Y) Rescan   (X) Change folder   (+) Settings   (−) Touch controls";
        text(canvas, fit(keys, rx - padX), padX, textY, size, COLOR_TEXT_SECONDARY, false);
    }

    // ---- Status of a game for this APK ----

    private String[] statusText(GameInfo g) {
        switch (status(g)) {
            case STATUS_BUILT:
                return new String[]{"Built into this APK", "This APK was built for this game: ready to launch."};
            case STATUS_OTHER:
                return new String[]{"Needs its own APK",
                        "This APK runs " + builtGameText() + "; build one with -PdmGame=" + g.titleId + "."};
            default:
                return new String[]{"Title ID unknown",
                        "No control.nacp names the game: launching starts " + builtGameText() + "'s host on it."};
        }
    }

    private int statusColor(GameInfo g) {
        switch (status(g)) {
            case STATUS_BUILT:
                return COLOR_GREEN;
            case STATUS_OTHER:
                return COLOR_CRIMSON;
            default:
                return COLOR_AMBER;
        }
    }

    // ---- Touch ----

    @Override
    public boolean onTouchEvent(MotionEvent event) {
        if (event.getAction() != MotionEvent.ACTION_UP) return true;
        float x = event.getX(), y = event.getY();
        if (mListener == null) return true;
        if (mBtnChangeFolder.contains(x, y)) {
            mListener.onChangeFolderRequested();
        } else if (mBtnRescan.contains(x, y)) {
            mListener.onRescanRequested();
        } else if (mBtnLaunch.contains(x, y)) {
            if (getSelectedGame() != null) mListener.onLaunchGame(getSelectedGame());
        } else if (mBtnTouch.contains(x, y)) {
            mListener.onTouchControlsToggled();
        } else if (mBtnSettings.contains(x, y)) {
            mListener.onSettingsRequested();
        } else if (mBtnPrevPage.contains(x, y)) {
            handleButton(MainActivity.DM_BTN_L);
        } else if (mBtnNextPage.contains(x, y)) {
            handleButton(MainActivity.DM_BTN_R);
        } else {
            int first = (mSelected / PAGE) * PAGE;
            for (int slot = 0; slot < mCardBounds.size(); slot++) {
                int i = first + slot;
                if (i < mGames.size() && mCardBounds.get(slot).contains(x, y)) {
                    if (i == mSelected) {
                        mListener.onLaunchGame(mGames.get(i));   // a second tap on the selected card launches it
                    } else {
                        mSelected = i;
                        invalidate();
                    }
                    break;
                }
            }
        }
        return true;
    }

    // ---- Drawing helpers ----

    private float dp(float v) {
        return v * getResources().getDisplayMetrics().density;
    }

    private void fill(Canvas canvas, float l, float t, float r, float b, float radius, int color) {
        mRectF.set(l, t, r, b);
        fill(canvas, mRectF, radius, color);
    }

    private void fill(Canvas canvas, RectF rect, float radius, int color) {
        mPaint.setStyle(Paint.Style.FILL);
        mPaint.setColor(color);
        if (radius > 0) canvas.drawRoundRect(rect, radius, radius, mPaint);
        else canvas.drawRect(rect, mPaint);
    }

    private void stroke(Canvas canvas, RectF rect, float radius, int color, float width) {
        mPaint.setStyle(Paint.Style.STROKE);
        mPaint.setStrokeWidth(width);
        mPaint.setColor(color);
        canvas.drawRoundRect(rect, radius, radius, mPaint);
        mPaint.setStyle(Paint.Style.FILL);
    }

    private void text(Canvas canvas, String s, float x, float y, float size, int color, boolean bold) {
        if (s == null) return;
        mPaint.setStyle(Paint.Style.FILL);
        mPaint.setTextSize(size);
        mPaint.setColor(color);
        mPaint.setTypeface(bold ? Typeface.DEFAULT_BOLD : Typeface.DEFAULT);
        canvas.drawText(s, x, y, mPaint);
    }

    /** Draws s ending at right; returns its left edge. */
    private float rightText(Canvas canvas, String s, float right, float y, float size, int color) {
        if (s == null || s.isEmpty()) return right;
        mPaint.setTextSize(size);
        mPaint.setTypeface(Typeface.DEFAULT);
        float left = right - mPaint.measureText(s);
        text(canvas, s, left, y, size, color, false);
        return left;
    }

    private void centered(Canvas canvas, String s, RectF r, float size, int color, boolean bold) {
        mPaint.setTextSize(size);
        mPaint.setTypeface(bold ? Typeface.DEFAULT_BOLD : Typeface.DEFAULT);
        String t = fit(s, r.width() - 16);
        float x = r.centerX() - mPaint.measureText(t) / 2;
        text(canvas, t, x, r.centerY() + size * 0.35f, size, color, bold);
    }

    private void button(Canvas canvas, RectF r, String label, float size, int fillColor, int border, int textColor) {
        fill(canvas, r, 8, fillColor);
        stroke(canvas, r, 8, border, 1.2f);
        centered(canvas, label, r, size, textColor, false);
    }

    private void bitmap(Canvas canvas, Bitmap b, RectF dst) {
        mSrc.set(0, 0, b.getWidth(), b.getHeight());
        canvas.drawBitmap(b, mSrc, dst, mPaint);
    }

    /** s cut with an ellipsis to fit width at the paint's current text size and typeface. */
    private String fit(String s, float width) {
        if (s == null) return "";
        if (width <= 0) return "";
        if (mPaint.measureText(s) <= width) return s;
        int n = mPaint.breakText(s, true, width - mPaint.measureText("…"), null);
        return n <= 0 ? "" : s.substring(0, n) + "…";
    }
}
