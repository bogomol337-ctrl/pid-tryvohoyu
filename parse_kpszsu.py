# -*- coding: utf-8 -*-
"""
Розбір повідомлень каналу Повітряних Сил ЗСУ (kpszsu).

Два різні типи повідомлень, які треба парсити по-різному:

  SUMMARY  — ранкові зведення. Дають типи озброєння, кількість запущеного
             і збитого, число локацій влучань. Географії майже немає.
  THREAT   — оперативні попередження. Дають географію (області, населені
             пункти, курс), але не кажуть, чи було влучання.

Використання:
    from parse_kpszsu import parse
    rec = parse(ts, text)
"""

import re

# ---------------------------------------------------------------- словники

# числівники в орудному/родовому відмінку: "двома ракетами", "трьох ракет"
WORDNUM = {
    'одн': 1, 'одна': 1, 'однією': 1, 'одним': 1, 'однієї': 1,
    'дв': 2, 'два': 2, 'дві': 2, 'двома': 2, 'двох': 2,
    'три': 3, 'трьома': 3, 'трьох': 3,
    'чотири': 4, 'чотирма': 4, 'чотирьох': 4,
    "п'ять": 5, "п'ятьма": 5, "п'яти": 5, "п'ятьох": 5,
    'шість': 6, 'шістьма': 6, 'шести': 6, 'шістьох': 6,
    'сім': 7, 'сьома': 7, 'семи': 7, 'сімох': 7,
    'вісім': 8, 'вісьма': 8, 'восьми': 8, 'вісьмох': 8,
    "дев'ять": 9, "дев'ятьма": 9, "дев'яти": 9,
    'десять': 10, 'десятьма': 10, 'десяти': 10,
    'одинадцять': 11, 'одинадцятьма': 11,
    'дванадцять': 12, 'дванадцятьма': 12,
    'тринадцять': 13, 'чотирнадцять': 14,
    "п'ятнадцять": 15, 'шістнадцять': 16, 'сімнадцять': 17,
    'вісімнадцять': 18, "дев'ятнадцять": 19, 'двадцять': 20,
}

# порядок важливий: перший збіг виграє
WEAPONS = [
    ('kinzhal',    r'кинджал|х-?47|міг-?31'),          # зліт МіГ-31К = загроза Кинджалом
    ('ballistic',  r'баліст|іскандер-?м|kn-?23|кн-?23|с-?300|с-?400'),
    ('antiship',   r'циркон|онікс|протикорабель'),
    ('cruise',     r'калібр|х-?101|х-?555|іскандер-?к|крилат'),
    ('guided_air', r'х-?59|х-?69|х-?31|х-?35|керован\w* авіаційн'),
    ('kab',        r'\bкаб\b|умпб|умпк|авіаційних засобів ураження|керован\w* авіабомб'),
    ('loitering',  r'бандероль|баражуюч'),
    # «Ракетна небезпека для Харківської області» — тип ракети не названо.
    # Оголошується ЛИШЕ по областях, населеного пункту тут не буває.
    ('missile_alert', r'ракетн\w*\s+(?:небезпек|загроз)|швидкісн\w*\s+ціл|'
                      r'ракетна\s+атака|загроза\s+балістик'),
    ('decoy',      r'гербера|італмас|пародія|імітатор'),
    ('shahed',     r'shahed|шахед|герань'),
    ('drone',      r'бпла|дрон|безпілотн'),
]

OBLAST = {  # розмовна форма -> офіційна назва
    'вінниччин': 'Вінницька область', 'волин': 'Волинська область',
    'дніпропетровщин': 'Дніпропетровська область', 'донеччин': 'Донецька область',
    'житомирщин': 'Житомирська область', 'закарпатт': 'Закарпатська область',
    'запоріжж': 'Запорізька область', 'івано-франківщин': 'Івано-Франківська область',
    'прикарпатт': 'Івано-Франківська область', 'київщин': 'Київська область',
    'кіровоградщин': 'Кіровоградська область', 'луганщин': 'Луганська область',
    'львівщин': 'Львівська область', 'миколаївщин': 'Миколаївська область',
    'одещин': 'Одеська область', 'полтавщин': 'Полтавська область',
    'рівненщин': 'Рівненська область', 'сумщин': 'Сумська область',
    'тернопільщин': 'Тернопільська область', 'харківщин': 'Харківська область',
    'херсонщин': 'Херсонська область', 'хмельниччин': 'Хмельницька область',
    'черкащин': 'Черкаська область', 'чернівеччин': 'Чернівецька область',
    'буковин': 'Чернівецька область', 'чернігівщин': 'Чернігівська область',
}

