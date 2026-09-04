# -*- coding: utf-8 -*-
"""
Перевірка API NEPTUN перед тим, як будувати на ньому бота.

Питання, на які має відповісти цей скрипт:
  1. Чи API взагалі живий і що віддає прямо зараз
  2. Наскільки заповнені поля, від яких залежить текст повідомлення
     (locality, count, heading, type) — бо без них бот напише «щось летить кудись»
  3. Скільки загроз мають точку, а скільки лише область (areaOnly)
  4. Скільки advisory — тих, що не є сигналом ховатися
  5. Чи збігаються офіційні тривоги з тим, що каже датасет
  6. Як швидко оновлюється стрім і чи стабільний

    pip install requests websockets
    python neptun_probe.py            # разова перевірка REST
    python neptun_probe.py --watch 10 # плюс 10 хвилин спостереження за WebSocket
"""

import sys, json, time, collections, datetime as dt, ssl
import certifi
SSL_CTX=ssl.create_default_context(cafile=certifi.where())
import requests

BASE = 'https://neptun.in.ua'
UA = {'User-Agent': 'tryvoha-probe/1.0 (+https://pid-tryvohoyu.netlify.app)'}


def get(path):
    r = requests.get(BASE + path, headers=UA, timeout=20)
    r.raise_for_status()
    return r.json()


print("=" * 66)
print("NEPTUN API — перевірка")
print("=" * 66)

# ---------------------------------------------------------------- загрози
try:
    t0 = time.time()
    data = get('/api/v1/threats')
    ms = (time.time() - t0) * 1000
except Exception as e:
    sys.exit(f"API недоступний: {type(e).__name__}: {e}")

threats = data.get('threats', [])
print(f"\nВідповідь за {ms:.0f} мс | serverTime: {data.get('serverTime')}")
print(f"Активних загроз зараз: {len(threats)}")

if not threats:
    print("\nЗагроз немає — зараз спокійно. Це не помилка, але для оцінки")
    print("заповненості полів запусти скрипт під час тривоги.")
else:
    fields = ['type', 'locality', 'district', 'region', 'lat', 'heading',
              'count', 'sourceCount', 'confidenceLevel', 'velocity',
              'explanationShort']
    fill = collections.Counter()
    for t in threats:
        for f in fields:
            v = t.get(f)
            if v not in (None, '', 0, [], {}):
                fill[f] += 1

    print("\nЗаповненість полів (від цього залежить текст у боті):")
    for f in fields:
        n = fill[f]
        p = n / len(threats) * 100
        crit = ' ← критичне для бота' if f in ('locality', 'type') and p < 80 else ''
        print(f"   {f:<18}{n:>4}/{len(threats):<4}{p:>6.0f}%{crit}")

    area = sum(1 for t in threats if t.get('areaOnly'))
    adv = sum(1 for t in threats if t.get('advisory'))
    print(f"\n   areaOnly (точки немає):  {area}/{len(threats)}")
    print(f"   advisory (не ховатися):  {adv}/{len(threats)}")

    print("\nЗа типами:")
    for ty, n in collections.Counter(t.get('type') for t in threats).most_common():
        print(f"   {str(ty):<12}{n}")

    print("\nЗа рівнем довіри:")
    for c, n in collections.Counter(
            t.get('confidenceLevel') for t in threats).most_common():
        print(f"   {str(c):<12}{n}")

    print("\nПриклади — як це виглядатиме в боті:")
    for t in threats[:6]:
        loc = t.get('locality') or t.get('region') or '?'
        cnt = t.get('count') or 0
        ty = t.get('type')
        hd = t.get('heading')
        dirn = ''
        if hd is not None:
            names = ['півночі', 'північного сходу', 'сходу', 'південного сходу',
                     'півдня', 'південного заходу', 'заходу', 'північного заходу']
            dirn = f" з {names[int(((hd + 180) % 360) / 45) % 8]}"
        tag = ' [лише область]' if t.get('areaOnly') else ''
        tag += ' [спостереження]' if t.get('advisory') else ''
        print(f"   {loc} — {cnt or ''} {ty}{dirn}"
              f" · джерел {t.get('sourceCount')}"
              f" · {t.get('confidenceLevel')}{tag}")

