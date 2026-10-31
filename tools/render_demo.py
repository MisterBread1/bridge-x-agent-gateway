"""Author two honest architecture GIFs. Pillow is a media-only dependency."""
import argparse
import hashlib
from functools import lru_cache
import json
import math
import os
from pathlib import Path
from PIL import Image, ImageChops, ImageDraw, ImageFont

W, H, FRAMES, DURATION = 1100, 680, 180, 80
BG = (9, 13, 26)
CARD = (17, 24, 44)
LINE = (47, 61, 88)
WHITE = (235, 241, 255)
MUTED = (141, 159, 191)
BLUE = (85, 154, 255)
VIOLET = (161, 125, 255)
TEAL = (92, 218, 190)
STEPS = [
    ('Task arrives', 'ZCode sends the task through Bridge X', 'request', -1),
    ('Request accepted', 'Bridge X forwards declared client tool schemas', 'upstream', -1),
    ('Native Read', 'AI proposes Read; Bridge X validates the input', 'proposal', 0),
    ('Client execution', 'ZCode reads the existing index.html', 'execute', 0),
    ('Native Edit', 'AI proposes one focused CSS replacement', 'proposal', 1),
    ('CSS changed', 'ZCode edits only the panel background', 'execute', 1),
    ('Read back', 'ZCode confirms the exact changed bytes', 'execute', 2),
    ('Python check', 'The client runs the fixed fixture check', 'execute', 3),
    ('Tool receipt', 'The real client result returns through Bridge X', 'receipt', 3),
    ('Completed', 'The agent continues from confirmed receipts', 'complete', 3),
]
TOOLS = [('Read', 'inspect file'), ('Edit', 'one CSS change'), ('Read Back', 'verify bytes'), ('Bash / Python', 'run check')]


@lru_cache(maxsize=None)
def font(size, bold=False, mono=False):
    fonts = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
    windows = fonts / ('consola.ttf' if mono else 'segoeuib.ttf' if bold else 'segoeui.ttf')
    linux = Path('/usr/share/fonts/truetype/dejavu') / ('DejaVuSansMono.ttf' if mono else 'DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf')
    for candidate in (windows, linux):
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size)
    raise RuntimeError('Install Segoe UI or DejaVu fonts before rendering media')


def text(d, xy, value, size=20, color=WHITE, bold=False, mono=False, max_width=None):
    face = font(size, bold, mono)
    bounds = d.textbbox(xy, value, font=face)
    if max_width is not None and bounds[2] - xy[0] > max_width:
        raise ValueError('Text exceeds its layout column: ' + value)
    if bounds[2] > W - 22 or bounds[3] > H - 8 or xy[0] < 0 or xy[1] < 0:
        raise ValueError('Text falls outside frame: ' + value)
    d.text(xy, value, font=face, fill=color)


def rounded(d, box, fill=CARD, outline=LINE, radius=18, width=1):
    d.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def pill(d, xy, value, color=BLUE, size=14):
    f = font(size, True)
    width = d.textlength(value, font=f) + 26
    x, y = xy
    rounded(d, (x, y, x + width, y + 29), fill=tuple(int(v * .15) for v in color), outline=tuple(int(v * .45) for v in color), radius=13)
    text(d, (x + 13, y + 5), value, size, color, True)


def ease(t):
    t = max(0, min(1, t))
    return t * t * (3 - 2 * t)


def particle(d, points, t, color=BLUE):
    lengths = [math.dist(a, b) for a, b in zip(points, points[1:])]
    distance = (t % 1) * sum(lengths)
    for i, length in enumerate(lengths):
        if distance <= length:
            a, b = points[i], points[i + 1]
            ratio = distance / max(length, 1)
            x, y = a[0] + (b[0] - a[0]) * ratio, a[1] + (b[1] - a[1]) * ratio
            for radius, mix in [(13, .08), (8, .22), (4, 1)]:
                fill = tuple(int(BG[c] * (1 - mix) + color[c] * mix) for c in range(3))
                d.ellipse((x-radius, y-radius, x+radius, y+radius), fill=fill)
            return
        distance -= length


