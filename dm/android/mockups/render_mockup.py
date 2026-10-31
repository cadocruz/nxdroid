#!/usr/bin/env python3
"""Render the nxdroid Android landscape home screen concept."""

from PIL import Image, ImageDraw, ImageFont
import math
import os


W, H = 1920, 1080
OUT = os.path.join(os.path.dirname(__file__), "mockup_opencode.png")

BG = (10, 13, 21)
PANEL = (18, 23, 34)
PANEL2 = (24, 31, 45)
LINE = (39, 49, 67)
TEXT = (241, 244, 250)
MUTED = (144, 157, 179)
DIM = (99, 114, 137)
MINT = (105, 239, 197)
BLUE = (106, 155, 255)
AMBER = (255, 190, 101)

im = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(im)


def font(size, bold=False):
    candidates = [
        "/usr/share/fonts/truetype/space-grotesk/SpaceGrotesk-Bold.ttf" if bold else "/usr/share/fonts/truetype/space-grotesk/SpaceGrotesk-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def rounded(box, radius, fill, outline=None, width=1):
    d.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def label(x, y, s, size=18, color=TEXT, bold=False, anchor=None):
    d.text((x, y), s, font=font(size, bold), fill=color, anchor=anchor)


def line(points, fill=LINE, width=1):
    d.line(points, fill=fill, width=width, joint="curve")


def icon(kind, x, y, color=MUTED, scale=1):
    # Simple geometric line icons, centered in a 24px area.
    x, y = int(x), int(y)
    sw = max(2, int(2 * scale))
    if kind == "home":
        line([(x+3,y+11),(x+12,y+3),(x+21,y+11)], color, sw)
        d.rectangle((x+6,y+10,x+18,y+21), outline=color, width=sw)
        line([(x+11,y+21),(x+11,y+15),(x+15,y+15),(x+15,y+21)], color, sw)
    elif kind == "grid":
        for xx in (4, 13):
            for yy in (4, 13):
                rounded((x+xx,y+yy,x+xx+6,y+yy+6), 1, None, color, sw)
    elif kind == "pad":
        rounded((x+2,y+7,x+22,y+19), 6, None, color, sw)
        line([(x+7,y+10),(x+7,y+16)], color, sw)
        line([(x+4,y+13),(x+10,y+13)], color, sw)
        d.ellipse((x+15,y+10,x+17,y+12), fill=color)
        d.ellipse((x+18,y+14,x+20,y+16), fill=color)
    elif kind == "gear":
        d.ellipse((x+5,y+5,x+19,y+19), outline=color, width=sw)
        d.ellipse((x+10,y+10,x+14,y+14), outline=color, width=sw)
        for a in range(0,360,45):
            r1,r2=9,12
            p1=(x+12+math.cos(math.radians(a))*r1,y+12+math.sin(math.radians(a))*r1)
            p2=(x+12+math.cos(math.radians(a))*r2,y+12+math.sin(math.radians(a))*r2)
            line([p1,p2], color, sw)
    elif kind == "folder":
        rounded((x+2,y+6,x+22,y+20), 3, None, color, sw)
        line([(x+3,y+7),(x+9,y+7),(x+11,y+10),(x+21,y+10)], color, sw)
    elif kind == "refresh":
        d.arc((x+3,y+3,x+21,y+21), 35, 315, fill=color, width=sw)
        line([(x+18,y+4),(x+21,y+4),(x+21,y+7)], color, sw)
    elif kind == "play":
        d.polygon([(x+7,y+4),(x+20,y+12),(x+7,y+20)], fill=color)
    elif kind == "chevron":
        line([(x+7,y+4),(x+15,y+12),(x+7,y+20)], color, sw)
    elif kind == "check":
        line([(x+4,y+12),(x+10,y+18),(x+21,y+5)], color, sw)
    elif kind == "device":
        rounded((x+3,y+2,x+21,y+22), 4, None, color, sw)
        line([(x+8,y+18),(x+16,y+18)], color, sw)


def badge(x, y, w, text, fg, bg=(29, 43, 47)):
    rounded((x,y,x+w,y+32), 16, bg)
    d.ellipse((x+11,y+12,x+19,y+20), fill=fg)
    label(x+28,y+7,text,14,fg,True)


def abstract_art(box, theme, title, subtitle, mark):
    x1,y1,x2,y2=box
    # Colorful original geometric cover art, clipped to a rounded card.
    art = Image.new("RGB", (x2-x1,y2-y1), theme[0])
    ad = ImageDraw.Draw(art)
    aw,ah=art.size
    for yy in range(ah):
        t=yy/max(1,ah-1)
        c=tuple(int(theme[0][i]*(1-t)+theme[1][i]*t) for i in range(3))
        ad.line((0,yy,aw,yy), fill=c)
    # atmospheric rings, angular shards, and a stylized central emblem
    ad.ellipse((int(aw*.50),int(ah*.10),int(aw*1.12),int(ah*.93)), outline=theme[2], width=max(3,aw//80))
    ad.ellipse((int(aw*.59),int(ah*.20),int(aw*1.00),int(ah*.83)), outline=(245,235,208), width=max(2,aw//140))
    ad.polygon([(0,int(ah*.78)),(int(aw*.30),int(ah*.40)),(int(aw*.53),ah),(0,ah)], fill=theme[3])
    ad.polygon([(int(aw*.09),ah),(int(aw*.40),int(ah*.57)),(int(aw*.54),ah)], fill=theme[2])
    cx,cy=int(aw*.77),int(ah*.53)
    ad.polygon([(cx,cy-int(ah*.23)),(cx+int(aw*.10),cy),(cx,cy+int(ah*.23)),(cx-int(aw*.10),cy)], fill=(245,231,189))
    ad.ellipse((cx-int(aw*.033),cy-int(ah*.06),cx+int(aw*.033),cy+int(ah*.06)), fill=theme[1])
    # round mask
    mask=Image.new("L",art.size,0)
    ImageDraw.Draw(mask).rounded_rectangle((0,0,aw-1,ah-1),radius=20,fill=255)
    im.paste(art,(x1,y1),mask)
    label(x1+22,y1+17,mark,13,(255,255,255),True)
    label(x1+22,y2-61,title,20,(255,255,255),True)
    label(x1+22,y2-34,subtitle,13,(228,232,238))


# Ambient glows
glow = Image.new("RGBA", (W,H), (0,0,0,0))
gd=ImageDraw.Draw(glow)
gd.ellipse((680,-350,1830,400), fill=(40,75,130,40))
gd.ellipse((1200,550,2100,1300), fill=(23,117,102,18))
im=Image.alpha_composite(im.convert("RGBA"),glow).convert("RGB")
d=ImageDraw.Draw(im)

# Navigation rail
d.rectangle((0,0,228,H), fill=(13,17,26))
line([(228,0),(228,H)], (31,39,53), 1)
rounded((31,27,77,73),14,(31,55,56))
# custom Joy-Con inspired mark
rounded((43,37,64,63),9,(105,239,197))
d.rectangle((52,37,55,63),fill=(31,55,56))
label(91,30,"nxdroid",27,TEXT,True)
label(32,111,"YOUR LIBRARY",12,DIM,True)

nav=[("home","Home",True),("grid","Games",False),("pad","Controls",False),("gear","Settings",False)]
for i,(ic,txt,sel) in enumerate(nav):
    yy=146+i*64
    if sel:
        rounded((18,yy,210,yy+50),15,(31,45,50))
        rounded((18,yy+12,21,yy+38),2,MINT)
    icon(ic,37,yy+13,MINT if sel else MUTED)
    label(76,yy+14,txt,17,TEXT if sel else MUTED,sel)

rounded((20,874,208,1035),18,(18,24,35),LINE)
icon("device",37,894,MINT)
label(70,893,"READY TO PLAY",12,MINT,True)
label(36,934,"Controller",15,TEXT,True)
label(36,960,"Not connected",13,MUTED)
rounded((36,991,192,1020),10,(31,40,55))
label(114,997,"Pair controller",12,TEXT,True,"mm")

# Main top bar
label(270,31,"GOOD EVENING",12,MUTED,True)
label(270,52,"Your games, ready when you are.",30,TEXT,True)
rounded((1498,30,1882,82),17,(18,24,35),LINE)
rounded((1511,40,1548,77),12,(34,54,57))
icon("device",1518,46,MINT,0.8)
label(1562,37,"GALAXY S23 ULTRA",11,MUTED,True)
label(1562,55,"Snapdragon 8 Gen 2  ·  Adreno 740",14,TEXT,True)

# Quick action bar - Play / Scan / Refresh / Settings / Controller mapping
rounded((266,104,775,148),13,MINT)
icon("play",283,117,(10,24,23),0.85)
label(313,118,"PLAY NOW",17,(10,24,23),True)
rounded((810,106,1015,146),12,(24,31,45),LINE)
icon("refresh",821,117,MUTED,0.85)
label(853,119,"Scan / Refresh",13,TEXT,True)
rounded((1050,106,1260,146),12,(24,31,45),LINE)
icon("gear",1062,117,MUTED,0.85)
label(1098,119,"Settings",13,TEXT,True)
rounded((1295,106,1505,146),12,(24,31,45),LINE)
icon("pad",1317,117,MUTED,0.85)
label(1353,119,"Controller Mapping",13,TEXT,True)

# Folder selection bar - deliberately prominent and persistent
rounded((266,166,1884,243),18,(18,24,35),LINE)
rounded((283,182,329,228),13,(30,45,48))
icon("folder",294,193,MINT)
label(348,179,"GAME LIBRARY FOLDER",11,MUTED,True)
label(348,200,"/storage/emulated/0/Games/Switch",19,TEXT,True)
rounded((1500,182,1695,227),13,(31,40,55))
icon("folder",1512,192,MUTED,0.85)
label(1545,195,"Change folder",15,TEXT,True)
rounded((1710,182,1866,227),13,(31,66,61))
icon("refresh",1722,192,MINT,0.85)
label(1754,195,"Scan library",15,MINT,True)

# Main featured game card
rounded((266,266,1240,698),24,(18,24,35),LINE)
abstract_art((284,284,1222,678),((32,75,92),(27,39,59),(142,195,169),(47,105,111)),"THE LEGEND OF ZELDA", "TEARS OF THE KINGDOM   ·   16.8 GB", "FEATURED  /  01")
overlay=Image.new("RGBA",(938,398),(0,0,0,0)); od=ImageDraw.Draw(overlay)
for xx in range(938):
    alpha=int(165*(1-xx/938)**2)
    od.line((xx,0,xx,398),fill=(5,9,17,alpha))
im.paste(overlay,(284,284),overlay); d=ImageDraw.Draw(im)
badge(312,524,133,"INSTALLED",MINT,(25,48,46))
label(312,570,"The Legend of",17,(225,233,240))
label(312,592,"Zelda: Tears of the Kingdom",30,TEXT,True)
label(312,637,"0100F2C0115B6000   ·   Last played 2 days ago",13,(194,205,220))
rounded((312,649,481,695),14,MINT)
icon("play",329,659,(10,24,23),0.85)
label(359,660,"Play now",16,(10,24,23),True)
label(1116,657,"A",14,(255,255,255),True)
rounded((1140,652,1203,688),11,(255,255,255,35), (255,255,255,65))
label(1172,660,"DETAILS",10,(255,255,255),True,"mt")

# Device / engine status panel
rounded((1260,266,1884,698),24,(18,24,35),LINE)
label(1292,293,"DEVICE & ENGINE",13,MUTED,True)
rounded((1773,286,1847,313),13,(32,52,48))
label(1810,293,"READY",11,MINT,True,"mt")
label(1292,330,"Galaxy S23 Ultra",24,TEXT,True)
label(1292,364,"Snapdragon 8 Gen 2  ·  Adreno 740",15,MUTED)
line([(1292,402),(1852,402)],LINE)
label(1292,422,"GRAPHICS API",11,DIM,True)
label(1292,445,"Vulkan 1.3.128",18,TEXT,True)
label(1292,478,"Driver 512.676.1",13,MUTED)
label(1580,422,"TARGET",11,DIM,True)
label(1580,445,"60 FPS",18,TEXT,True)
label(1580,478,"Landscape  ·  2340 × 1080",13,MUTED)
line([(1292,509),(1852,509)],LINE)
rounded((1292,531,1852,592),16,(22,31,42))
rounded((1307,544,1335,572),9,(34,54,56))
icon("check",1311,546,MINT,0.7)
label(1347,541,"Runtime is ready",15,TEXT,True)
label(1347,564,"Vulkan runtime",12,MUTED)
label(1292,620,"PERFORMANCE PROFILE",11,DIM,True)
label(1852,619,"Balanced",14,BLUE,True,"ra")
rounded((1292,650,1852,656),3,(39,49,67))
rounded((1292,650,1610,656),3,MINT)

# Library header and tools
label(270,736,"Recently added",23,TEXT,True)
label(270,769,"3 games in this folder",13,MUTED)
rounded((1453,737,1590,779),13,(18,24,35),LINE)
label(1522,749,"All games",14,TEXT,True)
rounded((1602,737,1760,779),13,(18,24,35),LINE)
icon("grid",1614,747,MUTED,0.75)
label(1644,749,"Sort: recent",13,TEXT,True)
rounded((1772,737,1882,779),13,(18,24,35),LINE)
label(1827,749,"Filter  ▾",13,TEXT,True)

# Compact game cards
cards=[
    (266,((109,72,47),(48,43,54),(233,177,105),(86,59,52)),"METROID DREAD","5.2 GB","010093801237C000","PLAYABLE",MINT),
    (806,((45,72,113),(35,43,70),(146,188,235),(50,62,107)),"HOLLOW KNIGHT","1.1 GB","0100633007D48000","PLAYABLE",MINT),
    (1346,((94,51,69),(53,38,70),(238,150,171),(119,62,103)),"CELESTE","1.8 GB","0100B7D0022EE000","READY TO SCAN",AMBER),
]
for x,theme,title,size,tid,status,scol in cards:
    rounded((x,798,x+518,1079),20,(18,24,35),LINE)
    abstract_art((x+12,810,x+506,960),theme,title,"NINTENDO SWITCH  ·  "+size,"")
    label(x+22,982,title,17,TEXT,True)
    label(x+22,1010,tid,12,MUTED)
    d.ellipse((x+23,1046,x+31,1054),fill=scol)
    label(x+40,1042,status,12,scol,True)
    if x==266:
        rounded((x+393,1027,x+494,1065),12,(31,66,61))
        icon("play",x+404,1036,(10,24,23),0.7)
        label(x+432,1039,"Play",13,MINT,True)
    else:
        icon("chevron",x+475,1036,DIM,0.7)

# Bottom hint and footer
line([(266,1105),(1884,1105)],(31,39,53))
label(270,1119,"TIP",10,MINT,True)
label(306,1116,"Choose any folder you own. Your library stays linked through Android’s document picker.",12,MUTED)
label(1882,1117,"v0.1.0  ·  ANDROID",10,DIM,True,"ra")

im.save(OUT, "PNG", optimize=True)
print(OUT)
