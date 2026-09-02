# -*- coding: utf-8 -*-
"""
Карта на deck.gl (WebGL) поверх MapLibre.

Читає таблицю events (її створює extract_all.py) і будує сторінку,
що тягне сотні тисяч точок без падіння FPS.

    python build_deck_map.py

На виході: mapa.html + events.json
"""

import sqlite3, json, os, sys, collections

DB = sys.argv[1] if len(sys.argv) > 1 else 'messages.db'

CLASS = {'drone': 0, 'ballistic': 1, 'cruise': 1, 'kinzhal': 1, 'antiship': 1,
         'guided_air': 1, 'missile_alert': 1, 'kab': 2, 'recon': 3, 'target': 4}
CLASS_NAME = ['Ударні БпЛА', 'Ракети', 'КАБи', 'Розвідувальні', 'Тип не вказано']

con = sqlite3.connect(DB)
rows = con.execute("""
    SELECT settlement, oblast, raion, lat, lon, weapon, jet, substr(ts,1,7)
    FROM events WHERE lat IS NOT NULL AND ts >= '2022-02-24'""").fetchall()
print(f"Подій у базі: {len(rows):,}".replace(',', ' '))

places, months = {}, {}
cells = collections.Counter()          # (place, month, class) -> кількість
jets = collections.Counter()

for st, obl, rai, lat, lon, weapon, jet, ym in rows:
    key = (st, obl)
    if key not in places:
        places[key] = [st, (obl or '').replace(' область', ''),
                       (rai or '').replace(' район', ''),
                       round(lon, 5), round(lat, 5)]
    if ym not in months:
        months[ym] = len(months)
    pi = list(places).index(key) if False else None   # заповнимо нижче
place_idx = {k: i for i, k in enumerate(places)}
month_list = sorted(months)
month_idx = {m: i for i, m in enumerate(month_list)}

for st, obl, rai, lat, lon, weapon, jet, ym in rows:
    pi = place_idx[(st, obl)]
    cells[(pi, month_idx[ym], CLASS.get(weapon, 0))] += 1
    if jet:
        jets[pi] += 1

flat = []
for (pi, mi, ci), n in cells.items():
    flat.extend([pi, mi, ci, n])

payload = {
    'places': list(places.values()),
    'months': month_list,
    'classes': CLASS_NAME,
    'cells': flat,                      # плоский масив по 4 числа
    'jets': [jets.get(i, 0) for i in range(len(places))],
}
json.dump(payload, open('events.json', 'w'), ensure_ascii=False,
          separators=(',', ':'))
print(f"Населених пунктів: {len(places):,}".replace(',', ' '))
print(f"Місяців: {len(month_list)} ({month_list[0]} — {month_list[-1]})"
      if month_list else "Порожньо")
print(f"Комірок: {len(cells):,}".replace(',', ' '),
      f"→ events.json ({os.path.getsize('events.json')//1024} KB)")

top = collections.Counter()
for (pi, mi, ci), n in cells.items():
    top[pi] += n
print("Топ-8:", ', '.join(
    f"{payload['places'][i][0]} ({n})" for i, n in top.most_common(8)))

