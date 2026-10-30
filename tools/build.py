# Build the map data (const D in brismap.html) for all localities of five councils from OSM
# (PSMA-imported) boundaries, and write it into the page. See README.md.
import base64, io, json, math, os, re, sys, time
import numpy as np
import shapely, shapely.ops
from shapely.geometry import LineString, Polygon, Point, box, MultiPolygon
from shapely.ops import linemerge, unary_union, polygonize
from shapely.affinity import affine_transform, rotate
from shapely import STRtree
from fontTools.ttLib import TTFont

HERE = os.path.dirname(os.path.abspath(__file__))
DL = os.path.join(HERE, 'data') + '/'
PAGE = os.path.join(HERE, '..', 'brismap.html')
# projection the page was drawn in (equirectangular, x/y ratio = cos 27.4°)
A, B, C, DD = 1331.96891005, -203577.98086559, -1499.86625126, -40496.36841359
P = [A, 0, 0, C, B, DD]
proj = lambda g: affine_transform(g, P)
COUNCILS = [('Brisbane', 'City of Brisbane'), ('Moreton Bay', 'City of Moreton Bay'),
            ('Redland', 'Redland City'), ('Ipswich', 'Ipswich City'), ('Logan', 'Logan City')]
t0 = time.time()
def log(*a): print(f'[{time.time()-t0:6.1f}s]', *a, flush=True)

def relpoly(e):
    def faces(role):
        ls = [LineString([(p['lon'], p['lat']) for p in m['geometry']])
              for m in e['members'] if m['type'] == 'way' and m.get('role', '') == role and len(m.get('geometry', [])) > 1]
        if not ls: return Polygon()
        u = unary_union(ls)
        merged = linemerge(u) if u.geom_type == 'MultiLineString' else u
        fs = list(polygonize(merged))
        if not fs:  # unclosed by a hair: close each chain
            for l in getattr(merged, 'geoms', [merged]):
                c = list(l.coords)
                if len(c) > 3: fs.append(Polygon(c + [c[0]]).buffer(0))
        return unary_union(fs)
    return faces('outer').difference(faces('inner')).buffer(0)

# ---------- councils ----------
LG = {e['tags']['name']: relpoly(e) for e in json.load(open(DL + 'councils.json'))['elements']}
CG = [LG[full] for _, full in COUNCILS]
CU = unary_union(CG)

# ---------- coastline -> land ----------
lines = [LineString([(p['lon'], p['lat']) for p in w['geometry']]) for w in json.load(open(DL + 'coastline.json'))['elements']]
bb = box(151.4, -29.2, 154.4, -25.6)
coast = linemerge(unary_union(lines)).intersection(bb)
faces = list(polygonize(unary_union([coast, bb.boundary])))
tree = STRtree(faces); votes = np.zeros(len(faces))
for ln in lines:
    c = np.array(ln.coords)
    for i in range(0, len(c) - 1, 3):
        (ax, ay), (bx, by) = c[i], c[i + 1]; L = math.hypot(bx - ax, by - ay)
        if L == 0: continue
        mx, my = (ax + bx) / 2, (ay + by) / 2; nx, ny = -(by - ay) / L * 1e-5, (bx - ax) / L * 1e-5
        for sg in (1, -1):
            for k in tree.query(Point(mx + sg * nx, my + sg * ny), predicate='within'): votes[k] += sg
land_ll = unary_union([f for f, v in zip(faces, votes) if v > 0])
log('land faces', len(faces), 'undecided', int((votes == 0).sum()))

# ---------- localities ----------
locs = []
for e in json.load(open(DL + 'localities.json'))['elements']:
    g = relpoly(e)
    if g.is_empty: log('EMPTY', e['tags'].get('name')); continue
    gl = g.intersection(land_ll)
    sh = [g.intersection(c).area / g.area for c in CG]
    shl = [gl.intersection(c).area / gl.area if gl.area > 0 else 0 for c in CG]
    ks = [i for i in range(5) if sh[i] >= 0.03 or shl[i] >= 0.03]
    if not ks: continue
    # keep only the part inside the five councils (drop slivers along the council edge)
    p = sum(sh)
    if p < 0.97:
        gc = g.intersection(CU)
        gc = unary_union([q for q in getattr(gc, 'geoms', [gc]) if q.geom_type == 'Polygon' and q.area > 0.01 * gc.area])
        g, gl = gc, gc.intersection(land_ll)
    locs.append(dict(n=e['tags']['name'], g=g, gl=gl, k=ks, sh=sh, shl=shl, p=p))
log('localities', len(locs))
for l in locs:
    if len(l['k']) > 1: log('  multi', l['n'], [(COUNCILS[i][0], round(l['sh'][i], 3), round(l['shl'][i], 3)) for i in l['k']])
