from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import numpy as np
import math
import random
import time

import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

MODEL = Path(__file__).resolve().parent.parent / 'models' / 'hand_landmarker.task'
EMOJIS = ['✌️', '🖐️', '✊', '👍', '👎', '☝️', '🤘', '🤙', '👌', '🤏']
KEYS = ['victory', 'palm', 'fist', 'up', 'down', 'point', 'rock', 'shaka', 'ok', 'pinch']
EMOJI_FONT = ImageFont.truetype('/System/Library/Fonts/Apple Color Emoji.ttc', 40)
TEXT_FONT = ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial Bold.ttf', 58)

LABELS = {'victory':'PEACE', 'palm':'MAGIC', 'fist':'BOOM!', 'up':'GREAT!', 'down':'OH NO!', 'point':'STAR', 'rock':'ROCK!', 'shaka':'ALOHA!', 'ok':'BUBBLES', 'pinch':'PLANET'}


def classify(hand):
    p = [(v.x, v.y) for v in hand]
    dist = lambda a, b: math.dist(p[a], p[b])
    scale = max(dist(0, 9), 0.001)
    extended = [dist(t, 0) > dist(j, 0) * 1.16 for t, j in [(8, 6), (12, 10), (16, 14), (20, 18)]]
    i, m, r, l = extended
    thumb = dist(4, 17) > dist(3, 17) * 1.12
    pinch = dist(4, 8) / scale < 0.45
    if pinch and m and r and l: return 'ok'
    if pinch and not m and not r and not l: return 'pinch'
    if i and m and not r and not l: return 'victory'
    if i and m and r and l: return 'palm'
    if i and not m and not r and l: return 'rock'
    if not i and not m and not r and l and thumb: return 'shaka'
    if i and not m and not r and not l: return 'point'
    if not any(extended):
        if thumb and p[4][1] < p[3][1] - 0.025: return 'up'
        if thumb and p[4][1] > p[3][1] + 0.025: return 'down'
        return 'fist'
    return None


