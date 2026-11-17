package com.nxdroid;

import static org.junit.Assert.assertEquals;

import org.junit.Test;

/** LauncherOverlayView.navigate: a two-column grid paged by four, moves that stay inside the list. */
public class LauncherNavigationTest {
    private static int nav(int selected, int count, long button) {
        return LauncherOverlayView.navigate(selected, count, button);
    }

    @Test
    public void leftAndRightWalkTheList() {
        assertEquals(1, nav(0, 5, MainActivity.DM_BTN_RIGHT));
        assertEquals(4, nav(3, 5, MainActivity.DM_BTN_RIGHT));   // on to the next page
        assertEquals(4, nav(4, 5, MainActivity.DM_BTN_RIGHT));   // the last game stays
        assertEquals(0, nav(0, 5, MainActivity.DM_BTN_LEFT));
        assertEquals(3, nav(4, 5, MainActivity.DM_BTN_LEFT));
    }

    @Test
    public void upAndDownMoveByARow() {
        assertEquals(2, nav(0, 5, MainActivity.DM_BTN_DOWN));
        assertEquals(4, nav(2, 5, MainActivity.DM_BTN_DOWN));
        assertEquals(4, nav(3, 5, MainActivity.DM_BTN_DOWN));    // the row below is shorter: its last game
        assertEquals(2, nav(1, 3, MainActivity.DM_BTN_DOWN));
        assertEquals(1, nav(1, 2, MainActivity.DM_BTN_DOWN));    // no row below
        assertEquals(2, nav(4, 5, MainActivity.DM_BTN_UP));
        assertEquals(1, nav(1, 5, MainActivity.DM_BTN_UP));
    }

    @Test
    public void shouldersTurnThePage() {
        assertEquals(4, nav(1, 9, MainActivity.DM_BTN_R));
        assertEquals(8, nav(5, 9, MainActivity.DM_BTN_ZR));
        assertEquals(8, nav(8, 9, MainActivity.DM_BTN_R));       // no page after the last
        assertEquals(0, nav(6, 9, MainActivity.DM_BTN_L));
        assertEquals(2, nav(2, 9, MainActivity.DM_BTN_ZL));      // no page before the first
    }

    @Test
    public void otherButtonsDoNotMove() {
        assertEquals(-1, nav(0, 5, MainActivity.DM_BTN_B));
        assertEquals(-1, nav(0, 5, MainActivity.DM_BTN_LS));
    }
}
