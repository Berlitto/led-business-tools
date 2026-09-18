# led-business-tools

Инструменты для LED-посреднического бизнеса в Баку (Азербайджан): компания
сводит клиентов, которым нужна реклама на LED-экранах, с владельцами этих
экранов (торговые центры, улицы, фасады зданий).

## Состав проекта

### `companies.md`

Список потенциальных партнёров/клиентов в Баку — рекламные агентства и
торговые центры с LED-экранами. Для каждой компании: телефон, статус
контакта, заметки. Ведётся вручную по мере обзвона.

### `email_bot/`

Бот, который читает новые письма в Gmail, отвечает на них через Claude API
от имени компании и логирует все диалоги. Полная инструкция по настройке —
в [`email_bot/README.md`](email_bot/README.md).

Коротко: Gmail API (OAuth) для чтения/отправки писем + Claude API
(`claude-opus-5`) с системным промптом менеджера LED-посреднической
компании + JSON Lines лог всех диалогов (`conversations.log.jsonl`).

## Установка

```bash
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Дальнейшая настройка (Gmail OAuth, ключ Claude API, `.env`) — в
[`email_bot/README.md`](email_bot/README.md).

## Структура репозитория

```
.
├── companies.md          # список компаний Баку для обзвона
├── requirements.txt       # зависимости Python (корень = email_bot)
├── .gitignore
└── email_bot/
    ├── bot.py             # основной скрипт бота
    ├── requirements.txt
    ├── .env.example       # шаблон переменных окружения
    ├── .gitignore
    └── README.md          # инструкция по настройке бота
```

## Секреты

`.env`, `credentials.json`, `token.json` и файлы логов в git не попадают
(см. `.gitignore`). Реальные ключи и токены хранить только локально.
