#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Printable camera test chart and an independent numeric analysis of captures.

  camera_chart.py make OUTDIR            write chart.svg, chart.pdf (needs rsvg-convert) and chart.png
  camera_chart.py capture NODE OUT.png   grab one settled frame through PipeWire (one camera at a time)
  camera_chart.py analyze IMG [-o DIR]   locate the chart, report neutrality/tone/colour/noise
  camera_chart.py flat IMG               white-sheet capture: vignetting and colour shading
  camera_chart.py black IMG              lens-covered capture: black level and noise

Colour numbers are relative: a home printer's patch colours are not calibrated, so use
neutrality, tone, shading, noise and black level as hard facts and delta-E as a trend.
"""
import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

W, H = 297.0, 210.0            # A4 landscape, millimetres
FID_SIZE, FID_HOLE = 14.0, 6.0
FIDUCIALS = [(12.0, 12.0), (285.0, 12.0), (12.0, 198.0), (285.0, 198.0)]  # TL TR BL BR centres

CC_X0, CC_Y0, CC_P, CC_GAP = 18.0, 22.0, 30.0, 2.0
CC_NAMES = ['dark skin', 'light skin', 'blue sky', 'foliage', 'blue flower', 'bluish green',
            'orange', 'purplish blue', 'moderate red', 'purple', 'yellow green', 'orange yellow',
            'blue', 'green', 'red', 'yellow', 'magenta', 'cyan',
            'white', 'neutral 8', 'neutral 6.5', 'neutral 5', 'neutral 3.5', 'black']
CC_SRGB = [(115, 82, 68), (194, 150, 130), (98, 122, 157), (87, 108, 67), (133, 128, 177), (103, 189, 170),
           (214, 126, 44), (80, 91, 166), (193, 90, 99), (94, 60, 108), (157, 188, 64), (224, 163, 46),
           (56, 61, 150), (70, 148, 73), (175, 54, 60), (231, 199, 31), (187, 86, 149), (8, 133, 161),
           (243, 243, 242), (200, 200, 200), (160, 160, 160), (122, 122, 121), (85, 85, 85), (52, 52, 52)]
NEUTRAL_CC = [18, 19, 20, 21, 22, 23]

WEDGE_X0, WEDGE_Y0, WEDGE_W, WEDGE_H, WEDGE_N = 18.0, 158.0, 17.0, 26.0, 11
WEDGE = [round(255 - i * (235 / (WEDGE_N - 1))) for i in range(WEDGE_N)]   # 255 .. 20
FLAT = {'white': (218.0, 22.0, 64.0, 58.0, (255, 255, 255)),               # x, y, w, h, sRGB
        'grey': (218.0, 82.0, 64.0, 58.0, (119, 119, 119))}


def patches():
    """name -> (centre_x, centre_y, size, nominal sRGB) in chart millimetres."""
    out = {}
    for i, (name, rgb) in enumerate(zip(CC_NAMES, CC_SRGB)):
        r, c = divmod(i, 6)
        out['cc%02d %s' % (i + 1, name)] = (CC_X0 + CC_P / 2 + c * (CC_P + CC_GAP),
                                           CC_Y0 + CC_P / 2 + r * (CC_P + CC_GAP), CC_P, rgb)
    for i, v in enumerate(WEDGE):
        out['wedge%02d' % (i + 1)] = (WEDGE_X0 + WEDGE_W / 2 + i * WEDGE_W, WEDGE_Y0 + WEDGE_H / 2, WEDGE_H, (v, v, v))
    for name, (x, y, w, h, rgb) in FLAT.items():
        out['field %s' % name] = (x + w / 2, y + h / 2, min(w, h), rgb)
    return out


def chart_svg():
    s = ['<svg xmlns="http://www.w3.org/2000/svg" width="%gmm" height="%gmm" viewBox="0 0 %g %g">' % (W, H, W, H),
         '<rect width="%g" height="%g" fill="#fff"/>' % (W, H)]
    for cx, cy in FIDUCIALS:
        s.append('<rect x="%g" y="%g" width="%g" height="%g" fill="#000"/>' % (cx - FID_SIZE / 2, cy - FID_SIZE / 2, FID_SIZE, FID_SIZE))
        s.append('<rect x="%g" y="%g" width="%g" height="%g" fill="#fff"/>' % (cx - FID_HOLE / 2, cy - FID_HOLE / 2, FID_HOLE, FID_HOLE))
    for name, (cx, cy, size, rgb) in patches().items():
        if name.startswith('field'):
            continue
        s.append('<rect x="%g" y="%g" width="%g" height="%g" fill="rgb%s"/>' % (cx - size / 2 if name.startswith('cc') else cx - WEDGE_W / 2,
                                                                                cy - size / 2, size if name.startswith('cc') else WEDGE_W, size, rgb))
    for name, (x, y, w, h, rgb) in FLAT.items():
        s.append('<rect x="%g" y="%g" width="%g" height="%g" fill="rgb%s"/>' % (x, y, w, h, rgb))
    s.append('<g font-family="sans-serif" font-size="3.2" fill="#444">'
             '<text x="18" y="12.5">SPX camera chart v1 - print at 100%% (no scaling / fit to page), matte paper, colour management off</text>'
             '<text x="202" y="153">Hold flat and square to the camera,</text><text x="202" y="157.5">fill most of the frame,</text>'
             '<text x="202" y="162">even daylight or a CRI&gt;90 lamp,</text><text x="202" y="166.5">no glare, no screen light on it.</text>'
             '<text x="202" y="175">Keep the four ring markers visible.</text></g>')
    s.append('</svg>')
    return '\n'.join(s)


def render(ppm=8):
    """Nominal chart as an RGB image (ppm = pixels per mm)."""
    img = Image.new('RGB', (int(W * ppm), int(H * ppm)), (255, 255, 255))
    d = ImageDraw.Draw(img)
    for cx, cy in FIDUCIALS:
        d.rectangle([(cx - FID_SIZE / 2) * ppm, (cy - FID_SIZE / 2) * ppm, (cx + FID_SIZE / 2) * ppm, (cy + FID_SIZE / 2) * ppm], fill=(0, 0, 0))
        d.rectangle([(cx - FID_HOLE / 2) * ppm, (cy - FID_HOLE / 2) * ppm, (cx + FID_HOLE / 2) * ppm, (cy + FID_HOLE / 2) * ppm], fill=(255, 255, 255))
    for name, (cx, cy, size, rgb) in patches().items():
        if name.startswith('field'):
            continue
        w = size if name.startswith('cc') else WEDGE_W
        d.rectangle([(cx - w / 2) * ppm, (cy - size / 2) * ppm, (cx + w / 2) * ppm, (cy + size / 2) * ppm], fill=rgb)
    for x, y, w, h, rgb in FLAT.values():
        d.rectangle([x * ppm, y * ppm, (x + w) * ppm, (y + h) * ppm], fill=rgb)
    return img


# ---- colour maths -----------------------------------------------------------
M = np.array([[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]])
WHITE = np.array([0.95047, 1.0, 1.08883])


def to_linear(c):
    c = np.asarray(c, float) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def to_lab(srgb):
    xyz = to_linear(srgb) @ M.T / WHITE
    f = np.where(xyz > 216 / 24389, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def delta_e2000(l1, l2):
    L1, a1, b1 = l1[..., 0], l1[..., 1], l1[..., 2]
    L2, a2, b2 = l2[..., 0], l2[..., 1], l2[..., 2]
    C1, C2 = np.hypot(a1, b1), np.hypot(a2, b2)
    G = 0.5 * (1 - np.sqrt((((C1 + C2) / 2) ** 7) / (((C1 + C2) / 2) ** 7 + 25 ** 7)))
    a1p, a2p = (1 + G) * a1, (1 + G) * a2
    C1p, C2p = np.hypot(a1p, b1), np.hypot(a2p, b2)
    h1p = np.degrees(np.arctan2(b1, a1p)) % 360
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360
    dL, dC = L2 - L1, C2p - C1p
    dh = h2p - h1p
    dh = np.where(dh > 180, dh - 360, np.where(dh < -180, dh + 360, dh))
    dH = 2 * np.sqrt(C1p * C2p) * np.sin(np.radians(dh) / 2)
    Lm, Cm = (L1 + L2) / 2, (C1p + C2p) / 2
    hm = np.where(np.abs(h1p - h2p) > 180, (h1p + h2p + 360) / 2, (h1p + h2p) / 2)
    T = (1 - 0.17 * np.cos(np.radians(hm - 30)) + 0.24 * np.cos(np.radians(2 * hm)) +
         0.32 * np.cos(np.radians(3 * hm + 6)) - 0.20 * np.cos(np.radians(4 * hm - 63)))
    SL = 1 + 0.015 * (Lm - 50) ** 2 / np.sqrt(20 + (Lm - 50) ** 2)
    SC, SH = 1 + 0.045 * Cm, 1 + 0.015 * Cm * T
    RT = -2 * np.sqrt(Cm ** 7 / (Cm ** 7 + 25 ** 7)) * np.sin(np.radians(60 * np.exp(-(((hm - 275) / 25) ** 2))))
    return np.sqrt((dL / SL) ** 2 + (dC / SC) ** 2 + (dH / SH) ** 2 + RT * (dC / SC) * (dH / SH))


# ---- locating the chart ------------------------------------------------------
def luma(a):
    return 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]


def components(mask):
    """4-connected components of a boolean mask -> list of (area, ys, xs)."""
    h, w = mask.shape
    seen = np.zeros_like(mask, bool)
    out = []
    for y0, x0 in zip(*np.nonzero(mask)):
        if seen[y0, x0]:
            continue
        stack, ys, xs = [(y0, x0)], [], []
        seen[y0, x0] = True
        while stack:
            y, x = stack.pop()
            ys.append(y)
            xs.append(x)
            for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        out.append((len(ys), np.array(ys), np.array(xs)))
    return out


def find_markers(arr):
    """Locate the four ring markers; returns centres (x, y) ordered TL, TR, BL, BR in full-size pixels."""
    h, w = arr.shape[:2]
    scale = min(1.0, 400.0 / max(h, w))
    small = np.asarray(Image.fromarray(arr.astype(np.uint8)).resize((max(8, int(w * scale)), max(8, int(h * scale))), Image.BOX), float)
    g = luma(small)
    white = np.percentile(g, 95)
    mask = g < 0.18 * white + 0.05 * g.min()
    cands = []
    for area, ys, xs in components(mask):
        bw, bh = xs.max() - xs.min() + 1, ys.max() - ys.min() + 1
        if area < 25 or min(bw, bh) / max(bw, bh) < 0.55:
            continue
        fill = area / float(bw * bh)
        if 0.45 < fill < 0.93:      # ring: solid patches fill ~1.0
            cands.append((area, xs.mean() / scale, ys.mean() / scale))
    if len(cands) < 4:
        raise RuntimeError('found %d ring markers, need 4: chart too small, cut off or glared' % len(cands))
    if len(cands) > 4:
        med = np.median([c[0] for c in cands])
        cands = sorted(cands, key=lambda c: abs(c[0] - med))[:4]
    pts = sorted([(c[1], c[2]) for c in cands], key=lambda p: p[1])
    top, bottom = sorted(pts[:2]), sorted(pts[2:])
    return top + bottom


def homography(src, dst):
    a = []
    for (x, y), (u, v) in zip(src, dst):
        a.append([x, y, 1, 0, 0, 0, -u * x, -u * y, -u])
        a.append([0, 0, 0, x, y, 1, -v * x, -v * y, -v])
    _, _, vt = np.linalg.svd(np.array(a, float))
    return vt[-1].reshape(3, 3) / vt[-1][-1]


def apply_h(hm, pts):
    p = np.c_[np.asarray(pts, float), np.ones(len(pts))] @ hm.T
    return p[:, :2] / p[:, 2:3]


def sample(arr, hm, cx, cy, size, inset=0.5, n=9):
    half = size * inset / 2
    g = np.linspace(-half, half, n)
    pts = apply_h(hm, [(cx + dx, cy + dy) for dy in g for dx in g])
    h, w = arr.shape[:2]
    xi = np.clip(np.rint(pts[:, 0]).astype(int), 0, w - 1)
    yi = np.clip(np.rint(pts[:, 1]).astype(int), 0, h - 1)
    px = arr[yi, xi]
    return np.median(px, 0), px.std(0), float((px.max(-1) >= 250).mean())


def load(path):
    return np.asarray(Image.open(path).convert('RGB'), float)


# ---- analyses ------------------------------------------------------------------
def analyze(path, outdir=None, label=None):
    arr = load(path)
    centres = find_markers(arr)
    hm = homography(FIDUCIALS, centres)
    rows, meas = {}, {}
    for name, (cx, cy, size, nominal) in patches().items():
        med, sd, clip = sample(arr, hm, cx, cy, size)
        rows[name] = dict(nominal=nominal, measured=[round(float(v), 1) for v in med],
                          noise=[round(float(v), 2) for v in sd], clipped=round(clip, 3))
        meas[name] = med
    report = dict(image=str(path), label=label, size=list(arr.shape[1::-1]),
                  markers=[[round(x, 1), round(y, 1)] for x, y in centres])
    # neutrality: a*, b* of neutral patches (0 = neutral) and R/G, B/G
    neutral_names = [n for n in rows if n.startswith('wedge')] + ['cc%02d %s' % (i + 1, CC_NAMES[i]) for i in NEUTRAL_CC]
    labs = {n: to_lab(meas[n]) for n in neutral_names}
    rg = [meas[n][0] / max(meas[n][1], 1e-6) for n in neutral_names if meas[n][1] > 25]
    bg = [meas[n][2] / max(meas[n][1], 1e-6) for n in neutral_names if meas[n][1] > 25]
    report['neutrality'] = dict(
        mean_abs_a=round(float(np.mean([abs(labs[n][1]) for n in neutral_names if labs[n][0] > 20])), 2),
        mean_abs_b=round(float(np.mean([abs(labs[n][2]) for n in neutral_names if labs[n][0] > 20])), 2),
        R_over_G=round(float(np.mean(rg)), 3), B_over_G=round(float(np.mean(bg)), 3),
        verdict='neutral' if max(abs(1 - np.mean(rg)), abs(1 - np.mean(bg))) < 0.04 else 'colour cast')
    # tone: measured relative luminance vs nominal on the wedge
    wn = sorted(n for n in rows if n.startswith('wedge'))
    ym = np.array([to_linear(meas[n]) @ M[1] for n in wn])
    yn = np.array([to_linear(rows[n]['nominal']) @ M[1] for n in wn])
    ym, yn = ym / ym[0], yn / yn[0]
    ok = (yn > 0.02) & (ym > 0.0005)
    gamma_fit = float(np.polyfit(np.log(yn[ok]), np.log(ym[ok]), 1)[0]) if ok.sum() > 3 else float('nan')
    report['tone'] = dict(wedge_measured_codes=[round(float(luma(meas[n])), 1) for n in wn],
                          wedge_nominal_codes=[rows[n]['nominal'][0] for n in wn],
                          monotonic=bool(np.all(np.diff([luma(meas[n]) for n in wn]) < 0)),
                          luminance_exponent_vs_nominal=round(gamma_fit, 3),
                          note='1.0 = same tone curve as nominal sRGB; >1 contrastier/darker mids, <1 flatter/brighter mids')
    # colour: white-normalise in linear light, then deltaE2000 against the nominal sRGB patches
    wl = to_linear(meas['cc19 white']) / to_linear(rows['cc19 white']['nominal'])
    des, per = [], {}
    for i, name in enumerate(CC_NAMES):
        n = 'cc%02d %s' % (i + 1, name)
        lin = to_linear(meas[n]) / wl
        srgb = 255 * np.where(lin <= 0.0031308, 12.92 * lin, 1.055 * np.clip(lin, 0, None) ** (1 / 2.4) - 0.055)
        de = float(delta_e2000(to_lab(np.clip(srgb, 0, 255)), to_lab(rows[n]['nominal'])))
        per[n] = round(de, 1)
        des.append(de)
    colour = [d for d, i in zip(des, range(24)) if i not in NEUTRAL_CC]
    cn = [np.hypot(*to_lab(meas['cc%02d %s' % (i + 1, CC_NAMES[i])])[1:]) / max(np.hypot(*to_lab(rows['cc%02d %s' % (i + 1, CC_NAMES[i])]['nominal'])[1:]), 1e-6)
          for i in range(18)]
    report['colour'] = dict(deltaE2000_mean=round(float(np.mean(des)), 1), deltaE2000_max=round(float(np.max(des)), 1),
                            deltaE2000_chromatic_mean=round(float(np.mean(colour)), 1),
                            chroma_vs_nominal=round(float(np.median(cn)), 2), per_patch=per,
                            note='printed patches are uncalibrated: read as a trend (<6 good, 6-12 fair, >12 poor)')
    flat = [rows[n]['noise'] for n in ('field white', 'field grey')]
    report['noise'] = dict(sigma_codes_white_field=flat[0], sigma_codes_grey_field=flat[1])
    report['clipping'] = dict(white_field_fraction_ge250=rows['field white']['clipped'], white_patch=rows['cc19 white']['clipped'])
    report['patches'] = rows
    if outdir:
        outdir = Path(outdir)
        outdir.mkdir(parents=True, exist_ok=True)
        ov = Image.fromarray(arr.astype(np.uint8))
        d = ImageDraw.Draw(ov)
        for (x, y) in centres:
            d.ellipse([x - 8, y - 8, x + 8, y + 8], outline=(255, 0, 0), width=2)
        for name, (cx, cy, size, _) in patches().items():
            q = apply_h(hm, [(cx - size / 4, cy - size / 4), (cx + size / 4, cy - size / 4), (cx + size / 4, cy + size / 4), (cx - size / 4, cy + size / 4)])
            d.polygon([tuple(p) for p in q], outline=(0, 255, 0))
        ov.save(outdir / (Path(path).stem + '-overlay.png'))
        (outdir / (Path(path).stem + '-report.json')).write_text(json.dumps(report, indent=1))
    return report


def flat_field(path):
    arr = load(path)
    h, w = arr.shape[:2]
    gh, gw = 6, 8
    cell = np.array([[arr[r * h // gh:(r + 1) * h // gh, c * w // gw:(c + 1) * w // gw].reshape(-1, 3).mean(0) for c in range(gw)] for r in range(gh)])
    y = luma(cell)
    centre = y[gh // 2 - 1:gh // 2 + 1, gw // 2 - 1:gw // 2 + 1].mean()
    rg = cell[..., 0] / np.maximum(cell[..., 1], 1e-6)
    bg = cell[..., 2] / np.maximum(cell[..., 1], 1e-6)
    rgc, bgc = rg[gh // 2 - 1:gh // 2 + 1, gw // 2 - 1:gw // 2 + 1].mean(), bg[gh // 2 - 1:gh // 2 + 1, gw // 2 - 1:gw // 2 + 1].mean()
    corners = [y[0, 0], y[0, -1], y[-1, 0], y[-1, -1]]
    return dict(image=str(path), centre_luma=round(float(centre), 1),
                corner_over_centre=[round(float(c / centre), 3) for c in corners],
                worst_vignette_pct=round(float(100 * (1 - min(corners) / centre)), 1),
                max_R_over_G_shift_pct=round(float(100 * np.abs(rg / rgc - 1).max()), 1),
                max_B_over_G_shift_pct=round(float(100 * np.abs(bg / bgc - 1).max()), 1),
                clipped_fraction=round(float((arr.max(-1) >= 250).mean()), 3),
                note='needs an evenly lit plain white sheet filling the frame; >10% vignette or >5% colour shift deserves shading correction')


def black_level(path):
    arr = load(path)
    return dict(image=str(path), mean_rgb=[round(float(v), 2) for v in arr.reshape(-1, 3).mean(0)],
                sigma_rgb=[round(float(v), 2) for v in arr.reshape(-1, 3).std(0)],
                note='lens fully covered; mean should be ~0-3 codes and equal across channels')


def capture(node, out, size='1024x768', frames=120, fmt='RGB'):
    width, height = size.split('x')
    cmd = ['gst-launch-1.0', '-q', 'pipewiresrc', 'target-object=' + node, 'num-buffers=%d' % frames, '!',
           'video/x-raw,format=%s,width=%s,height=%s' % (fmt, width, height), '!', 'fdsink', 'fd=1']
    p = subprocess.run(cmd, capture_output=True, timeout=90)
    bpp = 3 if fmt == 'RGB' else 4
    fs = int(width) * int(height) * bpp
    got = len(p.stdout) // fs
    if got < frames // 2:
        raise RuntimeError('only %d of %d frames: %s' % (got, frames, p.stderr.decode()[:200]))
    frame = np.frombuffer(p.stdout[(got - 1) * fs:got * fs], np.uint8).reshape(int(height), int(width), bpp)[..., :3]
    Image.fromarray(frame).save(out)
    return dict(frames_received=got, saved=str(out))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    m = sub.add_parser('make'); m.add_argument('outdir', type=Path)
    c = sub.add_parser('capture'); c.add_argument('node'); c.add_argument('out', type=Path)
    c.add_argument('--size', default='1024x768'); c.add_argument('--frames', type=int, default=120)
    a = sub.add_parser('analyze'); a.add_argument('image'); a.add_argument('-o', '--outdir', type=Path); a.add_argument('--label')
    sub.add_parser('flat').add_argument('image')
    sub.add_parser('black').add_argument('image')
    args = ap.parse_args()
    if args.cmd == 'make':
        args.outdir.mkdir(parents=True, exist_ok=True)
        (args.outdir / 'chart.svg').write_text(chart_svg())
        render().save(args.outdir / 'chart.png')
        try:
            subprocess.run(['rsvg-convert', '-f', 'pdf', '-o', str(args.outdir / 'chart.pdf'), str(args.outdir / 'chart.svg')], check=True)
        except (OSError, subprocess.CalledProcessError) as error:
            print('PDF not written (%s); print chart.svg or chart.png at 100%%' % error, file=sys.stderr)
        print('wrote', *sorted(p.name for p in args.outdir.iterdir()))
    elif args.cmd == 'capture':
        print(json.dumps(capture(args.node, args.out, args.size, args.frames)))
    elif args.cmd == 'analyze':
        r = analyze(args.image, args.outdir, args.label)
        r.pop('patches')
        print(json.dumps(r, indent=1))
    elif args.cmd == 'flat':
        print(json.dumps(flat_field(args.image), indent=1))
    else:
        print(json.dumps(black_level(args.image), indent=1))


if __name__ == '__main__':
    main()
