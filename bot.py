#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Бот повітряної тривоги.

Два незалежні потоки з NEPTUN:
  alerts  — офіційні тривоги по районах. Покриття 100%, це основа.
  threats — уточнення з моніторингових каналів: що саме летить і звідки.

Тривогу й відбій шле офіційний потік. Уточнення лише доповнюють уже
надіслане повідомлення редагуванням, окремих сповіщень не створюють —
інакше під час масованої атаки телефон перетвориться на кулемет.

Відбій НІКОЛИ не шлеться за мовчанням каналів, тільки за офіційним
сигналом. Помилитись у бік «сховайся дарма» дешево, у бік
«вже безпечно» — ні.

    pip install aiogram websockets certifi requests
    export BOT_TOKEN=...
    python bot.py
"""

import asyncio, json, logging, os, sqlite3, ssl, sys, time, math
import datetime as dt
from typing import Optional

import certifi
import requests
import websockets
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (Message, CallbackQuery, InlineKeyboardMarkup,
                           InlineKeyboardButton)
from aiogram.exceptions import TelegramRetryAfter, TelegramForbiddenError

TOKEN = os.environ.get('BOT_TOKEN')
DB = os.environ.get('BOT_DB', 'bot.db')
GAZ = os.environ.get('GAZETTEER', 'gazetteer.csv')
BASE = 'https://neptun.in.ua'
WS = 'wss://neptun.in.ua/api/v1/stream'
UA = {'User-Agent': 'pid-tryvohoyu-bot/1.0 (+https://pid-tryvohoyu.netlify.app)'}
SSL_CTX = ssl.create_default_context(cafile=certifi.where())

RADIUS_KM = 60          # у якому радіусі від міста користувача вважаємо загрозу його
STALE_SEC = 120         # якщо стрім мовчить довше — вважаємо з'єднання мертвим

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('bot')

TYPE_UA = {'uav': 'БпЛА', 'shahed': 'Шахед', 'fpv': 'FPV-дрон',
           'recon': 'розвідувальний БпЛА', 'kab': 'КАБ',
           'ballistic': 'балістична ракета', 'cruise': 'крилата ракета',
           'missile': 'ракета', 'mig31k': 'МіГ-31К (носій «Кинджала»)',
           'aviation': 'тактична авіація'}
DIRS = ['півночі', 'північного сходу', 'сходу', 'південного сходу',
        'півдня', 'південного заходу', 'заходу', 'північного заходу']


# ---------------------------------------------------------------- довідник

def load_places():
    """Міста з координатами: назва -> (lat, lon, район, область)."""
    import csv
    out = {}
    if not os.path.exists(GAZ):
        log.error('Немає %s — бот не зможе прив\'язати міста', GAZ)
        return out
    with open(GAZ, encoding='utf-8') as f:
        for r in csv.DictReader(f):
            try:
                lat, lon = float(r['lat_center']), float(r['lon_center'])
            except (TypeError, ValueError):
                continue
            rank = int(float(r.get('rank') or 4))
            name = r['settlement_name'].strip()
            oblast = (r.get('oblast_name') or '').strip()
            key = name.lower()
            # Обласний центр серед однойменних завжди виграє: Миколаїв є і на
            # Львівщині, але людина, що пише «Миколаїв», має на увазі обласний.
            capital = name.lower()[:5] == oblast.lower()[:5]
            score = rank - (10 if capital else 0)
            if key not in out or score < out[key][4]:
                out[key] = (name, lat, lon,
                            (r.get('raion_name') or '').strip(), score, oblast)
    return out


# Міста спецстатусу: у довіднику населених пунктів їх немає, натомість є
# однойменні села. Без цього «київ» знаходить село Київ на Миколаївщині.
SPECIAL = {
    'київ': ('Київ', 50.4501, 30.5234, 'Київський', -1, 'м. Київ'),
    'севастополь': ('Севастополь', 44.6166, 33.5254, 'Севастопольський', -1,
                    'м. Севастополь'),
}

# Найчастіші російські та розмовні варіанти. Люди пишуть як звикли,
# і відповідь «не знайшов» — найгірше, що бот може сказати про своє місто.
ALIASES = {
    'киев': 'київ', 'кыев': 'київ', 'кийв': 'київ',
    'одесса': 'одеса', 'харьков': 'харків', 'львов': 'львів',
    'днепр': 'дніпро', 'днипро': 'дніпро', 'днепропетровск': 'дніпро',
    'николаев': 'миколаїв', 'запорожье': 'запоріжжя', 'винница': 'вінниця',
    'чернигов': 'чернігів', 'черкассы': 'черкаси', 'житомир': 'житомир',
    'ровно': 'рівне', 'луцк': 'луцьк', 'тернополь': 'тернопіль',
    'ужгород': 'ужгород', 'ивано-франковск': 'івано-франківськ',
    'хмельницкий': 'хмельницький', 'кропивницкий': 'кропивницький',
    'кировоград': 'кропивницький', 'полтава': 'полтава', 'сумы': 'суми',
    'херсон': 'херсон', 'кривой рог': 'кривий ріг', 'кривой рiг': 'кривий ріг',
    'мариуполь': 'маріуполь', 'краматорск': 'краматорськ',
    'бровары': 'бровари', 'борисполь': 'бориспіль', 'ирпень': 'ірпінь',
    'белая церковь': 'біла церква', 'умань': 'умань', 'ковель': 'ковель',
    'мукачево': 'мукачево', 'бердянск': 'бердянськ', 'мелитополь': 'мелітополь',
    'никополь': 'нікополь', 'павлоград': 'павлоград', 'кременчуг': 'кременчук',
    'изюм': 'ізюм', 'чугуев': 'чугуїв', 'лозовая': 'лозова',
    'славянск': 'словянськ', 'константиновка': 'костянтинівка',
    'золотоноша': 'золотоноша', 'шостка': 'шостка', 'конотоп': 'конотоп',
    'нежин': 'ніжин', 'прилуки': 'прилуки', 'смела': 'сміла',
}

PLACES = load_places()
PLACES.update(SPECIAL)
log.info('Довідник: %d населених пунктів', len(PLACES))


def dist_km(a_lat, a_lon, b_lat, b_lon):
    dy = (a_lat - b_lat) * 111.0
    dx = (a_lon - b_lon) * 111.0 * math.cos(math.radians((a_lat + b_lat) / 2))
    return math.hypot(dx, dy)


# ---------------------------------------------------------------- база

def db():
    c = sqlite3.connect(DB)
    c.executescript("""
    CREATE TABLE IF NOT EXISTS subs (
        chat_id INTEGER, place TEXT, lat REAL, lon REAL, raion TEXT,
        oblast TEXT, PRIMARY KEY (chat_id, place));
    CREATE TABLE IF NOT EXISTS sent (
        chat_id INTEGER, key TEXT, message_id INTEGER, body TEXT,
        ts REAL, PRIMARY KEY (chat_id, key));
    CREATE TABLE IF NOT EXISTS seen_alerts (raion TEXT PRIMARY KEY, since TEXT);
    """)
    c.commit()
    return c


CON = db()


def subs_for_raion(key):
    """key — нормалізована назва району або 'obl:область'.
    Порівнюємо в пам'яті, бо в базі назви лежать у сирому вигляді."""
    rows = CON.execute("SELECT chat_id, place, raion, oblast FROM subs").fetchall()
    if key.startswith('obl:'):
        o = key[4:]
        return [(c, p) for c, p, _, ob in rows if norm_oblast(ob) == o]
    return [(c, p) for c, p, r, _ in rows if norm_raion(r) == key]