def background(variant):
    im = Image.new('RGB', (W, H), BG)
    d = ImageDraw.Draw(im)
    for y in range(H):
        glow = max(0, 1 - abs(y - 235) / 500)
        d.line((0, y, W, y), fill=(9 + int(3 * glow), 13 + int(4 * glow), 26 + int(12 * glow)))
    for x in range(30, W, 36):
        for y in range(28, H, 36):
            d.point((x, y), fill=(28, 37, 58))
    text(d, (48, 30), 'BRIDGE X', 18, BLUE, True)
    text(d, (48, 61), 'Native AI Agent Gateway', 36, WHITE, True, max_width=800)
    pill(d, (866, 42), 'ARCHITECTURE', VIOLET)
    text(d, (48, 116), 'Client-owned execution. Structured calls. Confirmed receipts.', 20, MUTED)
    text(d, (48, 640), 'Architecture illustration  /  scripted local acceptance workflow', 15, MUTED, max_width=900)
    text(d, (983, 640), 'LOOP', 14, BLUE, True)
    return im


def stage_for(frame):
    if frame < 144:
        return frame // 16, (frame % 16) / 15
    return 9, min(1, (frame - 144) / 23)


def lanes(frame):
    im = background('lanes')
    d = ImageDraw.Draw(im)
    stage, phase = stage_for(frame)
    title, detail, mode, tool = STEPS[stage]
    nodes = [(48, 188, 302, 290), (422, 188, 676, 290), (796, 188, 1050, 290)]
    colors = [VIOLET, BLUE, TEAL]
    for a, b in [(302, 422), (676, 796)]:
        d.line((a, 239, b, 239), fill=LINE, width=3)
    active = {0: [2], 1: [1, 0], 2: [0, 1], 3: [2], 4: [0, 1], 5: [2], 6: [2], 7: [2], 8: [2, 1, 0], 9: [0, 1, 2]}[stage]
    for i, box in enumerate(nodes):
        rounded(d, box, outline=colors[i] if i in active else LINE, width=2 if i in active else 1)
        text(d, (box[0]+22, box[1]+19), ['AI Provider', 'Bridge X', 'ZCode'][i], 25, colors[i], True, max_width=215)
        text(d, (box[0]+22, box[1]+58), ['propose next action', 'validate + coordinate', 'execute client tools'][i], 16, MUTED, max_width=220)
    if mode == 'request':
        path = [(796, 239), (676, 239), (422, 239)]
    elif mode == 'upstream':
        path = [(422, 239), (302, 239)]
    elif mode == 'proposal':
        path = [(302, 239), (422, 239), (676, 239), (796, 239)]
    elif mode == 'receipt':
        path = [(796, 239), (676, 239), (422, 239), (302, 239)]
    else:
        path = [(923, 290), (923, 330), (166 + max(tool, 0)*255, 330), (166 + max(tool, 0)*255, 365)]
        d.line(path, fill=(37, 65, 89), width=2)
    particle(d, path, ease(phase), TEAL if mode in ('receipt', 'complete') else BLUE)
    for i, (name, sub) in enumerate(TOOLS):
        x = 48 + 255*i
        box = (x, 365, x+237, 458)
        selected = tool == i and stage >= 2
        complete = stage > [3, 5, 6, 8][i]
        color = TEAL if complete else BLUE if selected else MUTED
        rounded(d, box, outline=color if complete or selected else LINE, width=2 if selected else 1)
        text(d, (x+18, 379), name, 22, color, True, max_width=205)
        text(d, (x+18, 416), 'receipt received' if complete else sub, 16, MUTED, max_width=205)
    rounded(d, (48, 483, 1050, 609), outline=(44, 58, 86))
    pill(d, (67, 499), f'{stage+1:02d} / 10', TEAL if stage == 9 else VIOLET)
    text(d, (193, 496), title, 25, TEAL if stage == 9 else WHITE, True, max_width=800)
    text(d, (193, 533), detail, 19, MUTED, max_width=800)
    color = '#e0f2fe' if stage >= 5 else '#f1f5f9'
    text(d, (193, 565), '.panel { background: ' + color + '; }', 17, BLUE, mono=True, max_width=780)
    return im


