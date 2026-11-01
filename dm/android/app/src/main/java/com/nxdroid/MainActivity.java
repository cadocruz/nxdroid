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
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import java.io.File;
import java.util.Locale;

/**
 * Main application Activity handling display setup, immersive fullscreen,
 * modern Welcome/Launcher UI, folder selection, gamepad/controller routing,
 * and host lifecycle.
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
    private static final int REQUEST_SELECT_FOLDER = 1001;
    private static final String PREF_NAME = "nxdroid_prefs";
    private static final String PREF_GAME_DIR = "game_dir";

    private FrameLayout mRootContainer;
    private GameSurfaceView mSurfaceView;
    private VirtualControllerOverlayView mVirtualController;
    private ScrollView mLauncherOverlay;
    private TextView mPathTextView;
    private TextView mStatusTextView;
    private Button mLaunchButton;
    private Button mPermButton;

    private String mGameDir;
    private float mDisplayHz = 60.0f;

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

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
            setShowWhenLocked(true);
            setTurnScreenOn(true);
        } else {
            getWindow().addFlags(WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED
                    | WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON);
        }

        applyImmersiveMode();
        configureRefreshRate();

        loadInitialGameDir();
        buildUiHierarchy();

        Intent intent = getIntent();
        if (intent != null && intent.hasExtra("gameDir")) {
            mGameDir = intent.getStringExtra("gameDir");
            saveGameDir(mGameDir);
            updateStatusDisplay();
            if (intent.getBooleanExtra("autoStart", false)) {
                startGameSession();
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

        mDisplayHz = maxHz;
        NativeBridge.nativeSetRefreshRate(maxHz);
    }

    private void loadInitialGameDir() {
        SharedPreferences prefs = getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE);
        String saved = prefs.getString(PREF_GAME_DIR, null);
        if (saved != null && !saved.trim().isEmpty()) {
            mGameDir = saved;
        } else {
            File ext = Environment.getExternalStorageDirectory();
            File defaultDir = new File(ext, "nxdroid/game");
            mGameDir = defaultDir.getAbsolutePath();
        }
    }

    private void saveGameDir(String path) {
        SharedPreferences prefs = getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE);
        prefs.edit().putString(PREF_GAME_DIR, path).apply();
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
        FrameLayout.LayoutParams surfaceParams = new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT);
        mRootContainer.addView(mSurfaceView, surfaceParams);

        // 1b. Virtual Controller Overlay
        mVirtualController = new VirtualControllerOverlayView(this);
        FrameLayout.LayoutParams controllerParams = new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT);
        mVirtualController.setVisibility(View.GONE);
        mVirtualController.setOnPadStateChangeListener(new VirtualControllerOverlayView.OnPadStateChangeListener() {
            @Override
            public void onPadStateChanged(long buttons, int lx, int ly, int rx, int ry) {
                mButtons = buttons;
                mLx = lx;
                mLy = ly;
                mRx = rx;
                mRy = ry;
                NativeBridge.nativeSendPad(0, mButtons, mLx, mLy, mRx, mRy);
                NativeBridge.nativeSendInput(mButtons, mLx, mLy, mRx, mRy);
            }
        });
        mRootContainer.addView(mVirtualController, controllerParams);

        // 2. Launcher Overlay
        mLauncherOverlay = new ScrollView(this);
        mLauncherOverlay.setBackgroundColor(0xF0101216);
        mLauncherOverlay.setFillViewport(true);

        LinearLayout contentLayout = new LinearLayout(this);
        contentLayout.setOrientation(LinearLayout.VERTICAL);
        contentLayout.setPadding(dp(28), dp(20), dp(28), dp(28));

        // --- Header Section ---
        LinearLayout header = new LinearLayout(this);
        header.setOrientation(LinearLayout.VERTICAL);

        TextView titleView = new TextView(this);
        titleView.setText("nxdroid");
        titleView.setTextSize(30);
        titleView.setTextColor(0xFF00E5FF);
        titleView.setTypeface(Typeface.DEFAULT_BOLD);
        header.addView(titleView);

        TextView subtitleView = new TextView(this);
        subtitleView.setText("Native AArch64 Switch Runner · Vulkan 1.3");
        subtitleView.setTextSize(13);
        subtitleView.setTextColor(0xFFA0AAB8);
        subtitleView.setPadding(0, dp(2), 0, dp(10));
        header.addView(subtitleView);

        // Badges row
        LinearLayout badgeRow = new LinearLayout(this);
        badgeRow.setOrientation(LinearLayout.HORIZONTAL);

        TextView chipHw = new TextView(this);
        chipHw.setText("Snapdragon 8 Gen 2 · Adreno 740");
        chipHw.setTextSize(11);
        chipHw.setTextColor(0xFF00E5FF);
        chipHw.setPadding(dp(10), dp(4), dp(10), dp(4));
        chipHw.setBackground(createRoundedDrawable(0xFF192330, 0xFF00E5FF, 12, density));
        badgeRow.addView(chipHw);

        View spacer = new View(this);
        badgeRow.addView(spacer, new LinearLayout.LayoutParams(dp(8), 1));

        TextView chipHz = new TextView(this);
        chipHz.setText(String.format(Locale.US, "Display: %.0f Hz", mDisplayHz));
        chipHz.setTextSize(11);
        chipHz.setTextColor(0xFF76FF03);
        chipHz.setPadding(dp(10), dp(4), dp(10), dp(4));
        chipHz.setBackground(createRoundedDrawable(0xFF1E2A1E, 0xFF76FF03, 12, density));
        badgeRow.addView(chipHz);

        header.addView(badgeRow);
        contentLayout.addView(header);

        // --- Storage Permission Banner (Android 11+) ---
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R && !Environment.isExternalStorageManager()) {
            mPermButton = new Button(this);
            mPermButton.setText("⚠️ Conceder Acesso Total ao Armazenamento (Android 11+)");
            mPermButton.setTextSize(12);
            mPermButton.setTextColor(0xFFFFD600);
            mPermButton.setBackground(createRoundedDrawable(0xFF2E2412, 0xFFFFD600, 8, density));
            LinearLayout.LayoutParams permParams = new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
            permParams.setMargins(0, dp(14), 0, 0);
            mPermButton.setLayoutParams(permParams);
            mPermButton.setOnClickListener(new View.OnClickListener() {
                @Override
                public void onClick(View v) {
                    try {
                        Intent intent = new Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION);
                        intent.setData(Uri.parse("package:" + getPackageName()));
                        startActivity(intent);
                    } catch (Exception e) {
                        Intent intent = new Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION);
                        startActivity(intent);
                    }
                }
            });
            contentLayout.addView(mPermButton);
        }

        // --- Game Folder Card ---
        LinearLayout folderCard = new LinearLayout(this);
        folderCard.setOrientation(LinearLayout.VERTICAL);
        folderCard.setBackground(createRoundedDrawable(0xFF181B22, 0xFF282E3C, 10, density));
        folderCard.setPadding(dp(16), dp(14), dp(16), dp(14));
        LinearLayout.LayoutParams cardParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        cardParams.setMargins(0, dp(14), 0, 0);
        folderCard.setLayoutParams(cardParams);

        TextView cardTitle = new TextView(this);
        cardTitle.setText("📁 Pasta do Jogo / Game Directory");
        cardTitle.setTextSize(14);
        cardTitle.setTextColor(Color.WHITE);
        cardTitle.setTypeface(Typeface.DEFAULT_BOLD);
        folderCard.addView(cardTitle);

        mPathTextView = new TextView(this);
        mPathTextView.setText(mGameDir);
        mPathTextView.setTextSize(12);
        mPathTextView.setTextColor(0xFFE4E9F2);
        mPathTextView.setTypeface(Typeface.MONOSPACE);
        mPathTextView.setBackground(createRoundedDrawable(0xFF101217, 0xFF202530, 6, density));
        mPathTextView.setPadding(dp(10), dp(8), dp(10), dp(8));
        LinearLayout.LayoutParams pathParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        pathParams.setMargins(0, dp(8), 0, dp(8));
        mPathTextView.setLayoutParams(pathParams);
        folderCard.addView(mPathTextView);

        mStatusTextView = new TextView(this);
        mStatusTextView.setTextSize(12);
        folderCard.addView(mStatusTextView);

        // Buttons row
        LinearLayout btnRow = new LinearLayout(this);
        btnRow.setOrientation(LinearLayout.HORIZONTAL);
        LinearLayout.LayoutParams btnRowParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        btnRowParams.setMargins(0, dp(10), 0, 0);
        btnRow.setLayoutParams(btnRowParams);

        Button selectBtn = new Button(this);
        selectBtn.setText("Selecionar Pasta");
        selectBtn.setTextSize(12);
        selectBtn.setTextColor(Color.WHITE);
        selectBtn.setBackground(createRoundedDrawable(0xFF0D47A1, 0xFF1976D2, 8, density));
        LinearLayout.LayoutParams selParams = new LinearLayout.LayoutParams(0, dp(40), 1.0f);
        selParams.setMargins(0, 0, dp(6), 0);
        selectBtn.setLayoutParams(selParams);
        selectBtn.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                launchFolderPicker();
            }
        });
        btnRow.addView(selectBtn);

        Button manualBtn = new Button(this);
        manualBtn.setText("Digitar Path");
        manualBtn.setTextSize(12);
        manualBtn.setTextColor(Color.WHITE);
        manualBtn.setBackground(createRoundedDrawable(0xFF263238, 0xFF455A64, 8, density));
        LinearLayout.LayoutParams manParams = new LinearLayout.LayoutParams(0, dp(40), 1.0f);
        manParams.setMargins(dp(6), 0, dp(6), 0);
        manualBtn.setLayoutParams(manParams);
        manualBtn.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                showEditPathDialog();
            }
        });
        btnRow.addView(manualBtn);

        Button defaultBtn = new Button(this);
        defaultBtn.setText("Reset (/sdcard)");
        defaultBtn.setTextSize(12);
        defaultBtn.setTextColor(Color.WHITE);
        defaultBtn.setBackground(createRoundedDrawable(0xFF263238, 0xFF455A64, 8, density));
        LinearLayout.LayoutParams defParams = new LinearLayout.LayoutParams(0, dp(40), 1.0f);
        defParams.setMargins(dp(6), 0, 0, 0);
        defaultBtn.setLayoutParams(defParams);
        defaultBtn.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                File ext = Environment.getExternalStorageDirectory();
                mGameDir = new File(ext, "nxdroid/game").getAbsolutePath();
                saveGameDir(mGameDir);
                updateStatusDisplay();
            }
        });
        btnRow.addView(defaultBtn);

        folderCard.addView(btnRow);
        contentLayout.addView(folderCard);

        // --- Launch Button ---
        mLaunchButton = new Button(this);
        mLaunchButton.setText("▶  INICIAR JOGO / START GAME");
        mLaunchButton.setTextSize(16);
        mLaunchButton.setTextColor(Color.WHITE);
        mLaunchButton.setTypeface(Typeface.DEFAULT_BOLD);
        LinearLayout.LayoutParams launchParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(52));
        launchParams.setMargins(0, dp(16), 0, 0);
        mLaunchButton.setLayoutParams(launchParams);
        mLaunchButton.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                startGameSession();
            }
        });
        contentLayout.addView(mLaunchButton);

        // --- Quick Instructions Card ---
        LinearLayout guideCard = new LinearLayout(this);
        guideCard.setOrientation(LinearLayout.VERTICAL);
        guideCard.setBackground(createRoundedDrawable(0xFF14171E, 0xFF242A38, 10, density));
        guideCard.setPadding(dp(16), dp(12), dp(16), dp(12));
        LinearLayout.LayoutParams guideParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        guideParams.setMargins(0, dp(16), 0, 0);
        guideCard.setLayoutParams(guideParams);

        TextView guideTitle = new TextView(this);
        guideTitle.setText("ℹ️ Instruções Rápidas / Quick Setup");
        guideTitle.setTextSize(13);
        guideTitle.setTextColor(0xFF00E5FF);
        guideTitle.setTypeface(Typeface.DEFAULT_BOLD);
        guideCard.addView(guideTitle);

        TextView guideText = new TextView(this);
        guideText.setText(
                "1. Selecione ou crie sua pasta no armazenamento interno (ex: /sdcard/nxdroid/game).\n" +
                "2. Coloque os módulos NSO recompilados para AArch64 ('main', 'sdk', 'subsdk*', etc.).\n" +
                "3. Shaders e RomFS podem ficar em 'shaders/' e 'romfs/' (ou arquivo 'romfs.img').\n" +
                "4. Para voltar ao launcher durante a execução do jogo, pressione 'Voltar' e confirme.");
        guideText.setTextSize(11);
        guideText.setTextColor(0xFF90A4AE);
        guideText.setPadding(0, dp(6), 0, 0);
        guideCard.addView(guideText);

        contentLayout.addView(guideCard);

        mLauncherOverlay.addView(contentLayout);
        mRootContainer.addView(mLauncherOverlay, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        setContentView(mRootContainer);
        updateStatusDisplay();
    }

    private void updateStatusDisplay() {
        float density = getResources().getDisplayMetrics().density;
        if (mPathTextView != null) {
            mPathTextView.setText(mGameDir);
        }

        File folder = new File(mGameDir);
        File mainNso = new File(folder, "main");
        boolean ready = mainNso.exists();

        if (mStatusTextView != null) {
            if (ready) {
                mStatusTextView.setText("🟢 Pronto para Executar: módulo 'main' encontrado (" + (mainNso.length() / (1024 * 1024)) + " MB)");
                mStatusTextView.setTextColor(0xFF76FF03);
            } else {
                mStatusTextView.setText("🟡 Pasta vazia ou ausente: coloque o arquivo 'main' em " + mGameDir);
                mStatusTextView.setTextColor(0xFFFFD600);
            }
        }

        if (mLaunchButton != null) {
            if (ready) {
                mLaunchButton.setBackground(createRoundedDrawable(0xFF00C853, 0xFF69F0AE, 10, density));
            } else {
                mLaunchButton.setBackground(createRoundedDrawable(0xFF37474F, 0xFF546E7A, 10, density));
            }
        }

        if (mPermButton != null) {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R && Environment.isExternalStorageManager()) {
                mPermButton.setVisibility(View.GONE);
            } else {
                mPermButton.setVisibility(View.VISIBLE);
            }
        }
    }

    private void launchFolderPicker() {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE);
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION
                | Intent.FLAG_GRANT_WRITE_URI_PERMISSION
                | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);
        try {
            startActivityForResult(intent, REQUEST_SELECT_FOLDER);
        } catch (Exception e) {
            Toast.makeText(this, "Erro ao abrir seletor de pastas: " + e.getMessage(), Toast.LENGTH_SHORT).show();
        }
    }

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
                    mGameDir = resolvedPath;
                    saveGameDir(mGameDir);
                    updateStatusDisplay();
                    Toast.makeText(this, "Pasta selecionada:\n" + mGameDir, Toast.LENGTH_SHORT).show();
                } else {
                    Toast.makeText(this, "Não foi possível converter URI:\n" + treeUri, Toast.LENGTH_LONG).show();
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
        input.setText(mGameDir);
        input.setTextColor(Color.WHITE);
        input.setBackgroundColor(0xFF1E222B);
        input.setPadding(dp(12), dp(12), dp(12), dp(12));
        input.setTextSize(12);
        input.setTypeface(Typeface.MONOSPACE);

        new AlertDialog.Builder(this)
                .setTitle("Digitar Caminho da Pasta")
                .setMessage("Informe o caminho absoluto da pasta do jogo:")
                .setView(input)
                .setPositiveButton("Salvar", new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface dialog, int which) {
                        String path = input.getText().toString().trim();
                        if (!path.isEmpty()) {
                            mGameDir = path;
                            saveGameDir(mGameDir);
                            updateStatusDisplay();
                        }
                    }
                })
                .setNegativeButton("Cancelar", null)
                .show();
    }

    private void startGameSession() {
        File gameFolder = new File(mGameDir);
        gameFolder.mkdirs();

        File mainNso = new File(gameFolder, "main");
        if (!mainNso.exists()) {
            new AlertDialog.Builder(this)
                    .setTitle("Arquivo 'main' não encontrado")
                    .setMessage("O módulo 'main' não existe na pasta selecionada:\n" + mGameDir +
                            "\n\nCertifique-se de copiar os binários do jogo para este diretório.")
                    .setPositiveButton("OK", null)
                    .show();
            return;
        }

        File shadersCandidate = new File(gameFolder, "shaders");
        String shaderDir = shadersCandidate.exists() ? shadersCandidate.getAbsolutePath() : mGameDir;

        File romfsImg = new File(gameFolder, "romfs.img");
        File romfsFolder = new File(gameFolder, "romfs");
        String romfsDir = romfsImg.exists() ? romfsImg.getAbsolutePath()
                : (romfsFolder.exists() ? romfsFolder.getAbsolutePath() : mGameDir);

        File saveFolder = new File(getFilesDir(), "save");
        saveFolder.mkdirs();
        String saveDir = saveFolder.getAbsolutePath();

        mLauncherOverlay.setVisibility(View.GONE);
        mSurfaceView.setVisibility(View.VISIBLE);
        mSurfaceView.bringToFront();
        mVirtualController.setVisibility(View.VISIBLE);
        mVirtualController.bringToFront();
        mVirtualController.requestFocus();

        NativeBridge.nativeStartHost(mGameDir, shaderDir, romfsDir, saveDir, null);
    }

    private void stopGameSession() {
        runOnUiThread(new Runnable() {
            @Override
            public void run() {
                mVirtualController.setVisibility(View.GONE);
                mSurfaceView.setVisibility(View.GONE);
                mLauncherOverlay.setVisibility(View.VISIBLE);
                mLauncherOverlay.bringToFront();
                updateStatusDisplay();
                applyImmersiveMode();
            }
        });
    }

    @Override
    public void onBackPressed() {
        if (NativeBridge.nativeIsRunning()) {
            new AlertDialog.Builder(this)
                    .setTitle("Sair do Jogo? / Quit Game?")
                    .setMessage("Deseja interromper a sessão do jogo e voltar ao launcher?")
                    .setPositiveButton("Sair / Quit", new DialogInterface.OnClickListener() {
                        @Override
                        public void onClick(DialogInterface dialog, int which) {
                            NativeBridge.nativeStopHost();
                            stopGameSession();
                        }
                    })
                    .setNegativeButton("Continuar / Continue", null)
                    .show();
        } else {
            super.onBackPressed();
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        applyImmersiveMode();
        updateStatusDisplay();
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
            NativeBridge.nativeSendInput(mButtons, mLx, mLy, mRx, mRy);
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
            NativeBridge.nativeSendInput(mButtons, mLx, mLy, mRx, mRy);
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

            NativeBridge.nativeSendPad(0, mButtons, mLx, mLy, mRx, mRy);
            NativeBridge.nativeSendInput(mButtons, mLx, mLy, mRx, mRy);
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