def all_subs():
    return CON.execute(
        "SELECT chat_id, place, lat, lon FROM subs").fetchall()


# ---------------------------------------------------------------- тексти

def human_type(t, count=None):
    name = TYPE_UA.get(t, t or 'ціль')
    if count and count > 1:
        return f"{count} × {name}"
    return name


def direction(heading):
    if heading is None:
        return ''
    # heading — куди летить; звідки летить = протилежний напрямок
    idx = int(((heading + 180) % 360) / 45) % 8
    return f" з {DIRS[idx]}"


def alert_text(place, since=None):
    t = ''
    if since:
        try:
            d = dt.datetime.fromisoformat(since.replace('Z', '+00:00'))
            t = d.astimezone().strftime(' о %H:%M')
        except Exception:
            pass
    return f"🔴 <b>{place}</b> · Повітряна тривога\nОголошено{t}"


def clear_text(place, minutes=None):
    d = f"\nТривала {minutes // 60} год {minutes % 60} хв" if minutes and minutes > 60 \
        else (f"\nТривала {minutes} хв" if minutes else '')
    return f"🟢 <b>{place}</b> · Відбій тривоги{d}"


def threat_line(t):
    typ = human_type(t.get('type'), t.get('count'))
    loc = t.get('locality') or ''
    d = direction(t.get('heading'))
    src = t.get('sourceCount') or 0
    conf = t.get('confidenceLevel')
    mark = '✅' if conf == 'high' else ('◽️' if src <= 1 else '▫️')
    tail = 'підтверджено' if src >= 2 else 'одне джерело'
    return f"{mark} {typ}{d} — {loc}\n<i>{tail}, джерел: {src}</i>"


