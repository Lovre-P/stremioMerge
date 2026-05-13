import hashlib
import io
import unittest
from unittest.mock import patch

import stremio_merge


class AuthTests(unittest.TestCase):
    def test_password_login_uses_md5_hash_first(self):
        calls = []

        def fake_api_post(url, payload):
            calls.append((url, payload))
            return {"result": {"authKey": "hashed-auth"}}

        with patch.object(stremio_merge, "api_post", side_effect=fake_api_post):
            auth_key = stremio_merge.login_with_password("user@example.com", "secret")

        self.assertEqual(auth_key, "hashed-auth")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], f"{stremio_merge.API_BASE}/login")
        self.assertEqual(calls[0][1]["email"], "user@example.com")
        self.assertEqual(
            calls[0][1]["password"],
            hashlib.md5("secret".encode()).hexdigest(),
        )
        self.assertEqual(calls[0][1]["type"], "Login")

    def test_password_login_falls_back_to_plain_password(self):
        calls = []

        def fake_api_post(url, payload):
            calls.append((url, payload))
            if len(calls) == 1:
                return {}
            return {"result": {"authKey": "plain-auth"}}

        with patch.object(stremio_merge, "api_post", side_effect=fake_api_post):
            auth_key = stremio_merge.login_with_password("user@example.com", "secret")

        self.assertEqual(auth_key, "plain-auth")
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1][1]["password"], "secret")

    def test_token_login_accepts_valid_auth_key(self):
        calls = []

        def fake_api_post(url, payload):
            calls.append((url, payload))
            return {"result": {"authKey": "fresh-auth"}}

        with patch.object(stremio_merge, "api_post", side_effect=fake_api_post):
            auth_key = stremio_merge.login_with_token(" pasted-token ")

        self.assertEqual(auth_key, "fresh-auth")
        self.assertEqual(calls, [
            (
                f"{stremio_merge.API_BASE}/loginWithToken",
                {"type": "LoginWithToken", "token": "pasted-token"},
            )
        ])

    def test_token_login_rejects_invalid_auth_key(self):
        with patch.object(stremio_merge, "api_post", return_value={"error": "invalid"}):
            self.assertIsNone(stremio_merge.login_with_token("bad-token"))

        with patch.object(stremio_merge, "api_post") as api_post:
            self.assertIsNone(stremio_merge.login_with_token("   "))
            api_post.assert_not_called()

    def test_prompt_routes_email_password_choice(self):
        with patch("builtins.input", side_effect=["1", "user@example.com"]), \
                patch("getpass.getpass", return_value="secret"), \
                patch("sys.stdout", new_callable=io.StringIO), \
                patch.object(stremio_merge, "login_with_password", return_value="email-auth") as login:
            auth_key, identity = stremio_merge.prompt_account_auth("SOURCE account")

        self.assertEqual(auth_key, "email-auth")
        self.assertEqual(identity, "user@example.com")
        login.assert_called_once_with("user@example.com", "secret")

    def test_prompt_routes_auth_key_choice_after_invalid_choice(self):
        with patch("builtins.input", side_effect=["x", "2"]), \
                patch("getpass.getpass", return_value="token"), \
                patch("sys.stdout", new_callable=io.StringIO), \
                patch.object(stremio_merge, "login_with_token", return_value="token-auth") as login:
            auth_key, identity = stremio_merge.prompt_account_auth("DESTINATION account")

        self.assertEqual(auth_key, "token-auth")
        self.assertEqual(identity, "auth key")
        login.assert_called_once_with("token")


if __name__ == "__main__":
    unittest.main()
