# Email-бот (Gmail + Claude API)

Бот читает новые письма в Gmail, отвечает на них через Claude API от имени
LED-посреднической компании в Азербайджане и логирует все диалоги в файл.

## Что нужно перед настройкой

- Python 3.10+
- Google-аккаунт с Gmail, на который будут приходить письма
- Ключ Claude API (Anthropic)

## 1. Установка зависимостей

```bash
cd email_bot
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Настройка Gmail API

1. Открыть [Google Cloud Console](https://console.cloud.google.com/) и создать
   новый проект (или выбрать существующий).
2. В меню **APIs & Services -> Library** найти **Gmail API** и включить его
   (Enable).
3. Перейти в **APIs & Services -> OAuth consent screen**, выбрать тип **External**
   (или **Internal**, если аккаунт в Google Workspace), заполнить обязательные
   поля (название приложения, email). На стадии тестирования добавить свой
   Gmail-адрес в **Test users**.
4. Перейти в **APIs & Services -> Credentials -> Create Credentials -> OAuth
   client ID**, выбрать тип приложения **Desktop app**, дать название.
5. Скачать JSON-файл с credentials, переименовать его в `credentials.json` и
   положить в папку `email_bot/` (рядом с `bot.py`).

Файл `credentials.json` — секретный, в `.gitignore` он уже исключён.

## 3. Настройка Claude API

1. Зарегистрироваться / войти в [console.anthropic.com](https://console.anthropic.com/).
2. Создать ключ в **Settings -> API Keys**.
3. Сохранить ключ — он понадобится на следующем шаге.

## 4. Переменные окружения

```bash
cp .env.example .env
```

Открыть `.env` и заполнить:

| Переменная | Значение |
|---|---|
| `ANTHROPIC_API_KEY` | ключ Claude API из шага 3 |
| `GMAIL_CREDENTIALS_PATH` | путь к `credentials.json` (по умолчанию `credentials.json`) |
| `GMAIL_TOKEN_PATH` | путь, куда бот сохранит токен доступа после первой авторизации (по умолчанию `token.json`) |
| `GMAIL_PROCESSED_LABEL` | название ярлыка Gmail для уже обработанных писем (по умолчанию `AI-Handled`) |
| `POLL_INTERVAL_SECONDS` | как часто проверять новые письма, в секундах (по умолчанию `60`) |
| `CONVERSATIONS_LOG_PATH` | файл для лога диалогов (по умолчанию `conversations.log.jsonl`) |
| `COMPANY_NAME` | название вашей компании — подставляется в системный промпт Claude |

`.env` в `.gitignore` — коммитить его не нужно.

## 5. Первый запуск

```bash
python bot.py
```

При первом запуске откроется браузер с запросом авторизации Gmail —
нужно войти под тем аккаунтом, куда приходят письма, и разрешить доступ
(scope `gmail.modify`: чтение, отправка, изменение ярлыков). После этого
рядом появится `token.json` — бот будет использовать его при следующих
запусках без повторной авторизации (токен обновляется автоматически).

Дальше бот в бесконечном цикле:

1. Ищет непрочитанные письма во входящих без ярлыка `AI-Handled`.
2. Отправляет текст письма в Claude API и получает ответ.
3. Отвечает в том же треде (заголовки `In-Reply-To` / `References`).
4. Помечает письмо ярлыком `AI-Handled` и снимает статус "непрочитано".
5. Записывает диалог в `conversations.log.jsonl`.
6. Засыпает на `POLL_INTERVAL_SECONDS` и повторяет.

Остановить — `Ctrl+C`.

## Формат лога диалогов

Каждая строка `conversations.log.jsonl` — отдельный JSON-объект:

```json
{
  "timestamp": "2026-09-18T10:15:00+00:00",
  "message_id": "18d2f...",
  "from": "Имя Клиента <client@example.com>",
  "subject": "Реклама на LED-экране",
  "incoming_body": "Текст письма клиента...",
  "reply": "Текст ответа бота...",
  "status": "sent"
}
```

При ошибке (сбой Claude API, Gmail API и т.д.) `status` будет `"error"`, а
`reply` — `null`, с дополнительным полем `error`.

## Настройка поведения бота

Текст, которым бот представляется и правила ответа, задаются в
`SYSTEM_PROMPT` в `bot.py` — его можно редактировать напрямую под свою
компанию: ассортимент экранов, тон общения, что можно и нельзя обещать
клиенту.

## Частые проблемы

- **`FileNotFoundError: credentials.json`** — файл не скачан из Google Cloud
  Console или лежит не в той папке (см. шаг 2.5).
- **Ошибка `access_denied` при авторизации** — Gmail-аккаунт не добавлен в
  **Test users** на экране OAuth consent (см. шаг 2.3), пока приложение не
  прошло верификацию Google.
- **Бот не видит новые письма** — проверить, что письмо действительно
  непрочитанное и лежит во «Входящих», а не в архиве/спаме.
- **`anthropic.AuthenticationError`** — неверный или не заполненный
  `ANTHROPIC_API_KEY` в `.env`.
