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


if __name__ == "__main__":
    unittest.main()
