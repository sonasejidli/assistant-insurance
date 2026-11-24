import sqlite3

import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient

from App.accounts import COOKIE
from App.main import app


class AccountTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(directory) / "accounts.sqlite3"
        self.enterContext(patch.dict("os.environ", {"INSURANCE_ACCOUNTS_DB": str(self.path)}))
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def test_new_email_creates_account_and_session(self):
        client, path = self.client, self.path
        response = client.post("/auth/register", json={"email": " New@Example.com ", "password": "a new password"})
        assert response.status_code == 201
        assert response.json() == {"email": "new@example.com"}
        assert "HttpOnly" in response.headers["set-cookie"]
        assert client.get("/auth/session").json() == {"email": "new@example.com"}
        with closing(sqlite3.connect(path)) as db:
            rows = db.execute("SELECT email, password_hash FROM accounts").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "new@example.com"
        assert len(rows[0][1]) == 64 and rows[0][1] != b"a new password"

        client.cookies.clear()
        assert client.get("/auth/session").status_code == 401
        assert client.post("/auth/login", json={"email": " NEW@EXAMPLE.COM ", "password": "wrong password"}).status_code == 401
        assert client.post("/auth/login", json={"email": " NEW@EXAMPLE.COM ", "password": "a new password"}).status_code == 200
        assert COOKIE in client.cookies
        assert client.get("/auth/session").json() == {"email": "new@example.com"}


    def test_only_normalized_email_can_conflict(self):
        client = self.client
        password = "a valid password"
        assert client.post("/auth/register", json={"email": "one@example.com", "password": password}).status_code == 201
        for email in ("one@example.com", " ONE@EXAMPLE.COM "):
            result = client.post("/auth/register", json={"email": email, "password": password})
            assert result.status_code == 409
            assert result.json() == {"detail": "duplicate_email"}
        assert client.post("/auth/register", json={"email": "two@example.com", "password": password}).status_code == 201


    def test_validation_does_not_echo_credentials(self):
        for email, password in [("invalid", "private-long-value"), ("one@example.com", "short")]:
            with self.subTest(email=email):
                result = self.client.post("/auth/register", json={"email": email, "password": password})
                assert result.status_code == 422
                assert result.json() == {"detail": "invalid_account_input"}
                assert not self.path.exists()


    def test_storage_failure_is_not_a_duplicate(self):
        client, path = self.client, self.path
        path.mkdir()
        result = client.post("/auth/register", json={"email": "one@example.com", "password": "valid password"})
        assert result.status_code == 500
        assert result.json() == {"detail": "account_storage_error"}
