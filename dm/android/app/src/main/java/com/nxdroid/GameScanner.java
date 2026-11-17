package com.nxdroid;

import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.os.Handler;
import android.os.Looper;

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.zip.DataFormatException;
import java.util.zip.Inflater;

/**
 * Finds prepared games in the library folder: the folder itself when it holds a 'main' module,
 * otherwise each subfolder that does (one level, as scripts/prepare_game_android.py lays them out:
 * /storage/emulated/0/nxdroid/game by default). Runs off the main thread.
 */
public final class GameScanner {
    public interface ScanCallback {
        void onScanCompleted(String rootPath, List<GameInfo> games);
    }

    private static final ExecutorService sExecutor = Executors.newSingleThreadExecutor();
    private static final Handler sMainHandler = new Handler(Looper.getMainLooper());
    private static final int ICON_PX = 256;

    private GameScanner() {}

    public static void scanDirectoryAsync(final String rootPath, final ScanCallback callback) {
        sExecutor.execute(new Runnable() {
            @Override
            public void run() {
                final List<GameInfo> results = scanDirectory(rootPath);
                sMainHandler.post(new Runnable() {
                    @Override
                    public void run() {
                        if (callback != null) callback.onScanCompleted(rootPath, results);
                    }
                });
            }
        });
    }

    public static List<GameInfo> scanDirectory(String rootPath) {
        List<GameInfo> list = new ArrayList<>();
        if (rootPath == null || rootPath.isEmpty()) return list;
        File root = new File(rootPath);
        if (!root.isDirectory()) return list;

        if (isGameFolder(root)) {
            list.add(readGame(root));
            return list;
        }
        File[] subdirs = root.listFiles();
        if (subdirs != null) {
            for (File sub : subdirs) {
                if (sub.isDirectory() && isGameFolder(sub)) list.add(readGame(sub));
            }
        }
        Collections.sort(list, new Comparator<GameInfo>() {
            @Override
            public int compare(GameInfo a, GameInfo b) {
                return a.title.compareToIgnoreCase(b.title);
            }
        });
        return list;
    }

    /** A folder the host can start: MainActivity passes it as the game directory, and the host loads 'main' from it. */
    public static boolean isGameFolder(File dir) {
        return new File(dir, "main").isFile();
    }

    private static GameInfo readGame(File dir) {
        String title = null, publisher = null, version = null, titleId = null;
        byte[] nacp = readFile(new File(dir, "control.nacp"), 0x4000);
        if (nacp != null && nacp.length >= 0x3080) {
            String[] entry = nacpTitle(nacp);
            if (entry != null) {
                title = entry[0];
                publisher = entry[1];
            }
            version = cString(nacp, 0x3060, 0x10);
            titleId = nacpTitleId(nacp);
        }
        if (title == null || title.isEmpty()) title = dir.getName().replace('_', ' ');
        if (titleId == null) titleId = titleIdFromName(dir.getName());

        long[] size = {0};
        int bundles = countBundles(dir) + countBundles(new File(dir, "shaders"));
        sizeOf(dir, size, 0);

        String romfs = new File(dir, "romfs.img").isFile() ? "romfs.img"
                : (new File(dir, "romfs").isDirectory() ? "romfs/" : null);
        return new GameInfo(title, publisher, version, titleId, dir.getAbsolutePath(),
                size[0], bundles, romfs, decodeIcon(new File(dir, "icon.jpg")));
    }

    // ---- control.nacp (the layout dm/tools/nacp.py reads) ----

    /** The first non-empty language entry: 0x300 bytes each, name 0x200 then publisher 0x100; newer SDKs deflate the 0x3000-byte title area. */
    private static String[] nacpTitle(byte[] b) {
        byte[] area = new byte[0x3000];
        System.arraycopy(b, 0, area, 0, 0x3000);
        int packed = (b[0] & 0xff) | (b[1] & 0xff) << 8;
        if (packed > 0 && packed + 2 <= 0x3000) {
            Inflater inf = new Inflater(true);
            try {
                inf.setInput(b, 2, packed);
                byte[] out = new byte[0x6000];
                int n = inf.inflate(out);
                if (n == 0x6000 && inf.finished()) area = out;
            } catch (DataFormatException ignored) {
                // not compressed
            } finally {
                inf.end();
            }
        }
        for (int i = 0; i + 0x300 <= area.length; i += 0x300) {
            String name = cString(area, i, 0x200);
            if (name != null && !name.isEmpty()) return new String[]{name, cString(area, i + 0x200, 0x100)};
        }
        return null;
    }

    /** SaveDataOwnerId (0x3078), the application's own ID for a game; else PresenceGroupId (0x3038). */
    private static String nacpTitleId(byte[] b) {
        long owner = u64(b, 0x3078);
        if (owner == 0) owner = u64(b, 0x3038);
        return owner == 0 ? null : String.format(Locale.US, "%016X", owner);
    }

    private static long u64(byte[] b, int off) {
        long v = 0;
        for (int i = 7; i >= 0; i--) v = v << 8 | (b[off + i] & 0xffL);
        return v;
    }

    private static String cString(byte[] b, int off, int max) {
        int end = off;
        while (end < off + max && end < b.length && b[end] != 0) end++;
        if (end == off) return null;
        String s = new String(b, off, end - off, StandardCharsets.UTF_8).trim();
        return s.isEmpty() ? null : s;
    }

    private static String titleIdFromName(String name) {
        for (String part : name.toUpperCase(Locale.ROOT).split("[^0-9A-F]")) {
            if (part.length() == 16 && part.startsWith("01")) return part;
        }
        return null;
    }

    // ---- Files ----

    private static byte[] readFile(File f, int max) {
        if (!f.isFile()) return null;
        try (InputStream in = new FileInputStream(f)) {
            byte[] buf = new byte[(int) Math.min(max, f.length())];
            int got = 0;
            while (got < buf.length) {
                int n = in.read(buf, got, buf.length - got);
                if (n < 0) break;
                got += n;
            }
            if (got == buf.length) return buf;
            byte[] cut = new byte[got];
            System.arraycopy(buf, 0, cut, 0, got);
            return cut;
        } catch (IOException e) {
            return null;
        }
    }

    private static int countBundles(File dir) {
        String[] names = dir.list();
        if (names == null) return 0;
        int n = 0;
        for (String s : names) if (s.endsWith(".xgs")) n++;
        return n;
    }

    private static void sizeOf(File dir, long[] total, int depth) {
        File[] files = dir.listFiles();
        if (files == null) return;
        for (File f : files) {
            if (f.isFile()) total[0] += f.length();
            else if (depth < 3 && f.isDirectory()) sizeOf(f, total, depth + 1);
        }
    }

    private static Bitmap decodeIcon(File f) {
        if (!f.isFile()) return null;
        BitmapFactory.Options bounds = new BitmapFactory.Options();
        bounds.inJustDecodeBounds = true;
        BitmapFactory.decodeFile(f.getAbsolutePath(), bounds);
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return null;
        BitmapFactory.Options opts = new BitmapFactory.Options();
        opts.inSampleSize = 1;
        while (bounds.outWidth / (opts.inSampleSize * 2) >= ICON_PX) opts.inSampleSize *= 2;
        return BitmapFactory.decodeFile(f.getAbsolutePath(), opts);
    }
}
