from __future__ import annotations

import json
import ssl
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import certifi

from mod.telegram_remote_control.bot_api import (
    _TELEGRAM_SSL_CONTEXT,
    _default_urlopen,
    TelegramAuthError,
    TelegramBotClient,
    TelegramRateLimitError,
    TelegramTransientError,
    TelegramWebhookConflictError,
)


class _Response:
    status = 200

    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self.payload


class BotApiTests(unittest.TestCase):
    def test_default_transport_uses_certifi_with_verification_enabled(self):
        self.assertTrue(Path(certifi.where()).is_file())
        sentinel = object()
        with patch("mod.telegram_remote_control.bot_api.urllib.request.urlopen") as urlopen:
            urlopen.return_value = sentinel

            result = _default_urlopen("request", timeout=7)

        self.assertIs(result, sentinel)
        self.assertIs(urlopen.call_args.kwargs["context"], _TELEGRAM_SSL_CONTEXT)
        self.assertEqual(_TELEGRAM_SSL_CONTEXT.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(_TELEGRAM_SSL_CONTEXT.check_hostname)

    def test_certificate_failure_log_is_specific_and_secret_free(self):
        token = "123:" + "x" * 20

        class _Logger:
            def __init__(self):
                self.messages = []

            def debug(self, message, *args):
                self.messages.append(message % args)

        logger = _Logger()

        def certificate_failure(_request, timeout):
            error = ssl.SSLCertVerificationError(1, f"certificate failed {token}")
            raise urllib.error.URLError(error)

        with self.assertRaises(TelegramTransientError):
            TelegramBotClient(token, logger, urlopen=certificate_failure).get_me()

        self.assertEqual(len(logger.messages), 1)
        self.assertIn("SSLCertVerificationError", logger.messages[0])
        self.assertNotIn(token, logger.messages[0])

    def test_get_updates_discards_only_one_startup_update(self):
        requests = []

        def urlopen(request, timeout):
            requests.append((request, timeout))
            return _Response({"ok": True, "result": []})

        client = TelegramBotClient("123:" + "x" * 20, None, urlopen=urlopen)
        self.assertEqual(client.get_updates(-1, timeout=0), [])
        body = json.loads(requests[0][0].data.decode("utf-8"))
        self.assertEqual(body["offset"], -1)
        self.assertEqual(body["limit"], 1)
        self.assertEqual(body["allowed_updates"], ["message", "callback_query"])

    def test_inline_keyboard_and_callback_answer_payloads(self):
        requests = []

        def urlopen(request, timeout):
            requests.append(request)
            result = True if request.full_url.endswith("/answerCallbackQuery") else {"message_id": 1}
            return _Response({"ok": True, "result": result})

        client = TelegramBotClient("123:" + "x" * 20, None, urlopen=urlopen)
        markup = {"inline_keyboard": [[{"text": "퀘스트", "callback_data": "quest:root"}]]}

        client.send_message("1", "choose", reply_markup=markup)
        self.assertTrue(client.answer_callback_query("callback-1"))

        send_body = json.loads(requests[0].data.decode("utf-8"))
        callback_body = json.loads(requests[1].data.decode("utf-8"))
        self.assertEqual(send_body["reply_markup"], markup)
        self.assertEqual(callback_body, {"callback_query_id": "callback-1"})

    def test_error_mapping_does_not_expose_token(self):
        token = "123:" + "x" * 20

        def urlopen(_request, timeout):
            return _Response(
                {
                    "ok": False,
                    "error_code": 429,
                    "description": f"retry token={token}",
                    "parameters": {"retry_after": 2},
                }
            )

        with self.assertRaises(TelegramRateLimitError) as caught:
            TelegramBotClient(token, None, urlopen=urlopen).send_message("1", "hello")
        self.assertNotIn(token, str(caught.exception))
        self.assertEqual(caught.exception.retry_after, 2)

        def unauthorized(_request, timeout):
            return _Response({"ok": False, "error_code": 401, "description": "bad"})

        with self.assertRaises(TelegramAuthError):
            TelegramBotClient(token, None, urlopen=unauthorized).get_me()

        def conflict(_request, timeout):
            return _Response({"ok": False, "error_code": 409, "description": "webhook conflict"})

        with self.assertRaises(TelegramWebhookConflictError):
            TelegramBotClient(token, None, urlopen=conflict).get_updates(None, timeout=0)


if __name__ == "__main__":
    unittest.main()
