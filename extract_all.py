# -*- coding: utf-8 -*-
"""
Витягує події з УСІХ каналів у базі, а не лише з kpszsu.

Головна відмінність від parse_kpszsu.py: топоніми шукаються не за
прийменниками («курсом на», «в районі»), а звіркою кожного слова
з великої літери з довідником населених пунктів. Саме тому працює
телеграфний стиль моніторингових каналів:

    Реактив на Рокитне - БЦ з півночі.
    Реактив Носівка.
    БПЛА Ситківці - Дашів.

Кожен рядок — окрема подія. Сленг («мопеди», «бляхи») впливає лише
на визначення типу цілі й лежить у списку нижче; назви міст беруться
з довідника й від сленгу не залежать.

    python extract_all.py

Створює таблицю events: час, канал, тип цілі, НП, координати, текст рядка.
"""

import sqlite3, re, sys, math, collections, datetime as dt
from geocode import Gazetteer, low

DB = sys.argv[1] if len(sys.argv) > 1 else 'messages.db'
WINDOW_H = 6
MAX_KM = 200

# Тип цілі. Порядок важливий — перший збіг виграє.
WEAPONS = [
    # Наслідки — перевіряються першими: у таких повідомленнях типу зброї часто
    # немає взагалі («Вибухи в Києві», «Працює ППО на Одещині»)
    ('explosion',     r'вибух\w*|гучно|чути\s+вибух|детонац'),
    ('ppo',           r'\bппо\b|протиповітрян\w*\s+оборон|працює\s+ппо|'
                      r'робота\s+ппо|збива\w+|мвг|мобільн\w*\s+вогнев'),
    ('kinzhal',       r'кинджал|х-?47|міг-?31'),
    ('ballistic',     r'баліст|іскандер-?м|kn-?23|кн-?23|с-?300|с-?400'),
    ('cruise',        r'калібр|х-?101|х-?555|крилат|іскандер-?к'),
    ('guided_air',    r'х-?59|х-?69|х-?31|х-?35|керован\w*\s+авіаційн'),
    ('kab',           r'\bкаб\b|\bкаби\b|умпб|умпк|авіабомб'),
    ('missile_alert', r'ракетн\w*\s+(?:небезпек|загроз)|швидкісн\w*\s+ціл|ракетна атака'),
    ('recon',         r'орлан|зала|розвідувальн\w*\s+бпла'),
    # сленг мониторингових каналів — саме те, чого немає в офіційних зведеннях
    ('drone',         r'бпла|дрон|шахед|shahed|герань|гербера|італмас|пародія|'
                      r'реактив|мопед|бляха|кукурузник|борт|беспілотн|безпілотн'),
    # «Збито 12 ворожих цілей над Кременчуком» — тип не названо, але подія є
    ('target',        r'\bціл[ьіеяй]\w*|повітрян\w*\s+ціл|загроз\w*\s+для'),
]