# ---------------------------------------------------------------- надсилання

class Sender:
    """Черга з обмеженням швидкості: Telegram пускає ~30 повідомлень/с."""

    def __init__(self, bot: Bot):
        self.bot = bot
        self.q = asyncio.Queue()

    async def run(self):
        while True:
            fn = await self.q.get()
            try:
                await fn()
            except TelegramRetryAfter as e:
                log.warning('Telegram просить зачекати %s с', e.retry_after)
                await asyncio.sleep(e.retry_after + 1)
                await self.q.put(fn)
            except TelegramForbiddenError:
                pass                     # користувач заблокував бота
            except Exception as e:
                log.error('Помилка надсилання: %s: %s', type(e).__name__, e)
            await asyncio.sleep(0.05)

    def push(self, fn):
        self.q.put_nowait(fn)


SENDER: Optional[Sender] = None


async def send_or_edit(chat_id, key, body):
    """Одна подія — одне повідомлення. Повторні виклики редагують його."""
    row = CON.execute("SELECT message_id, body FROM sent WHERE chat_id=? AND key=?",
                      (chat_id, key)).fetchone()
    if row and row[1] == body:
        return                            # нічого не змінилось
    bot = SENDER.bot
    if row:
        async def do_edit(mid=row[0]):
            try:
                await bot.edit_message_text(body, chat_id=chat_id, message_id=mid,
                                            parse_mode='HTML')
                CON.execute("UPDATE sent SET body=?, ts=? WHERE chat_id=? AND key=?",
                            (body, time.time(), chat_id, key))
                CON.commit()
            except Exception:
                pass                      # повідомлення застаре для редагування
        SENDER.push(do_edit)
    else:
        async def do_send():
            m = await bot.send_message(chat_id, body, parse_mode='HTML',
                                       disable_web_page_preview=True)
            CON.execute("INSERT OR REPLACE INTO sent VALUES (?,?,?,?,?)",
                        (chat_id, key, m.message_id, body, time.time()))
            CON.commit()
        SENDER.push(do_send)


# ---------------------------------------------------------------- стан

def load_alerts():
    """Стан тривог переживає перезапуск. Без цього після рестарту бот
    вважає всі поточні тривоги новими й розсилає їх скопом — а вони
    тривають уже годину."""
    return {r[0]: r[1] for r in
            CON.execute("SELECT raion, since FROM seen_alerts").fetchall()}


def save_alerts(now):
    CON.execute("DELETE FROM seen_alerts")
    CON.executemany("INSERT INTO seen_alerts VALUES (?,?)", list(now.items()))
    CON.commit()


STATE = {'threats': {}, 'alerts': load_alerts(), 'last_msg': time.time()}


def norm_raion(x):
    """Назви районів приходять у різних формах: NEPTUN пише «Харківський район»,
    довідник КШЕ — «Харківський». Плюс апострофи бувають різними символами.
    Тому порівнюємо не рядки, а нормалізовані ключі."""
    x = (x or '').lower().strip()
    x = x.replace('\u2019', "'").replace('\u02bc', "'").replace('`', "'")
    for suf in (' район', ' р-н', ' райони'):
        if x.endswith(suf):
            x = x[:-len(suf)]
    return x.strip()


