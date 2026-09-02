# -*- coding: utf-8 -*-
"""
Прив'язка топонімів з телеграм-повідомлень до реальних населених пунктів.

Проблема: в тексті назви стоять у непрямих відмінках — «над Полтавою»,
«в районі Кропивницького», «курсом на Суми». Довідник же містить
називний відмінок. Морфологічного аналізатора тут немає, тому працюємо
через відсікання закінчень і пошук за основою.

    from geocode import Gazetteer
    gz = Gazetteer('gazetteer.csv')
    gz.find('Полтавою')            -> Полтава, Полтавська, 49.58 34.55
    gz.find('Терни', 'Сумська')    -> уточнення областю знімає омоніми
"""

import csv
import re
import unicodedata
from collections import defaultdict

# закінчення непрямих відмінків, від довших до коротших
ENDINGS = ['ського', 'цького', 'ього', 'ами', 'ями', 'ові', 'еві', 'ому',
           'ею', 'ою', 'ям', 'ах', 'ях', 'ів', 'ом', 'ем', 'ої', 'ій',
           'им', 'ий', 'ку', 'ці', 'ої',
           'а', 'у', 'и', 'і', 'е', 'о', 'я', 'ю', 'й']

# слова, які не є населеними пунктами
STOP = {'україни', 'україну', 'україна', 'рф', 'тот', 'ар', 'крим', 'увага',
        'група', 'групи', 'курс', 'курсом', 'напрямку', 'районі', 'бпла',
        'дрон', 'дрони', 'реактивний', 'реактивні', 'ударні', 'ударний',
        'загроза', 'обережно', 'укриття', 'північ', 'південь', 'схід', 'захід',
        'центр', 'моря', 'море', 'акваторії', 'чорного', 'азовського'}

# Розмовні назви областей. Явний перелік, бо евристика «закінчується на -щину»
# вбиває реальні населені пункти: Сахновщина, Козельщина, Кам'янщина.
OBLAST_WORDS = {
    'вінниччин', 'волин', 'дніпропетровщин', 'донеччин', 'житомирщин',
    'закарпатт', 'івано-франківщин', 'прикарпатт', 'київщин',
    'кіровоградщин', 'луганщин', 'львівщин', 'миколаївщин', 'одещин',
    'полтавщин', 'рівненщин', 'сумщин', 'тернопільщин', 'харківщин',
    'херсонщин', 'хмельниччин', 'черкащин', 'чернівеччин', 'буковин',
    'чернігівщин',
}
# «Запоріжжя» навмисно НЕ в переліку: це насамперед місто, а область
# в офіційних текстах зветься Запорізькою.


def norm(s):
    s = unicodedata.normalize('NFC', s or '')
    return s.replace('\u2019', "'").replace('\u02bc', "'").replace('`', "'").strip()


def low(s):
    return norm(s).lower()


def stem(name, keep=3):
    """Відсікає найдовше відоме закінчення, лишаючи щонайменше keep літер."""
    n = low(name)
    for e in ENDINGS:
        if n.endswith(e) and len(n) - len(e) >= keep:
            return n[:-len(e)]
    return n


def variants(token):
    """Основи-кандидати з урахуванням чергування і<->о<->е у закритому складі.

    Харків -> Харкова, Чернігів -> Чернігова, Львів -> Львова.
    Довідник має називний, у тексті трапляється родовий, тому генеруємо обидві
    форми основи й шукаємо за кожною.
    """
    base = low(token)
    out = {base, stem(base), stem(stem(base))}
    for v in list(out):
        # і -> о та і -> е у передостанній позиції основи
        for i in range(len(v) - 1, max(len(v) - 5, 0), -1):
            if v[i] == 'і':
                out.add(v[:i] + 'о' + v[i + 1:])
                out.add(v[:i] + 'е' + v[i + 1:])
            elif v[i] in 'ое':
                out.add(v[:i] + 'і' + v[i + 1:])
            elif v[i] == 'є':               # Зміїв -> Змієва
                out.add(v[:i] + 'ї' + v[i + 1:])
            elif v[i] == 'ї':
                out.add(v[:i] + 'є' + v[i + 1:])
    return {v for v in out if len(v) >= 3}


def foldkey(name, n=4):
    """Ключ-кошик, стійкий до відмінків і чергування і/о/е.

    «Харків» і «Харкова» -> харков; «Кропивницький» і «Кропивницького» -> кропив.
    """
    v = low(name).replace('ь', '').replace('’', '').replace("'", '')
    v = v.replace('і', 'о').replace('ї', 'о').replace('є', 'е')
    return v[:n]