# офіційні форми: «Харківська область», «Донецька, Дніпропетровська області»
OBLAST_OFFICIAL = {}
for _full in set(OBLAST.values()):
    _adj = _full.replace(' область', '')
    OBLAST_OFFICIAL[_adj.lower()[:-1]] = _full    # «харківськ» -> Харківська область
OBLAST_OFFICIAL['м. київ'] = 'м. Київ'
OBLAST_OFFICIAL['києв'] = 'м. Київ'

MONTHS = {'січня':1,'лютого':2,'березня':3,'квітня':4,'травня':5,'червня':6,
          'липня':7,'серпня':8,'вересня':9,'жовтня':10,'листопада':11,'грудня':12}

# ---------------------------------------------------------------- утиліти


def _low(t):
    return t.lower().replace('\u2019', "'").replace('\u02bc', "'").replace('`', "'")


def _num(token):
    """'132' -> 132; 'двома' -> 2; None якщо не число."""
    token = token.strip().lower().replace('\u2019', "'")
    if token.isdigit():
        return int(token)
    if token in WORDNUM:
        return WORDNUM[token]
    for k, v in WORDNUM.items():          # 'балістичною' без числівника = 1
        if token.startswith(k) and len(k) > 2:
            return v
    return None


def weapon_of(chunk):
    c = _low(chunk)
    for name, pat in WEAPONS:
        if re.search(pat, c):
            return name
    return None


def oblasts_in(text):
    c = _low(text)
    found = []
    for table in (OBLAST, OBLAST_OFFICIAL):
        for stem, full in table.items():
            if stem in c and full not in found:
                found.append(full)
    return found

# ---------------------------------------------------------------- зведення

LAUNCH_RE = re.compile(
    r'([\wʼ\'-]+)\s+((?:ударн|баліст|крилат|керован|зенітн|протикорабель|'
    r'баражуюч|реактивн)\w*(?:\s+\w+){0,3}?\s*'
    r'(?:ракет\w*|бпла|дрон\w*|боєприпас\w*|бомб\w*))', re.I | re.U)

# "збито/подавлено 114 ворожих БпЛА" / "154 ворожі БпЛА типу Shahed"
KILL_RE = re.compile(
    r'(\d{1,4}|[а-яіїєґʼ\']{3,14})\s+(?:ворож\w+\s+)?'
    r'((?:ударн|баліст|крилат|керован|зенітн|протикорабель|баражуюч|реактивн)?\w*\s*'
    r'(?:ракет\w*|бпла|дрон\w*|ціл\w*))', re.I | re.U)

PLAIN_RE = re.compile(r'\b(\d{1,4})\s+((?:ударн|баліст|крилат|керован)\w*'
                      r'(?:\s+\w+){0,3}?\s*(?:ракет\w*|бпла|дрон\w*))', re.I | re.U)

BULLET_RE = re.compile(r'^[-–—•]\s*(\d{1,4})\s+(.{5,90}?)(?:\s*\(|;|$)', re.M | re.U)