def norm_oblast(x):
    x = (x or '').lower().strip()
    x = x.replace('\u2019', "'").replace('\u02bc', "'")
    return x.replace(' область', '').replace(' обл.', '').strip()


def active_key(raion, oblast):
    """Чи є тривога для цього місця: спершу район, потім уся область."""
    r = norm_raion(raion)
    if r in STATE['alerts']:
        return r
    o = 'obl:' + norm_oblast(oblast)
    if o in STATE['alerts']:
        return o
    return None


async def handle_alerts(data):
    """Офіційні тривоги: тільки вони вмикають і вимикають сигнал.

    NEPTUN віддає райони та області окремими списками. Коли тривогу
    оголошують на всю область, району в списку raions немає — і бот мовчав.
    Тому обласні тривоги накладаємо на всі райони цієї області.
    """
    now = {norm_raion(r.get('name')): r.get('since')
           for r in data.get('raions', [])}
    for o in data.get('oblasts', []):
        now['obl:' + norm_oblast(o.get('name'))] = o.get('since')
    prev = STATE['alerts']

    for raion, since in now.items():
        if raion in prev:
            continue
        # Тривога, оголошена давно, — не новина. Людина вже почула сирену,
        # а пуш о третій ночі про подію годинної давнини лише дратує.
        try:
            age = (dt.datetime.now(dt.timezone.utc) -
                   dt.datetime.fromisoformat(
                       (since or '').replace('Z', '+00:00'))).total_seconds()
        except Exception:
            age = 0
        if age > 20 * 60:
            continue
        for chat_id, place in subs_for_raion(raion):
            await send_or_edit(chat_id, f'alert:{raion}',
                               alert_text(place, since))

    for raion, since in prev.items():
        if raion in now:
            continue
        mins = None
        try:
            d = dt.datetime.fromisoformat(since.replace('Z', '+00:00'))
            mins = int((dt.datetime.now(dt.timezone.utc) - d).total_seconds() // 60)
        except Exception:
            pass
        for chat_id, place in subs_for_raion(raion):
            await send_or_edit(chat_id, f'clear:{raion}', clear_text(place, mins))
            CON.execute("DELETE FROM sent WHERE chat_id=? AND key=?",
                        (chat_id, f'alert:{raion}'))
        CON.commit()

    STATE['alerts'] = now
    save_alerts(now)


async def handle_threat(t):
    """Уточнення. Дописуються до повідомлення про тривогу, окремо не шлються."""
    if t.get('advisory') or t.get('areaOnly'):
        return                            # спостереження або без точки — мовчимо
    lat, lon = t.get('lat'), t.get('lon')
    if lat is None or lon is None:
        return
    STATE['threats'][t.get('id')] = t

    for chat_id, place, plat, plon in all_subs():
        if dist_km(plat, plon, lat, lon) > RADIUS_KM:
            continue
        row = CON.execute(
            "SELECT raion, oblast FROM subs WHERE chat_id=? AND place=?",
            (chat_id, place)).fetchone()
        if not row:
            continue
        key = active_key(row[0], row[1])
        if not key:
            continue                      # тривоги немає — не турбуємо
        near = [x for x in STATE['threats'].values()
                if x.get('lat') is not None
                and dist_km(plat, plon, x['lat'], x['lon']) <= RADIUS_KM]
        near.sort(key=lambda x: -(x.get('sourceCount') or 0))
        body = alert_text(place, STATE['alerts'].get(key))
        body += '\n\n' + '\n'.join(threat_line(x) for x in near[:4])
        await send_or_edit(chat_id, f'alert:{key}', body)


# ---------------------------------------------------------------- стрім

async def resync():
    """Після обриву забираємо повний стан, щоб не проґавити те, що сталось."""
    try:
        r = requests.get(BASE + '/api/v1/threats', headers=UA, timeout=20)
        STATE['threats'] = {t['id']: t for t in r.json().get('threats', [])}
        a = requests.get(BASE + '/api/v1/alerts', headers=UA, timeout=20)
        await handle_alerts(a.json())
        log.info('Ресинк: %d загроз, %d районів',
                 len(STATE['threats']), len(STATE['alerts']))
    except Exception as e:
        log.error('Ресинк не вдався: %s', e)


async def stream():
    """Слухаємо WebSocket. Обриви — норма, тому реконект із наростанням паузи."""
    delay = 1
    while True:
        try:
            async with websockets.connect(WS, ssl=SSL_CTX, additional_headers=UA,
                                          ping_interval=20, ping_timeout=20) as ws:
                log.info('Стрім підключено')
                await resync()
                delay = 1
                while True:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=STALE_SEC)
                    except asyncio.TimeoutError:
                        log.warning('Стрім мовчить %d с — перепідключаюсь', STALE_SEC)
                        break
                    STATE['last_msg'] = time.time()
                    env = json.loads(raw)
                    k = env.get('type')
                    if k == 'alerts':
                        await handle_alerts(env.get('data', {}))
                    elif k == 'upsert':
                        await handle_threat(env.get('data', {}))
                    elif k == 'remove':
                        STATE['threats'].pop(
                            env.get('data', {}).get('id'), None)
                    elif k == 'snapshot':
                        d = env.get('data', {})
                        STATE['threats'] = {t['id']: t
                                            for t in d.get('threats', [])}
        except Exception as e:
            log.warning('Стрім обірвано (%s), пауза %d с', type(e).__name__, delay)
        await asyncio.sleep(delay)
        delay = min(delay * 2, 30)


