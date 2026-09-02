#!/usr/bin/env python3
"""
Викачування історії публічних Telegram-каналів у SQLite.

Запуск:
    pip install telethon
    export TG_API_ID=...
    export TG_API_HASH=...
    python scraper.py

Скрипт можна зупиняти й перезапускати — він продовжить з того місця,
де зупинився (зберігає min_id по кожному каналу).
"""

import asyncio, os, sqlite3, sys, time, signal
from datetime import datetime, timezone

from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError, ChannelPrivateError, UsernameNotOccupiedError,
    UsernameInvalidError, RpcCallFailError,
)

# ---------------------------------------------------------------- налаштування

API_ID = os.environ.get("TG_API_ID")
API_HASH = os.environ.get("TG_API_HASH")
SESSION = "scraper"          # файл scraper.session поруч зі скриптом
DB = "messages.db"

# Перевір кожен канал руками перед запуском: частина могла змінити ім'я.
CHANNELS = [
    "kpszsu",            # 10 хв — типи озброєнь, найцінніше
    "AerisRimor",
    "napramok",
    "war_monitor",
    "monitorwar",
    "air_alert_ua",      # ~3 години — залишаємо наостанок
]

BATCH = 500              # повідомлень за один запит до API
PAUSE = 1.2              # пауза між батчами, секунд — не зменшуй
MAX_FLOOD = 3600         # якщо Telegram просить чекати довше — пропускаємо канал

# ---------------------------------------------------------------- база

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    channel   TEXT NOT NULL,
    msg_id    INTEGER NOT NULL,
    ts        TEXT NOT NULL,
    text      TEXT,
    views     INTEGER,
    reply_to  INTEGER,
    PRIMARY KEY (channel, msg_id)
);
CREATE INDEX IF NOT EXISTS idx_msg_ts ON messages(ts);
CREATE INDEX IF NOT EXISTS idx_msg_channel ON messages(channel);

CREATE TABLE IF NOT EXISTS progress (
    channel     TEXT PRIMARY KEY,
    oldest_id   INTEGER,   -- найстаріше завантажене повідомлення
    newest_id   INTEGER,   -- найновіше завантажене
    done        INTEGER DEFAULT 0,
    updated_at  TEXT
);
"""


def db_open():
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)
    con.commit()
    return con


def get_progress(con, ch):
    row = con.execute(
        "SELECT oldest_id, newest_id, done FROM progress WHERE channel=?", (ch,)
    ).fetchone()
    return row if row else (None, None, 0)


def save_progress(con, ch, oldest, newest, done=0):
    con.execute(
        """INSERT INTO progress (channel, oldest_id, newest_id, done, updated_at)
           VALUES (?,?,?,?,?)
           ON CONFLICT(channel) DO UPDATE SET
             oldest_id=COALESCE(MIN(excluded.oldest_id, progress.oldest_id), excluded.oldest_id),
             newest_id=COALESCE(MAX(excluded.newest_id, progress.newest_id), excluded.newest_id),
             done=excluded.done,
             updated_at=excluded.updated_at""",
        (ch, oldest, newest, done, datetime.now(timezone.utc).isoformat()),
    )
    con.commit()


def store(con, ch, msgs):
    rows = [
        (ch, m.id, m.date.astimezone(timezone.utc).isoformat(),
         m.message or "", getattr(m, "views", None), m.reply_to_msg_id)
        for m in msgs
    ]
    con.executemany(
        "INSERT OR IGNORE INTO messages (channel,msg_id,ts,text,views,reply_to) "
        "VALUES (?,?,?,?,?,?)", rows,
    )
    con.commit()
    return len(rows)

# ---------------------------------------------------------------- викачування

stopping = False


def _stop(*_):
    global stopping
    stopping = True
    print("\n  зупиняюся після поточного батча…", flush=True)


async def flood_guard(coro_factory, label):
    """Виконує запит, переживаючи FloodWait. Повертає None, якщо здалися."""
    while True:
        try:
            return await coro_factory()
        except FloodWaitError as e:
            if e.seconds > MAX_FLOOD:
                print(f"  [{label}] FloodWait {e.seconds}s — забагато, пропускаю")
                return None
            print(f"  [{label}] FloodWait {e.seconds}s — чекаю")
            await asyncio.sleep(e.seconds + 2)
        except RpcCallFailError:
            print(f"  [{label}] збій на боці Telegram, повтор через 15s")
            await asyncio.sleep(15)


async def pull(client, con, ch):
    """Тягне історію каналу від найновіших до найстаріших."""
    try:
        entity = await client.get_entity(ch)
    except (ChannelPrivateError, UsernameNotOccupiedError, UsernameInvalidError) as e:
        print(f"[{ch}] недоступний: {type(e).__name__}")
        return

    oldest, newest, done = get_progress(con, ch)
    if done:
        print(f"[{ch}] вже викачаний повністю, пропускаю")
        return

    offset = oldest if oldest else 0          # 0 = почати з найновішого
    total = con.execute(
        "SELECT COUNT(*) FROM messages WHERE channel=?", (ch,)
    ).fetchone()[0]
    print(f"[{ch}] старт, у базі вже {total} повідомлень"
          + (f", продовжую з id<{offset}" if offset else ""))

    t0 = time.time()
    while not stopping:
        batch = await flood_guard(
            lambda: client.get_messages(entity, limit=BATCH, offset_id=offset),
            ch,
        )
        if batch is None:
            return
        if not batch:
            save_progress(con, ch, oldest, newest, done=1)
            print(f"[{ch}] готово — дійшов до початку каналу")
            return

        texts = [m for m in batch if getattr(m, "message", None)]
        if texts:
            store(con, ch, texts)
        total += len(texts)

        ids = [m.id for m in batch]
        offset = min(ids)
        oldest = offset if oldest is None else min(oldest, offset)
        newest = max(ids) if newest is None else max(newest, max(ids))
        save_progress(con, ch, oldest, newest)

        first_date = batch[-1].date.date()
        rate = total / max(time.time() - t0, 1)
        print(f"  [{ch}] {total:>7} шт | дійшов до {first_date} | {rate:5.0f} msg/s",
              flush=True)

        await asyncio.sleep(PAUSE)


async def main():
    if not API_ID or not API_HASH:
        sys.exit("Задай змінні оточення TG_API_ID і TG_API_HASH")

    signal.signal(signal.SIGINT, _stop)
    con = db_open()

    async with TelegramClient(SESSION, int(API_ID), API_HASH) as client:
        me = await client.get_me()
        print(f"Увійшов як {me.first_name} (id {me.id})\n")
        for ch in CHANNELS:
            if stopping:
                break
            try:
                await pull(client, con, ch)
            except Exception as e:
                print(f"[{ch}] неочікувана помилка: {type(e).__name__}: {e}")
            print()

    n = con.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    print(f"\nУсього в базі: {n} повідомлень")
    for ch, c, lo, hi in con.execute(
        """SELECT m.channel, COUNT(*), MIN(m.ts), MAX(m.ts)
           FROM messages m GROUP BY m.channel"""
    ):
        print(f"  {ch:16s} {c:>8} | {lo[:10]} — {hi[:10]}")
    con.close()


if __name__ == "__main__":
    asyncio.run(main())
