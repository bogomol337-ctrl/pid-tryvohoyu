# -*- coding: utf-8 -*-
"""
Перехресна перевірка: наскільки наші події з телеграму збігаються
з офіційними тривогами.

Це відповідь на питання «як звіряти різні джерела». Офіційний датасет
тривог береться за еталон: якщо о 02:30 у Черкаській області була
оголошена тривога, а наш канал о 02:31 написав про БпЛА на Черкащині —
це збіг. Якщо канал написав, коли тривоги не було, — або він помилився,
або наш парсер поставив не ту область.

    pip install pandas requests
    python cross_check.py

Рахує по кожному каналу:
  precision  — частка наших подій, що потрапили у вікно офіційної тривоги
  coverage   — частка тривог, які канал взагалі помітив
  lead_time  — на скільки канал випереджає офіційне оголошення
"""

import sqlite3, sys, os, collections
import pandas as pd
import requests

DB = sys.argv[1] if len(sys.argv) > 1 else 'messages.db'
ALERTS = 'official_alerts.csv'
URL = ('https://raw.githubusercontent.com/Vadimkin/'
       'ukrainian-air-raid-sirens-dataset/main/datasets/official_data_uk.csv')

# Подія може випереджати тривогу (канал побачив раніше) або відставати
# (тривогу вже оголосили, канал уточнює курс). Обидва напрямки — збіг.
LEAD_MIN = 25      # скільки хвилин до тривоги ще вважаємо збігом
LAG_MIN = 15       # скільки хвилин після відбою ще вважаємо збігом

if not os.path.exists(ALERTS):
    print("Качаю офіційний датасет тривог…")
    r = requests.get(URL, timeout=180)
    r.raise_for_status()
    open(ALERTS, 'wb').write(r.content)
print(f"Датасет тривог: {os.path.getsize(ALERTS) // 1024 // 1024} MB")

al = pd.read_csv(ALERTS)
al['s'] = pd.to_datetime(al.started_at, utc=True, errors='coerce')
al['f'] = pd.to_datetime(al.finished_at, utc=True, errors='coerce')
al = al.dropna(subset=['s', 'f', 'oblast'])
al = al[al.f > al.s]
al['s'] -= pd.Timedelta(minutes=LEAD_MIN)
al['f'] += pd.Timedelta(minutes=LAG_MIN)
print(f"Тривог у датасеті: {len(al):,}".replace(',', ' '))

# Для швидкої перевірки «чи була тривога» тримаємо інтервали по областях
by_obl = {}
for ob, g in al.groupby('oblast'):
    iv = sorted(zip(g.s.values, g.f.values))
    merged = []
    for s, f in iv:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], f))
        else:
            merged.append((s, f))
    by_obl[ob.replace(' область', '')] = merged

import bisect
def under_alert(oblast, ts):
    iv = by_obl.get(oblast)
    if not iv:
        return None                      # немає даних по цій області
    starts = [x[0] for x in iv]
    i = bisect.bisect_right(starts, ts) - 1
    return i >= 0 and ts <= iv[i][1]

# Базовий рівень: яку частку часу область узагалі під тривогою.
# Випадковий шум дасть саме таку precision — усе, що не вище, нічого не значить.
BASE = {}
span = (al.f.max() - al.s.min()).total_seconds()
for ob, iv in by_obl.items():
    covered = sum((f - s) / pd.Timedelta(seconds=1) for s, f in iv)
    BASE[ob] = covered / span * 100 if span else 0
print(f"Базовий рівень (частка часу під тривогою): "
      f"{sum(BASE.values()) / len(BASE):.1f}% у середньому по областях")

con = sqlite3.connect(DB)
rows = con.execute("""
    SELECT channel, weapon, oblast, ts FROM events
    WHERE oblast IS NOT NULL AND ts >= '2022-03-16'""").fetchall()
print(f"Наших подій:      {len(rows):,}".replace(',', ' '))

