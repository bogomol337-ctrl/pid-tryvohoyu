# -*- coding: utf-8 -*-
"""
Будує сторінку «Чим били» — динаміка типів озброєння по місяцях
з ранкових зведень Повітряних Сил.

    python build_weapons.py

Потрібна таблиця summaries (її створює parse_kpszsu.py).
На виході — zbroya.html.
"""

import sqlite3, json, sys, os, collections

DB = sys.argv[1] if len(sys.argv) > 1 else 'messages.db'
OUT = 'zbroya.html'

# Родина дронів рахується одним числом. ПС у різні роки писали по-різному:
# то одним пакетом («255 БпЛА типу Shahed, Гербера, Італмас»), то по пунктах.
# Складати ці корзини не можна — беремо максимум як оцінку розміру нальоту.
DRONE = {'drone_mixed', 'drone', 'shahed', 'decoy', 'loitering'}
MISSILE = {'cruise', 'ballistic', 'kinzhal', 'antiship', 'guided_air'}

con = sqlite3.connect(DB)
rows = con.execute("SELECT ts, launched, destroyed, impact_locations FROM summaries "
                   "ORDER BY ts").fetchall()
print(f"Зведень у базі: {len(rows)}")

months = collections.defaultdict(lambda: {'drones': 0, 'missiles': 0,
                                          'ballistic': 0, 'cruise': 0,
                                          'impacts': 0, 'n': 0, 'itemized': 0})
for ts, launched, destroyed, impacts in rows:
    m = ts[:7]
    L = json.loads(launched or '{}')
    b = months[m]
    b['n'] += 1
    drone_vals = [v for k, v in L.items() if k in DRONE]
    if drone_vals:
        # якщо розписано по типах — сума; якщо одним пакетом — це вже все
        b['drones'] += max(drone_vals) if 'drone_mixed' in L else sum(drone_vals)
        b['itemized'] += int('drone_mixed' not in L)
    b['missiles'] += sum(v for k, v in L.items() if k in MISSILE)
    b['ballistic'] += L.get('ballistic', 0)
    b['cruise'] += L.get('cruise', 0)
    if impacts:
        b['impacts'] += impacts

keys = sorted(months)
data = [{'m': k, **months[k]} for k in keys]
print(f"Місяців: {len(data)} ({keys[0]} — {keys[-1]})" if keys else "Порожньо")
tot_d = sum(d['drones'] for d in data)
tot_m = sum(d['missiles'] for d in data)
print(f"Дронів запущено: {tot_d:,} | ракет: {tot_m:,}".replace(',', ' '))
peak = max(data, key=lambda d: d['drones']) if data else None
if peak:
    print(f"Пік по дронах: {peak['m']} — {peak['drones']}")

