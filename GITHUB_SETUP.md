# Налаштування автооновлення

Одноразова процедура. Далі сайт оновлюється щопонеділка сам.

---

## 1. Підготувати теку

```bash
cd ~/tryvoha
mv ~/Downloads/setup_github.sh ~/Downloads/update-data.yml .
chmod +x setup_github.sh
./setup_github.sh
```

Скрипт створить `.github/workflows/`, `.gitignore`, `README.md`, стисне базу
в `messages.db.gz` і покаже значення для секретів. Сесію Telegram у base64 він
одразу покладе в буфер обміну — не втрать її, вона знадобиться на кроці 4.

---

## 2. Створити репозиторій і залити код

Потрібен GitHub CLI:

```bash
brew install gh
gh auth login
```

Далі:

```bash
cd ~/tryvoha
git init -b main
git add .
git commit -m "Під тривогою — карти та дані про повітряну загрозу"
gh repo create pid-tryvohoyu --public --source=. --push
```

База й сесія не поїдуть — вони в `.gitignore`.

---

## 3. Залити базу в реліз

База завелика для git, тому кладемо її окремим файлом у реліз.
Workflow візьме її звідти при першому запуску, далі триматиме в кеші.

```bash
gh release create seed messages.db.gz \
  --title "Початковий знімок бази" \
  --notes "Знімок повідомлень каналів. Оновлюється автоматично в кеші Actions."
```

Якщо файл більший за 2 ГБ — GitHub не прийме. Тоді ріж базу по каналах
або клади на будь-який хостинг і заміни крок «Завантажити базу з релізу»
на `curl`.

---

## 4. Завести секрети

```bash
gh secret set TG_API_ID
gh secret set TG_API_HASH
gh secret set TG_SESSION_B64
gh secret set NETLIFY_SITE_ID
gh secret set NETLIFY_AUTH_TOKEN
```

Кожна команда запитає значення й сховає введене. Що вводити:

| Секрет | Звідки взяти |
|---|---|
| `TG_API_ID` | з `run.sh` |
| `TG_API_HASH` | з `run.sh` |
| `TG_SESSION_B64` | у буфері після `setup_github.sh`; або `base64 -i scraper.session \| pbcopy` |
| `NETLIFY_SITE_ID` | `46ba287f-913c-4172-9c89-f5d6094b0e09` |
| `NETLIFY_AUTH_TOKEN` | Netlify → аватар → User settings → Applications → New access token |

Перевірити, що всі п'ять на місці:

```bash
gh secret list
```

---

## 5. Запустити вручну й подивитися

```bash
gh workflow run "Оновлення даних"
sleep 15
gh run watch
```

Перший запуск довший: качає базу з релізу. Далі бере з кешу.

Якщо впаде — дивись, на якому кроці:

```bash
gh run view --log-failed
```

---

## Що робить workflow

Щопонеділка о 07:00 за Києвом:

1. дістає базу з кешу (перший раз — з релізу `seed`)
2. відновлює сесію Telegram із секрету
3. `update.py` докачує лише нові повідомлення
4. перебирає їх: `parse_kpszsu.py` → `geocode_threats.py` → `extract_all.py`
5. перебудовує всі сторінки
6. публікує на Netlify
7. комітить свіжі CSV у теку `data/`
8. зберігає оновлену базу в кеш

---

## Часті проблеми

**«messages.db відсутня»** — реліз `seed` не створено або назва файлу інша.
Перевір: `gh release view seed`.

**«порожня сесія»** — секрет `TG_SESSION_B64` записаний з переносами рядків.
Перезапиши: `base64 -i scraper.session | tr -d '\n' | gh secret set TG_SESSION_B64`.

**Telegram просить код при кожному запуску** — сесія протухла.
Перегенеруй локально (`python update.py`), потім залий заново.

**Кеш зник** — GitHub видаляє записи, до яких не зверталися 7 днів.
Щотижневий розклад тримає його живим, але після довгої паузи workflow
знову візьме базу з релізу. Це нормально, просто повільніше.

**Netlify каже про ліміт** — безкоштовний тариф дає 100 ГБ трафіку
й 300 хвилин збірки на місяць. Одна публікація на тиждень з'їдає
частки відсотка.
