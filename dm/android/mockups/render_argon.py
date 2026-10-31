#!/usr/bin/env python3
"""
render_argon.py - High-Resolution Android UI/UX Mockup Generator for nxdroid
Landscape Console Experience (1920x1080) targeting Galaxy S23 Ultra (Snapdragon 8 Gen 2 / Adreno 740)
"""

import os
import math
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1920, 1080
OUT_PATH = "/home/cado/Documentos/projetos/python/nxdroid/dm/android/mockups/mockup_argon.png"

# Color Palette (OLED Dark + Switch Neon Cyan/Crimson + Material You Dark Gaming)
BG_OBSIDIAN = (10, 13, 20)
SURFACE_0 = (14, 18, 27)
SURFACE_1 = (19, 25, 38)
SURFACE_2 = (25, 34, 51)
SURFACE_CARD = (18, 24, 36)
BORDER_SUBTLE = (35, 46, 68)
BORDER_ACTIVE = (0, 229, 255)

CYAN_NEON = (0, 229, 255)
CYAN_TEAL = (15, 216, 180)
CYAN_GLOW = (0, 229, 255, 40)
CRIMSON_NEON = (255, 51, 102)
GREEN_EMERALD = (16, 185, 129)
AMBER_WARM = (245, 158, 11)
PURPLE_ELECTRIC = (168, 85, 247)
BLUE_ACCENT = (59, 130, 246)
GOLD_SHINE = (251, 191, 36)

TEXT_PRIMARY = (248, 250, 252)
TEXT_SECONDARY = (160, 175, 200)
TEXT_MUTED = (100, 116, 139)
TEXT_DARK = (7, 19, 31)

# Fonts
FONT_DIR = "/usr/share/fonts/truetype"
def get_font(size, weight="regular", mono=False):
    if mono:
        path = f"{FONT_DIR}/ubuntu/UbuntuSansMono[wght].ttf"
    elif weight == "bold":
        path = f"{FONT_DIR}/space-grotesk/SpaceGrotesk-Bold.ttf"
    elif weight == "medium":
        path = f"{FONT_DIR}/space-grotesk/SpaceGrotesk-Medium.ttf"
    else:
        path = f"{FONT_DIR}/space-grotesk/SpaceGrotesk-Regular.ttf"
    
    if not os.path.exists(path):
        path = f"{FONT_DIR}/noto/NotoSans-Bold.ttf" if weight == "bold" else f"{FONT_DIR}/noto/NotoSans-Regular.ttf"
    
    if os.path.exists(path):
        return ImageFont.truetype(path, size)
    return ImageFont.load_default()

# Canvas initialization
img = Image.new("RGBA", (W, H), BG_OBSIDIAN + (255,))
draw = ImageDraw.Draw(img)

# Layer 1: Ambient Backdrop Glows (OLED depth effect)
glow_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
glow_draw = ImageDraw.Draw(glow_layer)

# Cyan bloom at top-left
glow_draw.ellipse((-100, -100, 600, 450), fill=(0, 229, 255, 28))
# Crimson bloom at top-right
glow_draw.ellipse((1400, -150, 2050, 400), fill=(255, 51, 102, 18))
# Indigo ambient pool near center-left
glow_draw.ellipse((100, 300, 950, 950), fill=(59, 130, 246, 20))
# Emerald ambient pool at bottom-right
glow_draw.ellipse((1200, 600, 2000, 1150), fill=(16, 185, 129, 16))

glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(60))
img = Image.alpha_composite(img, glow_layer)
draw = ImageDraw.Draw(img)

# Helper: Rounded Box with optional border
def draw_card(box, radius=16, fill=SURFACE_1, border=BORDER_SUBTLE, border_width=1):
    x0, y0, x1, y1 = box
    draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=fill, outline=border, width=border_width)

def draw_pill(box, text, fg=CYAN_NEON, bg=SURFACE_2, border=None, font_size=12, bold=True):
    x0, y0, x1, y1 = box
    radius = (y1 - y0) // 2
    draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=bg, outline=border, width=1 if border else 0)
    f = get_font(font_size, "bold" if bold else "medium")
    bbox = f.getbbox(text)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = x0 + (x1 - x0 - tw) // 2
    ty = y0 + (y1 - y0 - th) // 2 - 1
    draw.text((tx, ty), text, font=f, fill=fg)

