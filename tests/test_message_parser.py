import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app.db as database
from starlette.requests import Request

from app.repositories import panel_repository
from app.routers.message import message_write
from app.services.panels import find_panels_by_address
from app.services.parser import find_address_candidates, parse_message
from app.services.search import get_search_suggestions


class MessageParserTests(unittest.TestCase):
    def setUp(self):
        self._original_db_path = database.DB_PATH
        self._temporary_directory = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self._temporary_directory.name) / "test.db"
        database.init_db()

    def tearDown(self):
        database.DB_PATH = self._original_db_path
        self._temporary_directory.cleanup()

    @staticmethod
    def _create_panel(address: str, entrance: str, suffix: int) -> None:
        panel_repository.create_or_update_panel(
            address=address,
            entrance=entrance,
            mac=f"08:13:CD:00:10:{suffix:02X}",
        )

    def test_free_form_message_finds_address_apartment_keys_and_phone(self):
        self._create_panel(
            "Тепличная улица 65, корпус 1",
            "Подъезд 1",
            1,
        )
        self._create_panel(
            "Тепличная улица 65, корпус 1",
            "Подъезд 2",
            2,
        )

        parsed = parse_message(
            "Нужно прописать ключи №39107 и №39300.\n"
            "Сочи, ул. Тепличная, д.65 корп.1, квартира №10, подъезд 2.\n"
            "+7 (999) 000-00-00"
        )

        self.assertEqual(parsed["address"], "Тепличная улица 65, корпус 1")
        self.assertEqual(parsed["address_status"], "exact")
        self.assertEqual(parsed["apartment"], "10")
        self.assertEqual(parsed["entrance"], "2")
        self.assertEqual(parsed["key_numbers"], ["39107", "39300"])
        self.assertEqual(parsed["phones"], ["+7 (999) 000-00-00"])

    def test_typo_and_address_prefixes_still_offer_database_address(self):
        self._create_panel("пер. Рахманинова 35Д", "Основной вход", 3)
        self._create_panel("СТ Кипарис 11", "Калитка", 4)

        typo = parse_message(
            "Рахманинва д 35д, кв-ра 7. Ключ №40882"
        )
        self.assertEqual(typo["address"], "пер. Рахманинова 35Д")
        self.assertIn(typo["address_status"], {"exact", "similar"})

        prefix_free = parse_message(
            "Кипарис 11 кв. 4, прописать #40881"
        )
        self.assertEqual(prefix_free["address"], "СТ Кипарис 11")

    def test_house_letter_and_slash_are_recognized(self):
        self._create_panel(
            "Вин. 22/1В старая северная",
            "Старая северная",
            5,
        )

        parsed = parse_message(
            "Вин 22/1в, старая северная, квартира 15, ключ 40880"
        )
        self.assertEqual(
            parsed["address"],
            "Вин. 22/1В старая северная",
        )

    def test_missing_corpus_requires_confirmation_and_shows_variants(self):
        self._create_panel("Тепличная 63 корпус 1", "Подъезд 1", 6)
        self._create_panel("Тепличная 63 корпус 2", "Подъезд 2", 7)

        parsed = parse_message(
            "Тепличная 63, квартира 5, ключ №40879"
        )

        self.assertEqual(parsed["address"], "")
        self.assertEqual(parsed["address_status"], "needs_confirmation")
        self.assertEqual(
            {item["address"] for item in parsed["address_candidates"][:2]},
            {"Тепличная 63 корпус 1", "Тепличная 63 корпус 2"},
        )
        self.assertTrue(
            all(
                item["match_label"] == "Уточните корпус или строение"
                for item in parsed["address_candidates"][:2]
            )
        )

    def test_panel_selection_never_uses_partial_house_match(self):
        self._create_panel("Тестовая улица 3", "Подъезд 1", 8)
        self._create_panel("Тестовая улица 30", "Подъезд 1", 9)

        panels = find_panels_by_address("тестовая ул., д. 3")
        self.assertEqual(len(panels), 1)
        self.assertEqual(panels[0]["address"], "Тестовая улица 3")

    def test_similar_candidates_and_smart_search_ignore_punctuation(self):
        self._create_panel("Гагарина улица д.17", "Подъезд 1", 10)

        parsed = parse_message(
            "ключ 40882, гагарина, улица д17 кв.2",
        )
        candidates = parsed["address_candidates"]
        self.assertEqual(candidates[0]["address"], "Гагарина улица д.17")
        self.assertEqual(parsed["apartment"], "2")
        self.assertEqual(parsed["key_type"], "")

        suggestions = get_search_suggestions(
            "ГАГАРИНА, Д-17",
            scope="panels",
        )
        self.assertTrue(suggestions)
        self.assertEqual(suggestions[0]["value"], "Гагарина улица д.17")

    def test_message_write_never_falls_back_to_all_address_panels(self):
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/message/write",
                "headers": [],
                "client": ("127.0.0.1", 50000),
                "session": {
                    "user": {
                        "login": "test",
                        "full_name": "Тест",
                        "role": "admin",
                    }
                },
            }
        )

        with (
            patch(
                "app.routers.message.find_key",
                return_value={
                    "id": 1,
                    "number": "40882",
                    "hex_value": "363EE638",
                    "status": "free",
                },
            ),
            patch(
                "app.routers.message.is_ambiguous_key",
                return_value=False,
            ),
            patch("app.routers.message.write_key_to_panels") as writer,
        ):
            response = message_write(
                request=request,
                address="Гагарина улица д.17",
                apartment="7",
                source_text="Гагарина 17 кв.7 ключ 40882",
                key_numbers=["40882"],
                key_type_ids=[0],
                panel_ids=[],
            )

        writer.assert_not_called()
        self.assertIn(
            "не выбрана ни одна панель",
            response.body.decode("utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