HTML = r"""<!DOCTYPE html><html lang="uk"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Чим били — динаміка засобів повітряного нападу</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root{--bg:#E6EAEC;--panel:#F4F6F7;--ink:#15181B;--mid:#5B646A;--hair:#C3CBD0;
 --drone:#C4761F;--missile:#8E1F16}
*{box-sizing:border-box}html,body{margin:0}
body{background:var(--bg);color:var(--ink);font-family:Inter,system-ui,sans-serif;
 font-variant-numeric:tabular-nums;-webkit-font-smoothing:antialiased}
.wrap{max-width:1080px;margin:0 auto;padding:38px 22px 70px}
h1{font-size:clamp(28px,4.6vw,46px);font-weight:700;letter-spacing:-.03em;line-height:1.04;margin:0 0 12px;max-width:18ch}
.sub{max-width:62ch;color:var(--mid);font-size:15px;line-height:1.6;margin:0 0 28px}
.key{display:flex;gap:22px;flex-wrap:wrap;font-size:13px;color:var(--mid);margin-bottom:8px}
.key i{display:inline-block;width:11px;height:11px;margin-right:6px;vertical-align:-1px}
.ctl{display:flex;gap:22px;align-items:flex-end;border-top:1px solid var(--hair);
 border-bottom:1px solid var(--hair);padding:14px 0;margin-bottom:24px}
.ctl label{display:flex;flex-direction:column;gap:6px;font-size:12px;color:var(--mid)}
select{font:inherit;font-size:14px;background:var(--panel);border:1px solid var(--hair);
 border-radius:3px;padding:7px 10px;min-width:200px;color:var(--ink)}
svg{width:100%;height:auto;display:block}
.axis{font-size:11px;fill:var(--mid)}
.grid{stroke:var(--hair);stroke-width:.7}
rect.b{cursor:pointer}rect.b:hover{opacity:.75}
.tip{font-size:12px;fill:var(--ink);font-weight:600}
.note{margin-top:32px;padding-top:18px;border-top:1px solid var(--hair);max-width:74ch;
 font-size:13px;line-height:1.7;color:var(--mid)}
.note b{color:var(--ink);font-weight:600}
.big{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:22px;
 border-bottom:1px solid var(--hair);padding-bottom:22px;margin-bottom:26px}
.big div b{display:block;font-size:30px;font-weight:700;letter-spacing:-.02em}
.big div span{font-size:12px;color:var(--mid);display:block;margin-top:4px}
</style></head><body><div class="wrap">
<h1>Чим били по Україні</h1>
<p class="sub">Кількість засобів повітряного нападу, які Повітряні Сили зафіксували за кожну ніч, згруповано по місяцях. Джерело — ранкові зведення ПС ЗСУ.</p>
<div class="big" id="big"></div>
<div class="ctl">
  <label>Показник<select id="metric">
    <option value="drones">Ударні БпЛА</option>
    <option value="missiles">Ракети всіх типів</option>
    <option value="ballistic">Балістика</option>
    <option value="cruise">Крилаті ракети</option>
    <option value="impacts">Локацій влучань</option>
  </select></label>
</div>
<svg id="ch" viewBox="0 0 1000 380"></svg>
<div class="note">
<p><b>Дрони не можна розкласти за типами.</b> З 2025 року ПС пишуть одним числом: «255 ударним БпЛА типу Shahed, Гербера, Італмас та дронами-імітаторами». Скільки з них справжні «шахеди», а скільки дешеві приманки — не публікується. До 2024-го інколи розписували по пунктах, тому ранні місяці детальніші.</p>
<p><b>Формат зведень мінявся щонайменше тричі.</b> Порівнювати 2022 рік із 2026-м напряму не можна: змінилася і система обліку, і повнота публікацій.</p>
<p><b>«Локацій влучань» — не кількість влучань.</b> ПС рахують населені пункти, де щось впало, а не окремі удари. Десять ракет в одному місті — це одна локація.</p>
</div></div>
<script>
const D=__DATA__;
const $=i=>document.getElementById(i);
const COL={drones:'#C4761F',missiles:'#8E1F16',ballistic:'#8E1F16',cruise:'#C4561F',impacts:'#5B646A'};
const td=D.reduce((s,d)=>s+d.drones,0), tm=D.reduce((s,d)=>s+d.missiles,0),
      ti=D.reduce((s,d)=>s+d.impacts,0);
$('big').innerHTML=`<div><b>${td.toLocaleString('uk')}</b><span>ударних БпЛА зафіксовано</span></div>
<div><b>${tm.toLocaleString('uk')}</b><span>ракет усіх типів</span></div>
<div><b>${ti.toLocaleString('uk')}</b><span>локацій влучань</span></div>
<div><b>${D.length}</b><span>місяців спостережень</span></div>`;
function draw(){
  const k=$('metric').value, W=1000,H=380,P={l:52,r:12,t:16,b:40};
  const mx=Math.max(...D.map(d=>d[k]),1);
  const iw=(W-P.l-P.r)/D.length, bw=Math.max(1.5,iw*0.72);
  let s='';
  for(let g=0;g<=4;g++){const y=P.t+(H-P.t-P.b)*g/4, v=Math.round(mx*(1-g/4));
    s+=`<line class="grid" x1="${P.l}" y1="${y.toFixed(1)}" x2="${W-P.r}" y2="${y.toFixed(1)}"/>`
     + `<text class="axis" x="${P.l-8}" y="${(y+4).toFixed(1)}" text-anchor="end">${v.toLocaleString('uk')}</text>`;}
  D.forEach((d,i)=>{
    const h=(H-P.t-P.b)*d[k]/mx, x=P.l+i*iw+(iw-bw)/2, y=H-P.b-h;
    s+=`<rect class="b" x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(h,0).toFixed(1)}" fill="${COL[k]}"><title>${d.m} — ${d[k].toLocaleString('uk')}</title></rect>`;
    if(d.m.slice(5)==='01'||i===0) s+=`<text class="axis" x="${(x+bw/2).toFixed(1)}" y="${H-P.b+16}" text-anchor="middle">${d.m.slice(0,4)}</text>`;
  });
  $('ch').innerHTML=s;
}
$('metric').onchange=draw;draw();
</script></body></html>"""

open(OUT, 'w', encoding='utf-8').write(
    HTML.replace('__DATA__', json.dumps(data, ensure_ascii=False, separators=(',', ':'))))
print(f"\nГотово: {OUT} ({os.path.getsize(OUT)//1024} KB)")
con.close()
