# -*- coding: utf-8 -*-
"""
Прив'язує топоніми з таблиці threats до координат.

Топологічний метчинг: повідомлення обробляються в хронологічному порядку,
і для кожного зберігається «слід» — координати цілей за останні кілька годин.
Коли трапляється неоднозначна назва (Іванівок у довіднику 116), обирається
та, що лежить найближче до цього сліду, а не найбільша за розміром.

    python geocode_threats.py
"""

import sqlite3, json, sys, math, collections, datetime as dt
from geocode import Gazetteer, low

DB = sys.argv[1] if len(sys.argv) > 1 else 'messages.db'
WINDOW_H = 6        # скільки годин слід лишається актуальним
MAX_KM = 200        # далі за це відстань до сліду вже не аргумент

gz = Gazetteer('gazetteer.csv')
print(f"Довідник: {len(gz.rows)} населених пунктів")

homonyms = collections.defaultdict(list)
for r in gz.rows:
    homonyms[low(r['name'])].append(r)
ambiguous = {k: v for k, v in homonyms.items() if len(v) > 1}
worst = sorted(ambiguous.items(), key=lambda x: -len(x[1]))[:3]
print("Неоднозначних назв: %d (найгірші: %s)\n" % (
    len(ambiguous), ', '.join(f"{n} ×{len(v)}" for n, v in worst)))


def dist_km(a, b):
    dy = (a[0] - b[0]) * 111.0
    dx = (a[1] - b[1]) * 111.0 * math.cos(math.radians((a[0] + b[0]) / 2))
    return math.hypot(dx, dy)


def resolve(token, hint, anchors):
    base = gz.find(token, hint)
    if not base:
        return None, False
    cands = ambiguous.get(low(base['name']))
    if not cands or not anchors:
        return base, False

    def score(c):
        d = min(dist_km((c['lat'], c['lon']), a) for a in anchors)
        near = hint and low(c['oblast_name']).startswith(low(hint)[:6])
        return (0 if near else 1, d if d <= MAX_KM else 9e9, c['rank'])

    best = min(cands, key=score)
    moved = best['oblast_name'] != base['oblast_name']
    return best, moved


con = sqlite3.connect(DB)
con.executescript("""
CREATE TABLE IF NOT EXISTS threats_geo (
    ts TEXT, weapon TEXT, jet INT, place TEXT, matched TEXT,
    settlement_type TEXT, hromada TEXT, raion TEXT, oblast TEXT,
    lat REAL, lon REAL, topo INT DEFAULT 0);
CREATE INDEX IF NOT EXISTS idx_tg_ts ON threats_geo(ts);
CREATE INDEX IF NOT EXISTS idx_tg_obl ON threats_geo(oblast);
""")
try:
    con.execute("ALTER TABLE threats_geo ADD COLUMN topo INT DEFAULT 0")
except sqlite3.OperationalError:
    pass
con.execute("DELETE FROM threats_geo")

rows = con.execute(
    "SELECT ts, weapon, jet, oblasts, places FROM threats ORDER BY ts").fetchall()
print(f"Записів у threats: {len(rows)}")

hit = miss = oblword = nogeo = topo_fix = 0
missed = collections.Counter()
per_place = collections.Counter()
anchors = collections.deque()
batch = []


def epoch(ts):
    try:
        return dt.datetime.fromisoformat(ts).timestamp()
    except Exception:
        return 0.0


for ts, weapon, jet, obl_json, pl_json in rows:
    oblasts = json.loads(obl_json or '[]')
    places = json.loads(pl_json or '[]')
    hint = oblasts[0] if oblasts else None
    now = epoch(ts)

    while anchors and now - anchors[0][0] > WINDOW_H * 3600:
        anchors.popleft()
    ctx = tuple((a[1], a[2]) for a in anchors)

    if not places:
        nogeo += 1
        for o in oblasts:
            batch.append((ts, weapon, jet, None, None, None, None, None, o, None, None, 0))
        continue

    for p in places:
        if gz.is_oblast_word(p):
            oblword += 1
            continue
        r, moved = resolve(p, hint, ctx)
        if not r:
            miss += 1
            missed[p] += 1
            continue
        hit += 1
        topo_fix += int(moved)
        per_place[r['name']] += 1
        anchors.append((now, r['lat'], r['lon']))
        batch.append((ts, weapon, jet, p, r['name'], r['settlement_type'],
                      r.get('hromada_name'), r.get('raion_name'),
                      r['oblast_name'], r['lat'], r['lon'], int(moved)))

con.executemany("INSERT INTO threats_geo VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", batch)
con.commit()

total = hit + miss
print(f"\nПрив'язано:        {hit:>7} ({hit / max(total,1) * 100:.1f}% від придатних)")
print(f"  уточнено маршрутом:{topo_fix:>6} ({topo_fix / max(hit,1) * 100:.1f}%)")
print(f"Не розпізнано:     {miss:>7} ({miss / max(total,1) * 100:.1f}%)")
print(f"Назви областей:    {oblword:>7} (не помилка)")
print(f"Повідомлень без НП:{nogeo:>7} (тільки область)")

print("\nТоп-20 населених пунктів:")
for p, n in per_place.most_common(20):
    print(f"   {p:24s} {n:>6}")

if missed:
    print("\nТоп-15 нерозпізнаних:")
    for p, n in missed.most_common(15):
        print(f"   {p:24s} {n:>6}")

print("\nПриклади уточнень маршрутом:")
for r in con.execute("""SELECT place, matched, oblast, COUNT(*) c FROM threats_geo
                        WHERE topo=1 GROUP BY matched, oblast
                        ORDER BY c DESC LIMIT 10"""):
    print(f"   {r[0]:18s} -> {r[1]:16s} {r[2]:22s} x{r[3]}")
con.close()
