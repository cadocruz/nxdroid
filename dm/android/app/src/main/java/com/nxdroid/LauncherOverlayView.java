package com.nxdroid;

import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.LinearGradient;
import android.graphics.Paint;
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
 * Ultra-widescreen fluid console launcher overlay implementing the Argon UI specification.
 * Dynamically queries hardware (Model, SoC, Refresh Rate), system telemetries
 * (Battery, Temperature, Connected Gamepads, Clock), and library state in real time.
 */
public class LauncherOverlayView extends View {

    public interface LauncherEventListener {
        void onChangeFolderRequested();
        void onRescanRequested();
        void onLaunchGame(GameInfo game);
        void onSettingsRequested();
        void onTouchOverlayToggled();
    }

    // Color tokens matching Argon specification
    private static final int COLOR_BG = Color.rgb(10, 13, 20);
    private static final int COLOR_SURFACE_0 = Color.rgb(14, 18, 27);
    private static final int COLOR_SURFACE_1 = Color.rgb(19, 25, 38);
    private static final int COLOR_SURFACE_CARD = Color.rgb(18, 24, 36);
    private static final int COLOR_CYAN = Color.rgb(0, 229, 255);
    private static final int COLOR_CRIMSON = Color.rgb(255, 51, 102);
    private static final int COLOR_GREEN = Color.rgb(16, 185, 129);
    private static final int COLOR_BORDER = Color.rgb(35, 46, 68);
    private static final int COLOR_TEXT_PRIMARY = Color.rgb(248, 250, 252);
    private static final int COLOR_TEXT_SECONDARY = Color.rgb(160, 175, 200);
    private static final int COLOR_TEXT_MUTED = Color.rgb(100, 116, 139);

    private LauncherEventListener mListener;
    private String mCurrentDirectory = "/storage/emulated/0/Games/Switch/";
    private final List<GameInfo> mGames = new ArrayList<>();
    private int mSelectedGameIndex = 0;

    // Dynamic telemetry caches
    private String mDeviceModel = "Galaxy S23 Ultra";
    private String mSocInfo = "Snapdragon 8 Gen 2 · Adreno 740";
    private String mRefreshRateStr = "120 Hz";
    private String mLiveTime = "12:00";
    private String mLiveBattery = "100%";
    private String mLiveTemp = "32°C";
    private String mLiveGamepad = "🎮 Touch";
    private long mLastMetricsCheck = 0;

    private final Paint mPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final RectF mRectF = new RectF();

    // Dynamic Touch hitboxes
    private final RectF mBtnChangeFolder = new RectF();
    private final RectF mBtnRescan = new RectF();
    private final RectF mBtnLaunch = new RectF();
    private final RectF mBtnTouchOverlay = new RectF();
    private final RectF mBtnSettings = new RectF();
    private final List<RectF> mGameCardBounds = new ArrayList<>();

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
        setClickable(true);

        detectHardwareInfo();
        refreshSystemMetrics();

