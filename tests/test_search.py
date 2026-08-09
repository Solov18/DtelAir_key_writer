from pathlib import Path

from app.db import db
from app.repositories.panel_repository import get_panel_page
from app.services.search import get_search_suggestions, universal_search
from tests.postgres_test_case import PostgreSQLTestCase


class UniversalSearchTests(PostgreSQLTestCase):
    def setUp(self) -> None:
        super().setUp()
        with db() as conn:
            key_type_id = conn.execute(
                "INSERT INTO key_types(name, color) VALUES (?, ?)",
                ("Синий", "#2A9DF4"),
            ).lastrowid
            self.key_type_id = int(key_type_id)
            conn.execute(
                """
                INSERT INTO keys(key_type_id, number, hex_value, status)
                VALUES (?, ?, ?, 'free')
                """,
                (key_type_id, "20", "F0291360"),
            )
            conn.execute(
                """
                INSERT INTO panels(address, entrance, name, mac, ip, enabled)
                VALUES (?, ?, ?, ?, ?, 1)
                """,
                (
                    "ул. Тестовая 20",
                    "Подъезд 1",
                    "Тестовая панель",
                    "08:13:CD:00:20:60",
                    "10.29.136.0",
                ),
            )

    def _insert_location_fixture(self) -> dict[str, int]:
        with db() as conn:
            panel_ids = {}
            for suffix, address, entrance, name, ip in (
                ("51", "ул. Тепличная 71/5", "подъезд 1", "Тепличная 71/5 П1", "10.0.71.51"),
                ("52", "ул. Тепличная 71/5", "подъезд 2", "Тепличная 71/5 П2", "10.0.71.52"),
                ("53", "ул. Тепличная 71", "подъезд 1", "Тепличная 71 П1", "10.0.71.53"),
                ("32", "ул. Посторонняя 9", "вход", "P32", "10.0.0.32"),
            ):
                panel_ids[suffix] = int(
                    conn.execute(
                        """
                        INSERT INTO panels(address, entrance, name, mac, ip, enabled)
                        VALUES (?, ?, ?, ?, ?, 1)
                        """,
                        (address, entrance, name, f"08:13:CD:71:05:{suffix}", ip),
                    ).lastrowid
                )

            key_ids = {}
            for number, hex_value, address, apartment in (
                ("71532", "AA715032", "ул. Тепличная 71/5", "32"),
                ("71533", "AA715033", "ул. Тепличная 71/5", "33"),
                ("7132", "AA710032", "ул. Тепличная 71", "32"),
            ):
                key_id = int(
                    conn.execute(
                        """
                        INSERT INTO keys(key_type_id, number, hex_value, status)
                        VALUES (?, ?, ?, 'issued_resident')
                        """,
                        (self.key_type_id, number, hex_value),
                    ).lastrowid
                )
                key_ids[number] = key_id
                conn.execute(
                    """
                    INSERT INTO key_assignments(
                        key_id, assignment_type, address, apartment, assigned_by, active
                    ) VALUES (?, 'resident', ?, ?, 'Тест', 1)
                    """,
                    (key_id, address, apartment),
                )
                conn.execute(
                    """
                    INSERT INTO operation_log(
                        mode, printed_number, hex_value, flat_num, mac, panel_name,
                        status, address, apartment, action, object_type,
                        object_name, details, key_id
                    ) VALUES (
                        'test', ?, ?, ?, '', '', 'SUCCESS', ?, ?,
                        'Назначение ключа', 'key', ?, ?, ?
                    )
                    """,
                    (
                        number,
                        hex_value,
                        apartment,
                        address,
                        apartment,
                        f"Ключ №{number}",
                        f"{address}, кв. {apartment}",
                        key_id,
                    ),
                )
            conn.execute(
                """
                INSERT INTO operation_log(
                    mode, printed_number, hex_value, flat_num, mac, panel_name,
                    status, address, apartment, action, object_type,
                    object_name, details, panel_id
                ) VALUES (
                    'test', '', '', '', '', 'P32', 'SUCCESS',
                    'ул. Посторонняя 9', '', 'Проверка панели', 'panel',
                    'Панель P32', 'Техническая панель P32, IP 10.0.0.32', ?
                )
                """,
                (panel_ids["32"],),
            )
        return {**panel_ids, **key_ids}

    def test_exact_key_hex_does_not_fuzzy_match_unrelated_panels(self):
        result = universal_search("F0291360")

        self.assertEqual(
            [item["number"] for item in result["inventory_results"]],
            ["20"],
        )
        self.assertEqual(result["panel_results"], [])
        self.assertEqual(result["result_counts"]["panels"], 0)

    def test_key_suggestion_keeps_unambiguous_hex_as_value(self):
        suggestions = get_search_suggestions(
            "F0291360",
            scope="universal",
        )

        self.assertTrue(suggestions)
        self.assertEqual(suggestions[0]["label"], "Ключ №20")
        self.assertEqual(suggestions[0]["value"], "F0291360")
        self.assertFalse(
            any(item["meta"].startswith("Панель ID") for item in suggestions)
        )

    def test_suggestion_script_replaces_input_with_canonical_value(self):
        script = Path("app/static/js/smart-search.js").read_text(encoding="utf-8")
        self.assertIn("input.value = item.value", script)

    def test_suggestion_selection_is_shared_for_pointer_keyboard_and_submit(self):
        script = Path("app/static/js/smart-search.js").read_text(encoding="utf-8")
        message = Path("app/templates/message_preview.html").read_text(encoding="utf-8")
        manual = Path("app/templates/manual_write.html").read_text(encoding="utf-8")
        employee = Path("app/templates/employee_detail.html").read_text(encoding="utf-8")

        self.assertIn('"smart-autocomplete:select"', script)
        self.assertIn('option.addEventListener("pointerdown"', script)
        self.assertIn('event.key === "Enter"', script)
        self.assertIn('event.key === "Escape"', script)
        self.assertIn("chooseSuggestion(input, selected, \"keyboard\")", script)
        self.assertIn("form.requestSubmit(submitter || undefined)", script)
        self.assertIn("state.selecting = true", script)
        self.assertIn("Ничего не найдено", script)
        self.assertIn('data-smart-submit="messageCorrectionForm"', message)
        self.assertIn('data-smart-submit="manualPreviewForm"', manual)
        self.assertIn('data-smart-submit="false"', employee)

    def test_panel_address_suggestion_groups_all_entrances(self):
        with db() as conn:
            for index in range(1, 5):
                conn.execute(
                    """
                    INSERT INTO panels(address, entrance, name, mac, ip, enabled)
                    VALUES (?, ?, ?, ?, ?, 1)
                    """,
                    (
                        "ул. Голубые Дали 80",
                        f"подъезд {index}",
                        f"Голубые Дали 80 подъезд {index}",
                        f"08:13:CD:00:80:{index:02X}",
                        f"10.0.80.{index}",
                    ),
                )
            conn.execute(
                """
                INSERT INTO panels(address, entrance, name, mac, ip, enabled)
                VALUES (?, ?, ?, ?, ?, 1)
                """,
                (
                    "ул. Удачи 6",
                    "вход",
                    "Удачи 6 вход",
                    "08:13:CD:00:81:01",
                    "10.0.81.1",
                ),
            )

        suggestions = get_search_suggestions(
            "голубые дали",
            scope="panels",
        )

        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0]["value"], "ул. Голубые Дали 80")
        self.assertEqual(suggestions[0]["label"], "ул. Голубые Дали 80")
        self.assertIn("4 панели", suggestions[0]["meta"])
        self.assertNotIn("Удачи", suggestions[0]["label"])

        panel_page = get_panel_page(query=suggestions[0]["value"])
        self.assertEqual(panel_page["total"], 4)

    def test_registry_templates_have_first_and_last_page_navigation(self):
        panels_template = Path("app/templates/panels.html").read_text(encoding="utf-8")
        keys_template = Path("app/templates/keys.html").read_text(encoding="utf-8")

        for template in (panels_template, keys_template):
            self.assertIn('aria-label="Первая страница"', template)
            self.assertIn('aria-label="Последняя страница"', template)

    def test_address_and_apartment_variants_are_strict(self):
        ids = self._insert_location_fixture()

        for query in (
            "Тепличная 71/5 кв 32",
            "ул. Тепличная 71/5 квартира 32",
            "Тепличная, д. 71/5 кв. 32",
            "ул Тепличная дом 71/5 кв32",
            "Тепличная 71/5 квартира №32",
        ):
            result = universal_search(query)
            self.assertEqual(
                [item["number"] for item in result["inventory_results"]],
                ["71532"],
                query,
            )
            self.assertEqual(
                {item["id"] for item in result["panel_results"]},
                {ids["51"], ids["52"]},
                query,
            )
            self.assertTrue(result["operation_results"], query)
            self.assertTrue(
                all(row.get("key_id") == ids["71532"] for row in result["operation_results"]),
                query,
            )
            self.assertNotIn(ids["32"], {item["id"] for item in result["panel_results"]})

    def test_same_apartment_in_another_house_is_not_mixed(self):
        ids = self._insert_location_fixture()

        result = universal_search("Тепличная 71 кв 32")

        self.assertEqual(
            [item["number"] for item in result["inventory_results"]],
            ["7132"],
        )
        self.assertEqual({item["id"] for item in result["panel_results"]}, {ids["53"]})

    def test_exact_address_without_apartment_returns_only_that_house(self):
        ids = self._insert_location_fixture()

        result = universal_search("Тепличная 71/5")

        self.assertEqual(
            {item["number"] for item in result["inventory_results"]},
            {"71532", "71533"},
        )
        self.assertEqual(
            {item["id"] for item in result["panel_results"]},
            {ids["51"], ids["52"]},
        )

    def test_apartment_only_does_not_match_panel_p32_or_ip(self):
        ids = self._insert_location_fixture()

        result = universal_search("кв 32")

        self.assertEqual(
            {item["number"] for item in result["inventory_results"]},
            {"71532", "7132"},
        )
        panel_ids = {item["id"] for item in result["panel_results"]}
        self.assertNotIn(ids["32"], panel_ids)
        self.assertTrue(
            all("P32" not in str(row.get("object_name") or "") for row in result["operation_results"])
        )

    def test_missing_apartment_returns_explicit_message_without_house_panels(self):
        self._insert_location_fixture()

        result = universal_search("ул. Тепличная 71/5 кв 99")

        self.assertEqual(result["inventory_results"], [])
        self.assertEqual(result["panel_results"], [])
        self.assertEqual(result["operation_results"], [])
        self.assertEqual(
            result["no_results_message"],
            "По адресу ул. Тепличная 71/5 квартира 99 ничего не найдено",
        )
