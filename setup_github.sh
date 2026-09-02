#!/bin/bash
# Готує репозиторій для автооновлення: створює структуру, .gitignore,
# стискає базу й показує, які секрети треба завести.
#
#   ./setup_github.sh
#
# Нічого нікуди не надсилає — тільки готує файли й друкує інструкцію.

set -e
cd "$(dirname "$0")"

echo "▸ Структура репозиторію"
mkdir -p .github/workflows
[ -f update-data.yml ] && mv update-data.yml .github/workflows/update-data.yml
[ -f .github/workflows/update-data.yml ] \
  && echo "  ✓ .github/workflows/update-data.yml" \
  || { echo "  ✗ немає update-data.yml — завантаж його спершу"; exit 1; }

cat > .gitignore <<'EOF'
# База завелика для git — вона живе в кеші GitHub Actions
# і в релізі seed як початковий знімок
messages.db
messages.db.gz
*.session
*.session-journal
venv/
__pycache__/
site/
.DS_Store

# Згенеровані сторінки — їх щоразу перебудовує workflow
tryvoha-threats.html
zbroya.html
karta.html
mapa.html
events.json
settlements.json
EOF
echo "  ✓ .gitignore"

cat > README.md <<'EOF'
# Під тривогою

Відкриті дані про повітряну загрозу в Україні.
Сайт: https://pid-tryvohoyu.netlify.app

## Що всередині

| Скрипт | Що робить |
|---|---|
| `scraper.py` | Первинна викачка історії каналів (MTProto, чекпойнти) |
| `update.py` | Докачує лише нові повідомлення — запускається за розкладом |
| `parse_kpszsu.py` | Розбирає зведення Повітряних Сил |
| `extract_all.py` | Витягує події з усіх каналів через довідник НП |
| `geocode.py` | Прив'язка назв до координат з українською морфологією |
| `build_*.py` | Збирають сторінки сайту |
| `export_data.py` | Викладає агрегати у CSV (тека `data/`) |

## Дані

Теку `data/` оновлює workflow щопонеділка. Ліцензія CC BY 4.0.
Опис файлів і застереження — у `data/README.md`.

## Автооновлення

`.github/workflows/update-data.yml` щотижня докачує канали,
перебудовує сторінки й публікує їх на Netlify.
База лежить у кеші Actions; початковий знімок — у релізі `seed`.
EOF
echo "  ✓ README.md"

echo
echo "▸ Стискаю базу для релізу"
if [ -f messages.db ]; then
  gzip -kf messages.db
  echo "  messages.db      $(du -h messages.db | cut -f1)"
  echo "  messages.db.gz   $(du -h messages.db.gz | cut -f1)  ← це вантажити в реліз"
else
  echo "  ✗ messages.db не знайдено"
fi

echo
echo "▸ Значення для секретів (скопіюй, нікому не показуй)"
echo
echo "TG_SESSION_B64:"
if [ -f scraper.session ]; then
  base64 -i scraper.session | tr -d '\n' | pbcopy 2>/dev/null \
    && echo "  скопійовано в буфер обміну ✓" \
    || base64 -i scraper.session | head -c 80 && echo "…"
else
  echo "  ✗ scraper.session не знайдено"
fi
echo
echo "NETLIFY_SITE_ID:"
echo "  46ba287f-913c-4172-9c89-f5d6094b0e09"
echo
echo "TG_API_ID / TG_API_HASH: візьми з run.sh"
echo "NETLIFY_AUTH_TOKEN: Netlify → User settings → Applications → New access token"
echo
echo "Далі — інструкція в GITHUB_SETUP.md"
