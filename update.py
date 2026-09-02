#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Докачує лише нові повідомлення, що з'явилися після останнього запуску.

На відміну від scraper.py, який іде від свіжих до найстаріших і одного разу
доходить до початку каналу, цей скрипт щоразу забирає тільки хвіст —
усе, що новіше за максимальний msg_id у базі.

    export TG_API_ID=... TG_API_HASH=...
    python update.py

Саме він запускається за розкладом у GitHub Actions.
"""

import asyncio, os, sqlite3, sys, time
from datetime import datetime, timezone

from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError, ChannelPrivateError, UsernameNotOccupiedError,
    UsernameInvalidError, RpcCallFailError,
)

API_ID = os.environ.get("TG_API_ID")
API_HASH = os.environ.get("TG_API_HASH")
SESSION = os.environ.get("TG_SESSION", "scraper")
DB = os.environ.get("TRYVOHA_DB", "messages.db")

CHANNELS = [
    "kpszsu", "AerisRimor", "napramok", "war_monitor",
    "monitorwar", "air_alert_ua",
]

BATCH = 200
PAUSE = 1.2
MAX_FLOOD = 900


def db_open():
    con = sqlite3.connect(DB)
    con.executescript("""
    CREATE TABLE IF NOT EXISTS messages (
        channel TEXT NOT NULL, msg_id INTEGER NOT NULL, ts TEXT NOT NULL,
        text TEXT, views INTEGER, reply_to INTEGER,
        PRIMARY KEY (channel, msg_id));
    CREATE INDEX IF NOT EXISTS idx_msg_ts ON messages(ts);
    CREATE INDEX IF NOT EXISTS idx_msg_channel ON messages(channel);
    CREATE TABLE IF NOT EXISTS progress (
        channel TEXT PRIMARY KEY, oldest_id INTEGER, newest_id INTEGER,
        done INTEGER DEFAULT 0, updated_at TEXT);
    """)
    con.commit()
    return con


async def guard(factory, label):
    while True:
        try:
            return await factory()
        except FloodWaitError as e:
            if e.seconds > MAX_FLOOD:
                print(f"  [{label}] FloodWait {e.seconds}s — пропускаю")
                return None
            print(f"  [{label}] FloodWait {e.seconds}s")
            await asyncio.sleep(e.seconds + 2)
        except RpcCallFailError:
            await asyncio.sleep(15)


async def pull_new(client, con, ch):
    try:
        entity = await client.get_entity(ch)
    except (ChannelPrivateError, UsernameNotOccupiedError, UsernameInvalidError) as e:
        print(f"[{ch}] недоступний: {type(e).__name__}")
        return 0

    row = con.execute(
        "SELECT MAX(msg_id) FROM messages WHERE channel=?", (ch,)).fetchone()
    since = row[0] or 0
    if not since:
        print(f"[{ch}] порожньо в базі — спершу запусти scraper.py")
        return 0

    added, offset = 0, 0
    while True:
        batch = await guard(
            lambda: client.get_messages(entity, limit=BATCH,
                                        min_id=since, offset_id=offset), ch)
        if not batch:
            break
        texts = [m for m in batch if getattr(m, "message", None)]
        if texts:
            con.executemany(
                "INSERT OR IGNORE INTO messages (channel,msg_id,ts,text,views,reply_to) "
                "VALUES (?,?,?,?,?,?)",
                [(ch, m.id, m.date.astimezone(timezone.utc).isoformat(),
                  m.message, getattr(m, "views", None), m.reply_to_msg_id)
                 for m in texts])
            con.commit()
            added += len(texts)
        ids = [m.id for m in batch]
        offset = min(ids)
        if offset <= since + 1 or len(batch) < BATCH:
            break
        await asyncio.sleep(PAUSE)

    if added:
        con.execute("""UPDATE progress SET newest_id=?, updated_at=?
                       WHERE channel=?""",
                    (con.execute("SELECT MAX(msg_id) FROM messages WHERE channel=?",
                                 (ch,)).fetchone()[0],
                     datetime.now(timezone.utc).isoformat(), ch))
        con.commit()
    print(f"[{ch}] нових повідомлень: {added}")
    return added


async def main():
    if not API_ID or not API_HASH:
        sys.exit("Задай TG_API_ID і TG_API_HASH")
    con = db_open()
    total = 0
    async with TelegramClient(SESSION, int(API_ID), API_HASH) as client:
        me = await client.get_me()
        print(f"Увійшов як {me.first_name}\n")
        for ch in CHANNELS:
            try:
                total += await pull_new(client, con, ch)
            except Exception as e:
                print(f"[{ch}] помилка: {type(e).__name__}: {e}")
    n = con.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    print(f"\nДодано за цей запуск: {total} | усього в базі: {n}")
    con.close()
    return total


if __name__ == "__main__":
    asyncio.run(main())
