package com.nxdroid;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

import java.io.File;
import java.io.FileOutputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.zip.Deflater;

/**
 * GameScanner on synthetic game folders: control.nacp (plain and with the deflated title area of newer
 * SDKs, the layout dm/tools/nacp.py reads), the title ID fallbacks, shader bundles, RomFS and size, and
 * GameInfo.matches against what NativeBridge.nativeGetBuiltGame returns. A JVM unit test (android.jar's
 * methods return defaults: testOptions.unitTests.returnDefaultValues), so icons are not decoded here.
 */
public class GameScannerTest {
    @Rule
    public TemporaryFolder tmp = new TemporaryFolder();

    private static final String[] BUILT = {"0100152000022000", "Mario Kart 8 Deluxe", "0100152000022000"};

    static byte[] nacp(String name, String publisher, String version, long owner, int language, boolean compress) {
        byte[] titles = new byte[compress ? 0x6000 : 0x3000];
        byte[] n = name.getBytes(StandardCharsets.UTF_8);
        byte[] p = publisher.getBytes(StandardCharsets.UTF_8);
        System.arraycopy(n, 0, titles, language * 0x300, n.length);
        System.arraycopy(p, 0, titles, language * 0x300 + 0x200, p.length);
        ByteBuffer b = ByteBuffer.allocate(0x4000).order(ByteOrder.LITTLE_ENDIAN);
        if (compress) {
            Deflater d = new Deflater(Deflater.DEFAULT_COMPRESSION, true);
            d.setInput(titles);
            d.finish();
            byte[] out = new byte[0x2ff0];
            int len = d.deflate(out);
            d.end();
            b.putShort(0, (short) len);
            b.position(2);
            b.put(out, 0, len);
        } else {
            b.put(titles);
        }
        b.position(0x3060);
        b.put(version.getBytes(StandardCharsets.US_ASCII));
        b.putLong(0x3078, owner);
        return b.array();
    }

    static void write(File f, byte[] data) throws Exception {
        assertTrue(f.getParentFile().isDirectory() || f.getParentFile().mkdirs());
        try (FileOutputStream o = new FileOutputStream(f)) {
            o.write(data);
        }
    }

    private File library() throws Exception {
        File root = tmp.newFolder("nxdroid");
        File mk = new File(root, "game");
        write(new File(mk, "main"), new byte[100]);
        write(new File(mk, "romfs.img"), new byte[1000]);
        write(new File(mk, "aa.xgs"), new byte[10]);
        write(new File(mk, "bb.xgs"), new byte[10]);
        write(new File(mk, "control.nacp"), nacp("Mario Kart 8 Deluxe", "Nintendo", "4.0.1", 0x0100152000022000L, 0, false));
        File z = new File(root, "zelda");
        write(new File(z, "main"), new byte[10]);
        write(new File(z, "shaders/x.xgs"), new byte[10]);
        write(new File(z, "control.nacp"), nacp("Zelda Compressed", "Nintendo EPD", "1.2.1", 0x0100F2C0115B6000L, 3, true));
        File foo = new File(root, "Foo_0100ABCD00000000");
        write(new File(foo, "main"), new byte[10]);
        write(new File(foo, "romfs/a.bin"), new byte[10]);
        assertTrue(new File(root, "not_a_game").mkdirs());
        write(new File(root, "gfx-noload"), "0".getBytes(StandardCharsets.US_ASCII));   // an engine marker beside the games
        return root;
    }

    @Test
    public void findsEveryGameFolderSortedByTitle() throws Exception {
        List<GameInfo> games = GameScanner.scanDirectory(library().getPath());
        assertEquals(3, games.size());
        assertEquals("Foo 0100ABCD00000000", games.get(0).title);
        assertEquals("Mario Kart 8 Deluxe", games.get(1).title);
        assertEquals("Zelda Compressed", games.get(2).title);
    }

    @Test
    public void readsControlNacp() throws Exception {
        GameInfo mk = GameScanner.scanDirectory(library().getPath()).get(1);
        assertEquals("Nintendo", mk.publisher);
        assertEquals("4.0.1", mk.displayVersion);
        assertEquals("0100152000022000", mk.titleId);
        assertEquals(2, mk.shaderBundles);
        assertEquals("romfs.img", mk.romfs);
        assertEquals(100 + 1000 + 20 + 0x4000, mk.sizeBytes);
        assertNull(mk.icon);
    }

    @Test
    public void readsTheDeflatedTitleAreaOfNewerSdks() throws Exception {
        GameInfo z = GameScanner.scanDirectory(library().getPath()).get(2);
        assertEquals("Nintendo EPD", z.publisher);
        assertEquals("0100F2C0115B6000", z.titleId);
        assertEquals(1, z.shaderBundles);
        assertNull(z.romfs);
    }

    @Test
    public void withoutControlNacpTheFolderNameGivesTitleAndId() throws Exception {
        GameInfo foo = GameScanner.scanDirectory(library().getPath()).get(0);
        assertEquals("0100ABCD00000000", foo.titleId);
        assertEquals("romfs/", foo.romfs);
        assertNull(foo.publisher);
    }

    @Test
    public void aGameFolderAsTheLibraryIsTheOnlyGame() throws Exception {
        List<GameInfo> games = GameScanner.scanDirectory(new File(library(), "game").getPath());
        assertEquals(1, games.size());
        assertEquals("Mario Kart 8 Deluxe", games.get(0).title);
    }

    @Test
    public void aMissingFolderHasNoGames() {
        assertTrue(GameScanner.scanDirectory(new File(tmp.getRoot(), "missing").getPath()).isEmpty());
        assertTrue(GameScanner.scanDirectory("").isEmpty());
        assertTrue(GameScanner.scanDirectory(null).isEmpty());
    }

    @Test
    public void matchesTheBuiltGameByProfileOrProgramId() throws Exception {
        List<GameInfo> games = GameScanner.scanDirectory(library().getPath());
        assertTrue(games.get(1).matches(BUILT));
        assertTrue(games.get(1).matches(new String[]{"x", "y", "0100152000022000".toLowerCase()}));
        assertFalse(games.get(0).matches(BUILT));
        assertFalse(games.get(2).matches(BUILT));
        assertFalse(games.get(1).matches(null));
    }
}
