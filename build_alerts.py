# -*- coding: utf-8 -*-
"""
Перераховує статистику тривог зі свіжого датасету.

Без цього скрипта сторінки, побудовані на тривогах, лишаються замороженими:
геометрія районів у репозиторії є, а цифри в ній — станом на день першої
збірки. Тут вони оновлюються.

    python build_alerts.py

Читає:  official_data_uk.csv, raiony_alerts.geojson (геометрія)
Пише:   raiony_alerts.geojson (з новими цифрами), oblast_stats.json
"""

import json, os, sys, collections
import pandas as pd

CSV = next((f for f in ('official_data_uk.csv', 'official_alerts.csv')
            if os.path.exists(f)), None)
GEO = 'raiony_alerts.geojson'
if not CSV:
    sys.exit('Немає датасету тривог — запусти cross_check.py або workflow')
if not os.path.exists(GEO):
    sys.exit(f'Немає {GEO} — поклади його поруч зі скриптом')
print(f"Датасет: {CSV}")

geo = json.load(open(GEO, encoding='utf-8'))
r2o = {f['properties']['name']: f['properties']['oblast'] for f in geo['features']}
print(f"Районів у геометрії: {len(r2o)}")


def norm(s):
    return (s.replace('\u2019', "'").replace('\u02bc', "'").strip()
            if isinstance(s, str) else s)


RENAME = {'Звягельський район': 'Новоград-Волинський район',
          'Самарівський район': 'Новомосковськ район'}

df = pd.read_csv(CSV)
df['s'] = pd.to_datetime(df.started_at, utc=True, errors='coerce')
df['f'] = pd.to_datetime(df.finished_at, utc=True, errors='coerce')
df = df.dropna(subset=['s', 'f', 'oblast'])
df = df[df.f > df.s]
df = df[(df.f - df.s).dt.total_seconds() / 3600 < 72]
df['raion'] = df.raion.map(norm).replace(RENAME)
print(f"Записів про тривоги: {len(df):,}".replace(',', ' '))
print(f"Період: {df.s.min().date()} — {df.s.max().date()}")

# Вікно — останні 20 місяців від найсвіжішого запису. Прив'язуємось до даних,
# а не до фіксованої дати, інакше з часом вікно поїде в минуле.
END = df.f.max()
START = (END - pd.DateOffset(months=20)).tz_convert('UTC')
TOT = (END - START).total_seconds() / 3600
print(f"Вікно розрахунку: {START.date()} — {END.date()} ({TOT / 24:.0f} діб)")

w = df[(df.f > START) & (df.s < END)].copy()
w['s'] = w.s.clip(lower=START)
w['f'] = w.f.clip(upper=END)


def union(iv):
    """Сумарний час, покритий інтервалами, без подвійного рахунку перекриттів."""
    if not iv:
        return 0.0, 0
    iv = sorted(iv)
    tot = 0.0
    ep = 0
    cs, ce = iv[0]
    for s, f in iv[1:]:
        if s <= ce:
            ce = max(ce, f)
        else:
            tot += (ce - cs).total_seconds()
            ep += 1
            cs, ce = s, f
    tot += (ce - cs).total_seconds()
    ep += 1
    return tot / 3600, ep


obl_iv = {o: list(zip(g.s, g.f)) for o, g in w[w.level == 'oblast'].groupby('oblast')}
rai_iv = {r: list(zip(g.s, g.f))
          for r, g in w[w.level.isin(['raion', 'hromada'])].groupby('raion')}

# --- райони: власні тривоги + загальнообласні, бо область накриває район
changed = 0
for f in geo['features']:
    p = f['properties']
    rn = p['name']
    ob = r2o.get(rn)
    iv = rai_iv.get(rn, []) + obl_iv.get(ob + ' область' if ob else '', [])
    if not iv:
        iv = obl_iv.get((ob or '') + ' область', [])
    if not iv:
        p['pct'] = p['eps'] = None
        p['own'] = 0
        continue
    h, ep = union(iv)
    old = p.get('pct')
    p['pct'] = round(h / TOT * 100, 1)
    p['eps'] = ep
    p['own'] = len(rai_iv.get(rn, []))
    if old != p['pct']:
        changed += 1

json.dump(geo, open(GEO, 'w'), ensure_ascii=False)
have = [f['properties'] for f in geo['features'] if f['properties']['pct'] is not None]
have.sort(key=lambda x: -x['pct'])
print(f"\nОновлено районів: {changed} з {len(geo['features'])} "
      f"(з даними: {len(have)})")
print("Найвищі значення:")
for x in have[:5]:
    print(f"   {x['name']:<26}{x['pct']:>6.1f}%   {x['oblast']}")
print("Найнижчі:")
for x in have[-3:]:
    print(f"   {x['name']:<26}{x['pct']:>6.1f}%   {x['oblast']}")

# --- області: повна історія, не вікно
rows = []
for ob, g in df.groupby('oblast'):
    h, ep = union(list(zip(g.s, g.f)))
    by = {}
    for y, gg in g.groupby(g.s.dt.year):
        hy, epy = union(list(zip(gg.s, gg.f)))
        by[int(y)] = {'h': round(hy, 1), 'n': epy}
    rows.append({'oblast': ob, 'hours': round(h, 1), 'n': ep,
                 'median_min': round(float(((g.f - g.s).dt.total_seconds() / 60).median()), 1),
                 'by_year': by})
rows.sort(key=lambda r: -r['hours'])
json.dump({'rows': rows,
           'from': str(df.s.min().date()), 'to': str(df.f.max().date())},
          open('oblast_stats.json', 'w'), ensure_ascii=False)
print(f"\noblast_stats.json: {len(rows)} областей")
for r in rows[:3]:
    print(f"   {r['oblast']:<26}{r['hours']:>9.0f} год")