# Helper: Geometric Icon Drawing
def draw_icon(name, x, y, size=24, color=CYAN_NEON, width=2):
    x, y = int(x), int(y)
    w = size
    h = size
    if name == "joycon_pair":
        # Left joycon (Cyan)
        draw.rounded_rectangle([x, y+2, x+w*0.42, y+h-2], radius=6, fill=CYAN_NEON)
        draw.ellipse([x+w*0.14, y+h*0.25, x+w*0.28, y+h*0.39], fill=BG_OBSIDIAN)
        # Right joycon (Crimson)
        draw.rounded_rectangle([x+w*0.58, y+2, x+w, y+h-2], radius=6, fill=CRIMSON_NEON)
        draw.ellipse([x+w*0.72, y+h*0.60, x+w*0.86, y+h*0.74], fill=BG_OBSIDIAN)
    elif name == "folder":
        draw.line([x+2, y+h*0.35, x+w*0.42, y+h*0.35, x+w*0.55, y+h*0.48, x+w-2, y+h*0.48], fill=color, width=width)
        draw.rounded_rectangle([x+2, y+h*0.35, x+w-2, y+h-2], radius=4, outline=color, width=width)
    elif name == "refresh":
        draw.arc([x+3, y+3, x+w-3, y+h-3], 35, 315, fill=color, width=width)
        draw.polygon([(x+w-2, y+4), (x+w-7, y+4), (x+w-2, y+9)], fill=color)
    elif name == "play":
        draw.polygon([(x+w*0.22, y+h*0.18), (x+w*0.84, y+h*0.50), (x+w*0.22, y+h*0.82)], fill=color)
    elif name == "gear":
        draw.ellipse([x+w*0.25, y+h*0.25, x+w*0.75, y+h*0.75], outline=color, width=width)
        for angle in range(0, 360, 45):
            rad = math.radians(angle)
            x1 = x + w*0.5 + math.cos(rad) * (w*0.32)
            y1 = y + h*0.5 + math.sin(rad) * (h*0.32)
            x2 = x + w*0.5 + math.cos(rad) * (w*0.48)
            y2 = y + h*0.5 + math.sin(rad) * (h*0.48)
            draw.line([(x1, y1), (x2, y2)], fill=color, width=width)
    elif name == "gamepad":
        draw.rounded_rectangle([x+2, y+h*0.22, x+w-2, y+h*0.78], radius=8, outline=color, width=width)
        cx, cy = x + w*0.32, y + h*0.50
        draw.line([cx-4, cy, cx+4, cy], fill=color, width=2)
        draw.line([cx, cy-4, cx, cy+4], fill=color, width=2)
        bx, by = x + w*0.68, y + h*0.50
        draw.ellipse([bx-4, by-2, bx-2, by], fill=color)
        draw.ellipse([bx+2, by-2, bx+4, by], fill=color)
    elif name == "search":
        draw.ellipse([x+3, y+3, x+w*0.65, y+h*0.65], outline=color, width=width)
        draw.line([x+w*0.55, y+h*0.55, x+w-3, y+h-3], fill=color, width=width)
    elif name == "battery":
        draw.rounded_rectangle([x+2, y+h*0.25, x+w-5, y+h*0.75], radius=3, outline=color, width=width)
        draw.rectangle([x+w-5, y+h*0.4, x-1+w, y+h*0.6], fill=color)
        draw.rectangle([x+5, y+h*0.33, x+w*0.65, y+h*0.67], fill=color)

# ==============================================================================
# SECTION 1: TOP GLOBAL STATUS & DIAGNOSTIC BAR (Y: 20 to 82)
# ==============================================================================
TOP_BAR_Y = 22
draw_card([40, TOP_BAR_Y, 1880, TOP_BAR_Y + 62], radius=18, fill=SURFACE_0, border=BORDER_SUBTLE)

# App Logo & Branding
draw_icon("joycon_pair", 58, TOP_BAR_Y + 16, size=30)
draw.text((106, TOP_BAR_Y + 14), "nxdroid", font=get_font(26, "bold"), fill=TEXT_PRIMARY)
draw_pill([228, TOP_BAR_Y + 20, 376, TOP_BAR_Y + 44], "VULKAN AARCH64", fg=CYAN_NEON, bg=(14, 38, 48), border=(0, 229, 255, 100), font_size=11)

# Center Diagnostic Chip: Samsung Galaxy S23 Ultra hardware details
CHIP_X0, CHIP_X1 = 410, 1390
draw_card([CHIP_X0, TOP_BAR_Y + 10, CHIP_X1, TOP_BAR_Y + 52], radius=14, fill=SURFACE_1, border=BORDER_SUBTLE)
# Glowing status pulse dot (Emerald green = 60 FPS optimal)
draw.ellipse([CHIP_X0 + 16, TOP_BAR_Y + 26, CHIP_X0 + 26, TOP_BAR_Y + 36], fill=GREEN_EMERALD)
diag_text = "S23 Ultra  ·  Snapdragon 8 Gen 2  ·  Adreno 740  ·  Vulkan 1.3 (512.676.1)  ·  60 FPS Target"
draw.text((CHIP_X0 + 36, TOP_BAR_Y + 20), diag_text, font=get_font(14, "medium"), fill=TEXT_PRIMARY)

# Right Status utilities (Thermal, Controller, Battery, Time)
draw_card([1410, TOP_BAR_Y + 12, 1610, TOP_BAR_Y + 50], radius=12, fill=SURFACE_1, border=BORDER_SUBTLE)
draw_icon("gamepad", 1422, TOP_BAR_Y + 18, size=24, color=CYAN_NEON)
draw.text((1456, TOP_BAR_Y + 22), "DualSense BT", font=get_font(13, "bold"), fill=TEXT_PRIMARY)