def ledger(frame):
    im = background('ledger')
    d = ImageDraw.Draw(im)
    stage, phase = stage_for(frame)
    title, detail, mode, tool = STEPS[stage]
    rounded(d, (48, 176, 431, 608), outline=(48, 60, 89))
    text(d, (72, 195), 'PROTOCOL ROUTE', 14, MUTED, True)
    positions = [(80, 238, 399, 310), (80, 353, 399, 425), (80, 468, 399, 540)]
    for i, box in enumerate(positions):
        color = [VIOLET, BLUE, TEAL][i]
        rounded(d, box, fill=(20, 29, 51), outline=color if stage in (2*i, 2*i+1, 8, 9) else LINE, width=2)
        text(d, (104, box[1]+15), ['AI Provider', 'Bridge X', 'ZCode'][i], 23, color, True, max_width=270)
        if i < 2:
            d.line((239, box[3], 239, box[3]+43), fill=LINE, width=3)
    path = [(239, 468), (239, 425), (239, 353), (239, 310)] if mode in ('request', 'receipt', 'upstream') else [(239, 310), (239, 353), (239, 425), (239, 468)]
    particle(d, path, ease(phase), VIOLET if mode == 'proposal' else BLUE)
    text(d, (72, 566), 'Tool proposals are data.', 16, MUTED)
    rounded(d, (460, 176, 1050, 608), outline=(52, 66, 96))
    pill(d, (482, 195), 'VERIFIED FLOW', VIOLET)
    text(d, (482, 240), title, 30, TEAL if stage == 9 else WHITE, True, max_width=540)
    text(d, (482, 286), detail, 18, MUTED, max_width=540)
    labels = ['Read', 'Edit', 'Read Back', 'Bash / Python']
    for i, label in enumerate(labels):
        x, y = 482, 337 + 46*i
        passed = stage > [3, 5, 6, 8][i]
        selected = i == tool and stage >= 2
        accent = TEAL if passed else BLUE if selected else (68, 83, 110)
        d.ellipse((x, y+4, x+12, y+16), fill=accent)
        text(d, (x+28, y-2), label, 20, WHITE if selected or passed else MUTED, selected)
        state = 'RECEIPT' if passed else 'NATIVE CALL' if selected else 'PENDING'
        text(d, (855, y+1), state, 13, accent, True, max_width=170)
    d.line((482, 535, 1025, 535), fill=LINE, width=1)
    text(d, (482, 551), 'Client executes. Bridge X coordinates.', 19, TEAL if stage == 9 else MUTED, max_width=540)
    for i in range(10):
        x = 482 + i*54
        rounded(d, (x, 587, x+43, 591), fill=TEAL if i <= stage else LINE, outline=None, radius=2)
    return im


def palette():
    swatches = [BG, CARD, LINE, WHITE, MUTED, BLUE, VIOLET, TEAL]
    colors = []
    for a in swatches:
        for b in [BG, CARD, WHITE]:
            for n in range(9):
                colors.append(tuple(round(a[c]*(1-n/8)+b[c]*n/8) for c in range(3)))
    colors = list(dict.fromkeys(colors))[:256]
    colors += [(0, 0, 0)]*(256-len(colors))
    image = Image.new('P', (1, 1))
    image.putpalette([c for rgb in colors for c in rgb])
    return image


def render(output, style):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    draw_frame = lanes if style == 'lanes' else ledger
    first = draw_frame(0)
    frames = []
    pal = palette()
    for index in range(FRAMES):
        im = draw_frame(index)
        if index >= FRAMES-12:
            im = Image.blend(im, first, ease((index-(FRAMES-12))/11))
        frames.append(im.quantize(palette=pal, dither=Image.Dither.NONE))
    frames[0].save(output, save_all=True, append_images=frames[1:], duration=DURATION,
                   loop=0, optimize=True, disposal=1)
    with Image.open(output) as gif:
        first_decoded = gif.convert('RGB').copy()
        stored_frames = gif.n_frames
        durations = []
        signatures = set()
        for index in range(gif.n_frames):
            gif.seek(index)
            durations.append(gif.info['duration'])
            signatures.add(hashlib.sha256(gif.convert('RGB').tobytes()).digest())
        assert gif.size == (W, H) and gif.info['loop'] == 0
        assert len(signatures) > 100 and 10_000 <= sum(durations) <= 18_000
        assert ImageChops.difference(first_decoded, gif.convert('RGB')).getbbox() is None
    assert output.stat().st_size < 10_000_000
    return {'file': output.name, 'width': W, 'height': H, 'frames': stored_frames,
            'rendered_frames': len(frames),
            'duration_ms': sum(durations), 'fps': 1000/DURATION, 'bytes': output.stat().st_size}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=Path(__file__).resolve().parents[1]/'docs/assets')
    args = parser.parse_args()
    print(json.dumps([render(args.output_dir/'bridge-x-demo.gif', 'lanes'),
                      render(args.output_dir/'bridge-x-demo-ledger.gif', 'ledger')]))


if __name__ == '__main__':
    main()
