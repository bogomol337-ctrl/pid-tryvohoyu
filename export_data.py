# -*- coding: utf-8 -*-
"""
Викладає агреговані дані у відкритий формат — те, на що зможуть
посилатися журналісти й дослідники.

    python export_data.py

Створює теку data/ з CSV-файлами та README.
Сирі тексти повідомлень НЕ експортуються: це чужий контент,
а користь дають агрегати.
"""

import sqlite3, csv, json, os, sys, collections

DB = sys.argv[1] if len(sys.argv) > 1 else 'messages.db'
OUT = 'data'
os.makedirs(OUT, exist_ok=True)
con = sqlite3.connect(DB)


def dump(name, header, rows, note):
    path = os.path.join(OUT, name)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f"  {name:34s} {len(rows):>7} рядків — {note}")
    return len(rows)


print("Експортую…")

# 1. Згадки населених пунктів у попередженнях
r1 = con.execute("""
    SELECT matched, oblast, raion, lat, lon, substr(ts,1,7) AS ym,
           weapon, SUM(jet), COUNT(*)
    FROM threats_geo WHERE matched IS NOT NULL
    GROUP BY matched, oblast, ym, weapon ORDER BY ym, matched""").fetchall()
dump('threat_mentions_by_month.csv',
     ['settlement', 'oblast', 'raion', 'lat', 'lon', 'month',
      'weapon_class', 'jet_count', 'mentions'],
     r1, 'згадки НП у попередженнях ПС ЗСУ, по місяцях')

# 2. Ракетна небезпека по областях
r2 = con.execute("""
    SELECT oblast, substr(ts,1,7) AS ym, COUNT(*)
    FROM threats_geo
    WHERE weapon IN ('missile_alert','ballistic','cruise','kinzhal','antiship')
      AND oblast IS NOT NULL
    GROUP BY oblast, ym ORDER BY ym, oblast""").fetchall()
dump('missile_alerts_by_oblast.csv', ['oblast', 'month', 'alerts'], r2,
     'оголошення ракетної небезпеки')

# 3. Зведення по ночах
r3 = []
for ts, night, launched, destroyed, impacts, debris in con.execute(
        """SELECT ts, night_of, launched, destroyed, impact_locations,
                  debris_locations FROM summaries ORDER BY ts"""):
    L = json.loads(launched or '{}')
    D = json.loads(destroyed or '{}')
    r3.append([ts[:10], night,
               L.get('drone_mixed') or L.get('shahed') or L.get('drone') or '',
               'yes' if 'drone_mixed' in L else 'no',
               L.get('ballistic', ''), L.get('cruise', ''),
               L.get('kinzhal', ''), L.get('guided_air', ''),
               sum(D.values()) or '', impacts or '', debris or ''])
dump('nightly_summaries.csv',
     ['date', 'night_of', 'drones_launched', 'drones_reported_as_one_package',
      'ballistic', 'cruise', 'kinzhal', 'guided_air',
      'destroyed_total', 'impact_locations', 'debris_locations'],
     r3, 'ранкові зведення ПС ЗСУ')

# 4. Рейтинг НП за весь період
r4 = con.execute("""
    SELECT matched, oblast, raion, lat, lon, COUNT(*) c,
           ROUND(AVG(jet), 3), MIN(substr(ts,1,10)), MAX(substr(ts,1,10))
    FROM threats_geo WHERE matched IS NOT NULL
    GROUP BY matched, oblast ORDER BY c DESC""").fetchall()
dump('settlements_total.csv',
     ['settlement', 'oblast', 'raion', 'lat', 'lon', 'mentions',
      'jet_share', 'first_seen', 'last_seen'], r4, 'підсумок по НП')

README = """# Під тривогою — відкриті дані

Агреговані дані про повітряну загрозу в Україні, зібрані з публічних джерел.

## Файли

| Файл | Що всередині |
|---|---|
| `threat_mentions_by_month.csv` | Скільки разів кожен населений пункт згадували в оперативних попередженнях Повітряних Сил, по місяцях і типах цілі |
| `missile_alerts_by_oblast.csv` | Оголошення ракетної небезпеки по областях |
| `nightly_summaries.csv` | Ранкові зведення ПС ЗСУ: скільки запущено, збито, на скількох локаціях влучання |
| `settlements_total.csv` | Підсумок по кожному населеному пункту за весь період |

## Як це читати — і як не треба

**Згадка не дорівнює влучанню.** Повітряні Сили називають населений пункт,
коли ціль летить у його бік. Більшість цих цілей збили або вони пройшли повз.

**Великі міста завищені.** Їх називають частіше не тому, що там небезпечніше,
а тому, що вони служать орієнтирами для опису курсу.

**Повнота джерела змінювалася.** У 2022 році публікували в рази менше
повідомлень, ніж зараз. Порожнеча в ранніх періодах — це брак даних, не спокій.

**Ракети майже не мають географії.** Ракетну небезпеку оголошують тільки
по областях: підлітний час балістики — хвилини, а маршрут крилатих
не оприлюднюють навмисно.

**Дрони не розкладені за типами.** З 2025 року ПС пишуть одним числом
на весь пакет, де змішані «шахеди», «Гербери», «Італмаси» та приманки.

## Методика

Повідомлення зібрано MTProto-клієнтом із публічного каналу Повітряних Сил ЗСУ.
Розбір тексту — правила на регулярних виразах. Прив'язка назв до координат —
довідник населених пунктів KSE (28 658 записів) з урахуванням українських
відмінків і чергування і/о. Для неоднозначних назв (Іванівок у довіднику 116)
застосовано топологічний метчинг: обирається та, що ближча до маршруту цілі
за попередні години.

Точність прив'язки топонімів — близько 99%. Перевірено вручну на топ-30 назв.

## Джерела

- Сповіщення про тривоги: [Vadimkin/ukrainian-air-raid-sirens-dataset](https://github.com/Vadimkin/ukrainian-air-raid-sirens-dataset)
- Довідник населених пунктів: [KSE Loc Data Hub](https://github.com/kse-ua/KSE-Loc-Data-Hub)
- Межі районів і громад: [ukrainian_geodata](https://github.com/slawomirmatuszak/ukrainian_geodata)
- Оперативні повідомлення: канал Повітряних Сил ЗСУ

## Ліцензія

CC BY 4.0 — користуйтеся вільно, зазначайте джерело.
"""
open(os.path.join(OUT, 'README.md'), 'w', encoding='utf-8').write(README)
print(f"  {'README.md':34s}         — методика та застереження")

size = sum(os.path.getsize(os.path.join(OUT, f)) for f in os.listdir(OUT))
print(f"\nГотово: тека {OUT}/ ({size // 1024} KB)")
print("Заливай у публічний репозиторій на GitHub.")
con.close()