def draw_effect(frame, gesture, hand, elapsed):
    h, w = frame.shape[:2]
    x, y = int(hand[8].x*w), int(hand[8].y*h)
    cx, cy = int(hand[9].x*w), int(hand[9].y*h)
    t = elapsed
    if gesture != 'victory':
        cv2.putText(frame, LABELS[gesture], (30, 75), cv2.FONT_HERSHEY_DUPLEX, 1.5, (40, 230, 255), 3, cv2.LINE_AA)
    rng = random.Random(42)
    if gesture in ('victory', 'up', 'ok'):
        for n in range(28):
            px = int((rng.random()*w + math.sin(t*2+n)*20) % w)
            py = int((rng.random()*h - t*(35+n%5*12)) % h)
            color = [(180,120,255), (255,230,120), (100,220,255), (220,255,220)][n%4]
            if gesture == 'ok': cv2.circle(frame, (px, py), 8+n%5*4, color, 2, cv2.LINE_AA)
            elif gesture == 'up': cv2.circle(frame, (px, py), 3+n%4, color, -1, cv2.LINE_AA)
            else:
                if n % 3:
                    cv2.circle(frame, (px-5,py), 6, color, -1, cv2.LINE_AA)
                    cv2.circle(frame, (px+5,py), 6, color, -1, cv2.LINE_AA)
                    cv2.fillConvexPoly(frame, np.array([(px-11,py+2),(px+11,py+2),(px,py+15)]), color)
                else:
                    wing = int(8 * math.sin(t*7+n))
                    cv2.ellipse(frame,(px,py),(15,6),0,0,360,(255,255,255),-1,cv2.LINE_AA)
                    cv2.ellipse(frame,(px-2,py-3),(11,7+abs(wing)),wing*2,180,360,(255,255,255),-1,cv2.LINE_AA)
                    cv2.circle(frame,(px+14,py-3),4,(255,255,255),-1)
    elif gesture == 'palm':
        for rad in (55, 75, 100): cv2.circle(frame, (cx,cy), rad, (255,180,50), 2, cv2.LINE_AA)
        for n in range(12):
            a = n*math.tau/12+t
            cv2.circle(frame, (int(cx+90*math.cos(a)), int(cy+90*math.sin(a))), 5, (100,240,255), -1)
    elif gesture == 'fist':
        for n in range(14):
            a=n*math.tau/14; radius=70+int(25*abs(math.sin(t*4)))
            cv2.line(frame,(cx,cy),(int(cx+radius*math.cos(a)),int(cy+radius*math.sin(a))),(255,255,255),3)
    elif gesture == 'down':
        cv2.ellipse(frame,(cx,max(30,cy-130)),(75,30),0,0,360,(120,120,120),-1)
        for n in range(12):
            px=cx-60+n*11; py=int((t*180+n*31)%100)+cy-90
            cv2.line(frame,(px,py),(px-5,py+15),(255,170,80),2)
        cv2.putText(frame, ':(', (cx-20,cy+90), cv2.FONT_HERSHEY_SIMPLEX, 1.5,(255,180,80),3)
    elif gesture == 'point':
        for n in range(20):
            a=n*2.4; rad=n*3
            cv2.circle(frame,(int(x+math.cos(a+t)*rad),int(y+math.sin(a+t)*rad)),max(1,5-n//5),(255,220,100),-1)
        cv2.drawMarker(frame,(x,y),(100,255,255),cv2.MARKER_STAR,30,2)
    elif gesture == 'rock':
        for n in range(6):
            px=int((n+0.5)*w/6)
            cv2.line(frame,(px,0),(int(w/2+math.sin(t+n)*200),h),(80+n*25,50,180),5)
        cv2.drawMarker(frame,(cx,cy),(0,255,255),cv2.MARKER_TILTED_CROSS,100,5)
    elif gesture == 'shaka':
        cv2.circle(frame,(w-100,100),55,(0,220,255),-1)
        for row in range(3):
            pts=[(xx,int(h-50-row*25+10*math.sin(xx/40+t*2+row))) for xx in range(0,w,8)]
            for a,b in zip(pts,pts[1:]): cv2.line(frame,a,b,(255,180,40),3)
    elif gesture == 'pinch':
        tx,ty=int(hand[4].x*w),int(hand[4].y*h)
        center=((x+tx)//2,(y+ty)//2)
        radius=max(10,min(100,int(math.hypot(x-tx,y-ty)*1.3)))
        cv2.circle(frame,center,radius,(180,100,50),-1,cv2.LINE_AA)
        cv2.ellipse(frame,center,(radius*2,max(5,radius//3)),-20,0,360,(220,210,160),2,cv2.LINE_AA)


def draw_interface(frame, gesture):
    # Pillow supports Cyrillic and macOS colour emoji, unlike OpenCV's default font.
    h, w = frame.shape[:2]
    image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).convert('RGBA')
    panel = Image.new('RGBA', image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(panel)
    cell = min(44, max(20, (h - 16) // 10))
    left = max(0, w - cell - 12)
    draw.rounded_rectangle((left-3, 4, w-4, 12+cell*10), radius=12, fill=(12, 18, 35, 175))
    for index, emoji in enumerate(EMOJIS):
        y = 8 + index * cell
        if gesture == KEYS[index]:
            draw.rounded_rectangle((left, y, w-7, y+cell-1), radius=8, fill=(90, 190, 160, 150))
        # Apple Color Emoji provides fixed-size glyphs, so resize each icon.
        icon = Image.new('RGBA', (55, 55), (0, 0, 0, 0))
        ImageDraw.Draw(icon).text((2, 0), emoji, font=EMOJI_FONT, embedded_color=True)
        icon = icon.resize((cell, cell), Image.Resampling.LANCZOS)
        panel.alpha_composite(icon, (left, y))
    if gesture == 'victory':
        draw.text((28, 18), 'МИР', font=TEXT_FONT, fill=(255, 237, 100, 255), stroke_width=3, stroke_fill=(220, 80, 140, 255))
    image = Image.alpha_composite(image, panel).convert('RGB')
    return cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)


def main():
    if not MODEL.exists():
        print(f'Модель не найдена: {MODEL}')
        return
    options=vision.HandLandmarkerOptions(base_options=python.BaseOptions(model_asset_path=str(MODEL)),running_mode=vision.RunningMode.VIDEO,num_hands=1)
    camera=cv2.VideoCapture(0)
    if not camera.isOpened():
        print('Не удалось открыть камеру. Проверьте разрешения macOS.')
        camera.release(); return
    candidate=None; since=time.monotonic(); last=-1
    try:
        with vision.HandLandmarker.create_from_options(options) as detector:
            print('Покажите жест и удерживайте его. Нажмите Q для выхода.')
            while True:
                ok, frame=camera.read()
                if not ok: print('Не удалось получить кадр.'); break
                frame=cv2.flip(frame,1)
                rgb=cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)
                timestamp=max(time.monotonic_ns()//1_000_000,last+1); last=timestamp
                result=detector.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB,data=rgb),timestamp)
                now=time.monotonic()
                gesture=classify(result.hand_landmarks[0]) if result.hand_landmarks else None
                if gesture != candidate: candidate=gesture; since=now
                if result.hand_landmarks:
                    hand=result.hand_landmarks[0]; h,w=frame.shape[:2]
                    points=[(int(p.x*w),int(p.y*h)) for p in hand]
                    for c in vision.HandLandmarksConnections.HAND_CONNECTIONS: cv2.line(frame,points[c.start],points[c.end],(80,180,80),1)
                    for point in points: cv2.circle(frame,point,3,(255,255,255),-1)
                    if gesture and now-since>=0.5: draw_effect(frame,gesture,hand,now-since)
                cv2.putText(frame,'Hold gesture | Q: quit',(15,frame.shape[0]-20),cv2.FONT_HERSHEY_SIMPLEX,0.55,(255,255,255),1,cv2.LINE_AA)
                frame = draw_interface(frame, gesture if gesture and now-since >= 0.5 else None)
                cv2.imshow('Magic Hands',frame)
                if cv2.waitKey(1)&0xff==ord('q'): break
    finally:
        camera.release(); cv2.destroyAllWindows()


if __name__ == '__main__': main()
