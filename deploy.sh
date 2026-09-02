#!/bin/bash
# Збирає папку site/ і публікує її на Netlify.
#
#   ./deploy.sh          — чернетка, тимчасове посилання для перевірки
#   ./deploy.sh --prod   — бойова публікація
#
# Потрібні поруч у ~/tryvoha:
#   index.html            титульна
#   pid-tryvohoyu.html    карта районів і громад
#   tryvoha-threats.html  карта маршрутів дронів
#   ukraine-alert-map.html  карта областей за всю війну
#   zbroya.html           динаміка типів озброєння
#   data/                 відкриті CSV (необов'язково)

set -e
cd "$(dirname "$0")"

echo "▸ Збираю site/"
rm -rf site && mkdir -p site

copy () {   # copy <звідки> <куди>
  if [ -f "$1" ]; then
    cp "$1" "site/$2"
    printf '  ✓ %-24s → %s\n' "$1" "$2"
  else
    printf '  ✗ НЕМАЄ %s — сторінка %s не працюватиме\n' "$1" "$2"
    MISSING=1
  fi
}

copy index.html             index.html
copy pid-tryvohoyu.html     raiony.html
copy tryvoha-threats.html   drony.html
copy ukraine-alert-map.html oblasti.html
copy zbroya.html            zbroya.html
copy karta.html             karta.html
copy mapa.html              mapa.html
copy events.json            events.json
copy settlements.json       settlements.json
copy raiony_alerts.geojson  raiony_alerts.geojson

if [ -d data ]; then
  cp -r data site/data
  printf '  ✓ %-24s → %s\n' "data/" "data/ (відкриті дані)"
fi

# заборонити пошуковикам індексувати чернетку
cat > site/robots.txt <<'EOF'
User-agent: *
Allow: /
EOF

if [ "$MISSING" = "1" ]; then
  echo
  echo "Частини файлів немає. Завантаж їх у ~/tryvoha і запусти ще раз."
  echo "Продовжити все одно? [y/N]"
  read -r ans
  [ "$ans" = "y" ] || exit 1
fi

echo
echo "▸ Розмір site/: $(du -sh site | cut -f1)"
echo

if ! command -v node >/dev/null 2>&1; then
  echo "Node.js не встановлено — Netlify CLI не запуститься."
  echo "Або постав Node з nodejs.org, або задеплой вручну:"
  echo "  1. відкрий https://app.netlify.com/drop"
  echo "  2. перетягни туди папку ~/tryvoha/site"
  exit 0
fi

if [ "$1" = "--prod" ]; then
  echo "▸ Бойова публікація"
  npx --yes netlify-cli@17.38.1 deploy --dir=site --prod
else
  echo "▸ Чернетка (тимчасове посилання)"
  npx --yes netlify-cli@17.38.1 deploy --dir=site
fi
