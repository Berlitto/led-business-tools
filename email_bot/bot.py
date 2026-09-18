"""
Email-бот: читает новые письма в Gmail, отвечает на них через Claude API
от имени LED-посреднической компании в Азербайджане, логирует диалоги.

Настройка перед запуском:
  1. pip install -r requirements.txt
  2. Скопировать .env.example -> .env и заполнить значения
  3. Положить OAuth credentials.json (Google Cloud Console) в путь из
     GMAIL_CREDENTIALS_PATH
  4. Первый запуск откроет браузер для авторизации Gmail и создаст
     token.json (путь из GMAIL_TOKEN_PATH)
"""

import base64
import json
import logging
import os
import time
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.utils import parseaddr

import anthropic
from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# --- Конфигурация (значения берутся из .env, см. .env.example) ---

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "YOUR_ANTHROPIC_API_KEY_HERE")
CLAUDE_MODEL = "claude-opus-5"

GMAIL_CREDENTIALS_PATH = os.environ.get("GMAIL_CREDENTIALS_PATH", "credentials.json")
GMAIL_TOKEN_PATH = os.environ.get("GMAIL_TOKEN_PATH", "token.json")
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
GMAIL_PROCESSED_LABEL = os.environ.get("GMAIL_PROCESSED_LABEL", "AI-Handled")

POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "60"))
CONVERSATIONS_LOG_PATH = os.environ.get("CONVERSATIONS_LOG_PATH", "conversations.log.jsonl")
COMPANY_NAME = os.environ.get("COMPANY_NAME", "YOUR_COMPANY_NAME_HERE")

# Письма от адресов, содержащих любую из этих подстрок, пропускаются без
# ответа через Claude API (автоматические/системные рассылки).
SKIPPED_SENDER_SUBSTRINGS = ("no-reply", "noreply", "mailer-daemon")

SYSTEM_PROMPT = f"""Ты — менеджер по продажам компании "{COMPANY_NAME}",
LED-посреднической компании в Азербайджане (Баку). Компания сводит клиентов,
которым нужна реклама на LED-экранах (торговые центры, улицы, фасады
зданий), с владельцами этих экранов, и организует размещение рекламы под
ключ: подбор локаций, согласование сроков и форматов, изготовление
контента, размещение.

Правила ответа на входящее письмо:
- Отвечай на том же языке, на котором написано письмо (русский,
  азербайджанский или английский).
- Тон — деловой, доброжелательный, без излишней формальности.
- Если в письме не хватает деталей для расчёта (бюджет, желаемые локации,
  сроки размещения, формат ролика/баннера), задай уточняющие вопросы.
- Не называй точные цены и не давай финальных коммерческих обязательств —
  предлагай уточнить детали и/или созвониться с менеджером.
- Не выдумывай факты о компании, экранах или ценах, которых нет в письме
  или в этом системном промпте.
- Ответ должен быть коротким и по делу — как обычное деловое письмо, без
  markdown-разметки.
"""

anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


# --- Gmail: авторизация ---