def prefix_len(a, b):
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


# перейменування після 2020 — довідник їх ще не знає
RENAMED = {
    'звягель': 'Новоград-Волинський',
    'самар': 'Новомосковськ',
    'мукачево': 'Мукачево',
}

# міста зі спеціальним статусом, яких немає у звичайному списку поселень
SPECIAL = {
    'києва': dict(name='Київ', settlement_type='місто', oblast_name='м. Київ',
                  raion_name='', hromada_name='Київська міська',
                  lat=50.4501, lon=30.5234, rank=-1),
    'києві': dict(name='Київ', settlement_type='місто', oblast_name='м. Київ',
                  raion_name='', hromada_name='Київська міська',
                  lat=50.4501, lon=30.5234, rank=-1),
    'києвом': dict(name='Київ', settlement_type='місто', oblast_name='м. Київ',
                   raion_name='', hromada_name='Київська міська',
                   lat=50.4501, lon=30.5234, rank=-1),
    'київ': dict(name='Київ', settlement_type='місто', oblast_name='м. Київ',
                 raion_name='', hromada_name='Київська міська',
                 lat=50.4501, lon=30.5234, rank=-1),
    'севастополь': dict(name='Севастополь', settlement_type='місто',
                        oblast_name='м. Севастополь', raion_name='',
                        hromada_name='Севастопольська міська',
                        lat=44.6166, lon=33.5254, rank=-1),
}


class Gazetteer:
    def __init__(self, path='gazetteer.csv'):
        self.rows = []
        self.exact = defaultdict(list)
        self.by_stem = defaultdict(list)
        self.bucket = defaultdict(list)
        with open(path, encoding='utf-8') as f:
            for r in csv.DictReader(f):
                try:
                    r['lat'] = float(r['lat_center'])
                    r['lon'] = float(r['lon_center'])
                except (TypeError, ValueError):
                    continue
                r['rank'] = int(float(r.get('rank') or 4))
                r['name'] = norm(r['settlement_name'])
                # обласний центр: назва міста збігається з коренем назви області
                r['is_capital'] = int(
                    r['rank'] == 0 and
                    foldkey(r['name'], 6) == foldkey(r.get('oblast_name', ''), 6))
                self.rows.append(r)
                self.exact[low(r['name'])].append(r)
                self.by_stem[stem(r['name'])].append(r)
                self.bucket[foldkey(r['name'])].append(r)
        for d in (self.exact, self.by_stem, self.bucket):
            for k in d:
                d[k].sort(key=lambda x: x['rank'])

    # ------------------------------------------------------------------
    def is_oblast_word(self, token):
        t = low(token).rstrip('ауиіоюеяї')
        return t in OBLAST_WORDS

    def find(self, token, oblast_hint=None, min_rank=4):
        """Повертає найкращий збіг або None."""
        t = low(token)
        if not t or t in STOP or len(t) < 3 or self.is_oblast_word(t):
            return None

        for pref, real in RENAMED.items():
            if t.startswith(pref):
                t = low(real)
                break

        for k, v in SPECIAL.items():
            if t == k or foldkey(t, 4) == foldkey(k, 4):
                d = dict(v); d['is_capital'] = 1
                return d

        cands, seen = [], set()
        pool = self.bucket.get(foldkey(t), [])
        for v in variants(t):
            pool = pool + self.exact.get(v, []) + self.by_stem.get(v, [])
        for c in [pool]:
            pass
        for c in pool:
            if True:
                key = (c['name'], c['oblast_name'])
                if key not in seen:
                    seen.add(key)
                    cands.append(c)
        cands = [c for c in cands if c['rank'] <= min_rank]
        if not cands:
            return None

        hint = None
        if oblast_hint:
            hint = low(oblast_hint).replace(' область', '')[:6]

        def score(c):
            n = low(c['name'])
            return (
                0 if (hint and low(c['oblast_name']).startswith(hint)) else 1,
                0 if n == t else 1,         # точний збіг завжди виграє
                c['rank'],                  # потім — місто важливіше за село
                0 if c.get('is_capital') else 1,   # обласний центр за омонімів
                -prefix_len(n, t),
                abs(len(n) - len(t)),
            )
        return min(cands, key=score)

    def find_all(self, tokens, oblast_hint=None, min_rank=4):
        out, seen = [], set()
        for t in tokens:
            r = self.find(t, oblast_hint, min_rank)
            if r and r['name'] not in seen:
                seen.add(r['name'])
                out.append(r)
        return out
