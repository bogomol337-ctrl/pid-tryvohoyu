# -*- coding: utf-8 -*-
"""
Оцінка каналів: який із них справді вартий того, щоб на нього спиратися.

Питання «які канали брати» вирішується не на смак, а вимірюванням. Для
кожного каналу рахуємо чотири речі:

  обсяг       скільки корисних повідомлень дає
  точність    чи збігаються його повідомлення з офіційними тривогами
  географія   чи називає конкретні населені пункти, чи тільки області
  швидкість   на скільки хвилин випереджає офіційне оголошення тривоги

Останнє — найважливіше для бота. Канал, який пише через 10 хвилин після
офіційної сирени, для попереджень марний.

    python sources.py

Читає messages.db і official_data_uk.csv.
"""

import sqlite3, os, sys, bisect, collections
import pandas as pd

DB = sys.argv[1] if len(sys.argv) > 1 else 'messages.db'
# cross_check.py зберігає датасет як official_alerts.csv,
# build_alerts.py — як official_data_uk.csv. Беремо будь-який наявний.
CSV = next((f for f in ('official_alerts.csv', 'official_data_uk.csv')
            if os.path.exists(f)), None)
if not CSV:
    sys.exit('Немає датасету тривог — запусти спершу cross_check.py')
print(f"Датасет: {CSV}")

al = pd.read_csv(CSV)
al['s'] = pd.to_datetime(al.started_at, utc=True, errors='coerce')
al['f'] = pd.to_datetime(al.finished_at, utc=True, errors='coerce')
al = al.dropna(subset=['s', 'f', 'oblast'])
al = al[al.f > al.s]

# Початки тривог по областях — щоб міряти випередження
starts = {}
windows = {}
for ob, g in al.groupby('oblast'):
    o = ob.replace(' область', '')
    starts[o] = sorted(g.s.values)
    iv = sorted(zip(g.s.values, g.f.values))
    merged = []
    for s, f in iv:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], f))
        else:
            merged.append((s, f))
    windows[o] = merged

span_h = (al.f.max() - al.s.min()).total_seconds() / 3600
base = {o: sum((f - s) / pd.Timedelta(hours=1) for s, f in iv) / span_h * 100
        for o, iv in windows.items()}
BASE = sum(base.values()) / len(base)
print(f"Базовий рівень: {BASE:.1f}% часу області під тривогою")
print("Усе, що не вище за це, — випадковий шум.\n")


def in_window(o, t, lead=25, lag=15):
    iv = windows.get(o)
    if not iv:
        return None
    ss = [x[0] for x in iv]
    i = bisect.bisect_right(ss, t + pd.Timedelta(minutes=lead).to_timedelta64()) - 1
    if i < 0:
        return False
    s, f = iv[i]
    return (s - pd.Timedelta(minutes=lead).to_timedelta64()) <= t <= \
           (f + pd.Timedelta(minutes=lag).to_timedelta64())


def lead_minutes(o, t):
    """На скільки хвилин повідомлення випередило найближчий початок тривоги."""
    ss = starts.get(o)
    if not ss:
        return None
    i = bisect.bisect_left(ss, t)
    best = None
    for j in (i - 1, i):
        if 0 <= j < len(ss):
            d = (ss[j] - t) / pd.Timedelta(minutes=1).to_timedelta64()
            if -30 <= d <= 60 and (best is None or abs(d) < abs(best)):
                best = d
    return best


con = sqlite3.connect(DB)
try:
    rows = con.execute("""
        SELECT channel, oblast, settlement, ts FROM events
        WHERE oblast IS NOT NULL AND ts >= '2022-03-16'""").fetchall()
except sqlite3.OperationalError:
    sys.exit('Немає таблиці events — запусти спершу extract_all.py')
print(f"Подій: {len(rows):,}\n".replace(',', ' '))

stat = collections.defaultdict(lambda: {
    'n': 0, 'hit': 0, 'geo': 0, 'leads': [], 'obl': set()})

for ch, ob, st, ts in rows:
    o = (ob or '').replace(' область', '')
    t = pd.Timestamp(ts).to_datetime64()
    d = stat[ch]
    d['n'] += 1
    d['obl'].add(o)
    if st:
        d['geo'] += 1
    r = in_window(o, t)
    if r:
        d['hit'] += 1
    lm = lead_minutes(o, t)
    if lm is not None:
        d['leads'].append(lm)

print("=" * 78)
print(f"{'канал':<16}{'подій':>9}{'точність':>10}{'до бази':>9}"
      f"{'з НП':>8}{'областей':>10}{'випередж.':>11}")
print("=" * 78)

verdicts = {}
for ch in sorted(stat, key=lambda c: -stat[c]['n']):
    d = stat[ch]
    prec = d['hit'] / d['n'] * 100 if d['n'] else 0
    lift = prec / BASE if BASE else 0
    geo = d['geo'] / d['n'] * 100 if d['n'] else 0
    lead = (sorted(d['leads'])[len(d['leads']) // 2]
            if d['leads'] else None)
    lead_s = f"{lead:+.0f} хв" if lead is not None else "—"
    print(f"{ch:<16}{d['n']:>9,}{prec:>9.1f}%{lift:>8.1f}x"
          f"{geo:>7.0f}%{len(d['obl']):>10}{lead_s:>11}".replace(',', ' '))

    # Придатність для бота: потрібні точність, географія і випередження
    ok_prec = lift >= 1.8
    ok_geo = geo >= 25
    ok_lead = lead is not None and lead >= -2
    verdicts[ch] = (ok_prec, ok_geo, ok_lead)

print("\n" + "=" * 78)
print("ПРИДАТНІСТЬ ДЛЯ БОТА")
print("=" * 78)
for ch, (p, g, l) in verdicts.items():
    marks = []
    if not p:
        marks.append('низька точність')
    if not g:
        marks.append('майже без населених пунктів')
    if not l:
        marks.append('пише пізніше за офіційну тривогу')
    print(f"  {ch:<16}" + ('придатний' if not marks else 'ні: ' + ', '.join(marks)))

print("""
Як читати:
  точність   — частка подій у вікні офіційної тривоги
  до бази    — у скільки разів краще за випадковість; x1.0 = шум
  з НП       — частка подій із конкретним населеним пунктом, не лише областю
  випередж.  — медіана: плюс означає, що канал пише ДО офіційної тривоги

Для бота потрібні всі три: точність від x1.8, географія від 25%,
випередження не гірше -2 хвилин. Канал, що пише після сирени,
для попереджень не потрібен — людина вже почула сирену.
""")
con.close()
