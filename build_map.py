# -*- coding: utf-8 -*-
"""
Будує інтерактивну карту загроз із таблиці threats_geo.

    python build_map.py

Потрібні поруч: messages.db (з таблицею threats_geo) і geo_raion.json.
На виході — tryvoha-threats.html, самодостатній файл без залежностей.
"""

import sqlite3, json, math, os, sys, collections

DB = sys.argv[1] if len(sys.argv) > 1 else 'messages.db'
OUT = 'tryvoha-threats.html'

if not os.path.exists('geo_raion.json'):
    sys.exit('Немає geo_raion.json — поклади його поруч зі скриптом')

geo = json.load(open('geo_raion.json', encoding='utf-8'))
W, H = geo['w'], geo['h']
LON0, LON1, LAT0, LAT1 = 21.8, 40.4, 44.2, 52.5
MY0 = math.log(math.tan(math.pi / 4 + math.radians(LAT0) / 2))
MY1 = math.log(math.tan(math.pi / 4 + math.radians(LAT1) / 2))


def project(lon, lat):
    my = math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
    return ((lon - LON0) / (LON1 - LON0) * W, H - (my - MY0) / (MY1 - MY0) * H)


con = sqlite3.connect(DB)
rows = con.execute("""
    SELECT matched, oblast, lat, lon, weapon, jet, substr(ts,1,4), substr(ts,12,2)
    FROM threats_geo WHERE matched IS NOT NULL AND lat IS NOT NULL
""").fetchall()
print(f"Подій із координатами: {len(rows)}")

# Ракетна небезпека оголошується лише по областях — окрема таблиця, не крапки
missile = collections.Counter()
missile_years = collections.defaultdict(collections.Counter)
for obl, yr, cnt in con.execute("""
    SELECT oblast, substr(ts,1,4), COUNT(*) FROM threats_geo
    WHERE weapon IN ('missile_alert','ballistic','cruise','kinzhal','antiship')
      AND oblast IS NOT NULL GROUP BY oblast, substr(ts,1,4)"""):
    o = (obl or '').replace(' область', '')
    missile[o] += cnt
    missile_years[o][yr] += cnt
print(f"Оголошень ракетної небезпеки: {sum(missile.values())} у {len(missile)} областях")

WEAP = {'drone': 'drone', 'shahed': 'drone', 'decoy': 'drone',
        'ballistic': 'missile', 'cruise': 'missile', 'kinzhal': 'missile',
        'antiship': 'missile', 'guided_air': 'missile',
        'kab': 'kab', 'loitering': 'drone'}

places = {}
for name, obl, lat, lon, weapon, jet, year, hour in rows:
    k = (name, obl)
    if k not in places:
        x, y = project(lon, lat)
        places[k] = {'n': name, 'o': (obl or '').replace(' область', ''),
                     'x': round(x, 1), 'y': round(y, 1), 'c': 0,
                     'y_': collections.Counter(), 'w': collections.Counter(),
                     'night': 0, 'jet': 0}
    p = places[k]
    p['c'] += 1
    p['y_'][year] += 1
    p['w'][WEAP.get(weapon, 'other')] += 1
    p['jet'] += int(jet or 0)
    try:
        h = int(hour)
        if h >= 22 or h < 6:
            p['night'] += 1
    except (TypeError, ValueError):
        pass

data = []
for p in sorted(places.values(), key=lambda z: -z['c']):
    data.append({'n': p['n'], 'o': p['o'], 'x': p['x'], 'y': p['y'], 'c': p['c'],
                 'yr': dict(p['y_']), 'w': dict(p['w']),
                 'ni': round(p['night'] / p['c'], 2),
                 'je': round(p['jet'] / p['c'], 2)})

years = sorted({y for p in data for y in p['yr']})
# Повнота джерела різко зростала: у 2022 ПС публікували в рази менше.
# Показуємо роки лише з достатнім обсягом, решту прибираємо з фільтра,
# щоб порожня карта не читалась як «тоді було тихо».
vol = collections.Counter()
for p in data:
    for y, c in p['yr'].items():
        vol[y] += c
