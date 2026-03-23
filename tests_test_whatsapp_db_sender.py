import tempfile
import unittest
from pathlib import Path

from whatsapp_db_sender import (
    FAILED_STATUS,
    PENDING_STATUS,
    SENT_STATUS,
    build_whatsapp_url,
    connect_database,
    ensure_schema,
    fetch_pending_messages,
    insert_messages_from_lines,
    insert_outbound_message,
    list_outbound_messages,
    mark_failed,
    mark_sent,
    sanitize_phone,
    seed_example_messages,
)


class WhatsAppDbSenderTests(unittest.TestCase):
    def test_sanitize_phone_keeps_only_digits(self) -> None:
        self.assertEqual(sanitize_phone("+52 1 55 1234 5678"), "5215512345678")
        self.assertEqual(sanitize_phone("abc"), "")

    def test_build_whatsapp_url_encodes_message(self) -> None:
        url = build_whatsapp_url("5215512345678", "Hola mundo")
        self.assertEqual(
            url,
            "https://web.whatsapp.com/send?phone=5215512345678&text=Hola%20mundo",
        )

    def test_manual_insert_and_list_messages(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "manual.db"
            connection = connect_database(db_path)
            ensure_schema(connection)

            first_id = insert_outbound_message(connection, "+52 1 55 1234 5678", "Hola manual")
            inserted_ids = insert_messages_from_lines(
                connection,
                [
                    "5213312345678|Hola por lote",
                    "15559876543|Segundo mensaje",
                ],
            )

            rows = list_outbound_messages(connection, limit=10)
            self.assertEqual(first_id, rows[-1]["id"])
            self.assertEqual(len(inserted_ids), 2)
            self.assertEqual(rows[0]["status"], PENDING_STATUS)
            self.assertEqual(rows[0]["phone"], "15559876543")
            connection.close()

    def test_schema_seed_and_status_updates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "messages.db"
            connection = connect_database(db_path)
            ensure_schema(connection)
            seed_example_messages(connection)

            pending = fetch_pending_messages(connection, limit=10)
            self.assertTrue(pending)
            self.assertTrue(all(message.message for message in pending))

            first_message = pending[0]
            mark_sent(connection, first_message.id)
            sent_row = connection.execute(
                "SELECT status, sent_at FROM outbound_messages WHERE id = ?",
                (first_message.id,),
            ).fetchone()
            self.assertEqual(sent_row["status"], SENT_STATUS)
            self.assertIsNotNone(sent_row["sent_at"])

            second_message = pending[1]
            mark_failed(connection, second_message.id, "Fallo controlado")
            failed_row = connection.execute(
                "SELECT status, error_message FROM outbound_messages WHERE id = ?",
                (second_message.id,),
            ).fetchone()
            self.assertEqual(failed_row["status"], FAILED_STATUS)
            self.assertEqual(failed_row["error_message"], "Fallo controlado")
            connection.close()


if __name__ == "__main__":
    unittest.main()