HTML = r"""<!DOCTYPE html><html lang="uk"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Карта повітряних загроз — Під тривогою</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<link href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css" rel="stylesheet">
<script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
<script src="https://unpkg.com/deck.gl@9.0.35/dist.min.js"></script>
<style>
:root{--ink:#15181B;--mid:#5B646A;--hair:#C3CBD0;--panel:#F4F6F7;--hot:#AE4220}
*{box-sizing:border-box}html,body{margin:0;height:100%;overflow:hidden}
body{font-family:Inter,system-ui,sans-serif;font-variant-numeric:tabular-nums;color:var(--ink)}
#map{position:absolute;inset:0}
canvas{outline:none}
.maplibregl-canvas{cursor:grab}
.maplibregl-canvas:active{cursor:grabbing}
.card{position:absolute;z-index:5;background:rgba(244,246,247,.96);
 backdrop-filter:blur(8px);border:1px solid var(--hair);border-radius:5px}
#panel{top:14px;left:14px;width:300px;padding:16px 17px;max-height:calc(100% - 28px);overflow:auto}
h1{font-size:19px;font-weight:700;letter-spacing:-.02em;margin:0 0 5px}
.s{font-size:12.5px;color:var(--mid);line-height:1.5;margin:0 0 14px}
.f{display:block;font-size:12px;color:var(--mid);margin:13px 0 5px}
select,input[type=range]{width:100%}
select{font:inherit;font-size:13px;padding:6px 8px;background:#fff;
 border:1px solid var(--hair);border-radius:3px;color:var(--ink)}
input[type=range]{accent-color:var(--hot);margin:2px 0}
.lay{margin-top:11px;display:flex;flex-direction:column;gap:5px}
.lay label{font-size:12.5px;display:flex;align-items:center;gap:7px;cursor:pointer}
.lay input{accent-color:var(--hot);margin:0;width:auto}
#stat{border-top:1px solid var(--hair);margin-top:13px;padding-top:12px;font-size:13px}
#stat b{display:block;font-size:15px;font-weight:600}
#stat .n{font-size:27px;font-weight:700;letter-spacing:-.02em;line-height:1.1}
#tip{position:absolute;z-index:9;pointer-events:none;display:none;
 background:rgba(21,24,27,.94);color:#fff;padding:9px 12px;border-radius:4px;
 font-size:12.5px;line-height:1.45;max-width:230px}
#tip b{font-size:14px}
#tip span{color:#B9C2C7}
#legend{bottom:14px;left:14px;padding:11px 14px;font-size:11.5px;color:var(--mid)}
#legend i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px}
</style></head><body>
<div id="map"></div>
<div id="tip"></div>

<div class="card" id="panel">
  <h1>Карта повітряних загроз</h1>
  <p class="s">Кожна крапка — населений пункт, який називали в повідомленнях про повітряну загрозу. Розмір і колір — кількість згадок. Наближайте, щоб дійти до сіл.</p>

  <label class="f">Тип цілі
    <select id="cls"><option value="-1">усі</option></select>
  </label>

  <label class="f">Період: <span id="mlabel"></span></label>
  <input type="range" id="m0" min="0" value="0">
  <input type="range" id="m1" min="0" value="0">

  <div class="lay">
    <label><input type="checkbox" id="l-heat" checked> теплові плями</label>
    <label><input type="checkbox" id="l-pts" checked> населені пункти</label>
  </div>

  <div id="stat">
    <b id="s-name">Уся Україна</b>
    <div class="n" id="s-num"></div>
    <div class="s" id="s-sub" style="margin:2px 0 0"></div>
  </div>
</div>

<div class="card" id="legend">
  <div><i style="background:#F0D48F"></i>рідко</div>
  <div><i style="background:#D2762F"></i>часто</div>
  <div><i style="background:#5A140E"></i>дуже часто</div>
  <div style="margin-top:6px">Згадка ≠ влучання</div>
</div>

<script>
const {MapboxOverlay,ScatterplotLayer,HeatmapLayer}=deck;
const $=i=>document.getElementById(i);
let D=null, agg=null, maxC=1, overlay=null;

const RAMP=[[247,241,220],[240,212,143],[229,169,80],[210,118,47],[174,66,32],[90,20,14]];
function color(t){
  const x=Math.min(.999,Math.max(0,t))*(RAMP.length-1);
  const i=Math.floor(x), f=x-i, a=RAMP[i], b=RAMP[Math.min(i+1,RAMP.length-1)];
  return [a[0]+(b[0]-a[0])*f, a[1]+(b[1]-a[1])*f, a[2]+(b[2]-a[2])*f, 210];
}

function recompute(){
  const c=+$('cls').value;
  let a=+$('m0').value, b=+$('m1').value;
  if(a>b){const t=a;a=b;b=t;}
  $('mlabel').textContent = D.months[a]===D.months[b]
    ? D.months[a] : `${D.months[a]} — ${D.months[b]}`;
  agg=new Float64Array(D.places.length);
  const cells=D.cells;
  for(let i=0;i<cells.length;i+=4){
    const mi=cells[i+1];
    if(mi<a||mi>b) continue;
    if(c>=0 && cells[i+2]!==c) continue;
    agg[cells[i]]+=cells[i+3];
  }
  maxC=1; let tot=0, np=0;
  for(let i=0;i<agg.length;i++){ const v=agg[i]; if(v>maxC)maxC=v; tot+=v; if(v)np++; }
  $('s-name').textContent='Уся Україна';
  $('s-num').textContent=tot.toLocaleString('uk');
  $('s-sub').textContent=`згадок у ${np.toLocaleString('uk')} населених пунктах`;
  render();
}

function render(){
  if(!overlay||!agg) return;
  const idx=[];
  for(let i=0;i<agg.length;i++) if(agg[i]>0) idx.push(i);
  const layers=[];
  if($('l-heat').checked) layers.push(new HeatmapLayer({
    id:'heat', data:idx,
    getPosition:i=>[D.places[i][3],D.places[i][4]],
    getWeight:i=>agg[i],
    radiusPixels:55, intensity:1.1, threshold:.05,
    colorRange:RAMP.slice(1).map(c=>[c[0],c[1],c[2],185]),
    updateTriggers:{getWeight:agg}
  }));
  if($('l-pts').checked) layers.push(new ScatterplotLayer({
    id:'pts', data:idx, pickable:true,
    getPosition:i=>[D.places[i][3],D.places[i][4]],
    getRadius:i=>Math.sqrt(agg[i]/maxC)*11000+900,
    radiusMinPixels:2.5, radiusMaxPixels:36,
    getFillColor:i=>color(Math.sqrt(agg[i]/maxC)),
    stroked:true, lineWidthMinPixels:.6, getLineColor:[255,255,255,170],
    onHover:info=>{
      const t=$('tip');
      if(!info||info.object===undefined||info.object===null){
        t.style.display='none'; return;
      }
      const i=info.object, p=D.places[i], n=agg[i], jet=D.jets[i]||0;
      t.style.display='block';
      t.style.left=(info.x+16)+'px'; t.style.top=(info.y+16)+'px';
      t.innerHTML=`<b>${p[0]}</b><br><span>${p[2]?p[2]+' р-н, ':''}${p[1]}</span>`
        +`<br>${Math.round(n).toLocaleString('uk')} згадок про загрозу`
        +(jet/Math.max(n,1)>.05?`<br><span>реактивних: ${Math.round(jet/n*100)}%</span>`:'');
    },
    updateTriggers:{getRadius:[maxC,agg],getFillColor:[maxC,agg]}
  }));
  overlay.setProps({layers});
}

fetch('events.json').then(r=>r.json()).then(j=>{
  D=j;
  D.classes.forEach((c,i)=>$('cls').insertAdjacentHTML('beforeend',
    `<option value="${i}">${c}</option>`));
  const last=D.months.length-1;
  $('m0').max=last; $('m1').max=last;
  $('m0').value=0;  $('m1').value=last;

  const map=new maplibregl.Map({
    container:'map',
    style:'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json',
    center:[31.5,48.9], zoom:5.4, minZoom:4.5, maxZoom:14,
    scrollZoom:true, dragRotate:false
  });
  map.addControl(new maplibregl.NavigationControl({showCompass:false}),'top-right');
  map.addControl(new maplibregl.ScaleControl({unit:'metric'}),'bottom-right');

  // MapboxOverlay — штатний спосіб посадити deck.gl на MapLibre.
  // Камерою керує сама карта, колесо миші й перетягування працюють як завжди.
  overlay=new MapboxOverlay({interleaved:false, layers:[]});
  map.addControl(overlay);

  map.on('load',()=>{ recompute(); });
  ['cls','m0','m1'].forEach(i=>$(i).oninput=recompute);
  ['l-heat','l-pts'].forEach(i=>$(i).onchange=render);
}).catch(e=>{
  document.getElementById('s-name').textContent='Не вдалося завантажити дані';
  console.error(e);
});
</script></body></html>"""

open('mapa.html', 'w', encoding='utf-8').write(HTML)
print(f"Готово: mapa.html ({os.path.getsize('mapa.html')//1024} KB)")
con.close()
