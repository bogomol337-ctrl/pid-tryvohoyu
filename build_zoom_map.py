# -*- coding: utf-8 -*-
"""
Будує масштабовану карту на MapLibre: райони + населені пункти,
із зумом до окремого міста, як на DeepState.

    python build_zoom_map.py

Потрібні поруч:
    messages.db            (таблиця threats_geo)
    raiony_alerts.geojson  (межі районів зі статистикою тривог)

На виході: karta.html + settlements.json
Обидва файли треба покласти поруч на сайті.
"""

import sqlite3, json, os, sys, collections

DB = sys.argv[1] if len(sys.argv) > 1 else 'messages.db'
if not os.path.exists('raiony_alerts.geojson'):
    sys.exit('Немає raiony_alerts.geojson — поклади його поруч зі скриптом')

con = sqlite3.connect(DB)
rows = con.execute("""
    SELECT matched, oblast, raion, lat, lon, weapon, jet, substr(ts,1,4)
    FROM threats_geo WHERE matched IS NOT NULL AND lat IS NOT NULL""").fetchall()
print(f"Подій із координатами: {len(rows)}")

CLASS = {'drone': 'd', 'shahed': 'd', 'decoy': 'd', 'loitering': 'd',
         'ballistic': 'm', 'cruise': 'm', 'kinzhal': 'm', 'antiship': 'm',
         'guided_air': 'm', 'missile_alert': 'm', 'kab': 'k'}
pts = {}
for name, obl, raion, lat, lon, weapon, jet, year in rows:
    k = (name, obl)
    if k not in pts:
        pts[k] = {'n': name, 'o': (obl or '').replace(' область', ''),
                  'r': (raion or '').replace(' район', ''),
                  'lat': round(lat, 5), 'lon': round(lon, 5),
                  'c': 0, 'jet': 0, 'd': 0, 'm': 0, 'k': 0,
                  'yr': collections.Counter()}
    p = pts[k]
    p['c'] += 1
    p['jet'] += int(jet or 0)
    p[CLASS.get(weapon, 'd')] += 1
    p['yr'][year] += 1

data = sorted(pts.values(), key=lambda z: -z['c'])
for p in data:
    p['yr'] = dict(p['yr'])
    p['je'] = round(p['jet'] / p['c'], 2)
    del p['jet']

by_class = collections.Counter()
for p in data:
    for c in 'dmk':
        by_class[c] += p[c]
print(f"  дрони {by_class['d']} | ракети {by_class['m']} | КАБи {by_class['k']}")

fc = {'type': 'FeatureCollection', 'features': [
    {'type': 'Feature',
     'geometry': {'type': 'Point', 'coordinates': [p['lon'], p['lat']]},
     'properties': {k: v for k, v in p.items() if k not in ('lat', 'lon', 'yr')}}
    for p in data]}
json.dump(fc, open('settlements.json', 'w'), ensure_ascii=False)
print(f"Населених пунктів: {len(data)} → settlements.json "
      f"({os.path.getsize('settlements.json')//1024} KB)")
print("Топ-8:", ', '.join(f"{p['n']} ({p['c']})" for p in data[:8]))