hit = collections.Counter()
tot = collections.Counter()
nodata = collections.Counter()
by_weapon_hit = collections.Counter()
by_weapon_tot = collections.Counter()

for ch, w, ob, ts in rows:
    o = (ob or '').replace(' область', '')
    t = pd.Timestamp(ts).to_datetime64()
    r = under_alert(o, t)
    if r is None:
        nodata[ch] += 1
        continue
    tot[ch] += 1
    by_weapon_tot[w] += 1
    if r:
        hit[ch] += 1
        by_weapon_hit[w] += 1

print("\n" + "=" * 62)
print("ЗБІГ ІЗ ОФІЦІЙНИМИ ТРИВОГАМИ ПО КАНАЛАХ")
print("=" * 62)
print(f"{'канал':<16}{'подій':>9}{'збіг':>9}{'precision':>12}   до базового")
base_avg = sum(BASE.values()) / max(len(BASE), 1)
for ch in sorted(tot, key=lambda c: -tot[c]):
    p = hit[ch] / tot[ch] * 100 if tot[ch] else 0
    lift = p / base_avg if base_avg else 0
    mark = ' випадковий шум' if lift < 1.25 else (' слабко' if lift < 1.8 else '')
    print(f"{ch:<16}{tot[ch]:>9,}{hit[ch]:>9,}{p:>11.1f}%   x{lift:.1f}{mark}"
          .replace(',', ' '))

print("\n" + "=" * 62)
print("ЗБІГ ПО ТИПАХ ПОДІЙ")
print("=" * 62)
print(f"{'тип':<16}{'подій':>9}{'збіг':>9}{'precision':>12}")
for w in sorted(by_weapon_tot, key=lambda x: -by_weapon_tot[x]):
    n = by_weapon_tot[w]
    p = by_weapon_hit[w] / n * 100 if n else 0
    lift = p / base_avg if base_avg else 0
    flag = '  <- не краще за випадковість' if lift < 1.25 and n > 300 else ''
    print(f"{str(w):<16}{n:>9,}{by_weapon_hit[w]:>9,}{p:>11.1f}%{flag}"
          .replace(',', ' '))

# Скільки тривог канали взагалі помітили
print("\n" + "=" * 62)
print("ПОКРИТТЯ: чи бачили канали офіційні тривоги")
print("=" * 62)
ev = collections.defaultdict(list)
for ch, w, ob, ts in rows:
    ev[(ob or '').replace(' область', '')].append(pd.Timestamp(ts).to_datetime64())
for o in ev:
    ev[o].sort()

seen = miss = 0
per_obl = collections.Counter()
per_obl_tot = collections.Counter()
for ob, iv in by_obl.items():
    lst = ev.get(ob, [])
    if not lst:
        continue
    for s, f in iv:
        per_obl_tot[ob] += 1
        i = bisect.bisect_left(lst, s)
        if i < len(lst) and lst[i] <= f:
            seen += 1
            per_obl[ob] += 1
        else:
            miss += 1
if seen + miss:
    print(f"Тривог, які помітив хоча б один канал: {seen:,} з {seen + miss:,} "
          f"({seen / (seen + miss) * 100:.1f}%)".replace(',', ' '))

print("\nПокриття по областях (де найгірше — там дані найслабші):")
rank = sorted(((per_obl[o] / per_obl_tot[o] * 100, o, per_obl_tot[o])
               for o in per_obl_tot if per_obl_tot[o] > 50))
for p, o, n in rank[:8]:
    print(f"   {o:<24}{p:>6.1f}%   ({n} тривог)")
print("   …")
for p, o, n in rank[-5:]:
    print(f"   {o:<24}{p:>6.1f}%   ({n} тривог)")

con.close()
print("\nЯк читати:")
print(f"  Базовий рівень {base_avg:.0f}% — стільки дасть випадковий шум,")
print("  бо саме таку частку часу області в середньому під тривогою.")
print("  Множник x1.0 означає, що джерело не несе інформації взагалі.")
print("  x2 і вище — джерело справді бачить те, що бачить офіційна система.")