def get_gmail_service():
    creds = None
    if os.path.exists(GMAIL_TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(GMAIL_TOKEN_PATH, GMAIL_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(GMAIL_CREDENTIALS_PATH, GMAIL_SCOPES)
            creds = flow.run_local_server(port=0)
        with open(GMAIL_TOKEN_PATH, "w") as token_file:
            token_file.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def get_bot_email_address(service) -> str:
    profile = service.users().getProfile(userId="me").execute()
    return profile["emailAddress"].lower()


def get_or_create_label_id(service, label_name: str) -> str:
    labels = service.users().labels().list(userId="me").execute().get("labels", [])
    for label in labels:
        if label["name"] == label_name:
            return label["id"]

    created = service.users().labels().create(
        userId="me",
        body={
            "name": label_name,
            "labelListVisibility": "labelShow",
            "messageListVisibility": "show",
        },
    ).execute()
    return created["id"]


# --- Gmail: чтение писем ---

def list_new_message_ids(service, processed_label_id: str) -> list[str]:
    query = f"is:unread in:inbox -label:{GMAIL_PROCESSED_LABEL}"
    response = service.users().messages().list(userId="me", q=query).execute()
    return [m["id"] for m in response.get("messages", [])]


def _decode_body(payload: dict) -> str:
    if payload.get("mimeType") == "text/plain" and "data" in payload.get("body", {}):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

    for part in payload.get("parts", []):
        text = _decode_body(part)
        if text:
            return text

    return ""


def get_message_details(service, msg_id: str) -> dict:
    message = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
    headers = {h["name"]: h["value"] for h in message["payload"]["headers"]}

    return {
        "id": msg_id,
        "thread_id": message["threadId"],
        "from": headers.get("From", ""),
        "subject": headers.get("Subject", "(без темы)"),
        "message_id_header": headers.get("Message-ID", ""),
        "references": headers.get("References", ""),
        "body": _decode_body(message["payload"]).strip(),
    }


def should_skip_sender(sender: str, bot_email: str) -> bool:
    sender_address = parseaddr(sender)[1].lower()
    if not sender_address:
        return False
    if sender_address == bot_email:
        return True
    return any(substring in sender_address for substring in SKIPPED_SENDER_SUBSTRINGS)


# --- Claude: генерация ответа ---

def generate_reply(subject: str, body: str, sender: str) -> str:
    user_message = f"Тема письма: {subject}\nОтправитель: {sender}\n\nТекст письма:\n{body}"

    try:
        response = anthropic_client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
    except anthropic.RateLimitError as e:
        retry_after = int(e.response.headers.get("retry-after", "60"))
        raise RuntimeError(f"Claude API: превышен лимит запросов, повтор через {retry_after}с") from e
    except anthropic.APIStatusError as e:
        raise RuntimeError(f"Claude API: ошибка {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise RuntimeError("Claude API: ошибка сети") from e

    return next((b.text for b in response.content if b.type == "text"), "").strip()


# --- Gmail: отправка ответа ---

def send_reply(service, original: dict, reply_text: str) -> None:
    to_address = parseaddr(original["from"])[1]

    mime_message = MIMEText(reply_text)
    mime_message["To"] = to_address
    mime_message["Subject"] = "Re: " + original["subject"]
    if original["message_id_header"]:
        mime_message["In-Reply-To"] = original["message_id_header"]
        mime_message["References"] = (original["references"] + " " + original["message_id_header"]).strip()

    raw = base64.urlsafe_b64encode(mime_message.as_bytes()).decode("utf-8")

    service.users().messages().send(
        userId="me",
        body={"raw": raw, "threadId": original["thread_id"]},
    ).execute()


def mark_as_processed(service, msg_id: str, processed_label_id: str) -> None:
    service.users().messages().modify(
        userId="me",
        id=msg_id,
        body={"removeLabelIds": ["UNREAD"], "addLabelIds": [processed_label_id]},
    ).execute()


# --- Логирование диалогов ---

def log_conversation(entry: dict) -> None:
    entry_with_timestamp = {"timestamp": datetime.now(timezone.utc).isoformat(), **entry}
    with open(CONVERSATIONS_LOG_PATH, "a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(entry_with_timestamp, ensure_ascii=False) + "\n")


# --- Основной цикл ---

def process_new_messages(service, processed_label_id: str, bot_email: str) -> None:
    for msg_id in list_new_message_ids(service, processed_label_id):
        message = get_message_details(service, msg_id)

        if should_skip_sender(message["from"], bot_email):
            mark_as_processed(service, msg_id, processed_label_id)
            log_conversation({
                "message_id": msg_id,
                "from": message["from"],
                "subject": message["subject"],
                "incoming_body": message["body"],
                "reply": None,
                "status": "skipped",
            })
            continue

        try:
            reply_text = generate_reply(message["subject"], message["body"], message["from"])
            send_reply(service, message, reply_text)
            mark_as_processed(service, msg_id, processed_label_id)

            log_conversation({
                "message_id": msg_id,
                "from": message["from"],
                "subject": message["subject"],
                "incoming_body": message["body"],
                "reply": reply_text,
                "status": "sent",
            })
        except Exception as e:
            log_conversation({
                "message_id": msg_id,
                "from": message["from"],
                "subject": message["subject"],
                "incoming_body": message["body"],
                "reply": None,
                "status": "error",
                "error": str(e),
            })


def main() -> None:
    service = get_gmail_service()
    processed_label_id = get_or_create_label_id(service, GMAIL_PROCESSED_LABEL)
    bot_email = get_bot_email_address(service)

    while True:
        try:
            process_new_messages(service, processed_label_id, bot_email)
        except Exception:
            logger.exception("Непредвиденная ошибка в основном цикле")

        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