def parse_summary(ts, text):
    low = _low(text)
    out = {'kind': 'summary', 'ts': ts, 'launched': {}, 'destroyed': {},
           'impact_locations': None, 'debris_locations': None,
           'target_oblasts': [], 'origins': [], 'night_of': None}

    m = re.search(r'у ніч на (\d{1,2})\s+(' + '|'.join(MONTHS) + ')', low)
    if m:
        out['night_of'] = f"{int(m.group(1)):02d}.{MONTHS[m.group(2)]:02d}"

    # ---- запущено -------------------------------------------------------
    head = low.split('відбивали')[0].split('за попередніми')[0]

    bullets = BULLET_RE.findall(text)
    if bullets:                                   # деталізований формат
        for n, desc in bullets:
            w = weapon_of(desc)
            if w:
                out['launched'][w] = out['launched'].get(w, 0) + int(n)
    else:
        for tok, phrase in LAUNCH_RE.findall(head):
            n = _num(tok)
            w = weapon_of(phrase)
            if n and w:
                if w in ('drone', 'shahed', 'decoy'):
                    w = 'drone_mixed'   # ПС не розбивають пакет по типах
                out['launched'][w] = max(out['launched'].get(w, 0), n)
        out['drone_types'] = [k for k, pat in
                              [('shahed', r'shahed|шахед|герань'),
                               ('gerbera', r'гербера'), ('italmas', r'італмас'),
                               ('parodiya', r'пародія'), ('banderol', r'бандероль'),
                               ('jet', r'реактивн')] if re.search(pat, head)]
        # "балістичною ракетою Іскандер" без числівника = 1
        if 'ballistic' not in out['launched'] and re.search(
                r'атакував[^.]{0,60}баліст\w+ ракет(?:ою|ами)', head):
            out['launched']['ballistic'] = 1

    # ---- збито ----------------------------------------------------------
    tail = low.split('збито/подавлено')
    if len(tail) > 1:
        seg = tail[-1].split('зафіксовано')[0]
        for tok, phrase in KILL_RE.findall(seg):
            n, w = _num(tok), weapon_of(phrase)
            if n and w:
                out['destroyed'][w] = max(out['destroyed'].get(w, 0), n)
    # заголовок дає загальний підсумок: "ЗБИТО/ПОДАВЛЕНО 320 ЦІЛЕЙ: 55 РАКЕТ ТА 265 БПЛА"
    head_line = text.strip().split('\n')[0]
    hm = re.findall(r'(\d{1,4})\s*(ракет\w*|бпла|ціл\w*)', _low(head_line))
    for n, w in hm:
        key = {'р': 'missiles_total'}.get(w[0], 'targets_total' if w[0] == 'ц' else 'drones_total')
        out.setdefault('destroyed_total', {})[key] = int(n)

    # ---- локації --------------------------------------------------------
    m = re.search(r'влучанн\w*[^.]{0,160}?на (\d{1,3})\s*локац', low)
    if m:
        out['impact_locations'] = int(m.group(1))
    m = re.search(r'(?:падінн\w*|уламк\w*)[^.]{0,80}?на (\d{1,3})\b', low)
    if m:
        out['debris_locations'] = int(m.group(1))

    out['target_oblasts'] = oblasts_in(text)

    m = re.search(r'із напрямк\w+:?\s*([^.\n]{5,220})', low)
    if m:
        out['origins'] = [p.strip(' -–—,') for p in re.split(r'[,;]', m.group(1))
                          if 3 < len(p.strip(' -–—,')) < 40]
    return out

# ---------------------------------------------------------------- загрози

PLACE_RE = re.compile(
    r'(?:курс(?:ом)?\s+на|в\s+бік|в\s+напрямку|в\s+районі|над|н\.п\.)\s+'
    r'([А-ЯІЇЄҐ][\wʼ\'’\-]+(?:\s*,\s*[А-ЯІЇЄҐ][\wʼ\'’\-]+)*)', re.U)


def parse_threat(ts, text):
    out = {'kind': 'threat', 'ts': ts, 'weapon': weapon_of(text),
           'jet': bool(re.search(r'реактивн', _low(text))),
           'oblasts': oblasts_in(text), 'places': [], 'sea': False,
           'aviation': bool(re.search(r'тактичн\w* авіаці', _low(text)))}

    low = _low(text)
    out['sea'] = 'чорного моря' in low or 'азовського моря' in low

    seen = set()
    for grp in PLACE_RE.findall(text):
        for p in re.split(r'\s*,\s*', grp):
            p = p.strip(' .!?')
            if len(p) < 3:
                continue
            if _low(p).rstrip('иіа') in [o.rstrip('иіа') for o in OBLAST]:
                continue                       # це область, вже враховано
            if p not in seen:
                seen.add(p)
                out['places'].append(p)

    # "Чернігівщина: ... в бік Десни" — область на початку рядка
    if not out['oblasts']:
        m = re.match(r'^\W*([А-ЯІЇЄҐ][а-яіїєґ]+щина|[А-ЯІЇЄҐ][а-яіїєґ]+ччина)\s*:', text)
        if m:
            out['oblasts'] = oblasts_in(m.group(1))
    return out

