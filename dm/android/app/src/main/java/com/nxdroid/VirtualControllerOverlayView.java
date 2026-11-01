package com.nxdroid;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.RectF;
import android.graphics.Typeface;
import android.util.AttributeSet;
import android.view.MotionEvent;
import android.view.View;

import java.util.HashMap;
import java.util.Map;

/**
 * Modern semi-transparent on-screen multi-touch virtual controller overlay.
 * Designed for Nintendo Switch titles (Mario Kart 8 Deluxe, etc.).
 *
 * Features:
 * - Draggable Virtual Left Analog Stick reporting [-32767, 32767]
 * - D-Pad (Up, Down, Left, Right)
 * - Switch Diamond Face Buttons (A, B, X, Y)
 * - Shoulder / Trigger buttons (L, ZL, R, ZR)
 * - System buttons (+, -, and a dedicated "L+R" pairing/title button)
 * - Sleek toggle button (🎮) at top-center to show/hide overlay controls
 * - Full multi-touch pointer tracking across simultaneous inputs
 */
public class VirtualControllerOverlayView extends View {

    public interface OnPadStateChangeListener {
        void onPadStateChanged(long buttons, int lx, int ly, int rx, int ry);
    }

    private OnPadStateChangeListener mListener;
    private boolean mControlsVisible = true;

    // Active controller state
    private long mButtons = 0;
    private int mLx = 0;
    private int mLy = 0;
    private int mRx = 0;
    private int mRy = 0;

    // Paints
    private final Paint mPaintBase = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint mPaintKnob = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint mPaintPressed = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint mPaintStroke = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint mPaintText = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint mPaintToggle = new Paint(Paint.ANTI_ALIAS_FLAG);

    // Multi-touch tracking: pointerId -> button mask
    private final Map<Integer, Long> mPointerButtons = new HashMap<>();
    private int mStickPointerId = -1;

    // Layout elements (calculated in onSizeChanged)
    private float mDensity = 1.0f;

    // Left Stick
    private float mStickCenterX;
    private float mStickCenterY;
    private float mStickRadius;
    private float mKnobRadius;
    private float mKnobX;
    private float mKnobY;

    // Toggle button (top center)
    private final RectF mToggleRect = new RectF();

    // Rect buttons
    private final RectF mBtnZL = new RectF();
    private final RectF mBtnL = new RectF();
    private final RectF mBtnZR = new RectF();
    private final RectF mBtnR = new RectF();
    private final RectF mBtnLR = new RectF();
    private final RectF mBtnMinus = new RectF();
    private final RectF mBtnPlus = new RectF();

    // D-Pad buttons
    private final RectF mDpadUp = new RectF();
    private final RectF mDpadDown = new RectF();
    private final RectF mDpadLeft = new RectF();
    private final RectF mDpadRight = new RectF();

    // Face buttons (centers and radius)
    private float mFaceCenterX;
    private float mFaceCenterY;
    private float mFaceRadius;
    private float mBtnRadius;
    private float mBtnX_cx, mBtnX_cy;
    private float mBtnA_cx, mBtnA_cy;
    private float mBtnB_cx, mBtnB_cy;
    private float mBtnY_cx, mBtnY_cy;

    public VirtualControllerOverlayView(Context context) {
        super(context);
        init();
    }

    public VirtualControllerOverlayView(Context context, AttributeSet attrs) {
        super(context, attrs);
        init();
    }

    public VirtualControllerOverlayView(Context context, AttributeSet attrs, int defStyleAttr) {
        super(context, attrs, defStyleAttr);
        init();
    }

    private void init() {
        mDensity = getResources().getDisplayMetrics().density;

        mPaintBase.setStyle(Paint.Style.FILL);
        mPaintBase.setColor(0x55141926);

        mPaintKnob.setStyle(Paint.Style.FILL);
        mPaintKnob.setColor(0x8800E5FF);

        mPaintPressed.setStyle(Paint.Style.FILL);
        mPaintPressed.setColor(0xCC00E5FF);

        mPaintStroke.setStyle(Paint.Style.STROKE);
        mPaintStroke.setStrokeWidth(dp(2));
        mPaintStroke.setColor(0x88475569);

        mPaintText.setTextAlign(Paint.Align.CENTER);
        mPaintText.setTypeface(Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD));

