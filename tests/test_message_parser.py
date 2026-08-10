import json
from unittest.mock import patch

from starlette.requests import Request

from tests.postgres_test_case import PostgreSQLTestCase

from app.repositories import key_repository, panel_repository
from app.routers.message import _build_key_rows, message_write
from app.services.keys import find_keys
from app.services.panels import find_panels_by_address
from app.services.parser import find_address_candidates, parse_message
from app.services.search import get_search_suggestions


class MessageParserTests(PostgreSQLTestCase):
    def setUp(self):
        super().setUp()

    @staticmethod
    def _create_panel(address: str, entrance: str, suffix: int) -> None:
        panel_repository.create_or_update_panel(
            address=address,
            entrance=entrance,
            mac=f"08:13:CD:00:10:{suffix:02X}",
        )

    @staticmethod
    def _create_type(name: str, color: str = "#2299EE") -> int:
        return key_repository.create_key_type(name, color)

    def test_typed_key_is_never_substituted_by_same_number_of_other_type(self):
        orange_id = self._create_type("Оранжевый", "#FF982A")
        self._create_type("Бесплатный розовый", "#EE77AA")
        key_repository.save_prepared_key(orange_id, "001185", "AABBCCDD")

        parsed = parse_message("Ключ: Бесплатный розовый — 001185")
        rows = _build_key_rows(parsed["key_requests"])

        self.assertEqual(parsed["key_numbers"], ["001185"])
        self.assertEqual(parsed["key_requests"][0]["type_name"], "Бесплатный розовый")
        self.assertEqual(parsed["key_requests"][0]["number"], "001185")
        self.assertIsNone(rows[0]["item"])
        self.assertFalse(rows[0]["ambiguous"])

    def test_multiple_typed_keys_are_parsed_with_leading_zeroes(self):
        self._create_type("Оранжевый", "#FF982A")
        self._create_type("Уникальный", "#22B889")
        self._create_type("Стикер", "#9B72E8")

        parsed = parse_message(
            "Ключи: оранжевый 001185, уникальный 112, стикер 00341"
        )

        self.assertEqual(
            [(item["type_name"], item["number"]) for item in parsed["key_requests"]],
            [("Оранжевый", "001185"), ("Уникальный", "112"), ("Стикер", "00341")],
        )

    def test_grouped_message_extracts_all_six_keys_with_types(self):
        self._create_type("Оранжевый", "#FF982A")
        self._create_type("Стикер", "#9B72E8")
        self._create_type("Уникальный", "#22B889")
        message = (
            "Адрес: Роз 6/6а\nКвартира: 12\n"
            "ФИО собственник: Багдасарян Римма\nФИО кто получил:\n"
            "Номер тел:8988-360-77-71\nНомер тел2:\nПровайдер: бил\n"
            "Ключи:003049 ор\nПростые -\nПремиальные -\n"
            "Стикеры -396, 379, 211\nУникальные -1057, 918"
        )

        parsed = parse_message(message)

        self.assertEqual(
            [(item["type_name"], item["number"]) for item in parsed["key_requests"]],
            [
                ("Оранжевый", "003049"),
                ("Стикер", "396"),
                ("Стикер", "379"),
                ("Стикер", "211"),
                ("Уникальный", "1057"),
                ("Уникальный", "918"),
            ],
        )

    def test_type_aliases_come_back_to_real_catalog_types(self):
        orange_id = self._create_type("Оранжевый", "#FF982A")
        unique_id = self._create_type("Уникальный", "#22B889")
        sticker_id = self._create_type("Стикер", "#9B72E8")

        parsed = parse_message("оранж 00012, уник 00013, sticker 00014")

        self.assertEqual(
            [item["type_id"] for item in parsed["key_requests"]],
            [orange_id, unique_id, sticker_id],
        )

    def test_hex_lookup_respects_explicit_key_type(self):
        orange_id = self._create_type("Оранжевый", "#FF982A")
        sticker_id = self._create_type("Стикер", "#9B72E8")
        key_repository.save_prepared_key(orange_id, "001185", "AABBCCDD")

        self.assertEqual(find_keys("AABBCCDD", orange_id)[0]["number"], "001185")
        self.assertEqual(find_keys("AABBCCDD", sticker_id), [])

    def test_hex_has_priority_but_number_conflict_is_not_silent(self):
        orange_id = self._create_type("Оранжевый", "#FF982A")
        key_repository.save_prepared_key(orange_id, "001186", "AABBCCDD")

        parsed = parse_message("Оранжевый 001185, HEX: AABBCCDD")
        rows = _build_key_rows(parsed["key_requests"])

        self.assertEqual(rows[0]["item"]["number"], "001186")
        self.assertTrue(rows[0]["identity_conflict"])

    def test_untyped_duplicate_number_requires_type_choice(self):
        orange_id = self._create_type("Оранжевый", "#FF982A")
        sticker_id = self._create_type("Стикер", "#9B72E8")
        key_repository.save_prepared_key(orange_id, "001185", "AABBCCDD")
        key_repository.save_prepared_key(sticker_id, "001185", "11223344")

        rows = _build_key_rows(parse_message("Ключ №001185")["key_requests"])

        self.assertTrue(rows[0]["ambiguous"])
        self.assertEqual(len(rows[0]["matches"]), 2)

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

    def test_message_write_returns_managed_document_for_async_form(self):
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/message/write",
                "headers": [(b"x-requested-with", b"KeyWriterAsync")],
                "client": ("127.0.0.1", 50000),
                "session": {"user": {"login": "test", "role": "admin"}},
            }
        )

        response = message_write(
            request=request,
            address="Тестовая 1",
            apartment="7",
            source_text="",
            key_numbers=[],
            key_type_ids=[],
            panel_ids=[],
        )
        payload = json.loads(response.body)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["url"], "/message")
        self.assertIn("<!DOCTYPE html>", payload["html"])

    def test_message_write_keeps_assignment_address_separate_from_manual_panels(self):
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/message/write",
                "headers": [],
                "client": ("127.0.0.1", 50000),
                "session": {"user": {"login": "test", "role": "admin"}},
            }
        )
        key = {"id": 91, "number": "12345", "hex_value": "ABCD1234", "status": "free"}
        panels = [
            {"id": 10, "address": "Бамбуковая 34", "mac": "08:13:CD:00:00:10"},
            {"id": 11, "address": "Бамбуковая 44", "mac": "08:13:CD:00:00:11"},
        ]
        with (
            patch("app.routers.message.find_key", return_value=key),
            patch("app.routers.message.is_ambiguous_key", return_value=False),
            patch("app.routers.message.get_panels", return_value=panels) as get_panels_mock,
            patch(
                "app.routers.message.get_key_write_context",
                return_value={"is_used": False, "panel_ids": []},
            ),
            patch("app.routers.message.write_key_to_panels", return_value=[]) as writer,
        ):
            message_write(
                request=request,
                address="Бамбуковая 34",
                apartment="15",
                source_text="",
                key_numbers=["12345"],
                key_type_ids=[0],
                panel_ids=[10, 11, 11],
                automatic_panel_ids=[10],
                manual_panel_ids=[11, 11],
                occupied_action="",
            )

        get_panels_mock.assert_called_once_with(panel_ids=[10, 11])
        kwargs = writer.call_args.kwargs
        self.assertEqual(kwargs["address"], "Бамбуковая 34")
        self.assertEqual(kwargs["flat_num"], "15")
        self.assertEqual(kwargs["automatic_panel_ids"], {10})
        self.assertEqual(kwargs["manual_panel_ids"], {11})

    def test_used_key_requires_explicit_operator_choice_before_write(self):
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/message/write",
                "headers": [],
                "client": ("127.0.0.1", 50000),
                "session": {"user": {"login": "test", "role": "admin"}},
            }
        )
        key = {
            "id": 55,
            "number": "003044",
            "hex_value": "A0EEF8B2",
            "status": "issued_resident",
        }
        panel = {
            "id": 7,
            "address": "Новый дом 10",
            "name": "Подъезд 1",
            "mac": "08:13:CD:00:00:07",
        }
        context = {
            "is_used": True,
            "assignment_type_name": "Жилец",
            "assignment_address": "Старый дом 1",
            "assignment_apartment": "4",
            "owner_name": "",
            "panel_ids": [3],
        }

        with (
            patch("app.routers.message.find_key", return_value=key),
            patch("app.routers.message.is_ambiguous_key", return_value=False),
            patch("app.routers.message.get_panels", return_value=[panel]),
            patch(
                "app.routers.message.get_key_write_context",
                return_value=context,
            ),
            patch("app.routers.message.write_key_to_panels") as writer,
        ):
            response = message_write(
                request=request,
                address="Новый дом 10",
                apartment="8",
                source_text="",
                key_numbers=["003044"],
                key_type_ids=[0],
                panel_ids=[7],
                occupied_action="",
            )

        writer.assert_not_called()
        self.assertIn(
            "сначала выберите способ",
            response.body.decode("utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