# same name in two councils (e.g. Cedar Creek): qualify with the council, labels keep the bare name
from collections import Counter
dup = Counter(l['n'] for l in locs)
for l in locs:
    l['base'] = l['n']
    if dup[l['n']] > 1: l['n'] = f"{l['n']} ({COUNCILS[l['k'][0]][0]})"
names = [l['n'] for l in locs]; assert len(set(names)) == len(names), [n for n in names if names.count(n) > 1]

# area km2 (local scale at centroid)
for l in locs:
    lat = l['g'].centroid.y
    l['a'] = round(l['g'].area * 111.32 * math.cos(math.radians(lat)) * 110.57, 1)

# adjacency: shared boundary > ~20 m
G = [l['g'] for l in locs]; tr = STRtree(G); adj = {l['n']: [] for l in locs}
for i, g in enumerate(G):
    for j in tr.query(g.buffer(1e-6)):
        if j <= i: continue
        if g.boundary.intersection(G[j].buffer(2e-5)).length > 2e-4:
            adj[names[i]].append(names[j]); adj[names[j]].append(names[i])

# ---------- simplify as a coverage (shared edges stay shared) ----------
PG = [proj(g) for g in G]
SG = list(shapely.coverage_simplify(np.array(PG, dtype=object), 0.35))
def fmt(v): return f'{v:.1f}'
def ringd(cs, close=True):
    out, prev = [], None
    for x, y in cs:
        t = (fmt(x), fmt(y))
        if t != prev: out.append(t); prev = t
    if close and len(out) > 1 and out[0] == out[-1]: out.pop()
    return out
def polyd(g):
    s = []
    for p in getattr(g, 'geoms', [g]):
        if p.geom_type != 'Polygon': continue
        for r in [p.exterior, *p.interiors]:
            pts = ringd(r.coords)
            if len(pts) >= 3: s.append('M' + 'L'.join(f'{x},{y}' for x, y in pts) + 'Z')
    return ''.join(s)
def lined(g):
    s = []
    for l in getattr(g, 'geoms', [g]):
        pts = ringd(l.coords, False)
        if len(pts) >= 2: s.append('M' + 'L'.join(f'{x},{y}' for x, y in pts))
    return ''.join(s)

# ---------- colours: 16-colour palette, neighbours differ, spread second-order too ----------
PAL = ['#e8d24a', '#c94f8a', '#3f7fbf', '#b8834a', '#9a6fc1', '#4fb09a', '#6fd0c4', '#5ab4d6',
       '#e4574f', '#e0703a', '#e389b0', '#c86b4a', '#a4c639', '#2e9e6a', '#7bc142', '#d9a21b']
col = {}; used = {c: 0 for c in PAL}
for n in sorted(names, key=lambda n: -len(adj[n])):
    n1 = {col[m] for m in adj[n] if m in col}
    n2 = {col[q] for m in adj[n] for q in adj[m] if q in col and q != n}
    c = min(PAL, key=lambda c: (c in n1, c in n2, used[c]))
    col[n] = c; used[c] += 1

# ---------- labels ----------
page = open(PAGE).read()
fonts = {int(w): TTFont(io.BytesIO(base64.b64decode(b))) for w, b in
         re.findall(r'font-family:"MapSC";font-weight:(\d+);font-display:block;src:url\(data:font/woff2;base64,([A-Za-z0-9+/=]+)', page)}
def tw(s, w):  # width at font-size 1, incl. letter-spacing .02em
    f = fonts[w]; cm = f.getBestCmap(); hm = f['hmtx']
    return sum(hm[cm.get(ord(ch), cm[ord('?')])][0] for ch in s) / 1000 + 0.02 * (len(s) - 1)
def splits(name):
    w = name.upper().split()
    out = [[' '.join(w)]]
    for i in range(1, len(w)): out.append([' '.join(w[:i]), ' '.join(w[i:])])
    for i in range(1, len(w)):
        for j in range(i + 1, len(w)): out.append([' '.join(w[:i]), ' '.join(w[i:j]), ' '.join(w[j:])])
    return out
