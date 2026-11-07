import hashlib
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import app as api


class FakeCollection:
    def __init__(self, documents=None):
        self.documents = list(documents or [])

    def find_one(self, query):
        for document in self.documents:
            matched = True
            for key, expected in query.items():
                actual = document.get(key)
                if isinstance(expected, dict):
                    if "$gt" in expected and (actual is None or actual <= expected["$gt"]):
                        matched = False
                        break
                    if "$ne" in expected and actual == expected["$ne"]:
                        matched = False
                        break
                elif actual != expected:
                    matched = False
                    break
            if matched:
                return document
        return None

    def insert_one(self, document):
        document = dict(document)
        document["_id"] = "test-user-id"
        self.documents.append(document)
        return SimpleNamespace(inserted_id=document["_id"])

    def update_one(self, query, update):
        document = self.find_one(query)
        if not document:
            return
        document.update(update.get("$set", {}))
        for key in update.get("$unset", {}):
            document.pop(key, None)

    def delete_one(self, query):
        document = self.find_one(query)
        if document:
            self.documents.remove(document)


class FakePasswordContext:
    def hash(self, password):
        return f"hashed:{password}"

    def verify(self, password, password_hash):
        return password_hash == f"hashed:{password}"


class RateLimiterTests(unittest.TestCase):
    def test_rejects_requests_until_window_expires(self):
        limiter = api.SlidingWindowLimiter()
        self.assertEqual(limiter.hit("ip", 2, 60, at=100), (True, 0))
        self.assertEqual(limiter.hit("ip", 2, 60, at=101), (True, 0))
        allowed, retry_after = limiter.hit("ip", 2, 60, at=102)
        self.assertFalse(allowed)
        self.assertGreater(retry_after, 0)
        self.assertEqual(limiter.hit("ip", 2, 60, at=161), (True, 0))


class SecurityConfigurationTests(unittest.TestCase):
    def test_short_secrets_are_rejected(self):
        with patch.object(api, "JWT_SECRET", "too-short"), patch.object(api, "ADMIN_PASSWORD", "weak"):
            with self.assertRaises(RuntimeError):
                api.validate_security_config()


class EmailVerificationTests(unittest.TestCase):
    def test_registration_stores_only_a_hashed_verification_token(self):
        users = FakeCollection()
        with patch.object(api, "users", users), \
             patch.object(api, "pwd", FakePasswordContext()), \
             patch.object(api, "send_verification_email", return_value=False) as send_email, \
             patch.object(api, "record"):
            result = api.register(api.RegisterInput(name="Avery Morgan", email="avery@example.com", password="StrongPass123!"))

        stored = users.documents[0]
        self.assertFalse(stored["email_verified"])
        self.assertEqual(stored["status"], "pending")
        self.assertEqual(len(stored["verification_token_hash"]), 64)
        self.assertNotIn("verification_token", stored)
        send_email.assert_called_once()
        self.assertIn("backend console", result["message"])

    def test_verification_activates_only_a_valid_unexpired_token(self):
        token = "sample-verification-token-which-is-long-enough"
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        users = FakeCollection([{
            "_id": "test-user-id", "email": "avery@example.com", "email_verified": False,
            "verification_token_hash": token_hash,
            "verification_expires_at": api.now() + timedelta(hours=1),
        }])
        with patch.object(api, "users", users):
            response = api.verify_email(api.VerifyEmailInput(token=token))
        self.assertTrue(users.documents[0]["email_verified"])
        self.assertNotIn("verification_token_hash", users.documents[0])
        self.assertIn("waiting for admin approval", response["message"])

    def test_expired_verification_token_is_rejected(self):
        token = "expired-verification-token-which-is-long-enough"
        users = FakeCollection([{
            "_id": "test-user-id", "email_verified": False,
            "verification_token_hash": hashlib.sha256(token.encode()).hexdigest(),
            "verification_expires_at": api.now() - timedelta(seconds=1),
        }])
        with patch.object(api, "users", users):
            with self.assertRaises(api.HTTPException) as raised:
                api.verify_email(api.VerifyEmailInput(token=token))
        self.assertEqual(raised.exception.status_code, 400)

    def test_unverified_account_cannot_sign_in(self):
        user = {"_id": "test-user-id", "email": "avery@example.com", "password_hash": "hashed:StrongPass123!",
                "role": "user", "status": "pending", "email_verified": False}
        with patch.object(api, "users", FakeCollection([user])), patch.object(api, "pwd", FakePasswordContext()):
            with self.assertRaises(api.HTTPException) as raised:
                api.login(api.LoginInput(email="avery@example.com", password="StrongPass123!"))
        self.assertEqual(raised.exception.status_code, 403)
        self.assertIn("verify your email", raised.exception.detail)

    def test_email_change_requires_a_new_verification(self):
        user = {"_id": "test-user-id", "name": "Avery Morgan", "email": "avery@example.com",
                "role": "user", "status": "approved", "email_verified": True,
                "created_at": api.now()}
        users = FakeCollection([user])
        with patch.object(api, "users", users), \
             patch.object(api, "send_verification_email", return_value=False), \
             patch.object(api, "record"):
            updated = api.update_profile(api.ProfileInput(name="Avery Morgan", email="avery.new@example.com"), user)
        self.assertEqual(updated["email"], "avery.new@example.com")
        self.assertFalse(updated["email_verified"])
        self.assertIn("verification_token_hash", users.documents[0])


if __name__ == "__main__":
    unittest.main()
