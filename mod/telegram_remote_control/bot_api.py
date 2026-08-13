"""Small dependency-free Telegram Bot API client."""

from __future__ import annotations

import json
import logging
import re
import ssl
import urllib.error
import urllib.request
from typing import Any, Callable

import certifi

from .constants import (
    BOT_API_ORIGIN,
    LONG_POLL_HTTP_TIMEOUT_SECONDS,
    SHORT_HTTP_TIMEOUT_SECONDS,
)


class TelegramApiError(RuntimeError):
    permanent = False

    def __init__(self, public_message: str, *, error_code: int | None = None):
        self.public_message = public_message
        self.error_code = error_code
        super().__init__(public_message)


class TelegramAuthError(TelegramApiError):
    permanent = True


class TelegramWebhookConflictError(TelegramApiError):
    permanent = True


class TelegramRateLimitError(TelegramApiError):
    def __init__(self, public_message: str, retry_after: float | None = None, *, error_code=None):
        self.retry_after = max(0.0, float(retry_after or 0.0))
        super().__init__(public_message, error_code=error_code)


class TelegramTransientError(TelegramApiError):
    pass


class TelegramProtocolError(TelegramApiError):
    permanent = True


_TELEGRAM_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


def _default_urlopen(request: Any, *, timeout: int):
    return urllib.request.urlopen(
        request,
        timeout=timeout,
        context=_TELEGRAM_SSL_CONTEXT,
    )


def _network_error_kind(exc: BaseException) -> str:
    """Return a secret-free network failure category for diagnostics."""

    reason = getattr(exc, "reason", exc)
    if isinstance(reason, ssl.SSLCertVerificationError):
        code = getattr(reason, "verify_code", None)
        return f"SSLCertVerificationError(code={code})"
    return type(reason).__name__


def _redact(value: Any, token: str) -> str:
    text = str(value)
    if token:
        text = text.replace(token, "***")
        text = text.replace(f"/bot{token}/", "/bot***/")
    return text


def _description_is_webhook_conflict(description: str) -> bool:
    lowered = description.lower()
    return "webhook" in lowered and ("conflict" in lowered or "getupdates" in lowered)


class TelegramBotClient:
    def __init__(
        self,
        token: str,
        logger: logging.Logger | Any,
        urlopen: Callable[..., Any] | None = None,
    ):
        self._token = str(token)
        self._logger = logger
        self._urlopen = urlopen or _default_urlopen

    def get_me(self) -> dict:
        result = self._call("getMe", {}, timeout=SHORT_HTTP_TIMEOUT_SECONDS)
        if not isinstance(result, dict):
            raise TelegramProtocolError("Telegram getMe 응답 형식이 올바르지 않습니다.")
        return result

    def get_updates(self, offset: int | None, timeout: int = 25) -> list[dict]:
        payload: dict[str, Any] = {
            "timeout": int(timeout),
            "allowed_updates": ["message"],
        }
        if offset is not None:
            payload["offset"] = int(offset)
        if int(offset or 0) == -1:
            payload["limit"] = 1
        result = self._call(
            "getUpdates",
            payload,
            timeout=LONG_POLL_HTTP_TIMEOUT_SECONDS if timeout else SHORT_HTTP_TIMEOUT_SECONDS,
        )
        if not isinstance(result, list) or any(not isinstance(item, dict) for item in result):
            raise TelegramProtocolError("Telegram getUpdates 응답 형식이 올바르지 않습니다.")
        return result

    def send_message(self, chat_id: str, text: str) -> dict:
        result = self._call(
            "sendMessage",
            {"chat_id": str(chat_id), "text": str(text)},
            timeout=SHORT_HTTP_TIMEOUT_SECONDS,
        )
        if not isinstance(result, dict):
            raise TelegramProtocolError("Telegram sendMessage 응답 형식이 올바르지 않습니다.")
        return result

    def _call(self, method: str, payload: dict[str, Any], *, timeout: int) -> Any:
        url = f"{BOT_API_ORIGIN}/bot{self._token}/{method}"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        try:
            response = self._urlopen(request, timeout=timeout)
            raw = response.read()
            status = getattr(response, "status", 200)
        except urllib.error.HTTPError as exc:
            status = int(getattr(exc, "code", 0) or 0)
            try:
                raw = exc.read()
            except Exception:
                raw = b""
            return self._raise_response_error(status, raw)
        except (urllib.error.URLError, TimeoutError) as exc:
            public = "Telegram 연결이 일시적으로 실패했습니다."
            self._safe_log("telegram transient error: %s", _network_error_kind(exc))
            raise TelegramTransientError(public) from exc
        except OSError as exc:
            self._safe_log("telegram network error: %s", _network_error_kind(exc))
            raise TelegramTransientError("Telegram 연결이 일시적으로 실패했습니다.") from exc
        if status and status >= 400:
            return self._raise_response_error(status, raw)
        try:
            envelope = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TelegramProtocolError("Telegram 응답을 해석하지 못했습니다.") from exc
        if not isinstance(envelope, dict) or envelope.get("ok") is not True or "result" not in envelope:
            return self._raise_response_error(status, raw, envelope=envelope)
        return envelope["result"]

    def _raise_response_error(self, status: int, raw: bytes, *, envelope: Any = None):
        if envelope is None:
            try:
                envelope = json.loads(raw.decode("utf-8")) if raw else {}
            except (UnicodeDecodeError, json.JSONDecodeError):
                envelope = {}
        if not isinstance(envelope, dict):
            envelope = {}
        description = str(envelope.get("description") or "Telegram API 요청이 실패했습니다.")
        description = _redact(description, self._token)
        code = envelope.get("error_code")
        try:
            code = int(code) if code is not None else status or None
        except (ValueError, TypeError):
            code = status or None
        parameters = envelope.get("parameters")
        retry_after = parameters.get("retry_after") if isinstance(parameters, dict) else None
        if code in (401, 403):
            raise TelegramAuthError("Telegram Bot Token 인증에 실패했습니다.", error_code=code)
        if code == 409 or _description_is_webhook_conflict(description):
            raise TelegramWebhookConflictError(
                "Telegram webhook 충돌로 polling을 시작할 수 없습니다.", error_code=code
            )
        if code == 429:
            raise TelegramRateLimitError(
                "Telegram 요청이 제한되었습니다.", retry_after, error_code=code
            )
        if code is not None and code >= 500:
            raise TelegramTransientError("Telegram 서버가 일시적으로 응답하지 않습니다.", error_code=code)
        raise TelegramProtocolError("Telegram API 응답이 실패를 반환했습니다.", error_code=code)

    def _safe_log(self, message: str, *args: Any) -> None:
        try:
            self._logger.debug(message, *args)
        except Exception:
            pass