draw_card([1622, TOP_BAR_Y + 12, 1718, TOP_BAR_Y + 50], radius=12, fill=SURFACE_1, border=BORDER_SUBTLE)
draw.ellipse([1634, TOP_BAR_Y + 26, 1642, TOP_BAR_Y + 34], fill=GREEN_EMERALD)
draw.text((1650, TOP_BAR_Y + 22), "34°C", font=get_font(13, "bold"), fill=TEXT_PRIMARY)

# Battery & Clock
draw_icon("battery", 1726, TOP_BAR_Y + 21, size=20, color=TEXT_SECONDARY)
draw.text((1754, TOP_BAR_Y + 22), "94%", font=get_font(13, "medium"), fill=TEXT_SECONDARY)
draw.line([(1800, TOP_BAR_Y + 20), (1800, TOP_BAR_Y + 42)], fill=BORDER_SUBTLE, width=1)
draw.text((1818, TOP_BAR_Y + 21), "20:45", font=get_font(15, "bold"), fill=TEXT_PRIMARY)

# ==============================================================================
# SECTION 2: CUSTOM FOLDER SELECTOR BAR (The Core User Feature!) (Y: 98 to 184)
# ==============================================================================
FOLDER_Y = 98
FOLDER_H = 86
draw_card([40, FOLDER_Y, 1880, FOLDER_Y + FOLDER_H], radius=20, fill=SURFACE_CARD, border=(0, 229, 255, 110), border_width=1)
draw.rounded_rectangle([40, FOLDER_Y + 16, 46, FOLDER_Y + FOLDER_H - 16], radius=3, fill=CYAN_NEON)

# Folder Icon in frosted circular badge
draw.ellipse([64, FOLDER_Y + 18, 114, FOLDER_Y + 68], fill=(16, 42, 54))
draw_icon("folder", 77, FOLDER_Y + 31, size=24, color=CYAN_NEON)

# Path Details & Explanatory Labels
draw.text((130, FOLDER_Y + 14), "GAME DIRECTORY  (STORAGE ACCESS FRAMEWORK · PERSISTENT ACCESS)", font=get_font(11, "bold"), fill=CYAN_TEAL)
draw.text((130, FOLDER_Y + 33), "/storage/emulated/0/Games/Switch/", font=get_font(21, "bold", mono=True), fill=TEXT_PRIMARY)
draw.text((130, FOLDER_Y + 61), "Accessible without root  ·  Data preserved on app uninstall  ·  5 Switch titles discovered", font=get_font(12, "regular"), fill=TEXT_MUTED)

# Action Buttons: [ Change Folder ] and [ Rescan Library ]
BTN_CHG_X0, BTN_CHG_X1 = 1420, 1630
draw_card([BTN_CHG_X0, FOLDER_Y + 18, BTN_CHG_X1, FOLDER_Y + 68], radius=16, fill=SURFACE_2, border=(70, 90, 125), border_width=1)
draw_icon("folder", BTN_CHG_X0 + 16, FOLDER_Y + 31, size=24, color=TEXT_PRIMARY)
draw.text((BTN_CHG_X0 + 48, FOLDER_Y + 32), "Change Folder", font=get_font(15, "bold"), fill=TEXT_PRIMARY)

BTN_SCN_X0, BTN_SCN_X1 = 1646, 1856
draw_card([BTN_SCN_X0, FOLDER_Y + 18, BTN_SCN_X1, FOLDER_Y + 68], radius=16, fill=(14, 52, 54), border=CYAN_NEON, border_width=1)
draw_icon("refresh", BTN_SCN_X0 + 16, FOLDER_Y + 31, size=24, color=CYAN_NEON)
draw.text((BTN_SCN_X0 + 48, FOLDER_Y + 32), "Rescan Library", font=get_font(15, "bold"), fill=CYAN_NEON)

# ==============================================================================
# SECTION 3: MAIN DUAL-PANE WORKSPACE (Y: 198 to 990)
# ==============================================================================
CONTENT_Y = 198
HERO_W = 770
GRID_X0 = 830

# ------------------------------------------------------------------------------
# LEFT PANE: SELECTED GAME SHOWCASE (Super Mario Odyssey)
# ------------------------------------------------------------------------------
draw_card([40, CONTENT_Y, 40 + HERO_W, CONTENT_Y + 786], radius=24, fill=SURFACE_CARD, border=BORDER_SUBTLE)

# Hero Banner Artwork (New Donk City Skyline + Power Moon + Mario Cap)
BANNER_H = 340
banner_img = Image.new("RGBA", (HERO_W - 8, BANNER_H), (20, 24, 38, 255))
b_draw = ImageDraw.Draw(banner_img)