peak = max(vol.values()) if vol else 1
weak = sorted(y for y in years if vol[y] < peak * 0.15)
years = [y for y in years if y not in weak]
if weak:
    print(f"Роки з надто малим обсягом даних приховано з фільтра: {', '.join(weak)}")
    print(f"  (обсяг: {', '.join(f'{y}={vol[y]}' for y in sorted(vol))})")
print(f"Населених пунктів: {len(data)} | роки: {', '.join(years)}")
print("Топ-10:", ', '.join(f"{d['n']} ({d['c']})" for d in data[:10]))

payload = {'geo': geo, 'places': data, 'years': years, 'weak': weak,
           'missile': dict(missile.most_common()),
           'total': sum(d['c'] for d in data)}

HTML = r"""<!DOCTYPE html>
<html lang="uk"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Маршрути повітряних загроз</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root{--bg:#E6EAEC;--panel:#F4F6F7;--ink:#15181B;--mid:#5B646A;--hair:#C3CBD0;--hot:#AE4220}
*{box-sizing:border-box}html,body{margin:0}
body{background:var(--bg);color:var(--ink);font-family:Inter,system-ui,sans-serif;
 font-variant-numeric:tabular-nums;-webkit-font-smoothing:antialiased}
.wrap{max-width:1180px;margin:0 auto;padding:38px 22px 70px}
h1{font-size:clamp(28px,4.6vw,46px);font-weight:700;letter-spacing:-.03em;line-height:1.04;margin:0 0 12px;max-width:18ch}
.sub{max-width:62ch;color:var(--mid);font-size:15px;line-height:1.6;margin:0 0 26px}
.ctl{display:flex;gap:24px;flex-wrap:wrap;align-items:flex-end;border-top:1px solid var(--hair);
 border-bottom:1px solid var(--hair);padding:15px 0;margin-bottom:24px}
.ctl label{display:flex;flex-direction:column;gap:6px;font-size:12px;color:var(--mid)}
select{font:inherit;font-size:14px;background:var(--panel);border:1px solid var(--hair);
 border-radius:3px;padding:7px 10px;min-width:190px;color:var(--ink)}
.stage{display:grid;grid-template-columns:minmax(0,1.55fr) minmax(260px,1fr);gap:30px;align-items:start}
svg{width:100%;height:auto;display:block}
path.r{fill:#DDE3E6;stroke:var(--bg);stroke-width:.6}
circle.p{fill:var(--hot);fill-opacity:.5;stroke:#71180F;stroke-width:.6;cursor:pointer}
circle.p:hover,circle.p.on{fill-opacity:.9;stroke-width:1.6}
table{width:100%;border-collapse:collapse;font-size:13.5px}
td{padding:6px 0;border-bottom:1px solid rgba(195,203,208,.5);cursor:pointer}
td.v{text-align:right;font-weight:600}
tr.on td{background:rgba(21,24,27,.07)}
.small{font-size:12px;color:var(--mid);margin-top:10px}
.note{margin-top:34px;padding-top:18px;border-top:1px solid var(--hair);max-width:74ch;
 font-size:13px;line-height:1.7;color:var(--mid)}
.note b{color:var(--ink);font-weight:600}
@media(max-width:800px){.stage{grid-template-columns:1fr}}
</style></head><body><div class="wrap">
<h1>Куди летіли ударні дрони</h1>
<p class="sub" id="lede"></p>
<div class="ctl">
  <label>Період<select id="yr"><option value="all">Усі роки</option></select></label>
  <label>Тип цілі<select id="wp">
    <option value="all">Усі БпЛА</option><option value="drone">Звичайні</option>
    <option value="jet">Реактивні</option></select></label>
</div>
<div class="stage">
  <div><svg id="map" viewBox="0 0 1000 660"></svg>
    <p class="small">Розмір кола — кількість згадок населеного пункту в оперативних попередженнях Повітряних Сил.</p></div>
  <div><table><tbody id="rows"></tbody></table></div>
</div>
<h2 style="font-size:22px;font-weight:600;letter-spacing:-.02em;margin:44px 0 6px">Ракетна небезпека — тільки по областях</h2>
<p class="sub" style="margin-bottom:16px">Повітряні Сили ніколи не називають місто, коли попереджають про ракету: підлітний час балістики — хвилини, а маршрут крилатих не оприлюднюють навмисно. Тому ракети не можна нанести крапками. Ось скільки разів оголошували ракетну небезпеку в кожній області.</p>
<table style="max-width:560px"><tbody id="mrows"></tbody></table>

<div class="note">
<p><b>На крапках — лише дрони.</b> Їх ведуть маршрутом уголос, бо летять годинами і люди мають встигнути в укриття. Ракети сюди не потрапляють у принципі — див. блок вище.</p>
<p><b>Це маршрути, а не влучання.</b> Повітряні Сили називають населений пункт, коли ціль летить у його бік. Більшість цих цілей збили або вони пройшли повз. Мапа показує, над ким найчастіше літає, а не куди падає.</p>
<p><b>Ранні роки не показані.</b> <span id="weakn"></span>Повнота джерела зростала весь час війни: у 2022 році Повітряні Сили публікували в рази менше повідомлень, ніж зараз. Порожня карта за той період означала б брак даних, а не спокій, тому такі роки прибрано з фільтра.</p>
<p><b>Великі міста згадують частіше.</b> Не тому, що там небезпечніше, а тому, що вони служать орієнтирами для опису курсу. Село поряд із Харковом ніколи не назвуть окремо.</p>
<p>Джерело: канал Повітряних Сил ЗСУ. Прив'язка назв — довідник населених пунктів KSE.</p>
</div></div>
<script>
const D=__DATA__;
const $=i=>document.getElementById(i);
D.years.forEach(y=>$('yr').insertAdjacentHTML('beforeend',`<option value="${y}">${y}</option>`));
let hot=null;
function val(p){const y=$('yr').value,w=$('wp').value;
  if(y==='all'&&w==='all')return p.c;
  let base=(y==='all')?p.c:(p.yr[y]||0);
  if(w==='jet')  return Math.round(base*p.je);
  if(w==='drone')return Math.round(base*(1-p.je));
  return base;}
function render(){
  const d=D.places.map(p=>({p,v:val(p)})).filter(x=>x.v>0).sort((a,b)=>b.v-a.v);
  const mx=Math.max(...d.map(x=>x.v),1);
  $('lede').textContent=`${d.length.toLocaleString('uk')} населених пунктів, ${d.reduce((s,x)=>s+x.v,0).toLocaleString('uk')} згадок у попередженнях про повітряні цілі.`;
  $('map').innerHTML=Object.values(D.geo.paths).map(p=>`<path class="r" d="${p}"/>`).join('')
    + d.slice().reverse().map(x=>`<circle class="p" data-n="${x.p.n}" cx="${x.p.x}" cy="${x.p.y}" r="${(2+Math.sqrt(x.v/mx)*22).toFixed(1)}"><title>${x.p.n}, ${x.p.o} — ${x.v}</title></circle>`).join('');
  $('rows').innerHTML=d.slice(0,20).map(x=>`<tr data-n="${x.p.n}"><td>${x.p.n}<span style="color:#5B646A"> · ${x.p.o}</span></td><td class="v">${x.v}</td></tr>`).join('');
  document.querySelectorAll('[data-n]').forEach(e=>{
    e.onmouseenter=()=>{document.querySelectorAll('.on').forEach(z=>z.classList.remove('on'));
      document.querySelectorAll(`[data-n="${CSS.escape(e.dataset.n)}"]`).forEach(z=>z.classList.add('on'));};});
}
function missiles(){
  const m=Object.entries(D.missile).sort((a,b)=>b[1]-a[1]);
  const mx=m.length?m[0][1]:1;
  $('mrows').innerHTML=m.map(([o,n])=>`<tr><td>${o}</td><td style="width:45%"><div style="height:7px;background:rgba(195,203,208,.55)"><i style="display:block;height:100%;width:${(n/mx*100).toFixed(1)}%;background:#71160F"></i></div></td><td class="v">${n}</td></tr>`).join('');
}
if(D.weak&&D.weak.length)$('weakn').textContent=`Приховано: ${D.weak.join(', ')}. `;
$('yr').onchange=$('wp').onchange=render;render();missiles();
</script></body></html>"""

open(OUT, 'w', encoding='utf-8').write(
    HTML.replace('__DATA__', json.dumps(payload, ensure_ascii=False, separators=(',', ':'))))
print(f"\nГотово: {OUT} ({os.path.getsize(OUT)//1024} KB)")
print("Відкрий у браузері:  open " + OUT)
con.close()