ANG = [0, 20, -20, 40, -40, 60, -60, -90]
PAD = 1.18
def place(name, poly):
    best = None
    if poly.geom_type == 'MultiPolygon': poly = max(poly.geoms, key=lambda p: p.area)
    poly = poly.simplify(0.2)
    cx0, cy0 = poly.centroid.x, poly.centroid.y
    for ang in ANG:
        rp = rotate(poly, -ang, origin=(cx0, cy0)); shapely.prepare(rp)
        x0, y0, x1, y1 = rp.bounds
        gx, gy = np.meshgrid(np.linspace(x0, x1, 24), np.linspace(y0, y1, 24))
        pts = shapely.points(gx.ravel(), gy.ravel())
        inside = pts[shapely.contains(rp, pts)]
        if len(inside) == 0: inside = np.array([shapely.Point(rp.representative_point())])
        d = shapely.distance(inside, rp.exterior)
        cand = list(inside[np.argsort(-d)[:18]]) + [shapely.ops.polylabel(rp, 0.05)]
        cx = np.array([p.x for p in cand]); cy = np.array([p.y for p in cand])
        for L in splits(name):
            for wt in (400,):
                w = max(tw(s, wt) for s in L) * PAD; h = ((len(L) - 1) * 0.95 + 0.657) * PAD + 0.25
                lo = np.zeros(len(cand)); hi = np.full(len(cand), min((x1 - x0) / w, (y1 - y0) / h))
                for _ in range(11):
                    m = (lo + hi) / 2
                    ok = shapely.contains(rp, shapely.box(cx - w * m / 2, cy - h * m / 2, cx + w * m / 2, cy + h * m / 2))
                    lo = np.where(ok, m, lo); hi = np.where(ok, hi, m)
                k = int(np.argmax(lo)); fs = lo[k]
                score = fs * (1 - 0.0025 * abs(ang)) * (1 - 0.03 * (len(L) - 1))
                if best is None or score > best[0]:
                    c = rotate(Point(cx[k], cy[k]), ang, origin=(cx0, cy0))
                    best = (score, fs, ang, L, c.x, c.y)
    return best

out = []
for l, sg in zip(locs, SG):
    pl = proj(l['gl']) if l['gl'].area > 0.02 * l['g'].area else proj(l['g'])
    pl = pl.buffer(0)
    if pl.is_empty: pl = proj(l['g'])
    _, fs, ang, L, x, y = place(l['base'], pl)
    fs = min(fs, 18)
    if fs >= 8.5:  # bold is wider: refit width
        w4 = max(tw(s, 400) for s in L); w7 = max(tw(s, 700) for s in L); fs = fs * w4 / w7
    out.append(dict(n=l['n'], d=polyd(sg), c=col[l['n']], a=l['a'], k=l['k'], x=round(x, 2), y=round(y, 2),
                    fs=round(fs, 2), ang=ang, L=L, w=700 if fs >= 8.2 else 400, **({'p': round(l['p'], 2)} if l['p'] < 0.97 else {})))
log('labels done')

# ---------- extents ----------
allp = unary_union([proj(g) for g in G])
x0, y0, x1, y1 = allp.bounds
cn = []
for (short, full), cg in zip(COUNCILS, CG):
    b = proj(cg.intersection(land_ll)).bounds
    cn.append(dict(n=short, full=full, b=[round(v, 1) for v in (b[0], b[1], b[2] - b[0], b[3] - b[1])]))
# home view: all council land
hb = unary_union([proj(cg.intersection(land_ll)) for cg in CG]).bounds
box_ = [hb[0], hb[1], hb[2] - hb[0], hb[3] - hb[1]]

wb = box(*shapely.affinity.affine_transform(box(hb[0] - 2000, hb[1] - 2000, hb[2] + 2000, hb[3] + 2000),
                                             [1 / A, 0, 0, 1 / C, -B / A, -DD / C]).bounds).intersection(bb)
land = proj(land_ll.intersection(wb)).simplify(0.2).buffer(0)
land = unary_union([g for g in getattr(land, 'geoms', [land]) if g.area > 0.2])
shore = proj(coast.intersection(wb)).simplify(0.2)

# ---------- rivers ----------
rv = []
for e in json.load(open(DL + 'rivers.json'))['elements']:
    if e['type'] == 'way':
        c = [(p['lon'], p['lat']) for p in e['geometry']]
        if len(c) > 3 and c[0] == c[-1]: rv.append(Polygon(c).buffer(0))
    else:
        rv.append(relpoly(e))
river = proj(unary_union(rv).intersection(wb)).simplify(0.15).buffer(0)
river = unary_union([g for g in getattr(river, 'geoms', [river]) if g.area > 0.08])

# council boundary lines (each shared edge once)
cbl = unary_union([proj(cg).boundary for cg in CG]).simplify(0.2)
old = json.load(open(DL + 'extras.json'))  # river label path, POIs, water label positions
D = dict(f=out, cn=cn, land=polyd(land), shore=lined(shore), river=polyd(river), rlab=old['rlab'], cb=lined(linemerge(cbl) if cbl.geom_type == 'MultiLineString' else cbl),
         box=[round(v, 2) for v in box_], pois=old['pois'], bay=old['bay'], pac=old['pac'], adj=adj)
js = 'const D=' + json.dumps(D, separators=(',', ':'), ensure_ascii=False) + ';'
i = page.index('const D='); j = page.index('\n', i)
open(PAGE, 'w').write(page[:i] + js + page[j:])
log('sizes', {k: len(json.dumps(v, separators=(',', ':'), ensure_ascii=False)) for k, v in D.items()})
log('per council', [(c['n'], sum(1 for f in out if i in f['k'])) for i, c in enumerate(cn)])
