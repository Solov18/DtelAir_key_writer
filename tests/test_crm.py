import json
import unittest
from unittest.mock import patch

from app.services import crm


class FakeResponse:
    def __init__(
        self,
        *,
        status_code=200,
        data=None,
        text=None,
        headers=None,
    ):
        self.status_code = status_code
        self._data = data
        self.text = text if text is not None else json.dumps(data or {})
        self.headers = headers or {"Content-Type": "application/json"}

    @property
    def ok(self):
        return 200 <= self.status_code < 300

    def json(self):
        if self._data is None:
            raise ValueError("not json")

        return self._data


class FakeSession:
    def __init__(self):
        self.headers = {}
        self.calls = []
        self.create_responses = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return FakeResponse(
            text='<html><meta name="csrf-token" content="csrf-123"></html>',
            headers={"Content-Type": "text/html"},
        )

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))

        if url.endswith("/site/auth/login"):
            return FakeResponse(
                data={"result": True, "message": "Вход выполнен"}
            )

        if self.create_responses:
            return self.create_responses.pop(0)

        return FakeResponse(
            data={"result": True, "message": "Ключ добавлен"}
        )

    def delete(self, url, **kwargs):
        self.calls.append(("DELETE", url, kwargs))
        if self.create_responses:
            return self.create_responses.pop(0)
        return FakeResponse(
            data={"result": True, "message": "Ключ удалён"}
        )

    def close(self):
        pass


