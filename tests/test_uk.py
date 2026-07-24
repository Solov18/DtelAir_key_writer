import tempfile
import unittest
from pathlib import Path

import app.db as database
from app.repositories import uk_repository
from app.services.search import get_search_suggestions


class UkRepositoryTests(unittest.TestCase):
    def setUp(self):
        self._original_db_path = database.DB_PATH
        self._temporary_directory = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self._temporary_directory.name) / "test.db"
        database.init_db()

    def tearDown(self):
        database.DB_PATH = self._original_db_path
        self._temporary_directory.cleanup()

    def test_company_profile_and_punctuation_insensitive_search(self):
        group_id = uk_repository.save_group(
            name="УК Альфа-Сервис",
            legal_name="ООО «Альфа Сервис»",
            contact_name="Иванова Мария",
            phone="+7 (999) 123-45-67",
            email="office@alpha.ru",
            legal_address="г. Сочи, ул. Тепличная, 63",
            contract_number="Д-2026/15",
            created_by="Администратор",
            cooperation_status="negotiation",
            account_manager="Соловьёв Евгений",
            next_contact_at="2026-07-30T11:00",
            cooperation_note="Обсудить запуск уведомлений для собственников",
        )

        group = uk_repository.get_group(group_id)
        self.assertEqual(group["contact_name"], "Иванова Мария")
        self.assertEqual(group["contract_number"], "Д-2026/15")
        self.assertEqual(group["cooperation_status"], "negotiation")
        self.assertEqual(group["account_manager"], "Соловьёв Евгений")

        by_name = uk_repository.get_group_page(query="ук альфа сервис")
        by_phone = uk_repository.get_group_page(query="8 999 123 45 67")
        by_contract = uk_repository.get_group_page(query="д.2026-15")
        by_manager = uk_repository.get_group_page(query="соловьев, евгений")

        self.assertEqual(by_name["total"], 1)
        self.assertEqual(by_phone["total"], 1)
        self.assertEqual(by_contract["total"], 1)
        self.assertEqual(by_manager["total"], 1)

    def test_cooperation_pipeline_statistics_and_filter(self):
        uk_repository.save_group("УК Партнёр", cooperation_status="partner")
        uk_repository.save_group("УК Диалог", cooperation_status="contacted")
        uk_repository.save_group("УК Переговоры", cooperation_status="negotiation")
        uk_repository.save_group("УК Новый контакт", cooperation_status="potential")

        statistics = uk_repository.get_group_statistics()
        self.assertEqual(statistics["total"], 4)
        self.assertEqual(statistics["partners"], 1)
        self.assertEqual(statistics["in_progress"], 2)

        partners = uk_repository.get_group_page(cooperation_state="partner")
        negotiations = uk_repository.get_group_page(
            cooperation_state="negotiation"
        )
        invalid_filter = uk_repository.get_group_page(
            cooperation_state="configured"
        )

        self.assertEqual(partners["total"], 1)
        self.assertEqual(partners["items"][0]["name"], "УК Партнёр")
        self.assertEqual(negotiations["total"], 1)
        self.assertEqual(invalid_filter["total"], 4)

    def test_company_can_have_several_notification_drafts(self):
        group_id = uk_repository.save_group("УК Уведомления")

        first_id = uk_repository.save_notification_draft(
            group_id,
            "Плановые работы",
            "В среду с 10:00 до 12:00 будут проводиться работы.",
            category="works",
            channel="push",
            audience="address",
            audience_details="ул. Тепличная, 63",
            created_by="Администратор",
        )
        second_id = uk_repository.save_notification_draft(
            group_id,
            "Опрос собственников",
            "Выберите удобное время проведения собрания.",
            category="survey",
            channel="dtel",
            audience="all",
        )

        drafts = uk_repository.get_notification_drafts(group_id)
        self.assertEqual({item["id"] for item in drafts}, {first_id, second_id})
        self.assertEqual(
            {item["category"] for item in drafts},
            {"works", "survey"},
        )
        self.assertTrue(all(item["group_id"] == group_id for item in drafts))

        group = uk_repository.get_group(group_id)
        statistics = uk_repository.get_group_statistics()
        self.assertEqual(group["notification_drafts_count"], 2)
        self.assertEqual(statistics["notification_drafts"], 2)

    def test_suggestions_include_manager_and_notification_draft(self):
        group_id = uk_repository.save_group(
            "УК Поиск",
            contact_name="Петрова Анна",
            phone="+7 900 555-11-22",
            account_manager="Кузнецов Сергей",
        )
        uk_repository.save_notification_draft(
            group_id,
            "Отключение горячей воды",
            "Подача будет восстановлена после окончания работ.",
        )

        manager_suggestions = get_search_suggestions(
            "кузнецов",
            scope="uk",
        )
        draft_suggestions = get_search_suggestions(
            "отключение, горячей воды",
            scope="uk",
        )

        self.assertEqual(manager_suggestions[0]["value"], "УК Поиск")
        self.assertEqual(draft_suggestions[0]["value"], "УК Поиск")

    def test_notification_drafts_are_deleted_with_company(self):
        group_id = uk_repository.save_group("УК Удаление")
        uk_repository.save_notification_draft(
            group_id,
            "Тестовый черновик",
            "Этот текст не отправляется.",
        )

        uk_repository.delete_group(group_id)

        self.assertIsNone(uk_repository.get_group(group_id))
        self.assertEqual(uk_repository.get_notification_drafts(group_id), [])


if __name__ == "__main__":
    unittest.main()