        mPaintToggle.setStyle(Paint.Style.FILL);
        mPaintToggle.setColor(0x770E121B);
    }

    private float dp(float val) {
        return val * mDensity;
    }

    public void setOnPadStateChangeListener(OnPadStateChangeListener listener) {
        mListener = listener;
    }

    public void setControlsVisible(boolean visible) {
        mControlsVisible = visible;
        if (!visible) {
            resetInputs();
        }
        invalidate();
    }

    public boolean isControlsVisible() {
        return mControlsVisible;
    }

    private void resetInputs() {
        mButtons = 0;
        mLx = 0;
        mLy = 0;
        mRx = 0;
        mRy = 0;
        mStickPointerId = -1;
        mPointerButtons.clear();
        mKnobX = mStickCenterX;
        mKnobY = mStickCenterY;
        if (mListener != null) {
            mListener.onPadStateChanged(mButtons, mLx, mLy, mRx, mRy);
        }
    }

    @Override
    protected void onSizeChanged(int w, int h, int oldw, int oldh) {
        super.onSizeChanged(w, h, oldw, oldh);
        if (w == 0 || h == 0) return;

        // Toggle button at top center
        float toggleW = dp(56);
        float toggleH = dp(32);
        mToggleRect.set(w * 0.5f - toggleW * 0.5f, dp(8), w * 0.5f + toggleW * 0.5f, dp(8) + toggleH);

        // L+R dedicated combo button right next to toggle
        float lrW = dp(64);
        float lrH = dp(32);
        mBtnLR.set(w * 0.5f + toggleW * 0.5f + dp(12), dp(8), w * 0.5f + toggleW * 0.5f + dp(12) + lrW, dp(8) + lrH);

        // Top Left triggers
        mBtnZL.set(dp(20), dp(12), dp(95), dp(56));
        mBtnL.set(dp(105), dp(12), dp(180), dp(56));
        mBtnMinus.set(dp(195), dp(18), dp(245), dp(50));

        // Top Right triggers
        mBtnPlus.set(w - dp(245), dp(18), w - dp(195), dp(50));
        mBtnR.set(w - dp(180), dp(12), w - dp(105), dp(56));
        mBtnZR.set(w - dp(95), dp(12), w - dp(20), dp(56));

        // Left Stick (lower left area)
        mStickRadius = dp(58);
        mKnobRadius = dp(28);
        mStickCenterX = dp(105);
        mStickCenterY = h - dp(115);
        mKnobX = mStickCenterX;
        mKnobY = mStickCenterY;

        // D-Pad (placed to the right of Left Stick or above it)
        float dpadCenterY = h - dp(115);
        float dpadCenterX = dp(225);
        float dpadBtnW = dp(38);
        float dpadBtnH = dp(38);
        mDpadUp.set(dpadCenterX - dpadBtnW * 0.5f, dpadCenterY - dpadBtnH * 1.5f, dpadCenterX + dpadBtnW * 0.5f, dpadCenterY - dpadBtnH * 0.5f);
        mDpadDown.set(dpadCenterX - dpadBtnW * 0.5f, dpadCenterY + dpadBtnH * 0.5f, dpadCenterX + dpadBtnW * 0.5f, dpadCenterY + dpadBtnH * 1.5f);
        mDpadLeft.set(dpadCenterX - dpadBtnW * 1.5f, dpadCenterY - dpadBtnH * 0.5f, dpadCenterX - dpadBtnW * 0.5f, dpadCenterY + dpadBtnH * 0.5f);
        mDpadRight.set(dpadCenterX + dpadBtnW * 0.5f, dpadCenterY - dpadBtnH * 0.5f, dpadCenterX + dpadBtnW * 1.5f, dpadCenterY + dpadBtnH * 0.5f);

        // Right Face Buttons (Diamond layout at lower right)
        mFaceCenterX = w - dp(115);
        mFaceCenterY = h - dp(115);
        mFaceRadius = dp(52);
        mBtnRadius = dp(25);

        mBtnX_cx = mFaceCenterX;
        mBtnX_cy = mFaceCenterY - mFaceRadius;

        mBtnA_cx = mFaceCenterX + mFaceRadius;
        mBtnA_cy = mFaceCenterY;

        mBtnB_cx = mFaceCenterX;
        mBtnB_cy = mFaceCenterY + mFaceRadius;

        mBtnY_cx = mFaceCenterX - mFaceRadius;
        mBtnY_cy = mFaceCenterY;
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);

        // 1. Draw Toggle button (always visible)
        mPaintToggle.setColor(mControlsVisible ? 0x660E1827 : 0xAA0E1827);
        canvas.drawRoundRect(mToggleRect, dp(12), dp(12), mPaintToggle);
        mPaintStroke.setColor(0x8800E5FF);
        canvas.drawRoundRect(mToggleRect, dp(12), dp(12), mPaintStroke);

        mPaintText.setTextSize(dp(16));
        mPaintText.setColor(0xFFF8FAFC);
        canvas.drawText("🎮", mToggleRect.centerX(), mToggleRect.centerY() + dp(5), mPaintText);

        if (!mControlsVisible) return;

        // 2. Draw Left Analog Stick
        mPaintBase.setColor(0x44141926);
        canvas.drawCircle(mStickCenterX, mStickCenterY, mStickRadius, mPaintBase);
        mPaintStroke.setColor(0x6600E5FF);
        canvas.drawCircle(mStickCenterX, mStickCenterY, mStickRadius, mPaintStroke);

        // Stick knob
        boolean stickActive = (mStickPointerId != -1);
        mPaintKnob.setColor(stickActive ? 0xDD00E5FF : 0x7700E5FF);
        canvas.drawCircle(mKnobX, mKnobY, mKnobRadius, mPaintKnob);
        mPaintStroke.setColor(stickActive ? 0xFFFFFFFF : 0xAA00E5FF);
        canvas.drawCircle(mKnobX, mKnobY, mKnobRadius, mPaintStroke);

        // 3. Draw D-Pad
        drawRectButton(canvas, mDpadUp, MainActivity.DM_BTN_UP, "▲", dp(16));
        drawRectButton(canvas, mDpadDown, MainActivity.DM_BTN_DOWN, "▼", dp(16));
        drawRectButton(canvas, mDpadLeft, MainActivity.DM_BTN_LEFT, "◀", dp(16));
        drawRectButton(canvas, mDpadRight, MainActivity.DM_BTN_RIGHT, "▶", dp(16));

        // 4. Draw Shoulder buttons
        drawRectButton(canvas, mBtnZL, MainActivity.DM_BTN_ZL, "ZL", dp(15));
        drawRectButton(canvas, mBtnL, MainActivity.DM_BTN_L, "L", dp(15));
        drawRectButton(canvas, mBtnMinus, MainActivity.DM_BTN_MINUS, "—", dp(16));

        drawRectButton(canvas, mBtnLR, MainActivity.DM_BTN_L | MainActivity.DM_BTN_R, "L+R", dp(14));

        drawRectButton(canvas, mBtnPlus, MainActivity.DM_BTN_PLUS, "+", dp(18));
        drawRectButton(canvas, mBtnR, MainActivity.DM_BTN_R, "R", dp(15));
        drawRectButton(canvas, mBtnZR, MainActivity.DM_BTN_ZR, "ZR", dp(15));

        // 5. Draw Face Buttons (Diamond)
        drawCircleButton(canvas, mBtnX_cx, mBtnX_cy, mBtnRadius, MainActivity.DM_BTN_X, "X", dp(18));
        drawCircleButton(canvas, mBtnA_cx, mBtnA_cy, mBtnRadius, MainActivity.DM_BTN_A, "A", dp(18));
        drawCircleButton(canvas, mBtnB_cx, mBtnB_cy, mBtnRadius, MainActivity.DM_BTN_B, "B", dp(18));
        drawCircleButton(canvas, mBtnY_cx, mBtnY_cy, mBtnRadius, MainActivity.DM_BTN_Y, "Y", dp(18));
    }

    private void drawRectButton(Canvas canvas, RectF rect, long mask, String label, float textSize) {
        boolean pressed = (mButtons & mask) == mask;
        mPaintBase.setColor(pressed ? 0xCC00E5FF : 0x55141926);
        canvas.drawRoundRect(rect, dp(10), dp(10), mPaintBase);
        mPaintStroke.setColor(pressed ? 0xFFFFFFFF : 0x77475569);
        canvas.drawRoundRect(rect, dp(10), dp(10), mPaintStroke);

        mPaintText.setTextSize(textSize);
        mPaintText.setColor(pressed ? 0xFF0A0D14 : 0xFFE2E8F0);
        canvas.drawText(label, rect.centerX(), rect.centerY() + textSize * 0.35f, mPaintText);
    }

    private void drawCircleButton(Canvas canvas, float cx, float cy, float radius, long mask, String label, float textSize) {
        boolean pressed = (mButtons & mask) != 0;
        mPaintBase.setColor(pressed ? 0xCC00E5FF : 0x55141926);
        canvas.drawCircle(cx, cy, radius, mPaintBase);
        mPaintStroke.setColor(pressed ? 0xFFFFFFFF : 0x77475569);
        canvas.drawCircle(cx, cy, radius, mPaintStroke);

        mPaintText.setTextSize(textSize);
        mPaintText.setColor(pressed ? 0xFF0A0D14 : 0xFFE2E8F0);
        canvas.drawText(label, cx, cy + textSize * 0.35f, mPaintText);
    }

    @Override
    public boolean onTouchEvent(MotionEvent event) {
        int action = event.getActionMasked();
        int actionIndex = event.getActionIndex();
        int pointerId = event.getPointerId(actionIndex);

        switch (action) {
            case MotionEvent.ACTION_DOWN:
            case MotionEvent.ACTION_POINTER_DOWN: {
                float x = event.getX(actionIndex);
                float y = event.getY(actionIndex);

                // Check toggle button
                if (mToggleRect.contains(x, y)) {
                    mControlsVisible = !mControlsVisible;
                    if (!mControlsVisible) resetInputs();
                    invalidate();
                    return true;
                }

                if (!mControlsVisible) return false;

                // Check Left Stick capture
                float distStick = (float) Math.hypot(x - mStickCenterX, y - mStickCenterY);
                if (distStick <= mStickRadius * 1.6f && mStickPointerId == -1) {
                    mStickPointerId = pointerId;
                    updateStick(x, y);
                    notifyState();
                    invalidate();
                    return true;
                }

                // Check button hits
                long hitBtn = testHit(x, y);
                if (hitBtn != 0) {
                    mPointerButtons.put(pointerId, hitBtn);
                    rebuildButtons();
                    notifyState();
                    invalidate();
                    return true;
                }
                return false;
            }

            case MotionEvent.ACTION_MOVE: {
                if (!mControlsVisible) return false;
                boolean changed = false;

                // Update stick if active
                if (mStickPointerId != -1) {
                    int stickIndex = event.findPointerIndex(mStickPointerId);
                    if (stickIndex >= 0) {
                        float sx = event.getX(stickIndex);
                        float sy = event.getY(stickIndex);
                        updateStick(sx, sy);
                        changed = true;
                    }
                }

                // Update moving button pointers
                for (int i = 0; i < event.getPointerCount(); i++) {
                    int pId = event.getPointerId(i);
                    if (pId == mStickPointerId) continue;

                    float px = event.getX(i);
                    float py = event.getY(i);
                    long hit = testHit(px, py);
                    Long oldHit = mPointerButtons.get(pId);
                    if (oldHit == null && hit != 0) {
                        mPointerButtons.put(pId, hit);
                        changed = true;
                    } else if (oldHit != null && hit != oldHit) {
                        if (hit != 0) {
                            mPointerButtons.put(pId, hit);
                        } else {
                            mPointerButtons.remove(pId);
                        }
                        changed = true;
                    }
                }

                if (changed) {
                    rebuildButtons();
                    notifyState();
                    invalidate();
                }
                return true;
            }

            case MotionEvent.ACTION_POINTER_UP:
            case MotionEvent.ACTION_UP: {
                if (pointerId == mStickPointerId) {
                    mStickPointerId = -1;
                    mLx = 0;
                    mLy = 0;
                    mKnobX = mStickCenterX;
                    mKnobY = mStickCenterY;
                    notifyState();
                    invalidate();
                } else if (mPointerButtons.containsKey(pointerId)) {
                    mPointerButtons.remove(pointerId);
                    rebuildButtons();
                    notifyState();
                    invalidate();
                }

                if (action == MotionEvent.ACTION_UP) {
                    resetInputs();
                    invalidate();
                }
                return true;
            }

            case MotionEvent.ACTION_CANCEL: {
                resetInputs();
                invalidate();
                return true;
            }
        }
        return super.onTouchEvent(event);
    }

    private void updateStick(float x, float y) {
        float dx = x - mStickCenterX;
        float dy = y - mStickCenterY;
        float dist = (float) Math.hypot(dx, dy);

        if (dist > mStickRadius) {
            dx = dx * mStickRadius / dist;
            dy = dy * mStickRadius / dist;
        }

        mKnobX = mStickCenterX + dx;
        mKnobY = mStickCenterY + dy;

        float normX = dx / mStickRadius;
        float normY = dy / mStickRadius;

        mLx = Math.round(normX * 32767.0f);
        mLy = Math.round(-normY * 32767.0f); // Up is positive in Switch pad
    }

    private long testHit(float x, float y) {
        // D-Pad
        if (mDpadUp.contains(x, y)) return MainActivity.DM_BTN_UP;
        if (mDpadDown.contains(x, y)) return MainActivity.DM_BTN_DOWN;
        if (mDpadLeft.contains(x, y)) return MainActivity.DM_BTN_LEFT;
        if (mDpadRight.contains(x, y)) return MainActivity.DM_BTN_RIGHT;

        // Triggers and combos
        if (mBtnLR.contains(x, y)) return (MainActivity.DM_BTN_L | MainActivity.DM_BTN_R);
        if (mBtnZL.contains(x, y)) return MainActivity.DM_BTN_ZL;
        if (mBtnL.contains(x, y)) return MainActivity.DM_BTN_L;
        if (mBtnMinus.contains(x, y)) return MainActivity.DM_BTN_MINUS;

        if (mBtnPlus.contains(x, y)) return MainActivity.DM_BTN_PLUS;
        if (mBtnR.contains(x, y)) return MainActivity.DM_BTN_R;
        if (mBtnZR.contains(x, y)) return MainActivity.DM_BTN_ZR;

        // Face buttons (circle hit test with generous padding)
        float pad = dp(10);
        float rSq = (mBtnRadius + pad) * (mBtnRadius + pad);

        if ((x - mBtnX_cx) * (x - mBtnX_cx) + (y - mBtnX_cy) * (y - mBtnX_cy) <= rSq) return MainActivity.DM_BTN_X;
        if ((x - mBtnA_cx) * (x - mBtnA_cx) + (y - mBtnA_cy) * (y - mBtnA_cy) <= rSq) return MainActivity.DM_BTN_A;
        if ((x - mBtnB_cx) * (x - mBtnB_cx) + (y - mBtnB_cy) * (y - mBtnB_cy) <= rSq) return MainActivity.DM_BTN_B;
        if ((x - mBtnY_cx) * (x - mBtnY_cx) + (y - mBtnY_cy) * (y - mBtnY_cy) <= rSq) return MainActivity.DM_BTN_Y;

        return 0;
    }

    private void rebuildButtons() {
        mButtons = 0;
        for (long b : mPointerButtons.values()) {
            mButtons |= b;
        }
    }

    private void notifyState() {
        if (mListener != null) {
            mListener.onPadStateChanged(mButtons, mLx, mLy, mRx, mRy);
        }
    }
}