# Слова, які виглядають як топонім, але ним не є
STOP = {
    'бпла', 'реактив', 'реактивний', 'реактивні', 'бц', 'увага', 'курс', 'курсом',
    'група', 'групи', 'північ', 'південь', 'схід', 'захід', 'околиці', 'ціль',
    'цілі', 'район', 'районі', 'загроза', 'вибухи', 'вибух', 'укриття', 'увагу',
    'обережно', 'місто', 'напрямку', 'напрямок', 'область', 'області', 'обл',
    'балістика', 'балістику', 'ракета', 'ракети', 'ракетна', 'ракетну',
    'шахед', 'шахеди', 'шахедів', 'мопед', 'мопеди', 'дрон', 'дрони',
    'каб', 'каби', 'кинджал', 'калібр', 'іскандер', 'герань', 'гербера',
    'пародія', 'італмас', 'бляха', 'бляхи', 'борт', 'борти', 'увага!',
    'росія', 'рф', 'тот', 'крим', 'україна', 'україни', 'мить', 'сили',
    'повітряні', 'зсу', 'ппо', 'реб', 'новини', 'підписатися', 'джерело',
    # Пастки, знайдені на реальних даних. Кожне з цих слів ловилось довідником
    # як населений пункт і забруднювало топ:
    'атака', 'атаки', 'атаку', 'атакою', 'атакували',      # -> село Атаки
    'ворожа', 'ворожий', 'ворожі', 'ворожих', 'ворожої',
    'ворожою', 'ворожим', 'ворожими', 'ворожу',            # -> місто Ворожба
    'молнія', 'блискавка',                                 # -> село Молниця
    'тривога', 'тривоги', 'тривогу',                       # -> село Тривайли
    'небезпека', 'небезпеку', 'небезпеки',                 # -> село Небелівка
    'повітряна', 'повітряний', 'повітряних', 'повітряної',  # -> село Повітно
    'швидкісна', 'швидкісні', 'ударні', 'ударний', 'уламки', 'уламків',
    'відбій', 'вибухів', 'гучно', 'працює', 'працюють', 'рухається',
    'зафіксовано', 'знищено', 'збито', 'подавлено', 'мобільні', 'вогневі',
    'масована', 'масовану', 'масовий', 'масована!',        # -> село Масівці
    'комбінований', 'комбінована', 'групова', 'групи', 'кілька', 'декілька',
    # «Нові групи БпЛА…» — найчастіший початок повідомлення, ловився як Новоселиця
    'нові', 'нова', 'новий', 'нове', 'новою', 'знову',
    'коси', 'коса', 'косу',
    'багато', 'мало', 'частина', 'решта', 'решту',
    'наразі', 'зараз', 'тихо', 'відбій', 'скасовано', 'оновлення',
    'приблизно', 'орієнтовно', 'ймовірно', 'можливо', 'перша', 'друга',
    'сила', 'сили', 'силами', 'силою', 'силах',             # -> село Сила
    'кримськ', 'сумськ', 'харківськ', 'київськ', 'одеськ',  # прикметники областей
    'полтавськ', 'черкаськ', 'чернігівськ', 'вінницьк',
    'кримське', 'кримського', 'кримськ596', 'кримськ',      # -> смт Кримське
    'сумське', 'сумського', 'харківське', 'харківського',
    'дністра', 'дністер', 'дніпра', 'дніпром',              # річки, не міста
    'азовського', 'чорного', 'акваторії', 'моря', 'морем',
    'табун', 'сигнал', 'пусків', 'пуски', 'протягом', 'годин',
}

# Слова-напрямки. Це водночас і реальні міста (Південне на Харківщині,
# Північне на Донеччині), і сторони світу. Беремо їх лише тоді, коли поряд
# немає слова «напрямок» або «околиці» — інакше це опис курсу, не місто.
# Сторони світу в усіх формах. Довідник мапить їх на смт Південне (Харківщина)
# і смт Північне (Донеччина): «з Півдня», «на Південному-Сході», «з Півночі».
# Хибних спрацювань тисячі проти одиниць справжніх, тому відсіюємо безумовно.
DIRECTION = {
    'південне', 'південний', 'південна', 'південного', 'південному',
    'південною', 'південні', 'південних', 'півдня', 'півдні', 'південь',
    'північне', 'північний', 'північна', 'північного', 'північному',
    'північною', 'північні', 'північних', 'півночі', 'північ',
    'східне', 'східний', 'східна', 'східного', 'східному', 'сходу', 'схід',
    'західне', 'західний', 'західна', 'західного', 'західному', 'заходу', 'захід',
    'центральне', 'центральний', 'центрального', 'центр', 'центрі',
}

OBL_ADJ = re.compile(r'(ськ|цьк)(ої|ій|ою|а|у|им)?\s*(обл\b|області|область)', re.U)
TOKEN = re.compile(r"[А-ЯІЇЄҐ][а-яіїєґ'’\-]{2,}(?:\s+[А-ЯІЇЄҐ][а-яіїєґ'’\-]{2,})?", re.U)
JET = re.compile(r'реактивн', re.U)

gz = Gazetteer('gazetteer.csv')
homonyms = collections.defaultdict(list)
for r in gz.rows:
    homonyms[low(r['name'])].append(r)
ambiguous = {k: v for k, v in homonyms.items() if len(v) > 1}
print(f"Довідник: {len(gz.rows)} НП, з них неоднозначних назв {len(ambiguous)}")


def weapon_of(text):
    t = low(text)
    for name, pat in WEAPONS:
        if re.search(pat, t):
            return name
    return None


def dist_km(a, b):
    dy = (a[0] - b[0]) * 111.0
    dx = (a[1] - b[1]) * 111.0 * math.cos(math.radians((a[0] + b[0]) / 2))
    return math.hypot(dx, dy)


