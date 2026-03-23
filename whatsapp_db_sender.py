from __future__ import annotations

import argparse
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

if TYPE_CHECKING:
    from selenium.webdriver.remote.webdriver import WebDriver

DEFAULT_DB_PATH = Path("whatsapp_messages.db")
DEFAULT_PROFILE_DIR = Path("chrome-profile")
PENDING_STATUS = "pending"
PROCESSING_STATUS = "processing"
SENT_STATUS = "sent"
FAILED_STATUS = "failed"
VALID_STATUSES = {PENDING_STATUS, PROCESSING_STATUS, SENT_STATUS, FAILED_STATUS}

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS outbound_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone TEXT NOT NULL,
    message TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sent_at TEXT,
    error_message TEXT
);
""".strip()


@dataclass(frozen=True)
class OutboundMessage:
    id: int
    phone: str
    message: str


class WhatsAppAutomationError(RuntimeError):
    """Raised when WhatsApp Web automation fails."""


class InvalidOutboundMessageError(ValueError):
    """Raised when a phone or message is invalid before inserting in the DB."""


def sanitize_phone(raw_phone: str) -> str:
    digits = "".join(character for character in raw_phone if character.isdigit())
    if len(digits) < 8:
        return ""
    return digits


def build_whatsapp_url(phone: str, message: str) -> str:
    encoded_message = quote(message)
    return f"https://web.whatsapp.com/send?phone={phone}&text={encoded_message}"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect_database(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def ensure_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA_SQL)
    connection.commit()


def validate_outbound_message(phone: str, message: str) -> tuple[str, str]:
    sanitized_phone = sanitize_phone(phone)
    if not sanitized_phone:
        raise InvalidOutboundMessageError("Número inválido o incompleto.")

    normalized_message = message.strip()
    if not normalized_message:
        raise InvalidOutboundMessageError("El mensaje no puede estar vacío.")

    return sanitized_phone, normalized_message


def insert_outbound_message(
    connection: sqlite3.Connection,
    phone: str,
    message: str,
    status: str = PENDING_STATUS,
) -> int:
    if status not in VALID_STATUSES:
        raise InvalidOutboundMessageError(f"Estado no soportado: {status}")

    sanitized_phone, normalized_message = validate_outbound_message(phone, message)
    cursor = connection.execute(
        """
        INSERT INTO outbound_messages (phone, message, status)
        VALUES (?, ?, ?)
        """,
        (sanitized_phone, normalized_message, status),
    )
    connection.commit()
    return int(cursor.lastrowid)


def insert_messages_from_lines(connection: sqlite3.Connection, lines: list[str]) -> list[int]:
    inserted_ids: list[int] = []
    for index, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            continue
        if "|" not in line:
            raise InvalidOutboundMessageError(
                f"La línea {index} no tiene el formato esperado numero|mensaje."
            )
        phone, message = line.split("|", 1)
        inserted_ids.append(insert_outbound_message(connection, phone, message))
    return inserted_ids


def list_outbound_messages(connection: sqlite3.Connection, limit: int = 50) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT id, phone, message, status, created_at, sent_at, error_message
        FROM outbound_messages
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


def seed_example_messages(connection: sqlite3.Connection) -> None:
    total = connection.execute("SELECT COUNT(*) FROM outbound_messages").fetchone()[0]
    if total:
        return

    insert_outbound_message(
        connection,
        "+52 1 55 1234 5678",
        "Hola Ana, este mensaje salió desde la base de datos.",
    )
    insert_outbound_message(
        connection,
        "+1 (555) 987-6543",
        "Hola John, tu recordatorio fue preparado desde SQLite.",
    )


def fetch_pending_messages(connection: sqlite3.Connection, limit: int) -> list[OutboundMessage]:
    rows = connection.execute(
        """
        SELECT id, phone, message
        FROM outbound_messages
        WHERE status = ?
        ORDER BY id ASC
        LIMIT ?
        """,
        (PENDING_STATUS, limit),
    ).fetchall()

    messages: list[OutboundMessage] = []
    for row in rows:
        try:
            sanitized_phone, message_text = validate_outbound_message(row["phone"], row["message"])
        except InvalidOutboundMessageError as exc:
            mark_failed(connection, row["id"], str(exc))
            continue
        messages.append(
            OutboundMessage(
                id=row["id"],
                phone=sanitized_phone,
                message=message_text,
            )
        )
    return messages


def mark_processing(connection: sqlite3.Connection, message_id: int) -> None:
    connection.execute(
        "UPDATE outbound_messages SET status = ?, error_message = NULL WHERE id = ?",
        (PROCESSING_STATUS, message_id),
    )
    connection.commit()


def mark_sent(connection: sqlite3.Connection, message_id: int) -> None:
    connection.execute(
        """
        UPDATE outbound_messages
        SET status = ?, sent_at = ?, error_message = NULL
        WHERE id = ?
        """,
        (SENT_STATUS, utc_now(), message_id),
    )
    connection.commit()


def mark_failed(connection: sqlite3.Connection, message_id: int, error_message: str) -> None:
    connection.execute(
        """
        UPDATE outbound_messages
        SET status = ?, error_message = ?
        WHERE id = ?
        """,
        (FAILED_STATUS, error_message[:500], message_id),
    )
    connection.commit()


def create_driver(profile_dir: Path, chrome_binary: str | None = None) -> "WebDriver":
    from selenium import webdriver

    options = webdriver.ChromeOptions()
    options.add_argument("--start-maximized")
    options.add_argument(f"--user-data-dir={profile_dir.resolve()}")
    options.add_experimental_option("detach", True)
    if chrome_binary:
        options.binary_location = chrome_binary

    return webdriver.Chrome(options=options)


def wait_for_login(driver: "WebDriver", timeout_seconds: int) -> None:
    from selenium.webdriver.common.by import By

    driver.get("https://web.whatsapp.com/")
    deadline = time.time() + timeout_seconds
    qr_notice_shown = False

    while time.time() < deadline:
        if driver.find_elements(By.ID, "pane-side"):
            return

        qr_codes = driver.find_elements(By.XPATH, "//canvas")
        if qr_codes and not qr_notice_shown:
            print(
                "[INFO] WhatsApp Web requiere inicio de sesión. Escanea el código QR en Chrome y espera..."
            )
            qr_notice_shown = True

        time.sleep(2)

    raise WhatsAppAutomationError(
        "No se detectó una sesión activa en WhatsApp Web dentro del tiempo esperado."
    )


def find_send_button(driver: "WebDriver"):
    from selenium.webdriver.common.by import By

    selectors = [
        "//button[.//span[@data-icon='send']]",
        "//div[@role='button'][.//span[@data-icon='send']]",
        "//span[@data-icon='send']/ancestor::button[1]",
        "//span[@data-icon='send']/ancestor::div[@role='button'][1]",
    ]

    for selector in selectors:
        elements = driver.find_elements(By.XPATH, selector)
        if elements:
            return elements[0]
    return None


def send_message(driver: "WebDriver", outbound_message: OutboundMessage, wait_seconds: int) -> None:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support.ui import WebDriverWait

    url = build_whatsapp_url(outbound_message.phone, outbound_message.message)
    driver.get(url)

    wait = WebDriverWait(driver, wait_seconds)
    try:
        send_button = wait.until(lambda current_driver: find_send_button(current_driver))
        send_button.click()
        time.sleep(2)
        return
    except Exception:
        pass

    try:
        message_box = wait.until(
            lambda current_driver: current_driver.find_element(
                By.XPATH, "//div[@contenteditable='true'][@role='textbox']"
            )
        )
        message_box.send_keys(Keys.ENTER)
        time.sleep(2)
        return
    except Exception as exc:
        raise WhatsAppAutomationError(
            f"No se pudo enviar el mensaje al número {outbound_message.phone}."
        ) from exc


def process_pending_messages(
    db_path: Path,
    profile_dir: Path,
    limit: int,
    wait_seconds: int,
    chrome_binary: str | None,
) -> int:
    connection = connect_database(db_path)
    ensure_schema(connection)
    messages = fetch_pending_messages(connection, limit)

    if not messages:
        print("[INFO] No hay mensajes pendientes por enviar.")
        connection.close()
        return 0

    try:
        driver = create_driver(profile_dir=profile_dir, chrome_binary=chrome_binary)
    except ModuleNotFoundError as exc:
        connection.close()
        raise WhatsAppAutomationError(
            "Falta la dependencia 'selenium'. Instala requirements.txt antes de ejecutar el envío."
        ) from exc

    try:
        wait_for_login(driver, timeout_seconds=wait_seconds)
        sent_count = 0
        for outbound_message in messages:
            mark_processing(connection, outbound_message.id)
            try:
                send_message(driver, outbound_message, wait_seconds=wait_seconds)
                mark_sent(connection, outbound_message.id)
                sent_count += 1
                print(f"[OK] Mensaje enviado al {outbound_message.phone} (id={outbound_message.id}).")
            except Exception as exc:
                mark_failed(connection, outbound_message.id, str(exc))
                print(f"[ERROR] Falló el envío del id={outbound_message.id}: {exc}")
        return sent_count
    finally:
        driver.quit()
        connection.close()


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Lee mensajes pendientes desde una base SQLite, abre WhatsApp Web en Chrome y envía el texto al número guardado en la base de datos."
        )
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="Ruta del archivo SQLite.")
    parser.add_argument(
        "--profile-dir",
        type=Path,
        default=DEFAULT_PROFILE_DIR,
        help="Carpeta de perfil de Chrome para conservar la sesión de WhatsApp Web.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Cantidad máxima de mensajes pendientes a procesar por ejecución.",
    )
    parser.add_argument(
        "--wait-seconds",
        type=int,
        default=90,
        help="Segundos máximos para esperar carga/login en WhatsApp Web.",
    )
    parser.add_argument(
        "--chrome-binary",
        default=None,
        help="Ruta opcional de chrome.exe si Selenium no lo detecta automáticamente.",
    )
    parser.add_argument(
        "--init-db",
        action="store_true",
        help="Crea la tabla requerida si no existe.",
    )
    parser.add_argument(
        "--seed-example",
        action="store_true",
        help="Inserta mensajes de ejemplo en la base de datos si está vacía.",
    )
    return parser


def main() -> None:
    parser = build_argument_parser()
    args = parser.parse_args()

    connection = connect_database(args.db)
    ensure_schema(connection)

    if args.seed_example:
        seed_example_messages(connection)
        print(f"[OK] Base de datos de ejemplo lista en {args.db}.")

    connection.close()

    if args.init_db and not args.seed_example:
        print(f"[OK] Estructura validada en {args.db}.")
        return

    process_pending_messages(
        db_path=args.db,
        profile_dir=args.profile_dir,
        limit=args.limit,
        wait_seconds=args.wait_seconds,
        chrome_binary=args.chrome_binary,
    )


if __name__ == "__main__":
    main()