# ---------------------------------------------------------------- вхід


def parse(ts, text):
    if not text or len(text) < 15:
        return None
    if re.search(r'збито/подавлено|засобів повітряного нападу|противник атакував',
                 _low(text)):
        return parse_summary(ts, text)
    if re.search(r'бпла|дрон|ракет|авіаці|балістик', _low(text)):
        return parse_threat(ts, text)
    return None


# ---------------------------------------------------------------- запуск

if __name__ == '__main__':
    import sqlite3, json, sys, collections

    db = sys.argv[1] if len(sys.argv) > 1 else 'messages.db'
    con = sqlite3.connect(db)
    con.executescript("""
    CREATE TABLE IF NOT EXISTS summaries (
        ts TEXT PRIMARY KEY, night_of TEXT, launched TEXT, destroyed TEXT,
        drone_types TEXT, impact_locations INT, debris_locations INT,
        target_oblasts TEXT, origins TEXT);
    CREATE TABLE IF NOT EXISTS threats (
        ts TEXT, weapon TEXT, jet INT, sea INT, aviation INT,
        oblasts TEXT, places TEXT);
    CREATE INDEX IF NOT EXISTS idx_thr_ts ON threats(ts);
    """)
    con.execute("DELETE FROM summaries"); con.execute("DELETE FROM threats")

    rows = con.execute(
        "SELECT ts, text FROM messages WHERE channel='kpszsu' ORDER BY ts").fetchall()
    print(f"Повідомлень kpszsu у базі: {len(rows)}")

    S = T = skip = 0
    wcount = collections.Counter()
    ocount = collections.Counter()
    pcount = collections.Counter()
    for ts, text in rows:
        r = parse(ts, text)
        if not r:
            skip += 1
            continue
        if r['kind'] == 'summary':
            S += 1
            con.execute("INSERT OR REPLACE INTO summaries VALUES (?,?,?,?,?,?,?,?,?)", (
                r['ts'], r['night_of'], json.dumps(r['launched'], ensure_ascii=False),
                json.dumps(r['destroyed'], ensure_ascii=False),
                json.dumps(r.get('drone_types'), ensure_ascii=False),
                r['impact_locations'], r['debris_locations'],
                json.dumps(r['target_oblasts'], ensure_ascii=False),
                json.dumps(r['origins'], ensure_ascii=False)))
            for w, n in r['launched'].items():
                wcount[w] += n
        else:
            T += 1
            con.execute("INSERT INTO threats VALUES (?,?,?,?,?,?,?)", (
                r['ts'], r['weapon'], int(r['jet']), int(r['sea']), int(r['aviation']),
                json.dumps(r['oblasts'], ensure_ascii=False),
                json.dumps(r['places'], ensure_ascii=False)))
            for o in r['oblasts']:
                ocount[o] += 1
            for p in r['places']:
                pcount[p] += 1
    con.commit()

    print(f"\nЗведень:  {S}\nЗагроз:   {T}\nПропущено:{skip}")
    print("\nЗапущено по типах (сума за весь період):")
    for w, n in wcount.most_common():
        print(f"   {w:12s} {n:>8,}".replace(',', ' '))
    print("\nТоп-15 областей за згадками в оперативних попередженнях:")
    for o, n in ocount.most_common(15):
        print(f"   {o:28s} {n:>6}")
    print("\nТоп-25 населених пунктів:")
    for p, n in pcount.most_common(25):
        print(f"   {p:22s} {n:>5}")
    con.close()