def resolve(token, anchors):
    base = gz.find(token, strict=True)
    if not base:
        return None
    cands = ambiguous.get(low(base['name']))
    if not cands or not anchors:
        return base
    return min(cands, key=lambda c: (
        min(dist_km((c['lat'], c['lon']), a) for a in anchors) if
        min(dist_km((c['lat'], c['lon']), a) for a in anchors) <= MAX_KM else 9e9,
        c['rank']))


def extract(text, anchors):
    """Повертає список подій із одного повідомлення."""
    out = []
    for line in re.split(r'[\n;]+', text):
        line = line.strip(' .!?-–—•')
        if len(line) < 4:
            continue
        w = weapon_of(line)
        if not w:
            continue
        jet = bool(JET.search(low(line)))
        obl_spans = [m.span() for m in OBL_ADJ.finditer(low(line))]
        seen = set()
        for m in TOKEN.finditer(line):
            tok = m.group(0).strip()
            lt = low(tok)
            if lt in STOP or gz.is_oblast_word(tok):
                continue
            if any(lt.startswith(d[:6]) for d in
                   ('південн', 'північн', 'східн', 'західн', 'півдн', 'півноч')):
                continue
            if any(a - 24 <= m.start() <= b for a, b in obl_spans):
                continue
            if low(tok) in DIRECTION:
                continue
            r = resolve(tok, anchors)
            if not r and ' ' in tok:
                for part in tok.split():
                    if low(part) in STOP or gz.is_oblast_word(part):
                        continue
                    r = resolve(part, anchors)
                    if r:
                        break
            if r and r['name'] not in seen:
                seen.add(r['name'])
                out.append((w, jet, tok, r, line[:220]))
    return out


con = sqlite3.connect(DB)
con.executescript("""
CREATE TABLE IF NOT EXISTS events (
    ts TEXT, channel TEXT, weapon TEXT, jet INT,
    raw TEXT, settlement TEXT, settlement_type TEXT,
    raion TEXT, oblast TEXT, lat REAL, lon REAL, line TEXT);
CREATE INDEX IF NOT EXISTS idx_ev_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_ev_set ON events(settlement);
""")
con.execute("DELETE FROM events")

rows = con.execute(
    "SELECT ts, channel, text FROM messages WHERE text IS NOT NULL ORDER BY ts").fetchall()
print(f"Повідомлень у базі: {len(rows):,}".replace(',', ' '))

anchors = collections.deque()
batch = []
per_channel = collections.Counter()
per_weapon = collections.Counter()
per_place = collections.Counter()
seen_msgs = 0


def epoch(ts):
    try:
        return dt.datetime.fromisoformat(ts).timestamp()
    except Exception:
        return 0.0


for ts, channel, text in rows:
    now = epoch(ts)
    while anchors and now - anchors[0][0] > WINDOW_H * 3600:
        anchors.popleft()
    ctx = tuple((a[1], a[2]) for a in anchors)

    ev = extract(text, ctx)
    if ev:
        seen_msgs += 1
    for w, jet, tok, r, line in ev:
        anchors.append((now, r['lat'], r['lon']))
        per_channel[channel] += 1
        per_weapon[w] += 1
        per_place[r['name']] += 1
        batch.append((ts, channel, w, int(jet), tok, r['name'],
                      r['settlement_type'], r.get('raion_name'),
                      r['oblast_name'], r['lat'], r['lon'], line))
    if len(batch) >= 20000:
        con.executemany("INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", batch)
        con.commit()
        batch.clear()

if batch:
    con.executemany("INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", batch)
    con.commit()

total = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
places = con.execute("SELECT COUNT(DISTINCT settlement) FROM events").fetchone()[0]
print(f"\nПодій витягнуто: {total:,}".replace(',', ' '))
print(f"Повідомлень, що дали хоч одну подію: {seen_msgs:,}".replace(',', ' '))
print(f"Унікальних населених пунктів: {places:,}".replace(',', ' '))

print("\nПо каналах:")
for c, n in per_channel.most_common():
    print(f"   {c:16s} {n:>8,}".replace(',', ' '))

print("\nПо типах цілі:")
for w, n in per_weapon.most_common():
    print(f"   {w:16s} {n:>8,}".replace(',', ' '))

print("\nТоп-20 населених пунктів:")
for p, n in per_place.most_common(20):
    print(f"   {p:24s} {n:>7,}".replace(',', ' '))

print("\nПо роках:")
for y, n in con.execute(
        "SELECT substr(ts,1,4), COUNT(*) FROM events GROUP BY 1 ORDER BY 1"):
    print(f"   {y}  {n:>8,}".replace(',', ' '))
con.close()