# Deep Twilight & Sunset Sky Gradient
for y_idx in range(BANNER_H):
    t = y_idx / BANNER_H
    r = int(140 * (1-t) + 15 * t)
    g = int(30 * (1-t) + 20 * t)
    b = int(80 * (1-t) + 50 * t)
    b_draw.line([(0, y_idx), (HERO_W - 8, y_idx)], fill=(r, g, b, 255))

# Starry sky dots
import random
rng = random.Random(42)
for _ in range(35):
    sx = rng.randint(20, HERO_W - 30)
    sy = rng.randint(10, int(BANNER_H * 0.6))
    sa = rng.randint(120, 240)
    b_draw.point((sx, sy), fill=(255, 255, 255, sa))

# New Donk City Skyline silhouettes in background
buildings = [(20, 110, 70), (100, 150, 60), (170, 90, 80), (260, 130, 75), (345, 80, 90), (445, 120, 70), (525, 160, 65), (600, 100, 80), (690, 140, 60)]
for bx, by, bw in buildings:
    b_draw.rectangle([bx, by, bx + bw, BANNER_H], fill=(18, 15, 32, 220))
    # little windows
    for wx in range(bx + 8, bx + bw - 8, 14):
        for wy in range(by + 16, BANNER_H - 80, 22):
            if rng.random() > 0.4:
                b_draw.rectangle([wx, wy, wx + 6, wy + 8], fill=(255, 230, 130, 180))

# Mario Odyssey Golden Power Moon
MOON_CX, MOON_CY = HERO_W - 170, 130
b_draw.ellipse([MOON_CX - 70, MOON_CY - 70, MOON_CX + 70, MOON_CY + 70], fill=(255, 225, 100, 250))
b_draw.ellipse([MOON_CX - 56, MOON_CY - 56, MOON_CX + 56, MOON_CY + 56], fill=(255, 205, 50, 255))
# Odyssey Moon expressive cartoon eyes
b_draw.ellipse([MOON_CX - 28, MOON_CY - 16, MOON_CX - 12, MOON_CY + 18], fill=(30, 20, 10, 240))
b_draw.ellipse([MOON_CX + 12, MOON_CY - 16, MOON_CX + 28, MOON_CY + 18], fill=(30, 20, 10, 240))
b_draw.ellipse([MOON_CX - 22, MOON_CY - 10, MOON_CX - 16, MOON_CY - 2], fill=(255, 255, 255, 255))
b_draw.ellipse([MOON_CX + 18, MOON_CY - 10, MOON_CX + 24, MOON_CY - 2], fill=(255, 255, 255, 255))

# Mario Cappy Red Hat in foreground
b_draw.ellipse([80, 170, 360, 290], fill=(225, 25, 45, 240))
b_draw.rounded_rectangle([70, 235, 370, 285], radius=24, fill=(195, 18, 35, 250))
# White M Emblem
b_draw.ellipse([175, 175, 265, 245], fill=(255, 255, 255, 255))
b_draw.text((200, 176), "M", font=get_font(44, "bold"), fill=(220, 20, 40))

# Dark Vignette overlay for text readability
vignette = Image.new("RGBA", (HERO_W - 8, BANNER_H), (0, 0, 0, 0))
v_draw = ImageDraw.Draw(vignette)
for y_idx in range(BANNER_H):
    alpha = int(255 * (y_idx / BANNER_H) ** 2.2)
    v_draw.line([(0, y_idx), (HERO_W - 8, y_idx)], fill=(18, 24, 36, alpha))
banner_img = Image.alpha_composite(banner_img, vignette)

banner_mask = Image.new("L", (HERO_W - 8, BANNER_H), 0)
ImageDraw.Draw(banner_mask).rounded_rectangle([0, 0, HERO_W - 9, BANNER_H - 1], radius=20, fill=255)
img.paste(banner_img, (44, CONTENT_Y + 4), banner_mask)
draw = ImageDraw.Draw(img)

# Hero Overlay Badges
draw_pill([64, CONTENT_Y + 24, 210, CONTENT_Y + 54], "SELECTED GAME", fg=CYAN_NEON, bg=(10, 20, 30, 220), border=CYAN_NEON, font_size=11)
draw_pill([222, CONTENT_Y + 24, 396, CONTENT_Y + 54], "VERIFIED 60 FPS · DOCKED", fg=GREEN_EMERALD, bg=(12, 34, 24, 220), border=GREEN_EMERALD, font_size=11)

# Hero Title & Metadata
draw.text((64, CONTENT_Y + 260), "Super Mario Odyssey", font=get_font(34, "bold"), fill=TEXT_PRIMARY)
draw.text((64, CONTENT_Y + 304), "Nintendo EPD  ·  3D Platformer  ·  Version 1.3.0 (Base + All DLC)", font=get_font(15, "medium"), fill=TEXT_SECONDARY)