HTML = r"""<!DOCTYPE html><html lang="uk"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Карта повітряної загрози — Під тривогою</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<link href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css" rel="stylesheet">
<script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
<style>
:root{--ink:#15181B;--mid:#5B646A;--hair:#C3CBD0;--panel:#F4F6F7}
*{box-sizing:border-box}html,body{margin:0;height:100%}
body{font-family:Inter,system-ui,sans-serif;font-variant-numeric:tabular-nums;color:var(--ink)}
#map{position:absolute;inset:0}
.card{position:absolute;z-index:5;background:rgba(244,246,247,.96);backdrop-filter:blur(8px);
 border:1px solid var(--hair);border-radius:5px}
#panel{top:14px;left:14px;width:290px;padding:16px 17px;max-height:calc(100% - 28px);overflow:auto}
#panel h1{font-size:19px;font-weight:700;letter-spacing:-.02em;margin:0 0 5px}
#panel p.s{font-size:12.5px;color:var(--mid);line-height:1.5;margin:0 0 14px}
#panel a{color:var(--ink)}
.lg{font-size:11.5px;color:var(--mid)}
.ramp{display:flex;height:9px;margin:5px 0 3px}
.ramp i{flex:1}
.rowb{display:flex;justify-content:space-between;font-size:11px;color:var(--mid)}
label.f{display:block;font-size:12px;color:var(--mid);margin:14px 0 5px}
.lay{margin-top:11px;display:flex;flex-direction:column;gap:5px}
.lay label{font-size:12.5px;display:flex;align-items:center;gap:7px;cursor:pointer}
.lay input{accent-color:#AE4220;margin:0}
select{width:100%;font:inherit;font-size:13px;padding:6px 8px;background:#fff;
 border:1px solid var(--hair);border-radius:3px;color:var(--ink)}
#info{border-top:1px solid var(--hair);margin-top:14px;padding-top:12px;font-size:13px;display:none}
#info b{display:block;font-size:16px;font-weight:600;letter-spacing:-.01em;margin-bottom:2px}
#info .m{color:var(--mid);font-size:12px;margin-bottom:9px}
#info dl{display:grid;grid-template-columns:1fr auto;gap:4px 10px;margin:0;font-size:12.5px}
#info dt{color:var(--mid)}#info dd{margin:0;font-weight:600;text-align:right}
#hint{bottom:14px;left:14px;right:14px;max-width:640px;margin:0 auto;padding:11px 14px;
 font-size:12px;color:var(--mid);line-height:1.5}
#hint b{color:var(--ink)}
.maplibregl-popup-content{font-family:Inter,sans-serif;font-size:13px;padding:9px 12px;border-radius:4px}
@media(max-width:640px){#panel{width:auto;right:14px;max-height:46%}}
</style></head><body>
<div id="map"></div>

<div class="card" id="panel">
  <h1>Під тривогою</h1>
  <p class="s">Наближайте карту, щоб дійти до району й окремого міста. Заливка — частка часу під повітряною тривогою за 2025–2026. Теплі плями й крапки — населені пункти, які називали в оперативних попередженнях.</p>

  <div class="lg">Частка часу під тривогою</div>
  <div class="ramp">
    <i style="background:#F7F1DC"></i><i style="background:#F0D48F"></i><i style="background:#E5A950"></i>
    <i style="background:#D2762F"></i><i style="background:#AE4220"></i><i style="background:#761811"></i>
  </div>
  <div class="rowb"><span>0%</span><span>97%</span></div>

  <label class="f">Тип загрози
    <select id="wf">
      <option value="c">усі</option>
      <option value="d">ударні дрони</option>
      <option value="m">ракети</option>
      <option value="k">КАБи</option>
    </select>
  </label>

  <div class="lay">
    <label><input type="checkbox" id="l-heat" checked> теплові плями</label>
    <label><input type="checkbox" id="l-pt" checked> населені пункти</label>
    <label><input type="checkbox" id="l-rai" checked> заливка районів</label>
  </div>

  <div id="info">
    <b id="i-name"></b>
    <div class="m" id="i-loc"></div>
    <dl id="i-dl"></dl>
  </div>
</div>

<div class="card" id="hint">
  <b>Тривога — це не влучання.</b> Мапа показує, де оголошували загрозу і куди летіли цілі, а не куди падало. У прифронтових районах тривогу вмикають на кілька хвилин підлітного часу, у тилу — на весь маршрут ракети через півкраїни. Не ухвалюйте рішення про переїзд лише за цією картою.
</div>

<script>
const RAMP=['#F7F1DC','#F0D48F','#E5A950','#D2762F','#AE4220','#761811'];
const map=new maplibregl.Map({
  container:'map',
  style:'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json',
  center:[31.5,48.9], zoom:5.3, minZoom:4.5, maxZoom:13,
  maxBounds:[[19.5,42.5],[42.5,53.6]]
});
map.addControl(new maplibregl.NavigationControl({showCompass:false}),'top-right');
map.addControl(new maplibregl.ScaleControl({unit:'metric'}),'bottom-right');

const $=i=>document.getElementById(i);
function show(o){
  $('info').style.display='block';
  $('i-name').textContent=o.name; $('i-loc').textContent=o.loc;
  $('i-dl').innerHTML=o.rows.map(([k,v])=>`<dt>${k}</dt><dd>${v}</dd>`).join('');
}

map.on('load',async()=>{
  const [rai,set]=await Promise.all([
    fetch('raiony_alerts.geojson').then(r=>r.json()),
    fetch('settlements.json').then(r=>r.json())
  ]);

  map.addSource('rai',{type:'geojson',data:rai});
  map.addLayer({id:'rai-fill',type:'fill',source:'rai',
    paint:{'fill-color':['case',['==',['get','pct'],null],'#D4DADE',
      ['interpolate',['linear'],['get','pct'],0,RAMP[0],8,RAMP[1],20,RAMP[2],
       38,RAMP[3],60,RAMP[4],85,RAMP[5]]],
      'fill-opacity':['interpolate',['linear'],['zoom'],5,.82,9,.55,12,.32]}},
    'watername_ocean');
  map.addLayer({id:'rai-line',type:'line',source:'rai',
    paint:{'line-color':'#7C878E','line-width':['interpolate',['linear'],['zoom'],5,.4,10,1.1],
           'line-opacity':.5}});
  map.addLayer({id:'rai-hot',type:'line',source:'rai',filter:['==','name',''],
    paint:{'line-color':'#15181B','line-width':2.2}});

  map.addSource('set',{type:'geojson',data:set});

  map.addLayer({id:'set-heat',type:'heatmap',source:'set',
    maxzoom:11,
    paint:{
      'heatmap-weight':['interpolate',['linear'],['get','c'],0,0,1,.12,60,1],
      'heatmap-intensity':['interpolate',['linear'],['zoom'],5,.9,11,2.6],
      'heatmap-radius':['interpolate',['linear'],['zoom'],5,14,8,32,11,58],
      'heatmap-opacity':['interpolate',['linear'],['zoom'],5,.75,9,.6,11,0],
      'heatmap-color':['interpolate',['linear'],['heatmap-density'],
        0,'rgba(0,0,0,0)',.2,'#F0D48F',.4,'#E5A950',
        .6,'#D2762F',.8,'#AE4220',1,'#5A140E']}});

  map.addLayer({id:'set-pt',type:'circle',source:'set',
    paint:{
      'circle-radius':['interpolate',['linear'],['zoom'],
        5,['interpolate',['linear'],['sqrt',['get','c']],1,1.6,24,7],
        10,['interpolate',['linear'],['sqrt',['get','c']],1,4,24,20]],
      'circle-opacity':['interpolate',['linear'],['zoom'],7,.25,10,.65],
      'circle-color':'#5A140E',
      'circle-stroke-color':'#fff','circle-stroke-width':.7}});
  map.addLayer({id:'set-lbl',type:'symbol',source:'set',
    minzoom:8,
    layout:{'text-field':['get','n'],'text-size':11,
      'text-font':['Open Sans Semibold'],'text-offset':[0,1.1],'text-anchor':'top',
      'text-allow-overlap':false},
    paint:{'text-color':'#15181B','text-halo-color':'#fff','text-halo-width':1.4}});

  map.on('mousemove','rai-fill',e=>{
    const p=e.features[0].properties;
    map.setFilter('rai-hot',['==','name',p.name]);
    map.getCanvas().style.cursor='pointer';
    show({name:p.name,loc:p.oblast+' область',rows:[
      ['Часу під тривогою', p.pct==null?'немає даних':p.pct+'%'],
      ['Тривог за 2025–26', p.eps==null?'—':Number(p.eps).toLocaleString('uk')],
      ['Рівень оголошень', p.own>30?'по району':'по всій області']]});
  });
  map.on('mouseleave','rai-fill',()=>{
    map.setFilter('rai-hot',['==','name','']);
    map.getCanvas().style.cursor='';
  });

  map.on('click','set-pt',e=>{
    const p=e.features[0].properties;
    new maplibregl.Popup({closeButton:false,offset:9})
      .setLngLat(e.lngLat)
      .setHTML(`<strong>${p.n}</strong><br><span style="color:#5B646A">${p.r} р-н, ${p.o}</span>`
        +`<br>${p.c} згадок: дрони ${p.d}`
        +(p.m?`, ракети ${p.m}`:'')+(p.k?`, КАБи ${p.k}`:'')
        +(p.je>0.05?`<br>реактивних: ${Math.round(p.je*100)}%`:''))
      .addTo(map);
  });
  map.on('mouseenter','set-pt',()=>map.getCanvas().style.cursor='pointer');
  map.on('mouseleave','set-pt',()=>map.getCanvas().style.cursor='');

  function apply(){
    const w=$('wf').value;
    const f = w==='c' ? null : ['>',['get',w],0];
    ['set-pt','set-lbl','set-heat'].forEach(l=>map.setFilter(l,f));
    if(w!=='c') map.setPaintProperty('set-heat','heatmap-weight',
      ['interpolate',['linear'],['get',w],0,0,1,.15,40,1]);
    else map.setPaintProperty('set-heat','heatmap-weight',
      ['interpolate',['linear'],['get','c'],0,0,1,.12,60,1]);
    const on=(id,layers)=>layers.forEach(l=>
      map.setLayoutProperty(l,'visibility',$(id).checked?'visible':'none'));
    on('l-heat',['set-heat']); on('l-pt',['set-pt','set-lbl']);
    on('l-rai',['rai-fill','rai-line']);
  }
  $('wf').onchange=apply;
  ['l-heat','l-pt','l-rai'].forEach(i=>$(i).onchange=apply);
  apply();
});
</script></body></html>"""

open('karta.html', 'w', encoding='utf-8').write(HTML)
print(f"\nГотово: karta.html ({os.path.getsize('karta.html')//1024} KB)")
print("Поклади поруч: karta.html, settlements.json, raiony_alerts.geojson")
con.close()