# ---------------------------------------------------------------- інтерфейс

DISCLAIMER = (
    "⚠️ <b>Це не заміна офіційній системі оповіщення</b>\n\n"
    "Бот бере офіційні тривоги та уточнення з відкритих джерел. "
    "Можливі затримки, пропуски й помилкові спрацювання. "
    "Не покладайтесь на нього як на єдине джерело — слухайте сирену "
    "та офіційний застосунок.\n\n"
    "Уточнення про тип цілі доступні не для всіх областей."
)

dp = Dispatcher()


@dp.message(Command('start'))
async def cmd_start(m: Message):
    await m.answer(
        "🛡 <b>Під тривогою</b>\n\n"
        "Надішліть назву свого міста або села — і я повідомлятиму про "
        "повітряну тривогу та про те, що саме летить у ваш бік.\n\n"
        "Наприклад: <code>Умань</code>\n\n"
        "/list — ваші міста\n"
        "/status — що бот бачить зараз\n"
        "/test — зразок сповіщення\n"
        "/stop — відписатись від усього\n\n"
        + DISCLAIMER +
        "\n\nДані: <a href='https://neptun.in.ua'>NEPTUN</a> · "
        "Історія: <a href='https://pid-tryvohoyu.netlify.app'>pid-tryvohoyu</a>",
        parse_mode='HTML', disable_web_page_preview=True)


@dp.message(Command('list'))
async def cmd_list(m: Message):
    rows = CON.execute("SELECT place, raion FROM subs WHERE chat_id=?",
                       (m.chat.id,)).fetchall()
    if not rows:
        return await m.answer("Ви ще нічого не обрали. Надішліть назву міста.")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"❌ {p}", callback_data=f"del:{p}")]
        for p, _ in rows])
    await m.answer("Ваші міста:\n" + '\n'.join(f"• {p} ({r})" for p, r in rows),
                   reply_markup=kb)


