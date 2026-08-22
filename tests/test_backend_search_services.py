"""Characterization and contract tests for shared read-only searches."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from app.db import db
from app.main import app
from app.repositories import uk_repository
from app.repositories.key_repository import get_keys_page, search_keys_for_selection
from app.repositories.user_repository import create_user
from app.routers.message import message_panel_search
from app.routers.search import key_picker_search, panel_picker_search
from app.services.auth import hash_password
from app.services.key_search import KeySearchProfile, KeySearchService
from app.services.keys import find_key, find_keys
from app.key_numbers import normalize_key_number_for_lookup
from app.services.panel_search import PanelSearchProfile, PanelSearchService
from tests.postgres_test_case import PostgreSQLTestCase


class BackendSearchServiceTests(PostgreSQLTestCase):
    def _type(self, name: str, color: str = "#2A9DF4") -> int:
        with db() as conn:
            existing = conn.execute(
                "SELECT id FROM key_types WHERE LOWER(name) = LOWER(?)",
                (name,),
            ).fetchone()
            if existing:
                return int(existing["id"])
            return int(
                conn.execute(
                    "INSERT INTO key_types(name, color, enabled) VALUES (?, ?, 1)",
                    (name, color),
                ).lastrowid
            )

    def _key(self, type_id: int, type_name: str, number: str, hex_value: str,
             status: str = "free") -> int:
        with db() as conn:
            return int(
                conn.execute(
                    """
                    INSERT INTO keys(key_type_id, number, hex_value, key_type, status)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (type_id, number, hex_value, type_name, status),
                ).lastrowid
            )

    def _panel(self, address: str, entrance: str, mac: str, *, ip: str = "",
               enabled: int = 1) -> int:
        with db() as conn:
            return int(
                conn.execute(
                    """
                    INSERT INTO panels(address, entrance, name, mac, ip, enabled)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (address, entrance, f"{address} {entrance}", mac, ip, enabled),
                ).lastrowid
            )

    def _key_fixture(self) -> dict[str, int]:
        sticker = self._type("Стикер", "#ef4444")
        premium = self._type("Премиальный", "#8b5cf6")
        ids = {
            "exact": self._key(sticker, "Стикер", "000123", "A1B2C3D4"),
            "same_other_type": self._key(premium, "Премиальный", "000123", "B1C2D3E4"),
            "prefix": self._key(sticker, "Стикер", "0001234", "A1B2FFFF"),
            "contains": self._key(sticker, "Стикер", "91000123", "00A1B200"),
            "occupied": self._key(sticker, "Стикер", "000124", "A1B2C3D5", "issued_resident"),
        }
        with db() as conn:
            conn.execute(
                """
                INSERT INTO key_assignments(
                    key_id, assignment_type, address, apartment, active, note
                ) VALUES (?, 'resident', 'ул. Тестовая 10', '32', 1, 'Иванов')
                """,
                (ids["occupied"],),
            )
        return ids

    def test_key_exact_leading_zero_ambiguity_and_owner_contract(self):
        ids = self._key_fixture()

        exact = KeySearchService.exact_lookup("000123")
        self.assertEqual({item.id for item in exact}, {ids["exact"], ids["same_other_type"]})
        self.assertTrue(all(item.number == "000123" for item in exact))

        occupied = KeySearchService.exact_lookup("000124")[0]
        self.assertTrue(occupied.occupied)
        self.assertFalse(occupied.is_available)
        self.assertIn("Тестовая 10", occupied.current_owner)
        self.assertIn("кв. 32", occupied.current_owner)
        self.assertEqual(find_keys("000124")[0]["id"], ids["occupied"])

    def test_numeric_key_lookup_ignores_zero_padding_and_respects_type(self):
        blue = self._type("Синий", "#2A9DF4")
        orange = self._type("Оранжевый", "#FF982A")
        blue_key = self._key(blue, "Синий", "50", "AA000050")
        orange_key = self._key(orange, "Оранжевый", "000050", "BB000050")
        first_key = self._key(orange, "Оранжевый", "000001", "BB000001")

        self.assertEqual(normalize_key_number_for_lookup("000000"), "0")
        self.assertEqual(
            {item.id for item in KeySearchService.exact_lookup("50")},
            {blue_key, orange_key},
        )
        self.assertEqual(
            {item.id for item in KeySearchService.exact_lookup("000050")},
            {blue_key, orange_key},
        )
        self.assertEqual(
            [item.id for item in KeySearchService.exact_lookup("1")],
            [first_key],
        )
        ambiguous = find_key("50")
        self.assertTrue(ambiguous["_ambiguous"])
        self.assertEqual({item["id"] for item in ambiguous["matches"]}, {blue_key, orange_key})
        self.assertEqual(find_key("50", orange)["id"], orange_key)
        self.assertEqual(find_key("000050", blue)["id"], blue_key)

        registry = get_keys_page(query="50", page=1, page_size=20)
        self.assertTrue({blue_key, orange_key} <= {item["id"] for item in registry["items"]})
        picker = search_keys_for_selection("50", limit=20)
        self.assertTrue({blue_key, orange_key} <= {item["id"] for item in picker})

    def test_registry_numeric_query_is_exact_across_padding_and_types(self):
        blue = self._type("Синий", "#2A9DF4")
        orange = self._type("Оранжевый", "#FF982A")
        blue_key = self._key(blue, "Синий", "12", "AA000012")
        orange_key = self._key(orange, "Оранжевый", "000012", "BB000012")
        unrelated = self._key(orange, "Оранжевый", "009128", "BB009128")

        for query in ("12", "012", "00012"):
            result = get_keys_page(query=query, page=1, page_size=20)
            self.assertEqual(
                {blue_key, orange_key},
                {item["id"] for item in result["items"]},
            )
            self.assertNotIn(unrelated, {item["id"] for item in result["items"]})

        blue_result = get_keys_page(query="00012", key_type_id=blue)
        orange_result = get_keys_page(query="12", key_type_id=orange)
        self.assertEqual([blue_key], [item["id"] for item in blue_result["items"]])
        self.assertEqual([orange_key], [item["id"] for item in orange_result["items"]])

    def test_keys_http_form_query_returns_exact_numeric_matches(self):
        blue = self._type("Синий", "#2A9DF4")
        exact_id = self._key(blue, "Синий", "12", "CC000012")
        self._key(blue, "Синий", "009128", "CC009128")
        password = "number-search-test-password"
        create_user("Тестовый администратор", "number-search-admin", hash_password(password), "admin")

        client = TestClient(app)
        login_page = client.get("/login")
        csrf_match = re.search(
            r'name="csrf_token"\s+value="([^"]+)"',
            login_page.text,
        )
        self.assertIsNotNone(csrf_match)
        login_response = client.post(
            "/login",
            data={
                "login": "number-search-admin",
                "password": password,
                "csrf_token": csrf_match.group(1),
            },
            follow_redirects=False,
        )
        self.assertEqual(login_response.status_code, 303)

        response = client.get("/keys", params={"q": "00012"})
        self.assertEqual(response.status_code, 200)
        page = get_keys_page(query="00012", page=1, page_size=20)
        self.assertEqual([exact_id], [item["id"] for item in page["items"]])
        self.assertIn('name="q"', response.text)
        self.assertIn('value="00012"', response.text)
        self.assertIn("12", response.text)

    def test_key_partial_type_hex_filters_ranking_limit_and_legacy_adapter(self):
        ids = self._key_fixture()

        ranked = KeySearchService.search("000123", limit=10)
        ranks = {item.id: item.rank for item in ranked}
        self.assertLess(ranks[ids["exact"]], ranks[ids["prefix"]])
        self.assertLess(ranks[ids["prefix"]], ranks[ids["contains"]])
        self.assertEqual(len(KeySearchService.search("000123", limit=1)), 1)

        typed = KeySearchService.search("стикер 000123", limit=10)
        self.assertEqual([item.id for item in typed], [ids["exact"], ids["prefix"]])
        by_partial_hex = KeySearchService.search("A1B2", limit=10)
        self.assertIn(ids["exact"], {item.id for item in by_partial_hex})
        by_exact_hex = KeySearchService.exact_lookup("a1-b2-c3-d4")
        self.assertEqual([item.id for item in by_exact_hex], [ids["exact"]])
        typed_hex = KeySearchService.search("стикер A1B2C3D4", limit=10)
        self.assertEqual([item.id for item in typed_hex], [ids["exact"]])
        self.assertEqual(typed_hex[0].match_type, "contains")
        self.assertIn("000123", typed_hex[0].display_label)
        self.assertEqual(KeySearchService.search("не существует", limit=10), [])

        legacy = search_keys_for_selection("A1B2", limit=10)
        self.assertEqual(
            [item["id"] for item in legacy],
            [item.id for item in by_partial_hex],
        )
        self.assertTrue(all("hex_value" in item and "available" in item for item in legacy))

    def test_key_available_only_and_http_contract(self):
        ids = self._key_fixture()
        available = KeySearchService.search("A1B2", available_only=True, limit=20)
        self.assertNotIn(ids["occupied"], {item.id for item in available})

        payload = key_picker_search(q="A1B2", key_type_id=None, only_free=False, limit=20)
        self.assertIn(ids["occupied"], {item["id"] for item in payload["items"]})
        used = next(item for item in payload["items"] if item["id"] == ids["occupied"])
        self.assertTrue(used["disabled"])

    def test_panel_search_all_fields_inactive_ranking_limit_and_contracts(self):
        exact = self._panel(
            "ул. Бамбуковая 44 к.2", "верхняя калитка",
            "D4:A0:FB:1B:3C:57", ip="10.20.30.40",
        )
        parking = self._panel(
            "ул. Бамбуковая 44 к.2", "парковка и лифт",
            "D4:A0:FB:1B:3C:58", ip="10.20.30.41",
        )
        inactive = self._panel(
            "ул. Бамбуковая 44 к.2", "подъезд 3",
            "D4:A0:FB:1B:3C:59", enabled=0,
        )
        with db() as conn:
            conn.execute(
                """
                UPDATE panels
                SET api_status = 'online', last_checked_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (exact,),
            )
        self._panel("ул. Другая 144", "калитка", "D4:A0:FB:1B:3C:60")

        by_house = PanelSearchService.search("Бамбуковая 44", limit=20)
        self.assertEqual({item.id for item in by_house}, {exact, parking, inactive})
        self.assertEqual([item.id for item in PanelSearchService.search("верхняя калитка")], [exact])
        self.assertEqual([item.id for item in PanelSearchService.search("парковка лифт")], [parking])
        self.assertEqual([item.id for item in PanelSearchService.search("D4 A0 FB 1B 3C 57")], [exact])
        self.assertEqual([item.id for item in PanelSearchService.search("10.20.30.40")], [exact])
        self.assertNotIn(
            inactive,
            {item.id for item in PanelSearchService.search("Бамбуковая", active_only=True)},
        )
        self.assertEqual(len(PanelSearchService.search("Бамбуковая", limit=1)), 1)

        old_contract = message_panel_search(query="Бамбуковая 44")
        neutral_contract = panel_picker_search(
            q="Бамбуковая 44",
            scope="all",
            group_id=None,
            active_only=False,
            exact_address="",
            limit=20,
        )
        self.assertEqual(old_contract["total"], 3)
        exact_old_dto = next(item for item in old_contract["items"] if item["id"] == exact)
        self.assertEqual(exact_old_dto["status_name"], "В сети")
        self.assertEqual(exact_old_dto["status_tone"], "success")
        self.assertEqual(neutral_contract["total"], 3)
        self.assertEqual(
            {item["id"] for item in old_contract["items"]},
            {item["id"] for item in neutral_contract["items"]},
        )
        panel_dto = next(item for item in neutral_contract["items"] if item["id"] == exact)
        self.assertEqual(panel_dto["house"], "44/2")
        self.assertEqual(panel_dto["corpus"], "2")
        self.assertIn("бамбуковая", panel_dto["street"])

    def test_panel_uk_scope_does_not_leak_other_groups(self):
        first = self._panel("ул. Ясногорская 16/2 к.13", "подъезд 1", "08:13:CD:00:01:01")
        second = self._panel("ул. Ясногорская 16/2 к.13", "парковка", "08:13:CD:00:01:02")
        outside = self._panel("ул. Ясногорская 16/2 к.13", "калитка", "08:13:CD:00:01:03")
        group = uk_repository.save_group("УК Поисковый контракт")
        uk_repository.add_panel(group, first, "1")
        uk_repository.add_panel(group, second, "2")

        scoped = PanelSearchService.search(
            "Ясногорская", profile=PanelSearchProfile.PICKER_UK,
            scope="uk", group_id=group,
        )
        self.assertEqual({item.id for item in scoped}, {first, second})
        self.assertNotIn(outside, {item.id for item in scoped})
        self.assertEqual(
            {item["panel_id"] for item in uk_repository.search_group_panels(group, "Ясногорская")},
            {first, second},
        )
        neutral_scoped = panel_picker_search(
            q="Ясногорская",
            scope="uk",
            group_id=group,
            active_only=False,
            exact_address="",
            limit=20,
        )
        self.assertEqual({item["id"] for item in neutral_scoped["items"]}, {first, second})
