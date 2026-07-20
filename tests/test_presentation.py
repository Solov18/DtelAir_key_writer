import unittest

from app.presentation import operation_status_name, operation_status_tone
from app.repositories.log_repository import normalize_operation_row


class PresentationTests(unittest.TestCase):
    def test_crm_statuses_are_human_readable(self):
        self.assertEqual(operation_status_name("SUCCESS"), "Успешно")
        self.assertEqual(
            operation_status_name("AUTH_REQUIRED"),
            "Требуется вход в CRM",
        )
        self.assertEqual(operation_status_name("HTTP_503"), "Ошибка CRM (HTTP 503)")
        self.assertEqual(operation_status_tone("AUTH_REQUIRED"), "error")
        self.assertEqual(operation_status_tone("DRY_RUN"), "warning")

    def test_old_message_action_is_translated(self):
        row = normalize_operation_row(
            {
                "action": "resident",
                "status": "SUCCESS",
                "printed_number": "40579",
            }
        )

        self.assertEqual(row["action_name"], "Из сообщения")
        self.assertEqual(row["status_name"], "Успешно")
        self.assertEqual(row["status_tone"], "success")


if __name__ == "__main__":
    unittest.main()