class CrmServiceTests(unittest.TestCase):
    def setUp(self):
        crm._reset_session()

    def tearDown(self):
        crm._reset_session()

    def configure(self, **values):
        defaults = {
            "crm_base_url": "https://crm.example",
            "crm_cookie": "",
            "crm_login": "",
            "crm_password": "",
            "crm_buyer_id": "",
            "dry_run": False,
            "request_timeout": 5,
        }
        defaults.update(values)

        for name, value in defaults.items():
            setattr(crm.settings, name, value)

    def test_dry_run_does_not_open_session(self):
        self.configure(dry_run=True)

        with patch.object(crm.requests, "Session") as session_factory:
            result = crm.crm_add_key(
                "08:13:CD:00:1D:C2",
                "363FFAD7",
                "10",
                1,
            )

        self.assertEqual(result["status"], "DRY_RUN")
        self.assertFalse(result["written"])
        session_factory.assert_not_called()

    def test_cookie_session_writes_key(self):
        self.configure(crm_cookie="Cookie: PHPSESSID=test-session")
        session = FakeSession()

        with patch.object(crm.requests, "Session", return_value=session):
            result = crm.crm_add_key(
                "08:13:CD:00:1D:C2",
                "363FFAD7",
                "10",
                1,
            )

        self.assertTrue(result["written"])
        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(session.headers["Cookie"], "PHPSESSID=test-session")
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(
            session.calls[0][1],
            "https://crm.example/front/device-keys/08:13:CD:00:1D:C2/create-key",
        )
        self.assertEqual(session.calls[0][2]["json"]["value"], "363FFAD7")

    def test_existing_key_has_separate_status(self):
        self.configure(crm_cookie="PHPSESSID=test-session")
        session = FakeSession()
        session.create_responses.append(
            FakeResponse(data={"result": False, "message": "Ключ уже существует"})
        )

        with patch.object(crm.requests, "Session", return_value=session):
            result = crm.crm_add_key(
                "08:13:CD:00:1D:C2",
                "363FFAD7",
                "10",
                1,
            )

        self.assertFalse(result["written"])
        self.assertEqual(result["status"], "ALREADY_EXISTS")
        self.assertTrue(result["ok"])

    def test_write_lock_wait_has_timeout(self):
        self.configure(crm_cookie="PHPSESSID=test-session", request_timeout=3)

        class BusyLock:
            def acquire(self, *, timeout):
                self.timeout = timeout
                return False

            def release(self):
                raise AssertionError("Нельзя освобождать lock, который не был получен")

        busy_lock = BusyLock()
        with patch.object(crm, "_crm_lock", busy_lock):
            result = crm.crm_add_key(
                "08:13:CD:00:1D:C2",
                "363FFAD7",
                "10",
                1,
            )

        self.assertEqual(result["status"], "TIMEOUT")
        self.assertEqual(busy_lock.timeout, 3)

    def test_credentials_login_before_write(self):
        self.configure(
            crm_login="operator",
            crm_password="secret",
            crm_buyer_id="42",
        )
        session = FakeSession()

        with patch.object(crm.requests, "Session", return_value=session):
            result = crm.crm_add_key(
                "08:13:CD:00:1D:C2",
                "363FFAD7",
                "0",
                0,
            )

        self.assertTrue(result["written"])
        self.assertEqual([call[0] for call in session.calls], ["GET", "POST", "POST"])
        login_call = session.calls[1]
        login_page_call = session.calls[0]
        self.assertEqual(login_call[1], "https://crm.example/site/auth/login")
        self.assertEqual(login_call[2]["json"]["buyer"], "42")
        self.assertEqual(login_call[2]["headers"]["X-CSRF-Token"], "csrf-123")
        self.assertEqual(session.headers["X-CSRF-Token"], "csrf-123")
        self.assertIn("text/html", login_page_call[2]["headers"]["Accept"])
        self.assertIsNone(login_page_call[2]["headers"]["Content-Type"])
        self.assertIsNone(login_page_call[2]["headers"]["X-Requested-With"])

    def test_multi_step_write_uses_one_shared_deadline(self):
        self.configure(
            crm_login="operator",
            crm_password="secret",
            crm_buyer_id="42",
            request_timeout=5,
        )
        session = FakeSession()

        with (
            patch.object(crm.requests, "Session", return_value=session),
            patch.object(crm, "monotonic", side_effect=[100.0, 101.0, 102.0, 103.0]),
        ):
            result = crm.crm_add_key(
                "08:13:CD:00:1D:C2",
                "363FFAD7",
                "0",
                1,
            )

        self.assertTrue(result["written"])
        timeouts = [call[2]["timeout"] for call in session.calls]
        self.assertEqual(timeouts, [4.0, 3.0, 2.0])

    def test_extracts_csrf_from_hidden_form_field(self):
        token = crm._extract_csrf(
            '<form><input type="hidden" name="_csrf" value="csrf-from-form"></form>'
        )

        self.assertEqual(token, "csrf-from-form")

    def test_expired_login_session_is_recreated_once(self):
        self.configure(
            crm_login="operator",
            crm_password="secret",
            crm_buyer_id="42",
        )
        expired_session = FakeSession()
        expired_session.create_responses.append(
            FakeResponse(
                status_code=302,
                data={},
                headers={"Location": "/site/auth"},
            )
        )
        renewed_session = FakeSession()

        with patch.object(
            crm.requests,
            "Session",
            side_effect=[expired_session, renewed_session],
        ):
            result = crm.crm_add_key(
                "08:13:CD:00:1D:C2",
                "363FFAD7",
                "0",
                1,
            )

        self.assertTrue(result["written"])
        self.assertEqual(len(expired_session.calls), 3)
        self.assertEqual(len(renewed_session.calls), 3)

    def test_missing_auth_is_explicit_error(self):
        self.configure()

        result = crm.crm_add_key(
            "08:13:CD:00:1D:C2",
            "363FFAD7",
            "0",
            1,
        )

        self.assertFalse(result["written"])
        self.assertEqual(result["status"], "AUTH_REQUIRED")

    def test_invalid_key_is_rejected_before_network(self):
        self.configure(crm_cookie="PHPSESSID=test-session")

        with patch.object(crm.requests, "Session") as session_factory:
            result = crm.crm_add_key(
                "08:13:CD:00:1D:C2",
                "NOT-HEX",
                "0",
                1,
            )

        self.assertEqual(result["status"], "VALIDATION_ERROR")
        session_factory.assert_not_called()

    def test_company_credentials_use_isolated_session(self):
        self.configure(crm_buyer_id="42")
        session = FakeSession()

        with patch.object(crm.requests, "Session", return_value=session):
            result = crm.crm_add_key_for_company(
                "08:13:CD:00:1D:C2",
                "363FFAD7",
                "150",
                0,
                login="uk-operator",
                password="uk-secret",
            )

        self.assertTrue(result["written"])
        self.assertEqual([call[0] for call in session.calls], ["GET", "POST", "POST"])
        login_payload = session.calls[1][2]["json"]
        self.assertEqual(login_payload["username"], "uk-operator")
        self.assertEqual(login_payload["password"], "uk-secret")
        self.assertEqual(session.calls[2][2]["json"]["flatNum"], "150")

    def test_company_dry_run_does_not_open_session_or_authorize(self):
        self.configure(dry_run=True, crm_buyer_id="42")

        with patch.object(crm.requests, "Session") as session_factory:
            result = crm.crm_add_key_for_company(
                "08:13:CD:00:1D:C2",
                "363FFAD7",
                "150",
                0,
                login="uk-operator",
                password="uk-secret",
            )

        self.assertEqual(result["status"], "DRY_RUN")
        session_factory.assert_not_called()

    def test_company_remove_is_an_explicit_separate_request(self):
        self.configure(crm_buyer_id="42")
        session = FakeSession()

        with patch.object(crm.requests, "Session", return_value=session):
            result = crm.crm_remove_key_for_company(
                "08:13:CD:00:1D:C2",
                "363FFAD7",
                "87",
                0,
                login="uk-operator",
                password="uk-secret",
            )

        self.assertTrue(result["ok"])
        self.assertFalse(result["written"])
        self.assertEqual(session.calls[2][0], "DELETE")
        self.assertEqual(
            session.calls[2][1],
            "https://crm.example/front/device/08:13:CD:00:1D:C2/key/363FFAD7/delete",
        )
        self.assertNotIn("json", session.calls[2][2])

    def test_cookie_remove_uses_current_crm_delete_contract(self):
        self.configure(crm_cookie="PHPSESSID=test-session")
        session = FakeSession()

        with patch.object(crm.requests, "Session", return_value=session):
            result = crm.crm_remove_key(
                "08:13:CD:00:1D:C2", "363FFAD7", "87", 0,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(session.calls[0][0], "DELETE")
        self.assertEqual(
            session.calls[0][1],
            "https://crm.example/front/device/08:13:CD:00:1D:C2/key/363FFAD7/delete",
        )
        self.assertNotIn("json", session.calls[0][2])

    def test_cookie_remove_does_not_treat_generic_route_404_as_absent_key(self):
        self.configure(crm_cookie="PHPSESSID=test-session")
        session = FakeSession()
        session.create_responses.append(
            FakeResponse(
                status_code=404,
                text="<html><body>Not Found</body></html>",
                headers={"Content-Type": "text/html"},
            )
        )

        with patch.object(crm.requests, "Session", return_value=session):
            result = crm.crm_remove_key(
                "08:13:CD:00:1D:C2", "363FFAD7", "87", 0,
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "INVALID_ROUTE")
        self.assertIn("неверный маршрут", result["response"])
        self.assertEqual(session.calls[0][0], "DELETE")

    def test_cookie_remove_treats_explicit_key_absence_as_idempotent(self):
        self.configure(crm_cookie="PHPSESSID=test-session")
        session = FakeSession()
        session.create_responses.append(
            FakeResponse(
                status_code=404,
                data={"message": "Ключ не найден"},
            )
        )

        with patch.object(crm.requests, "Session", return_value=session):
            result = crm.crm_remove_key(
                "08:13:CD:00:1D:C2", "363FFAD7", "87", 0,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "ALREADY_ABSENT")
        self.assertEqual(session.calls[0][0], "DELETE")

    def test_company_existing_and_absent_results_are_idempotent(self):
        self.configure(crm_buyer_id="42")
        add_session = FakeSession()
        add_session.create_responses.append(
            FakeResponse(data={"result": False, "message": "Ключ уже существует"})
        )
        with patch.object(crm.requests, "Session", return_value=add_session):
            added = crm.crm_add_key_for_company(
                "08:13:CD:00:1D:C2", "363FFAD7", "87", 0,
                login="uk-operator", password="uk-secret",
            )
        self.assertTrue(added["ok"])
        self.assertEqual(added["status"], "ALREADY_EXISTS")

        remove_session = FakeSession()
        remove_session.create_responses.append(
            FakeResponse(data={"result": False, "message": "Ключ не найден"})
        )
        with patch.object(crm.requests, "Session", return_value=remove_session):
            removed = crm.crm_remove_key_for_company(
                "08:13:CD:00:1D:C2", "363FFAD7", "87", 0,
                login="uk-operator", password="uk-secret",
            )
        self.assertTrue(removed["ok"])
        self.assertEqual(removed["status"], "ALREADY_ABSENT")

    def test_company_remove_does_not_treat_generic_route_404_as_absent_key(self):
        self.configure(crm_buyer_id="42")
        session = FakeSession()
        session.create_responses.append(
            FakeResponse(
                status_code=404,
                text="<html><body>Not Found</body></html>",
                headers={"Content-Type": "text/html"},
            )
        )

        with patch.object(crm.requests, "Session", return_value=session):
            result = crm.crm_remove_key_for_company(
                "08:13:CD:00:1D:C2", "363FFAD7", "87", 0,
                login="uk-operator", password="uk-secret",
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "INVALID_ROUTE")
        self.assertEqual(session.calls[2][0], "DELETE")


if __name__ == "__main__":
    unittest.main()