@dp.message(Command('status'))
async def cmd_status(m: Message):
    """Показує, що бот бачить прямо зараз. Без цього неможливо зрозуміти,
    чи він мовчить тому, що спокійно, чи тому, що зламався."""
    rows = CON.execute(
        "SELECT place, lat, lon, raion FROM subs WHERE chat_id=?",
        (m.chat.id,)).fetchall()
    age = int(time.time() - STATE['last_msg'])
    live = '🟢 працює' if age < STALE_SEC else f'🔴 мовчить {age} с'
    out = [f"<b>Стрім:</b> {live}",
           f"<b>Тривог зараз:</b> {len(STATE['alerts'])} районів",
           f"<b>Активних цілей:</b> {len(STATE['threats'])}", ""]
    if not rows:
        out.append("Ви ще нічого не обрали.")
    for place, lat, lon, raion in rows:
        obl = CON.execute("SELECT oblast FROM subs WHERE chat_id=? AND place=?",
                          (m.chat.id, place)).fetchone()
        on = active_key(raion, obl[0] if obl else '') is not None
        near = [t for t in STATE['threats'].values()
                if t.get('lat') is not None
                and dist_km(lat, lon, t['lat'], t['lon']) <= RADIUS_KM]
        line = f"{'🔴' if on else '🟢'} <b>{place}</b> — " \
               f"{'тривога' if on else 'спокійно'}"
        if near:
            line += f", цілей поруч: {len(near)}"
            for t in sorted(near, key=lambda x: -(x.get('sourceCount') or 0))[:3]:
                line += "\n   " + threat_line(t).replace("\n", " ")
        out.append(line)
    out.append("\nБот пише, коли тривога <i>починається</i>. "
               "Якщо вона вже триває — побачите її тут.")
    await m.answer('\n'.join(out), parse_mode='HTML')


@dp.message(Command('test'))
async def cmd_test(m: Message):
    """Надсилає зразок повідомлення, щоб перевірити доставку сповіщень."""
    rows = CON.execute("SELECT place, raion FROM subs WHERE chat_id=? LIMIT 1",
                       (m.chat.id,)).fetchall()
    place = rows[0][0] if rows else 'Умань'
    body = ("⚠️ <b>ТЕСТ — справжньої загрози немає</b>\n"
            "Так виглядатиме справжнє сповіщення:\n\n"
            f"🔴 <b>{place}</b> · Повітряна тривога\n"
            "Оголошено о 01:43\n\n"
            f"✅ 2 × БпЛА з півночі — {place}\n"
            "<i>підтверджено, джерел: 3</i>")
    await m.answer(body, parse_mode='HTML')


@dp.message(Command('stop'))
async def cmd_stop(m: Message):
    CON.execute("DELETE FROM subs WHERE chat_id=?", (m.chat.id,))
    CON.commit()
    await m.answer("Відписано від усіх міст.")


@dp.callback_query(F.data.startswith('del:'))
async def cb_del(c: CallbackQuery):
    place = c.data[4:]
    CON.execute("DELETE FROM subs WHERE chat_id=? AND place=?",
                (c.message.chat.id, place))
    CON.commit()
    await c.answer(f"{place} видалено")
    await c.message.edit_text(f"❌ {place} видалено. /list — решта міст")


@dp.message(F.text)
async def add_place(m: Message):
    q = (m.text or '').strip().lower().replace('ё', 'е')
    if len(q) < 3:
        return await m.answer("Надто коротко. Введіть назву міста повністю.")
    q = ALIASES.get(q, q)
    hit = PLACES.get(q)
    if not hit:
        cand = [v for k, v in PLACES.items() if k.startswith(q)][:5]
        if not cand:
            return await m.answer(
                "Не знайшов такого населеного пункту. "
                "Спробуйте написати повну назву українською.")
        if len(cand) > 1:
            names = '\n'.join(f"• {c[0]} — {c[3]} р-н, {c[5]}" for c in cand)
            return await m.answer(f"Знайшов кілька:\n{names}\n\n"
                                  "Напишіть точніше або додайте область.")
        hit = cand[0]
    name, lat, lon, raion, _, oblast = hit
    CON.execute("INSERT OR REPLACE INTO subs VALUES (?,?,?,?,?,?)",
                (m.chat.id, name, lat, lon, raion, oblast))
    CON.commit()
    active = active_key(raion, oblast) is not None
    now = "\n\n🔴 Зараз у вашому районі тривога." if active else ""
    await m.answer(f"✅ Стежу за <b>{name}</b> ({raion}, {oblast}){now}",
                   parse_mode='HTML')


async def main():
    global SENDER
    if not TOKEN:
        sys.exit('Задай BOT_TOKEN')
    if not PLACES:
        sys.exit('Немає gazetteer.csv поруч із ботом')
    bot = Bot(TOKEN)
    SENDER = Sender(bot)
    asyncio.create_task(SENDER.run())
    asyncio.create_task(stream())
    log.info('Бот запущено')
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())
