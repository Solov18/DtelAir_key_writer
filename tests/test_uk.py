import unittest
from unittest.mock import patch

from starlette.requests import Request

from tests.postgres_test_case import PostgreSQLTestCase

from app.db import db
from app.repositories import uk_repository
from app.routers.uk import uk_credentials_reveal, uk_page
from app.services import uk_keys
from app.services.search import get_search_suggestions


class UkRegistryTests(PostgreSQLTestCase):
    def _request(self, *, role="admin", user_id=None):
        session = {
            "user": {
                "id": user_id or 1,
                "login": "admin",
                "full_name": "Администратор",
                "role": role,
                "active": 1,
            }
        }
        if user_id:
            session["user_id"] = user_id
        return Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/uk",
                "query_string": b"",
                "headers": [],
                "client": ("127.0.0.1", 10000),
                "session": session,
            }
        )

    def _panel(self, address, entrance, mac):
        with db() as conn:
            cursor = conn.execute(
                """
                INSERT INTO panels(address, entrance, name, mac, enabled)
                VALUES (?, ?, ?, ?, 1)
                """,
                (address, entrance, f"{address} {entrance}", mac),
            )
            return int(cursor.lastrowid)

    def _key(self, number, hex_value):
        with db() as conn:
            key_type = conn.execute(
                "SELECT id FROM key_types ORDER BY id LIMIT 1"
            ).fetchone()
            if not key_type:
                key_type_id = int(
                    conn.execute(
                        """
                        INSERT INTO key_types(name, color, enabled)
                        VALUES ('Синий', '#2A9DF4', 1)
                        """
                    ).lastrowid
                )
            else:
                key_type_id = int(key_type["id"])
            return int(
                conn.execute(
                    """
                    INSERT INTO keys(
                        key_type_id, number, hex_value, key_type, status
                    )
                    VALUES (?, ?, ?, 'Синий', 'free')
                    """,
                    (key_type_id, number, hex_value),
                ).lastrowid
            )

    def _company_with_panels(self):
        group_id = uk_repository.save_group(
            "УК Александрия",
            crm_login="uk-login",
            crm_password="top-secret",
            contact_name="Иванова Мария",
            phone="+7 (999) 123-45-67",
        )
        first_panel = self._panel(
            "Тепличная 63",
            "Подъезд 1",
            "08:13:CD:00:00:01",
        )
        second_panel = self._panel(
            "Тепличная 65",
            "Подъезд 2",
            "08:13:CD:00:00:02",
        )
        first_link = uk_repository.add_panel(
            group_id,
            first_panel,
            "150",
            "Основной дом",
        )
        second_link = uk_repository.add_panel(
            group_id,
            second_panel,
            "87",
        )
        return group_id, first_panel, second_panel, first_link, second_link

    @staticmethod
    def _crm_success():
        return {
            "ok": True,
            "written": True,
            "status": "SUCCESS",
            "response": "Ключ успешно записан",
        }

    def test_company_crud_search_and_credentials_are_not_in_safe_queries(self):
        group_id = uk_repository.save_group(
            name="УК Альфа-Сервис",
            legal_name="ООО «Альфа Сервис»",
            contact_name="Иванова Мария",
            phone="+7 (999) 123-45-67",
            email="office@alpha.ru",
            legal_address="г. Сочи, ул. Тепличная, 63",
            actual_address="Сочи, Тепличная 65",
            crm_login="alpha-login",
            crm_password="secret-value-123",
            note="Внутренний комментарий",
        )

        group = uk_repository.get_group(group_id)
        page = uk_repository.get_group_page(query="альфа сервис")
        by_phone = uk_repository.get_group_page(query="8.999.123-45-67")
        by_login = uk_repository.get_group_page(query="alpha login")

        self.assertNotIn("crm_password", group)
        self.assertNotIn("crm_password", page["items"][0])
        self.assertEqual(page["total"], 1)
        self.assertEqual(by_phone["total"], 1)
        self.assertEqual(by_login["total"], 1)

        uk_repository.update_group(
            group_id,
            "УК Альфа",
            phone="+7 900 000-00-01",
            crm_login="alpha-new",
            crm_password=None,
            allow_credentials=True,
        )
        credentials = uk_repository.get_group_credentials(group_id)
        self.assertEqual(credentials["crm_login"], "alpha-new")
        self.assertEqual(credentials["crm_password"], "secret-value-123")

    def test_password_reveal_requires_admin_and_normal_html_has_no_secret(self):
        group_id = uk_repository.save_group(
            "УК Секрет",
            crm_login="secret-login",
            crm_password="never-render-this",
        )
        with db() as conn:
            user_id = int(
                conn.execute(
                    """
                    INSERT INTO users(
                        full_name, login, password_hash, role_id, active
                    )
                    VALUES (
                        'Администратор',
                        'admin',
                        'hash',
                        (SELECT id FROM roles WHERE code = 'admin'),
                        1
                    )
                    """
                ).lastrowid
            )

        request = self._request(role="admin", user_id=user_id)
        response = uk_page(
            request,
            q="",
            page=1,
            selected_group_id=group_id,
            notice="",
        )
        html = response.body.decode("utf-8")
        self.assertNotIn("never-render-this", html)
        self.assertNotIn("secret-login", html)

        denied = uk_credentials_reveal(
            self._request(role="operator"),
            group_id,
        )
        allowed = uk_credentials_reveal(
            request,
            group_id,
        )
        self.assertEqual(denied.status_code, 403)
        self.assertIn(b"never-render-this", allowed.body)
        self.assertEqual(allowed.headers["cache-control"], "no-store")

    def test_panel_link_keeps_individual_apartment_and_one_active_owner(self):
        first_group = uk_repository.save_group("УК Первая")
        second_group = uk_repository.save_group("УК Вторая")
        first_panel = self._panel("Дом 1", "1", "08:13:CD:00:00:11")
        second_panel = self._panel("Дом 2", "2", "08:13:CD:00:00:12")

        first_link = uk_repository.add_panel(first_group, first_panel, "150")
        second_link = uk_repository.add_panel(first_group, second_panel, "87")
        panels = uk_repository.get_group_panels(first_group)
        self.assertEqual(
            {item["panel_id"]: item["apartment"] for item in panels},
            {first_panel: "150", second_panel: "87"},
        )
        with self.assertRaises(ValueError):
            uk_repository.add_panel(second_group, first_panel, "1")

        uk_repository.update_panel_link(first_group, first_link, "151", "Исправлено")
        updated = uk_repository.get_group_panels(first_group)
        self.assertEqual(
            next(item for item in updated if item["link_id"] == first_link)[
                "apartment"
            ],
            "151",
        )
        uk_repository.remove_panel(first_group, link_id=second_link)
        self.assertEqual(len(uk_repository.get_group_panels(first_group)), 1)

    def test_issue_key_and_make_master_uses_each_panel_apartment(self):
        group_id, _, _, first_link, second_link = self._company_with_panels()
        key_id = self._key("456790", "363FFAD7")

        with patch(
            "app.services.uk_keys.crm_add_key_for_company",
            side_effect=[self._crm_success(), self._crm_success()],
        ) as crm_call:
            issued = uk_keys.issue_key(
                group_id=group_id,
                key_id=key_id,
                panel_link_id=first_link,
            )
            extra = uk_keys.add_master_panel(
                group_id=group_id,
                issue_id=issued["issue_id"],
                panel_link_id=second_link,
            )

        self.assertTrue(issued["ok"])
        self.assertTrue(extra["ok"])
        self.assertEqual(
            [call.args[2] for call in crm_call.call_args_list],
            ["150", "87"],
        )
        issue = uk_repository.get_issue(issued["issue_id"])
        programmings = uk_repository.get_issue_programmings(issue["id"])
        self.assertEqual(issue["status"], "active")
        self.assertEqual(
            {item["apartment"] for item in programmings if item["active"]},
            {"150", "87"},
        )
        self.assertEqual(uk_repository.get_group_statistics()["master_keys"], 1)
        with db() as conn:
            key_status = conn.execute(
                "SELECT status FROM keys WHERE id = ?",
                (key_id,),
            ).fetchone()["status"]
        self.assertEqual(key_status, "assigned_uk")

    def test_duplicate_programming_and_cross_company_panel_are_rejected(self):
        group_id, _, _, first_link, second_link = self._company_with_panels()
        other_group = uk_repository.save_group("УК Чужая")
        other_panel = self._panel("Чужой дом", "1", "08:13:CD:00:00:03")
        other_link = uk_repository.add_panel(other_group, other_panel, "5")
        key_id = self._key("456791", "AF3B8C91")
        with patch(
            "app.services.uk_keys.crm_add_key_for_company",
            return_value=self._crm_success(),
        ):
            issued = uk_keys.issue_key(
                group_id=group_id,
                key_id=key_id,
                panel_link_id=first_link,
            )
            uk_keys.add_master_panel(
                group_id=group_id,
                issue_id=issued["issue_id"],
                panel_link_id=second_link,
            )
        with self.assertRaises(ValueError):
            uk_repository.create_programming(
                group_id,
                issued["issue_id"],
                second_link,
            )
        with self.assertRaises(ValueError):
            uk_repository.create_programming(
                group_id,
                issued["issue_id"],
                other_link,
            )

    def test_apartment_override_requires_explicit_confirmation(self):
        group_id, _, _, first_link, _ = self._company_with_panels()
        first_key = self._key("456792", "7B6A29F3")
        with self.assertRaises(ValueError):
            uk_repository.create_key_issue(
                group_id,
                first_key,
                first_link,
                apartment_override="999",
            )

        second_key = self._key("456793", "28D4B7E1")
        issue_id, programming_id = uk_repository.create_key_issue(
            group_id,
            second_key,
            first_link,
            apartment_override="999",
            override_confirmed=True,
        )
        self.assertGreater(issue_id, 0)
        self.assertEqual(
            uk_repository.get_programming(programming_id)["apartment"],
            "999",
        )

    def test_unlink_one_master_panel_does_not_touch_other_panels_or_crm(self):
        group_id, _, _, first_link, second_link = self._company_with_panels()
        key_id = self._key("456794", "91AF03C7")
        with patch(
            "app.services.uk_keys.crm_add_key_for_company",
            return_value=self._crm_success(),
        ):
            issued = uk_keys.issue_key(
                group_id=group_id,
                key_id=key_id,
                panel_link_id=first_link,
            )
            uk_keys.add_master_panel(
                group_id=group_id,
                issue_id=issued["issue_id"],
                panel_link_id=second_link,
            )
        programmings = uk_repository.get_issue_programmings(issued["issue_id"])
        removed = next(
            item for item in programmings if item["panel_link_id"] == second_link
        )
        with patch(
            "app.services.uk_keys.crm_remove_key_for_company"
        ) as remove_call:
            uk_keys.unlink_accounting(removed["id"])
        remove_call.assert_not_called()
        active = [
            item
            for item in uk_repository.get_issue_programmings(issued["issue_id"])
            if item["active"]
        ]
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["panel_link_id"], first_link)
        self.assertEqual(
            uk_repository.get_issue(issued["issue_id"])["status"],
            "active",
        )

    def test_explicit_crm_remove_affects_only_selected_panel(self):
        group_id, _, _, first_link, second_link = self._company_with_panels()
        key_id = self._key("456795", "A6B23F10")
        with patch(
            "app.services.uk_keys.crm_add_key_for_company",
            return_value=self._crm_success(),
        ):
            issued = uk_keys.issue_key(
                group_id=group_id,
                key_id=key_id,
                panel_link_id=first_link,
            )
            uk_keys.add_master_panel(
                group_id=group_id,
                issue_id=issued["issue_id"],
                panel_link_id=second_link,
            )
        second = next(
            item
            for item in uk_repository.get_issue_programmings(issued["issue_id"])
            if item["panel_link_id"] == second_link
        )
        with patch(
            "app.services.uk_keys.crm_remove_key_for_company",
            return_value={
                "ok": True,
                "written": False,
                "status": "SUCCESS",
                "response": "Ключ удалён",
            },
        ) as remove_call:
            result = uk_keys.remove_from_crm(second["id"])
        self.assertTrue(result["ok"])
        remove_call.assert_called_once()
        active = [
            item
            for item in uk_repository.get_issue_programmings(issued["issue_id"])
            if item["active"]
        ]
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["panel_link_id"], first_link)

    def test_dry_run_and_training_never_make_real_crm_call(self):
        group_id, _, _, first_link, _ = self._company_with_panels()
        training_key = self._key("456796", "4E29D1B6")
        with patch(
            "app.services.uk_keys.crm_add_key_for_company"
        ) as crm_call:
            result = uk_keys.issue_key(
                group_id=group_id,
                key_id=training_key,
                panel_link_id=first_link,
                training_mode=True,
            )
        self.assertEqual(result["status"], "TRAINING_MODE")
        crm_call.assert_not_called()
        self.assertEqual(uk_repository.get_group_keys(group_id), [])

        dry_key = self._key("456797", "D7A98E22")
        with patch(
            "app.services.uk_keys.crm_add_key_for_company",
            return_value={
                "ok": True,
                "written": False,
                "status": "DRY_RUN",
                "response": "Тестовый режим",
            },
        ):
            result = uk_keys.issue_key(
                group_id=group_id,
                key_id=dry_key,
                panel_link_id=first_link,
            )
        self.assertEqual(result["status"], "DRY_RUN")
        issue = uk_repository.get_issue(result["issue_id"])
        programming = uk_repository.get_programming(result["programming_id"])
        self.assertEqual(issue["status"], "pending")
        self.assertEqual(programming["status"], "dry_run")

    def test_archive_preserves_panels_keys_and_history_but_clears_credentials(self):
        group_id, first_panel, _, first_link, _ = self._company_with_panels()
        key_id = self._key("456798", "F043D6F0")
        with patch(
            "app.services.uk_keys.crm_add_key_for_company",
            return_value=self._crm_success(),
        ):
            issued = uk_keys.issue_key(
                group_id=group_id,
                key_id=key_id,
                panel_link_id=first_link,
            )

        uk_repository.archive_group(group_id)
        self.assertIsNone(uk_repository.get_group(group_id))
        archived = uk_repository.get_group(group_id, include_archived=True)
        self.assertIsNotNone(archived["archived_at"])
        credentials = uk_repository.get_group_credentials(group_id)
        self.assertIsNone(credentials)
        archived_links = uk_repository.get_group_panels(
            group_id,
            include_detached=True,
        )
        self.assertEqual(len(archived_links), 2)
        self.assertTrue(all(not row["link_active"] for row in archived_links))
        with db() as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM panels WHERE id = ?",
                    (first_panel,),
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM keys WHERE id = ?",
                    (key_id,),
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM uk_key_issues WHERE id = ?",
                    (issued["issue_id"],),
                ).fetchone()[0],
                1,
            )

    def test_smart_suggestions_use_current_fields_only(self):
        uk_repository.save_group(
            "УК Поиск",
            contact_name="Петрова Анна",
            phone="+7 900 555-11-22",
            actual_address="Сочи, улица Рахманинова, 35",
            crm_login="rahmaninova-admin",
        )
        by_name = get_search_suggestions("ук, поиск", scope="uk")
        by_address = get_search_suggestions("рахманинова.35", scope="uk")
        by_login = get_search_suggestions("rahmaninova admin", scope="uk")
        self.assertEqual(by_name[0]["value"], "УК Поиск")
        self.assertEqual(by_address[0]["value"], "УК Поиск")
        self.assertEqual(by_login[0]["value"], "УК Поиск")


if __name__ == "__main__":
    unittest.main()