# Specs Grid
SPEC_Y0 = CONTENT_Y + 360
draw_card([64, SPEC_Y0, 40 + HERO_W - 24, SPEC_Y0 + 170], radius=16, fill=SURFACE_0, border=BORDER_SUBTLE)
draw.text((88, SPEC_Y0 + 18), "TITLE ID", font=get_font(11, "bold"), fill=TEXT_MUTED)
draw.text((88, SPEC_Y0 + 38), "010015100B514000", font=get_font(15, "bold", mono=True), fill=TEXT_PRIMARY)
draw.text((430, SPEC_Y0 + 18), "PACKAGE SIZE", font=get_font(11, "bold"), fill=TEXT_MUTED)
draw.text((430, SPEC_Y0 + 38), "5.7 GB (RomFS + Patch NSO)", font=get_font(15, "bold"), fill=TEXT_PRIMARY)

draw.line([(88, SPEC_Y0 + 85), (40 + HERO_W - 48, SPEC_Y0 + 85)], fill=BORDER_SUBTLE, width=1)

draw.text((88, SPEC_Y0 + 98), "GRAPHICS TRANSLATOR", font=get_font(11, "bold"), fill=TEXT_MUTED)
draw.text((88, SPEC_Y0 + 118), "NVN → Vulkan 1.3 (Adreno 740 native)", font=get_font(15, "bold"), fill=CYAN_TEAL)
draw.text((430, SPEC_Y0 + 98), "PIPELINE CACHE", font=get_font(11, "bold"), fill=TEXT_MUTED)
draw.text((430, SPEC_Y0 + 118), "2,841 Prewarmed (No Stutter)", font=get_font(15, "bold"), fill=GREEN_EMERALD)

# Launch Button
BTN_PLAY_Y0 = SPEC_Y0 + 192
BTN_PLAY_H = 68
play_box = [64, BTN_PLAY_Y0, 40 + HERO_W - 24, BTN_PLAY_Y0 + BTN_PLAY_H]

play_btn = Image.new("RGBA", (play_box[2]-play_box[0], BTN_PLAY_H), (0, 0, 0, 0))
p_draw = ImageDraw.Draw(play_btn)
btn_w = play_box[2] - play_box[0]
for x_idx in range(btn_w):
    t = x_idx / btn_w
    r = int(0 * (1-t) + 0 * t)
    g = int(229 * (1-t) + 160 * t)
    b = int(255 * (1-t) + 255 * t)
    p_draw.line([(x_idx, 0), (x_idx, BTN_PLAY_H)], fill=(r, g, b, 255))

play_mask = Image.new("L", (btn_w, BTN_PLAY_H), 0)
ImageDraw.Draw(play_mask).rounded_rectangle([0, 0, btn_w-1, BTN_PLAY_H-1], radius=18, fill=255)
img.paste(play_btn, (play_box[0], play_box[1]), play_mask)
draw = ImageDraw.Draw(img)

