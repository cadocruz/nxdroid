package com.nxdroid;

import android.content.Context;
import android.util.AttributeSet;
import android.view.MotionEvent;
import android.view.SurfaceHolder;
import android.view.SurfaceView;

/**
 * Dedicated presentation SurfaceView hosting Vulkan rendering and touch input dispatch.
 */
public class GameSurfaceView extends SurfaceView implements SurfaceHolder.Callback2 {
    private final int[] mTouchIds = new int[16];
    private final float[] mTouchXs = new float[16];
    private final float[] mTouchYs = new float[16];

    public GameSurfaceView(Context context) {
        super(context);
        init();
    }

    public GameSurfaceView(Context context, AttributeSet attrs) {
        super(context, attrs);
        init();
    }

    public GameSurfaceView(Context context, AttributeSet attrs, int defStyleAttr) {
        super(context, attrs, defStyleAttr);
        init();
    }

    private void init() {
        getHolder().addCallback(this);
        setFocusable(true);
        setFocusableInTouchMode(true);
    }

    @Override
    public void surfaceCreated(SurfaceHolder holder) {
        NativeBridge.nativeSetSurface(holder.getSurface(), getWidth(), getHeight());
    }

    @Override
    public void surfaceChanged(SurfaceHolder holder, int format, int width, int height) {
        NativeBridge.nativeSetSurface(holder.getSurface(), width, height);
    }

    @Override
    public void surfaceDestroyed(SurfaceHolder holder) {
        NativeBridge.nativeSurfaceDestroyed();
    }

    @Override
    public void surfaceRedrawNeeded(SurfaceHolder holder) {
        // Vulkan handles frame presentations directly on the presentation queue
    }

    @Override
    public boolean onTouchEvent(MotionEvent event) {
        int action = event.getActionMasked();
        int width = getWidth();
        int height = getHeight();
        if (width <= 0 || height <= 0) {
            return true;
        }

        if (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_CANCEL) {
            NativeBridge.nativeSendTouch(0, mTouchIds, mTouchXs, mTouchYs);
            return true;
        }

        int upIndex = (action == MotionEvent.ACTION_POINTER_UP) ? event.getActionIndex() : -1;
        int pointerCount = event.getPointerCount();
        int validCount = 0;

        for (int i = 0; i < pointerCount && validCount < 16; i++) {
            if (i == upIndex) {
                continue;
            }
            mTouchIds[validCount] = event.getPointerId(i);
            float rawX = event.getX(i) / (float) width;
            float rawY = event.getY(i) / (float) height;
            mTouchXs[validCount] = Math.max(0.0f, Math.min(0.999f, rawX));
            mTouchYs[validCount] = Math.max(0.0f, Math.min(0.999f, rawY));
            validCount++;
        }

        NativeBridge.nativeSendTouch(validCount, mTouchIds, mTouchXs, mTouchYs);
        return true;
    }
}