# ---------------------------------------------------------------- тривоги
try:
    al = get('/api/v1/alerts')
    ra, ob = al.get('raions', []), al.get('oblasts', [])
    print(f"\nОфіційні тривоги зараз: {len(ra)} районів, {len(ob)} областей")
    for x in ra[:8]:
        print(f"   {x.get('name')} ({x.get('oblast')}) з {x.get('since')}")
    if len(ra) > 8:
        print(f"   … ще {len(ra) - 8}")
except Exception as e:
    print(f"\n/api/v1/alerts недоступний: {e}")

# ---------------------------------------------------------------- стрічка
try:
    ms_ = get('/api/v1/messages').get('messages', [])
    print(f"\nСтрічка повідомлень: {len(ms_)} останніх")
    chans = collections.Counter(m.get('channel') for m in ms_)
    print("Канали, з яких вони беруть дані:")
    for c, n in chans.most_common(20):
        print(f"   {str(c):<28}{n}")
except Exception as e:
    print(f"\n/api/v1/messages недоступний: {e}")

# ---------------------------------------------------------------- стрім
if '--watch' in sys.argv:
    mins = int(sys.argv[sys.argv.index('--watch') + 1])
    print(f"\n{'=' * 66}\nСпостереження за WebSocket {mins} хв\n{'=' * 66}")
    try:
        import asyncio, websockets
    except ImportError:
        sys.exit("Постав: pip install websockets")

    async def watch():
        stats = collections.Counter()
        first_seen = {}
        end = time.time() + mins * 60
        url = 'wss://neptun.in.ua/api/v1/stream'
        async with websockets.connect(url, ssl=SSL_CTX, additional_headers=UA) as ws:
            print("Підключено. Кожна подія друкується одразу.\n")
            while time.time() < end:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=60)
                except asyncio.TimeoutError:
                    print("  … 60 с без жодного фрейму (навіть heartbeat)")
                    stats['timeout'] += 1
                    continue
                env = json.loads(raw)
                k = env.get('type')
                stats[k] += 1
                now = dt.datetime.now().strftime('%H:%M:%S')
                if k == 'upsert':
                    d = env.get('data', {})
                    tid = d.get('id')
                    lag = ''
                    if tid not in first_seen:
                        first_seen[tid] = time.time()
                    up = d.get('updatedAt')
                    if up:
                        try:
                            u = dt.datetime.fromisoformat(up.replace('Z', '+00:00'))
                            lag = f" | затримка {(dt.datetime.now(dt.timezone.utc) - u).total_seconds():.0f} с"
                        except Exception:
                            pass
                    print(f"  {now} upsert  {d.get('locality') or d.get('region')} "
                          f"· {d.get('type')} · {d.get('confidenceLevel')}{lag}")
                elif k == 'remove':
                    print(f"  {now} remove  {env.get('data', {}).get('id')}")
                elif k == 'alerts':
                    d = env.get('data', {})
                    print(f"  {now} alerts  районів {len(d.get('raions', []))}, "
                          f"областей {len(d.get('oblasts', []))}")
        print("\nПідсумок за період:")
        for k, n in stats.most_common():
            print(f"   {k:<12}{n}")
        print(f"   унікальних треків: {len(first_seen)}")

    asyncio.run(watch())

print("""
Що дивитись:
  locality заповнена менш ніж у 80% — бот часто не зможе назвати місто
  багато areaOnly — багато загроз без точки, лише область
  heartbeat раз на N секунд — так виглядає нормальний стрім
  timeout у підсумку — стрім рветься, потрібен авто-реконект
""")