draw_icon("play", play_box[0] + btn_w//2 - 130, BTN_PLAY_Y0 + 19, size=28, color=TEXT_DARK)
draw.text((play_box[0] + btn_w//2 - 90, BTN_PLAY_Y0 + 19), "LAUNCH GAME", font=get_font(24, "bold"), fill=TEXT_DARK)

# Sub Action Controls
SUB_ACT_Y = BTN_PLAY_Y0 + 86
SUB_ACT_H = 50
sub_w = (btn_w - 24) // 3

draw_card([64, SUB_ACT_Y, 64 + sub_w, SUB_ACT_Y + SUB_ACT_H], radius=14, fill=SURFACE_1, border=BORDER_SUBTLE)
draw_icon("gamepad", 80, SUB_ACT_Y + 13, size=22, color=CYAN_NEON)
draw.text((112, SUB_ACT_Y + 16), "Touch Overlay", font=get_font(14, "bold"), fill=TEXT_PRIMARY)

draw_card([64 + sub_w + 12, SUB_ACT_Y, 64 + sub_w*2 + 12, SUB_ACT_Y + SUB_ACT_H], radius=14, fill=SURFACE_1, border=BORDER_SUBTLE)
draw_icon("gear", 64 + sub_w + 26, SUB_ACT_Y + 13, size=22, color=TEXT_SECONDARY)
draw.text((64 + sub_w + 58, SUB_ACT_Y + 16), "Game Settings", font=get_font(14, "bold"), fill=TEXT_PRIMARY)

draw_card([64 + sub_w*2 + 24, SUB_ACT_Y, 64 + sub_w*3 + 24, SUB_ACT_Y + SUB_ACT_H], radius=14, fill=SURFACE_1, border=BORDER_SUBTLE)
draw_icon("folder", 64 + sub_w*2 + 38, SUB_ACT_Y + 13, size=22, color=TEXT_SECONDARY)
draw.text((64 + sub_w*2 + 70, SUB_ACT_Y + 16), "Save Data", font=get_font(14, "bold"), fill=TEXT_PRIMARY)

# ------------------------------------------------------------------------------
# RIGHT PANE: DISCOVERED TITLES GRID (X: 830 to 1880)
# ------------------------------------------------------------------------------
TAB_Y = CONTENT_Y + 4
draw.text((GRID_X0, TAB_Y + 4), "Discovered Titles", font=get_font(24, "bold"), fill=TEXT_PRIMARY)

TAB_BTN_X = GRID_X0 + 260
draw_pill([TAB_BTN_X, TAB_Y + 2, TAB_BTN_X + 110, TAB_Y + 36], "All (5)", fg=TEXT_PRIMARY, bg=SURFACE_2, border=CYAN_NEON, font_size=13)
draw_pill([TAB_BTN_X + 120, TAB_Y + 2, TAB_BTN_X + 250, TAB_Y + 36], "Favorites (2)", fg=TEXT_SECONDARY, bg=SURFACE_0, border=BORDER_SUBTLE, font_size=13)
draw_pill([TAB_BTN_X + 260, TAB_Y + 2, TAB_BTN_X + 380, TAB_Y + 36], "Recent (3)", fg=TEXT_SECONDARY, bg=SURFACE_0, border=BORDER_SUBTLE, font_size=13)

SEARCH_X0 = 1550
draw_card([SEARCH_X0, TAB_Y, 1880, TAB_Y + 38], radius=12, fill=SURFACE_0, border=BORDER_SUBTLE)
draw_icon("search", SEARCH_X0 + 12, TAB_Y + 10, size=18, color=TEXT_MUTED)
draw.text((SEARCH_X0 + 38, TAB_Y + 9), "Search games or title IDs...", font=get_font(13, "medium"), fill=TEXT_MUTED)

GRID_TOP_Y = CONTENT_Y + 54
CARD_W = 510
CARD_H = 354
GRID_GAP_X = 28
GRID_GAP_Y = 24

# Artwork renderer functions for each game
def render_zelda_art(w, h):
    art = Image.new("RGBA", (w, h), (14, 28, 32, 255))
    d = ImageDraw.Draw(art)
    # Emerald sky gradient
    for y in range(h):
        t = y / h
        d.line([(0, y), (w, y)], fill=(int(8*(1-t)+22*t), int(45*(1-t)+65*t), int(40*(1-t)+55*t), 255))
    # Sky islands floating
    d.ellipse([w*0.08, h*0.55, w*0.45, h*0.75], fill=(22, 50, 42, 230))
    d.polygon([(w*0.12, h*0.65), (w*0.25, h*0.95), (w*0.38, h*0.65)], fill=(18, 42, 36, 230))
    # Zonai green spiral energy circles
    for r in range(20, 80, 18):
        d.ellipse([w*0.72 - r, h*0.45 - r, w*0.72 + r, h*0.45 + r], outline=(0, 229, 180, 140), width=2)
    # Golden Triforce at top center
    tx, ty = int(w * 0.72), int(h * 0.45)
    s = 28
    # top tri
    d.polygon([(tx, ty - s), (tx + s//2, ty), (tx - s//2, ty)], fill=GOLD_SHINE)
    # bottom left tri
    d.polygon([(tx - s//2, ty), (tx, ty + s), (tx - s, ty + s)], fill=GOLD_SHINE)
    # bottom right tri
    d.polygon([(tx + s//2, ty), (tx + s, ty + s), (tx, ty + s)], fill=GOLD_SHINE)
    return art

def render_metroid_art(w, h):
    art = Image.new("RGBA", (w, h), (26, 15, 25, 255))
    d = ImageDraw.Draw(art)
    # Biome gradient
    for y in range(h):
        t = y / h
        d.line([(0, y), (w, y)], fill=(int(60*(1-t)+18*t), int(15*(1-t)+12*t), int(25*(1-t)+30*t), 255))
    # High-tech hex radar
    cx, cy = int(w * 0.75), int(h * 0.48)
    for rad in (25, 50, 75):
        points = []
        for a in range(0, 360, 60):
            ra = math.radians(a)
            points.append((cx + math.cos(ra) * rad, cy + math.sin(ra) * rad))
        d.polygon(points, outline=(255, 51, 102, 120), width=2)
    # E.M.M.I. glowing optical lens / Samus Visor
    d.ellipse([cx - 20, cy - 20, cx + 20, cy + 20], fill=(255, 30, 60, 240))
    d.ellipse([cx - 10, cy - 10, cx + 10, cy + 10], fill=(255, 230, 230, 255))
    # Left mechanical armor plating
    d.polygon([(10, h-10), (w*0.35, h*0.35), (w*0.48, h-10)], fill=(40, 25, 45, 220))
    d.line([(w*0.35, h*0.35), (w*0.48, h-10)], fill=(0, 229, 255, 200), width=3)
    return art

def render_balatro_art(w, h):
    art = Image.new("RGBA", (w, h), (30, 15, 42, 255))
    d = ImageDraw.Draw(art)
    # Synthwave purple gradient
    for y in range(h):
        t = y / h
        d.line([(0, y), (w, y)], fill=(int(55*(1-t)+15*t), int(20*(1-t)+12*t), int(75*(1-t)+35*t), 255))
    # Perspective retro grid
    for gx in range(0, w, 32):
        d.line([(gx, int(h * 0.65)), (int(w*0.5 + (gx - w*0.5)*2.5), h)], fill=(139, 92, 246, 60), width=1)
    # Tilted Playing Cards
    # Card 1: Ace of Spades
    card_w, card_h = 70, 95
    c1_x, c1_y = int(w * 0.62), int(h * 0.22)
    d.rounded_rectangle([c1_x, c1_y, c1_x + card_w, c1_y + card_h], radius=6, fill=(245, 240, 250, 240), outline=(200, 180, 230), width=2)
    # Spade symbol ♠
    d.ellipse([c1_x + 28, c1_y + 35, c1_x + 42, c1_y + 50], fill=(20, 15, 30))
    d.polygon([(c1_x + 35, c1_y + 24), (c1_x + 44, c1_y + 40), (c1_x + 26, c1_y + 40)], fill=(20, 15, 30))
    d.polygon([(c1_x + 33, c1_y + 45), (c1_x + 37, c1_y + 45), (c1_x + 35, c1_y + 56)], fill=(20, 15, 30))
    # Card 2: Ace of Hearts (tilted slightly)
    c2_x, c2_y = int(w * 0.74), int(h * 0.28)
    d.rounded_rectangle([c2_x, c2_y, c2_x + card_w, c2_y + card_h], radius=6, fill=(255, 250, 250, 240), outline=(255, 150, 170), width=2)
    # Heart symbol ♥
    hx, hy = c2_x + 35, c2_y + 40
    d.ellipse([hx - 12, hy - 8, hx, hy + 4], fill=(225, 30, 60))
    d.ellipse([hx, hy - 8, hx + 12, hy + 4], fill=(225, 30, 60))
    d.polygon([(hx - 12, hy), (hx + 12, hy), (hx, hy + 16)], fill=(225, 30, 60))
    return art

def render_animal_crossing_art(w, h):
    art = Image.new("RGBA", (w, h), (18, 38, 28, 255))
    d = ImageDraw.Draw(art)
    # Tropical gradient
    for y in range(h):
        t = y / h
        d.line([(0, y), (w, y)], fill=(int(15*(1-t)+25*t), int(60*(1-t)+40*t), int(50*(1-t)+30*t), 255))
    # Tropical warm sun
    d.ellipse([w*0.70 - 45, h*0.40 - 45, w*0.70 + 45, h*0.40 + 45], fill=(255, 210, 80, 230))
    # Sandy island shore
    d.ellipse([w*0.40, h*0.65, w*1.10, h*1.20], fill=(235, 195, 120, 240))
    # Iconic Animal Crossing Green Leaf
    lx, ly = int(w * 0.28), int(h * 0.45)
    d.ellipse([lx - 35, ly - 45, lx + 35, ly + 45], fill=(52, 211, 153, 240))
    # Cutout notch
    d.ellipse([lx + 10, ly - 30, lx + 35, ly - 5], fill=(18, 38, 28, 255))
    # Leaf stem
    d.line([(lx, ly - 35), (lx, ly + 35)], fill=(20, 80, 50), width=3)
    return art

GAMES_DATA = [
    {
        "title": "Zelda: Tears of the Kingdom",
        "tid": "0100F2C0115B6000",
        "size": "16.3 GB",
        "api": "NVN",
        "fps": "30 / 60 FPS",
        "status": "Playable",
        "status_color": GREEN_EMERALD,
        "renderer": render_zelda_art,
        "is_focused": True
    },
    {
        "title": "Metroid Dread",
        "tid": "010093801237C000",
        "size": "4.2 GB",
        "api": "NVN",
        "fps": "60 FPS Flawless",
        "status": "Playable",
        "status_color": GREEN_EMERALD,
        "renderer": render_metroid_art,
        "is_focused": False
    },
    {
        "title": "Balatro",
        "tid": "0100CD801CE5E000",
        "size": "320 MB",
        "api": "OpenGL",
        "fps": "60 FPS Native",
        "status": "Playable",
        "status_color": GREEN_EMERALD,
        "renderer": render_balatro_art,
        "is_focused": False
    },
    {
        "title": "Animal Crossing: New Horizons",
        "tid": "01006F8002326000",
        "size": "6.9 GB",
        "api": "NVN",
        "fps": "30 FPS",
        "status": "Playable",
        "status_color": GREEN_EMERALD,
        "renderer": render_animal_crossing_art,
        "is_focused": False
    }
]

def render_grid_card(cx, cy, g):
    # Card outer
    border_col = CYAN_NEON if g.get("is_focused") else BORDER_SUBTLE
    border_w = 2 if g.get("is_focused") else 1
    draw_card([cx, cy, cx + CARD_W, cy + CARD_H], radius=20, fill=SURFACE_CARD, border=border_col, border_width=border_w)
    
    # Custom Art Header
    art_h = 190
    card_art = g["renderer"](CARD_W - 6, art_h)
    
    # Vignette
    c_vig = Image.new("RGBA", (CARD_W - 6, art_h), (0, 0, 0, 0))
    cv_draw = ImageDraw.Draw(c_vig)
    for y_idx in range(art_h):
        a = int(245 * (y_idx / art_h) ** 2.2)
        cv_draw.line([(0, y_idx), (CARD_W - 6, y_idx)], fill=(18, 24, 36, a))
    card_art = Image.alpha_composite(card_art, c_vig)
    
    card_mask = Image.new("L", (CARD_W - 6, art_h), 0)
    ImageDraw.Draw(card_mask).rounded_rectangle([0, 0, CARD_W - 7, art_h - 1], radius=18, fill=255)
    img.paste(card_art, (cx + 3, cy + 3), card_mask)
    
    # Artwork Badges
    draw_pill([cx + 16, cy + 14, cx + 110, cy + 38], g["api"], fg=TEXT_PRIMARY, bg=(10, 16, 26, 210), border=BORDER_SUBTLE, font_size=11)
    draw_pill([cx + CARD_W - 146, cy + 14, cx + CARD_W - 16, cy + 38], g["fps"], fg=CYAN_NEON, bg=(10, 16, 26, 210), border=(0, 229, 255, 120), font_size=11)
    
    # Game Title
    draw.text((cx + 18, cy + art_h + 16), g["title"], font=get_font(20, "bold"), fill=TEXT_PRIMARY)
    
    # Title ID & Rom size
    meta_str = f"{g['tid']}   ·   {g['size']}"
    draw.text((cx + 18, cy + art_h + 46), meta_str, font=get_font(13, "medium", mono=True), fill=TEXT_SECONDARY)
    
    # Status Row
    ROW_Y = cy + CARD_H - 52
    draw.ellipse([cx + 18, ROW_Y + 10, cx + 28, ROW_Y + 20], fill=g["status_color"])
    draw.text((cx + 36, ROW_Y + 7), g["status"], font=get_font(13, "bold"), fill=g["status_color"])
    
    # Select button
    BTN_QL_X0 = cx + CARD_W - 140
    btn_bg = (14, 52, 54) if g.get("is_focused") else SURFACE_1
    btn_border = CYAN_NEON if g.get("is_focused") else (60, 80, 110)
    draw_card([BTN_QL_X0, ROW_Y - 4, cx + CARD_W - 16, ROW_Y + 36], radius=12, fill=btn_bg, border=btn_border)
    draw_icon("play", BTN_QL_X0 + 14, ROW_Y + 4, size=18, color=CYAN_NEON)
    draw.text((BTN_QL_X0 + 40, ROW_Y + 4), "Select", font=get_font(14, "bold"), fill=TEXT_PRIMARY)

for idx, g in enumerate(GAMES_DATA):
    col = idx % 2
    row = idx // 2
    cx = GRID_X0 + col * (CARD_W + GRID_GAP_X)
    cy = GRID_TOP_Y + row * (CARD_H + GRID_GAP_Y)
    render_grid_card(cx, cy, g)

# ==============================================================================
# SECTION 4: CONSOLE FOOTER & GAMEPAD NAVIGATION SHORTCUTS (Y: 1004 to 1066)
# ==============================================================================
FOOTER_Y = 1004
draw_card([40, FOOTER_Y, 1880, FOOTER_Y + 58], radius=16, fill=SURFACE_0, border=BORDER_SUBTLE)

def draw_controller_hint(x, y, btn_letter, action_label, btn_color=CYAN_NEON):
    draw.ellipse([x, y, x + 24, y + 24], outline=btn_color, width=2)
    draw.text((x + 7, y + 3), btn_letter, font=get_font(13, "bold"), fill=btn_color)
    draw.text((x + 32, y + 4), action_label, font=get_font(14, "medium"), fill=TEXT_PRIMARY)
    return x + 32 + int(len(action_label) * 8.5) + 30

hx = 64
hx = draw_controller_hint(hx, FOOTER_Y + 16, "A", "Launch Game", CYAN_NEON)
hx = draw_controller_hint(hx, FOOTER_Y + 16, "X", "Game Config", TEXT_SECONDARY)
hx = draw_controller_hint(hx, FOOTER_Y + 16, "Y", "Scan Folder", CYAN_TEAL)
hx = draw_controller_hint(hx, FOOTER_Y + 16, "+", "Global Settings", CRIMSON_NEON)
hx = draw_controller_hint(hx, FOOTER_Y + 16, "L", "Prev Tab", TEXT_MUTED)
hx = draw_controller_hint(hx, FOOTER_Y + 16, "R", "Next Tab", TEXT_MUTED)

draw.text((1580, FOOTER_Y + 20), "nxdroid v0.1.0-alpha · AArch64 Host Runtime", font=get_font(13, "medium"), fill=TEXT_MUTED)

# Save image
os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
img.convert("RGB").save(OUT_PATH, "PNG", optimize=True)
print(f"Successfully generated mockup at: {OUT_PATH}")