        // Initial default sample library if empty
        mGames.add(new GameInfo("Super Mario Odyssey", "010015100B514000",
                mCurrentDirectory + "Mario", "5.7 GB", "NVN", 60, true, 2841));
        mGames.add(new GameInfo("Zelda: Tears of the Kingdom", "0100F2C0115B6000",
                mCurrentDirectory + "ZeldaTotK", "16.3 GB", "NVN", 60, true, 3120));
        mGames.add(new GameInfo("Metroid Dread", "010093801237C000",
                mCurrentDirectory + "MetroidDread", "4.2 GB", "NVN", 60, true, 1940));
        mGames.add(new GameInfo("Balatro", "0100CD801CE5E000",
                mCurrentDirectory + "Balatro", "320 MB", "OpenGL", 60, true, 420));
    }

    private void detectHardwareInfo() {
        String model = Build.MODEL;
        if ("SM-S918B".equalsIgnoreCase(model) || "SM-S918U".equalsIgnoreCase(model) || "SM-S9180".equalsIgnoreCase(model)) {
            mDeviceModel = "Galaxy S23 Ultra (" + model + ")";
            mSocInfo = "Snapdragon 8 Gen 2 · Adreno 740";
        } else {
            mDeviceModel = (Build.MANUFACTURER != null ? Build.MANUFACTURER.toUpperCase(Locale.ROOT) + " " : "") + model;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S && Build.SOC_MODEL != null && !Build.SOC_MODEL.isEmpty()) {
                mSocInfo = Build.SOC_MODEL;
            } else if (Build.HARDWARE != null && !Build.HARDWARE.isEmpty()) {
                mSocInfo = Build.HARDWARE;
            }
        }

        // Query real screen refresh rate
        WindowManager wm = (WindowManager) getContext().getSystemService(Context.WINDOW_SERVICE);
        if (wm != null) {
            Display display = wm.getDefaultDisplay();
            if (display != null) {
                float hz = display.getRefreshRate();
                mRefreshRateStr = Math.round(hz) + " Hz";
            }
        }
    }

    private void refreshSystemMetrics() {
        long now = System.currentTimeMillis();
        if (now - mLastMetricsCheck < 2000) {
            return; // Cache for 2 seconds to avoid overhead
        }
        mLastMetricsCheck = now;

        // 1. Live System Time
        SimpleDateFormat sdf = new SimpleDateFormat("HH:mm", Locale.getDefault());
        mLiveTime = sdf.format(new Date());

        // 2. Battery & Temperature from system sticky intent
        try {
            Intent batteryIntent = getContext().registerReceiver(null, new IntentFilter(Intent.ACTION_BATTERY_CHANGED));
            if (batteryIntent != null) {
                int level = batteryIntent.getIntExtra(BatteryManager.EXTRA_LEVEL, -1);
                int scale = batteryIntent.getIntExtra(BatteryManager.EXTRA_SCALE, -1);
                int status = batteryIntent.getIntExtra(BatteryManager.EXTRA_STATUS, -1);
                boolean isCharging = (status == BatteryManager.BATTERY_STATUS_CHARGING
                        || status == BatteryManager.BATTERY_STATUS_FULL);

                if (level >= 0 && scale > 0) {
                    int pct = Math.round((level / (float) scale) * 100);
                    mLiveBattery = pct + "%" + (isCharging ? " ⚡" : "");
                }

                int tempRaw = batteryIntent.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, 0);
                if (tempRaw > 0) {
                    float tempC = tempRaw / 10.0f;
                    mLiveTemp = Math.round(tempC) + "°C";
                }
            }
        } catch (Exception ignored) {
        }

        // 3. Real Physical Controller Detection (Bluetooth / USB)
        boolean hasGamepad = false;
        String padName = "Touch";
        int[] deviceIds = InputDevice.getDeviceIds();
        for (int id : deviceIds) {
            InputDevice dev = InputDevice.getDevice(id);
            if (dev != null && !dev.isVirtual()) {
                int sources = dev.getSources();
                if ((sources & InputDevice.SOURCE_GAMEPAD) == InputDevice.SOURCE_GAMEPAD
                        || (sources & InputDevice.SOURCE_JOYSTICK) == InputDevice.SOURCE_JOYSTICK) {
                    hasGamepad = true;
                    padName = dev.getName();
                    if (padName != null && padName.length() > 14) {
                        padName = padName.substring(0, 14);
                    }
                    break;
                }
            }
        }
        mLiveGamepad = hasGamepad ? ("🎮 " + padName) : "🎮 Touch";
    }

    public void setListener(LauncherEventListener listener) {
        mListener = listener;
    }

    public void setCurrentDirectory(String path) {
        if (path != null && !path.isEmpty()) {
            mCurrentDirectory = path;
            invalidate();
        }
    }

    public void setGames(List<GameInfo> games) {
        mGames.clear();
        if (games != null && !games.isEmpty()) {
            mGames.addAll(games);
        } else {
            mGames.add(new GameInfo("Select Your Game Folder", "0000000000000000",
                    mCurrentDirectory, "0.0 GB", "NVN", 60, false, 0));
        }
        mSelectedGameIndex = 0;
        invalidate();
    }

    public GameInfo getSelectedGame() {
        if (mGames.isEmpty()) return null;
        if (mSelectedGameIndex < 0 || mSelectedGameIndex >= mGames.size()) {
            mSelectedGameIndex = 0;
        }
        return mGames.get(mSelectedGameIndex);
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        float w = getWidth();
        float h = getHeight();
        if (w <= 0 || h <= 0) return;

        refreshSystemMetrics();

        // Base background fill (covers entire physical screen)
        canvas.drawColor(COLOR_BG);

        // Fluid layout dimensions based on actual screen size
        float padX = Math.max(16f, w * 0.02f);
        float topBarH = Math.max(48f, h * 0.08f);
        float folderH = Math.max(54f, h * 0.10f);
        float footerH = Math.max(38f, h * 0.06f);

        float folderY1 = topBarH + 8;
        float folderY2 = folderY1 + folderH;

        float mainY1 = folderY2 + 10;
        float mainY2 = h - footerH - 6;

        // Draw components across full width
        drawTopStatusBar(canvas, w, topBarH, padX);
        drawDirectoryBar(canvas, w, folderY1, folderY2, padX);
        drawDualPane(canvas, w, mainY1, mainY2, padX);
        drawFooter(canvas, w, h, footerH, padX);
    }

    private void drawTopStatusBar(Canvas canvas, float w, float barH, float padX) {
        mRectF.set(0, 0, w, barH);
        mPaint.setColor(COLOR_SURFACE_0);
        mPaint.setStyle(Paint.Style.FILL);
        canvas.drawRect(mRectF, mPaint);

        float midY = barH * 0.5f;

        // Joy-Con pills
        float joyX = padX;
        float pillW = barH * 0.22f;
        float pillH = barH * 0.55f;
        float pillR = pillW * 0.5f;

        mPaint.setColor(COLOR_CYAN);
        mRectF.set(joyX, midY - pillH * 0.5f, joyX + pillW, midY + pillH * 0.5f);
        canvas.drawRoundRect(mRectF, pillR, pillR, mPaint);

        mPaint.setColor(COLOR_CRIMSON);
        mRectF.set(joyX + pillW + 4, midY - pillH * 0.5f, joyX + 2 * pillW + 4, midY + pillH * 0.5f);
        canvas.drawRoundRect(mRectF, pillR, pillR, mPaint);

        // Title: nxdroid
        float titleX = joyX + 2 * pillW + 14;
        mPaint.setColor(COLOR_TEXT_PRIMARY);
        mPaint.setTextSize(barH * 0.42f);
        mPaint.setTypeface(Typeface.create(Typeface.DEFAULT, Typeface.BOLD));
        canvas.drawText("nxdroid", titleX, midY + barH * 0.15f, mPaint);

        // Badge: VULKAN AARCH64
        float textW = mPaint.measureText("nxdroid");
        float badgeX = titleX + textW + 12;
        float badgeW = barH * 2.3f;
        float badgeH = barH * 0.45f;
        mRectF.set(badgeX, midY - badgeH * 0.5f, badgeX + badgeW, midY + badgeH * 0.5f);
        mPaint.setColor(COLOR_SURFACE_1);
        canvas.drawRoundRect(mRectF, 8, 8, mPaint);
        mPaint.setColor(COLOR_CYAN);
        mPaint.setTextSize(barH * 0.24f);
        canvas.drawText("VULKAN AARCH64", badgeX + 10, midY + barH * 0.08f, mPaint);

        // Right Utility chips (anchored to w - padX)
        float rx = w - padX;
        mPaint.setTypeface(Typeface.create(Typeface.DEFAULT, Typeface.NORMAL));
        mPaint.setTextSize(barH * 0.28f);

        // Dynamic System Clock
        mPaint.setColor(COLOR_TEXT_PRIMARY);
        canvas.drawText(mLiveTime, rx - 45, midY + barH * 0.1f, mPaint);
        rx -= 100;

        // Dynamic System Battery
        mPaint.setColor(COLOR_TEXT_PRIMARY);
        canvas.drawText(mLiveBattery, rx - 55, midY + barH * 0.1f, mPaint);
        rx -= 90;

        // Dynamic Device Temperature
        mPaint.setColor(COLOR_GREEN);
        canvas.drawText(mLiveTemp, rx - 40, midY + barH * 0.1f, mPaint);
        rx -= 75;

        // Dynamic Gamepad Connection
        mPaint.setColor(COLOR_TEXT_SECONDARY);
        canvas.drawText(mLiveGamepad, rx - 65, midY + barH * 0.1f, mPaint);
        rx -= 80;

        // Center Diagnostic Chip (Dynamic Model, SoC, Refresh Rate)
        float chipX1 = Math.max(badgeX + badgeW + 16, w * 0.26f);
        float chipX2 = Math.min(rx - 16, w * 0.72f);
        if (chipX2 > chipX1 + 100) {
            float chipH = barH * 0.60f;
            mRectF.set(chipX1, midY - chipH * 0.5f, chipX2, midY + chipH * 0.5f);
            mPaint.setColor(COLOR_SURFACE_1);
            canvas.drawRoundRect(mRectF, chipH * 0.5f, chipH * 0.5f, mPaint);
            mPaint.setStyle(Paint.Style.STROKE);
            mPaint.setStrokeWidth(1.2f);
            mPaint.setColor(COLOR_BORDER);
            canvas.drawRoundRect(mRectF, chipH * 0.5f, chipH * 0.5f, mPaint);
            mPaint.setStyle(Paint.Style.FILL);

            mPaint.setColor(COLOR_GREEN);
            canvas.drawCircle(chipX1 + 16, midY, 4, mPaint);

            mPaint.setColor(COLOR_TEXT_PRIMARY);
            mPaint.setTextSize(barH * 0.25f);
            String diag = mDeviceModel + " · " + mSocInfo + " · Vulkan 1.3 · " + mRefreshRateStr;
            canvas.drawText(diag, chipX1 + 28, midY + barH * 0.09f, mPaint);
        }

        // Separator line
        mPaint.setColor(COLOR_BORDER);
        mPaint.setStrokeWidth(1);
        canvas.drawLine(0, barH, w, barH, mPaint);
    }

    private void drawDirectoryBar(Canvas canvas, float w, float y1, float y2, float padX) {
        float h = y2 - y1;

        mRectF.set(padX, y1, w - padX, y2);
        mPaint.setColor(COLOR_SURFACE_1);
        mPaint.setStyle(Paint.Style.FILL);
        canvas.drawRoundRect(mRectF, 10, 10, mPaint);

        mPaint.setStyle(Paint.Style.STROKE);
        mPaint.setColor(COLOR_BORDER);
        mPaint.setStrokeWidth(1.2f);
        canvas.drawRoundRect(mRectF, 10, 10, mPaint);
        mPaint.setStyle(Paint.Style.FILL);

        // Neon Cyan Left accent bar
        mRectF.set(padX, y1, padX + 6, y2);
        mPaint.setColor(COLOR_CYAN);
        canvas.drawRoundRect(mRectF, 3, 3, mPaint);

        // Right buttons anchored to w - padX
        float btnH = h * 0.65f;
        float btnY1 = y1 + (h - btnH) * 0.5f;
        float btnY2 = btnY1 + btnH;

        float rescanW = Math.max(90f, w * 0.08f);
        mBtnRescan.set(w - padX - rescanW - 10, btnY1, w - padX - 10, btnY2);
        mPaint.setColor(COLOR_SURFACE_CARD);
        canvas.drawRoundRect(mBtnRescan, 8, 8, mPaint);
        mPaint.setStyle(Paint.Style.STROKE);
        mPaint.setColor(COLOR_BORDER);
        mPaint.setStrokeWidth(1.2f);
        canvas.drawRoundRect(mBtnRescan, 8, 8, mPaint);
        mPaint.setStyle(Paint.Style.FILL);
        mPaint.setColor(COLOR_TEXT_PRIMARY);
        mPaint.setTextSize(btnH * 0.40f);
        mPaint.setTypeface(Typeface.create(Typeface.DEFAULT, Typeface.NORMAL));
        canvas.drawText("🔄 Rescan", mBtnRescan.left + 12, btnY1 + btnH * 0.62f, mPaint);

        float changeW = Math.max(130f, w * 0.12f);
        mBtnChangeFolder.set(mBtnRescan.left - changeW - 10, btnY1, mBtnRescan.left - 10, btnY2);
        mPaint.setColor(COLOR_SURFACE_CARD);
        canvas.drawRoundRect(mBtnChangeFolder, 8, 8, mPaint);
        mPaint.setStyle(Paint.Style.STROKE);
        mPaint.setColor(COLOR_CYAN);
        mPaint.setStrokeWidth(1.2f);
        canvas.drawRoundRect(mBtnChangeFolder, 8, 8, mPaint);
        mPaint.setStyle(Paint.Style.FILL);
        mPaint.setColor(COLOR_CYAN);
        mPaint.setTextSize(btnH * 0.40f);
        mPaint.setTypeface(Typeface.create(Typeface.DEFAULT, Typeface.BOLD));
        canvas.drawText("📁 Change Folder", mBtnChangeFolder.left + 12, btnY1 + btnH * 0.62f, mPaint);

        // Path and Labels
        float textX = padX + 18;
        mPaint.setColor(COLOR_CYAN);
        mPaint.setTextSize(h * 0.18f);
        mPaint.setTypeface(Typeface.create(Typeface.DEFAULT, Typeface.BOLD));
        canvas.drawText("GAME DIRECTORY (SAF  ·  PERSISTENT ACCESS)", textX, y1 + h * 0.30f, mPaint);

        mPaint.setColor(COLOR_TEXT_PRIMARY);
        mPaint.setTextSize(h * 0.30f);
        mPaint.setTypeface(Typeface.MONOSPACE);
        canvas.drawText(mCurrentDirectory, textX, y1 + h * 0.64f, mPaint);

        mPaint.setColor(COLOR_TEXT_MUTED);
        mPaint.setTextSize(h * 0.17f);
        mPaint.setTypeface(Typeface.DEFAULT);
        canvas.drawText("Accessible without root  ·  Data preserved on app uninstall  ·  "
                + mGames.size() + " Switch titles discovered", textX, y1 + h * 0.88f, mPaint);
    }

    private void drawDualPane(Canvas canvas, float w, float y1, float y2, float padX) {
        float availableW = w - 2 * padX;
        float heroW = Math.max(340f, availableW * 0.38f);
        float gridW = availableW - heroW - 14;

        float heroX1 = padX;
        float heroX2 = heroX1 + heroW;
        float gridX1 = heroX2 + 14;
        float gridX2 = w - padX;

        GameInfo selected = getSelectedGame();

        // 1. Left Hero Pane
        mRectF.set(heroX1, y1, heroX2, y2);
        mPaint.setColor(COLOR_SURFACE_1);
        canvas.drawRoundRect(mRectF, 12, 12, mPaint);
        mPaint.setStyle(Paint.Style.STROKE);
        mPaint.setColor(COLOR_BORDER);
        mPaint.setStrokeWidth(1.2f);
        canvas.drawRoundRect(mRectF, 12, 12, mPaint);
        mPaint.setStyle(Paint.Style.FILL);

        // Hero Art Banner
        float paneH = y2 - y1;
        float artH = paneH * 0.28f;
        mRectF.set(heroX1, y1, heroX2, y1 + artH);
        Shader heroShader = new LinearGradient(heroX1, y1, heroX2, y1 + artH,
                Color.rgb(180, 30, 60), Color.rgb(20, 24, 38), Shader.TileMode.CLAMP);
        mPaint.setShader(heroShader);
        canvas.drawRoundRect(mRectF, 12, 12, mPaint);
        mPaint.setShader(null);

        // Hero Title & Details
        float cx = heroX1 + 18;
        float curY = y1 + artH + paneH * 0.08f;
        mPaint.setColor(COLOR_TEXT_PRIMARY);
        mPaint.setTextSize(paneH * 0.06f);
        mPaint.setTypeface(Typeface.create(Typeface.DEFAULT, Typeface.BOLD));
        String heroTitle = selected != null ? selected.title : "No Game Selected";
        canvas.drawText(heroTitle, cx, curY, mPaint);

        curY += paneH * 0.045f;
        mPaint.setColor(COLOR_TEXT_SECONDARY);
        mPaint.setTextSize(paneH * 0.035f);
        mPaint.setTypeface(Typeface.DEFAULT);
        canvas.drawText("Nintendo Switch  ·  AArch64 Native Replay", cx, curY, mPaint);

        // 2x2 Tech Specs Grid in Hero
        float specCol2 = heroX1 + heroW * 0.52f;
        float row1Y = curY + paneH * 0.06f;
        drawHeroSpec(canvas, cx, row1Y, "TITLE ID", selected != null ? selected.titleId : "-", paneH);
        drawHeroSpec(canvas, specCol2, row1Y, "PACKAGE SIZE", selected != null ? selected.sizeStr : "-", paneH);

        float row2Y = row1Y + paneH * 0.10f;
        drawHeroSpec(canvas, cx, row2Y, "GRAPHICS API", selected != null ? (selected.apiType + " → Vulkan 1.3") : "-", paneH);
        drawHeroSpec(canvas, specCol2, row2Y, "PIPELINE CACHE", selected != null ? (selected.prewarmedShaders + " Shaders") : "-", paneH);

        // Giant Action Button: [ ▶ LAUNCH GAME ]
        float btnLaunchH = paneH * 0.13f;
        float btnLaunchY = y2 - paneH * 0.26f;
        mBtnLaunch.set(cx, btnLaunchY, heroX2 - 18, btnLaunchY + btnLaunchH);
        Shader btnShader = new LinearGradient(mBtnLaunch.left, mBtnLaunch.top, mBtnLaunch.right, mBtnLaunch.bottom,
                COLOR_CYAN, Color.rgb(0, 140, 255), Shader.TileMode.CLAMP);
        mPaint.setShader(btnShader);
        canvas.drawRoundRect(mBtnLaunch, 10, 10, mPaint);
        mPaint.setShader(null);

        mPaint.setColor(COLOR_BG);
        mPaint.setTextSize(btnLaunchH * 0.38f);
        mPaint.setTypeface(Typeface.create(Typeface.DEFAULT, Typeface.BOLD));
        canvas.drawText("▶  LAUNCH GAME", mBtnLaunch.centerX() - 70, mBtnLaunch.centerY() + btnLaunchH * 0.12f, mPaint);

        // Sub-buttons: Touch Overlay & Settings
        float subBtnY = mBtnLaunch.bottom + paneH * 0.025f;
        float subBtnH = paneH * 0.08f;
        float halfW = (mBtnLaunch.width() - 10) * 0.5f;

        mBtnTouchOverlay.set(cx, subBtnY, cx + halfW, subBtnY + subBtnH);
        mPaint.setColor(COLOR_SURFACE_CARD);
        canvas.drawRoundRect(mBtnTouchOverlay, 8, 8, mPaint);
        mPaint.setColor(COLOR_TEXT_PRIMARY);
        mPaint.setTextSize(subBtnH * 0.42f);
        canvas.drawText("🎮 Controls", mBtnTouchOverlay.left + 16, mBtnTouchOverlay.centerY() + subBtnH * 0.12f, mPaint);

        mBtnSettings.set(cx + halfW + 10, subBtnY, heroX2 - 18, subBtnY + subBtnH);
        mPaint.setColor(COLOR_SURFACE_CARD);
        canvas.drawRoundRect(mBtnSettings, 8, 8, mPaint);
        mPaint.setColor(COLOR_TEXT_PRIMARY);
        canvas.drawText("⚙ Config", mBtnSettings.left + 20, mBtnSettings.centerY() + subBtnH * 0.12f, mPaint);

        // 2. Right Library Grid
        drawLibraryGrid(canvas, gridX1, gridX2, y1, y2);
    }

    private void drawHeroSpec(Canvas canvas, float x, float y, String label, String val, float paneH) {
        mPaint.setColor(COLOR_TEXT_MUTED);
        mPaint.setTextSize(paneH * 0.028f);
        mPaint.setTypeface(Typeface.create(Typeface.DEFAULT, Typeface.BOLD));
        canvas.drawText(label, x, y, mPaint);

        mPaint.setColor(COLOR_TEXT_PRIMARY);
        mPaint.setTextSize(paneH * 0.038f);
        mPaint.setTypeface(Typeface.DEFAULT);
        canvas.drawText(val, x, y + paneH * 0.045f, mPaint);
    }

    private void drawLibraryGrid(Canvas canvas, float left, float right, float top, float bottom) {
        mGameCardBounds.clear();
        float gridW = right - left;
        float gridH = bottom - top;

        float gap = 12;
        float colW = (gridW - gap) * 0.5f;
        float rowH = (gridH - gap) * 0.5f;

        for (int i = 0; i < 4; i++) {
            float cx = left + (i % 2) * (colW + gap);
            float cy = top + (i / 2) * (rowH + gap);

            RectF card = new RectF(cx, cy, cx + colW, cy + rowH);
            mGameCardBounds.add(card);

            boolean isSelected = (i == mSelectedGameIndex);

            mPaint.setColor(COLOR_SURFACE_CARD);
            canvas.drawRoundRect(card, 10, 10, mPaint);

            // Focused card gets Cyan glow outline
            mPaint.setStyle(Paint.Style.STROKE);
            mPaint.setColor(isSelected ? COLOR_CYAN : COLOR_BORDER);
            mPaint.setStrokeWidth(isSelected ? 2.5f : 1.2f);
            canvas.drawRoundRect(card, 10, 10, mPaint);
            mPaint.setStyle(Paint.Style.FILL);

            if (i < mGames.size()) {
                GameInfo game = mGames.get(i);

                // Card Art Area
                float cardArtH = rowH * 0.48f;
                mRectF.set(cx + 8, cy + 8, cx + colW - 8, cy + cardArtH);
                int c1 = (i == 0) ? Color.rgb(160, 40, 50) : (i == 1) ? Color.rgb(30, 100, 140) : Color.rgb(60, 40, 80);
                Shader artShader = new LinearGradient(cx, cy, cx + colW, cy + cardArtH,
                        c1, Color.rgb(20, 24, 34), Shader.TileMode.CLAMP);
                mPaint.setShader(artShader);
                canvas.drawRoundRect(mRectF, 8, 8, mPaint);
                mPaint.setShader(null);

                // API tag
                mRectF.set(cx + 16, cy + 16, cx + 70, cy + 38);
                mPaint.setColor(COLOR_SURFACE_0);
                canvas.drawRoundRect(mRectF, 4, 4, mPaint);
                mPaint.setColor(COLOR_CYAN);
                mPaint.setTextSize(11);
                mPaint.setTypeface(Typeface.create(Typeface.DEFAULT, Typeface.BOLD));
                canvas.drawText(game.apiType, cx + 24, cy + 32, mPaint);

                // Game Title
                mPaint.setColor(COLOR_TEXT_PRIMARY);
                mPaint.setTextSize(rowH * 0.085f);
                mPaint.setTypeface(Typeface.create(Typeface.DEFAULT, Typeface.BOLD));
                canvas.drawText(game.title, cx + 12, cy + cardArtH + rowH * 0.12f, mPaint);

                // ID & Size
                mPaint.setColor(COLOR_TEXT_SECONDARY);
                mPaint.setTextSize(rowH * 0.065f);
                mPaint.setTypeface(Typeface.DEFAULT);
                canvas.drawText(game.titleId + "  ·  " + game.sizeStr, cx + 12, cy + cardArtH + rowH * 0.24f, mPaint);

                // Status
                mPaint.setColor(COLOR_GREEN);
                canvas.drawCircle(cx + 18, cy + rowH - rowH * 0.14f, 3, mPaint);
                canvas.drawText("● Playable · " + game.targetFps + " FPS", cx + 28, cy + rowH - rowH * 0.10f, mPaint);

                // Select Button
                float selW = colW * 0.28f;
                float selH = rowH * 0.16f;
                RectF selectBtn = new RectF(cx + colW - selW - 10, cy + rowH - selH - 10, cx + colW - 10, cy + rowH - 10);
                mPaint.setColor(isSelected ? COLOR_CYAN : COLOR_SURFACE_1);
                canvas.drawRoundRect(selectBtn, 6, 6, mPaint);
                mPaint.setColor(isSelected ? COLOR_BG : COLOR_TEXT_PRIMARY);
                mPaint.setTextSize(selH * 0.45f);
                mPaint.setTypeface(Typeface.create(Typeface.DEFAULT, Typeface.BOLD));
                canvas.drawText(isSelected ? "SELECTED" : "SELECT", selectBtn.centerX() - 25, selectBtn.centerY() + selH * 0.15f, mPaint);
            }
        }
    }

    private void drawFooter(Canvas canvas, float w, float h, float footerH, float padX) {
        float y = h - footerH;

        mRectF.set(0, y, w, h);
        mPaint.setColor(COLOR_SURFACE_0);
        canvas.drawRect(mRectF, mPaint);

        mPaint.setColor(COLOR_BORDER);
        mPaint.setStrokeWidth(1);
        canvas.drawLine(0, y, w, y, mPaint);

        float textY = y + footerH * 0.62f;

        // Gamepad shortcuts anchored to padX
        mPaint.setColor(COLOR_TEXT_SECONDARY);
        mPaint.setTextSize(footerH * 0.38f);
        mPaint.setTypeface(Typeface.create(Typeface.DEFAULT, Typeface.NORMAL));
        canvas.drawText("(A) Launch Game   (X) Game Config   (Y) Scan Folder   (+) Global Settings", padX, textY, mPaint);

        // Version stamp anchored to w - padX
        mPaint.setColor(COLOR_TEXT_MUTED);
        String stamp = "nxdroid v0.1.0-alpha  ·  AArch64 Host Runtime";
        float stampW = mPaint.measureText(stamp);
        canvas.drawText(stamp, w - padX - stampW, textY, mPaint);
    }

    @Override
    public boolean onTouchEvent(MotionEvent event) {
        if (event.getAction() == MotionEvent.ACTION_UP) {
            float tx = event.getX();
            float ty = event.getY();

            if (mBtnChangeFolder.contains(tx, ty)) {
                if (mListener != null) mListener.onChangeFolderRequested();
                return true;
            } else if (mBtnRescan.contains(tx, ty)) {
                if (mListener != null) mListener.onRescanRequested();
                return true;
            } else if (mBtnLaunch.contains(tx, ty)) {
                if (mListener != null) mListener.onLaunchGame(getSelectedGame());
                return true;
            } else if (mBtnTouchOverlay.contains(tx, ty)) {
                if (mListener != null) mListener.onTouchOverlayToggled();
                return true;
            } else if (mBtnSettings.contains(tx, ty)) {
                if (mListener != null) mListener.onSettingsRequested();
                return true;
            }

            // Game card selection
            for (int i = 0; i < mGameCardBounds.size(); i++) {
                if (mGameCardBounds.get(i).contains(tx, ty) && i < mGames.size()) {
                    mSelectedGameIndex = i;
                    invalidate();
                    return true;
                }
            }
        }
        return true;
    }
}
