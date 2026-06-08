from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import frappe
import requests
from frappe import _
from frappe.utils.password import get_decrypted_password


class OpenWAError(frappe.ValidationError):
    pass


@dataclass
class OpenWAClient:
    base_url: str
    api_key: str | None = None
    timeout: int = 20

    @classmethod
    def from_settings(cls) -> "OpenWAClient":
        settings = frappe.get_single("WAHA Settings")
        parsed = urlparse(settings.server_base_url or "")
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            frappe.throw(_("Set a valid OpenWA Server Base URL, for example https://openwa.arab-erp.com."))

        api_key = get_decrypted_password("WAHA Settings", "WAHA Settings", "api_key", raise_exception=False)
        if not api_key:
            frappe.throw(_("Set OpenWA API Key in WhatsApp Settings."))

        return cls(
            base_url=settings.server_base_url,
            api_key=api_key,
            timeout=settings.request_timeout or 20,
        )

    def list_sessions(self) -> list[dict[str, Any]]:
        response = self.request("GET", "/sessions")
        if isinstance(response, list):
            return response
        if isinstance(response, dict):
            data = response.get("data")
            if isinstance(data, list):
                return data
        return []

    def create_session(self, session_name: str) -> dict[str, Any]:
        try:
            return self.request("POST", "/sessions", json={"name": session_name})
        except OpenWAError as exc:
            if "already" not in str(exc).lower() and "exists" not in str(exc).lower():
                raise
            existing = self.find_session(session_name)
            if existing:
                return existing
            raise

    def start_session(self, session_ref: str) -> dict[str, Any]:
        session_id = self.resolve_session_id(session_ref)
        try:
            return self.request("POST", f"/sessions/{session_id}/start")
        except OpenWAError as exc:
            message = str(exc).lower()
            if "already" in message or "active" in message or "started" in message:
                return self.get_session(session_id)
            raise

    def stop_session(self, session_ref: str) -> dict[str, Any]:
        session_id = self.resolve_session_id(session_ref)
        return self.request("POST", f"/sessions/{session_id}/stop")

    def logout_session(self, session_ref: str) -> dict[str, Any]:
        session_id = self.resolve_session_id(session_ref)
        return self.request("POST", f"/sessions/{session_id}/logout")

    def delete_session(self, session_ref: str) -> dict[str, Any]:
        session_id = self.resolve_session_id(session_ref)
        return self.request("DELETE", f"/sessions/{session_id}")

    def get_session(self, session_ref: str) -> dict[str, Any]:
        try:
            return self.request("GET", f"/sessions/{session_ref}")
        except OpenWAError as exc:
            if "not found" not in str(exc).lower():
                raise
            session = self.find_session(session_ref)
            if session:
                return session
            raise

    def find_session(self, session_ref: str) -> dict[str, Any] | None:
        for session in self.list_sessions():
            if session.get("id") == session_ref or session.get("name") == session_ref:
                return session
        return None

    def resolve_session_id(self, session_ref: str) -> str:
        session = self.get_session(session_ref)
        return session.get("id") or session_ref

    def get_qr_image_data_url(self, session_ref: str) -> str:
        session_id = self.resolve_session_id(session_ref)
        response = self.request("GET", f"/sessions/{session_id}/qr")
        if isinstance(response, dict):
            qr = response.get("qrCode") or response.get("image") or response.get("qr")
            data = response.get("data") if isinstance(response.get("data"), dict) else {}
            qr = qr or data.get("qrCode") or data.get("image") or data.get("qr")
            if qr:
                return qr
        frappe.throw(_("OpenWA did not return a QR image."))

    def send_text(self, *, session: str, chat_id: str, text: str) -> dict[str, Any]:
        session_id = self.resolve_session_id(session)
        return self.request(
            "POST",
            f"/sessions/{session_id}/messages/send-text",
            json={"chatId": chat_id, "text": text},
        )

    def send_document_file(
        self,
        *,
        session: str,
        chat_id: str,
        filename: str,
        content: bytes,
        mimetype: str = "application/octet-stream",
        caption: str | None = None,
    ) -> dict[str, Any]:
        session_id = self.resolve_session_id(session)
        return self.request(
            "POST",
            f"/sessions/{session_id}/messages/send-document",
            json={
                "chatId": chat_id,
                "base64": base64.b64encode(content).decode(),
                "mimetype": mimetype,
                "filename": filename,
                "caption": caption or "",
            },
        )

    def send_pdf_file(
        self,
        *,
        session: str,
        chat_id: str,
        filename: str,
        pdf_bytes: bytes,
        caption: str | None = None,
    ) -> dict[str, Any]:
        return self.send_document_file(
            session=session,
            chat_id=chat_id,
            filename=filename,
            content=pdf_bytes,
            mimetype="application/pdf",
            caption=caption,
        )

    def send_image_file(
        self,
        *,
        session: str,
        chat_id: str,
        filename: str,
        content: bytes,
        mimetype: str,
        caption: str | None = None,
    ) -> dict[str, Any]:
        session_id = self.resolve_session_id(session)
        return self.request(
            "POST",
            f"/sessions/{session_id}/messages/send-image",
            json={
                "chatId": chat_id,
                "base64": base64.b64encode(content).decode(),
                "mimetype": mimetype,
                "filename": filename,
                "caption": caption or "",
            },
        )

    def request(self, method: str, path: str, **kwargs) -> Any:
        response = self.raw_request(method, path, **kwargs)
        if not response.content:
            return {}
        try:
            payload = response.json()
        except ValueError:
            return {"raw": response.text}

        if isinstance(payload, dict) and payload.get("success") is True and "data" in payload:
            return payload.get("data")
        if isinstance(payload, dict) and payload.get("success") is False:
            error = payload.get("error") or {}
            frappe.throw(error.get("message") or _("OpenWA request failed."), OpenWAError)
        return payload

    def raw_request(self, method: str, path: str, **kwargs) -> requests.Response:
        url = self._url(path)
        headers = kwargs.pop("headers", {}) or {}
        headers.setdefault("Accept", "application/json")
        if self.api_key:
            headers["X-API-Key"] = self.api_key

        try:
            response = requests.request(method, url, headers=headers, timeout=self.timeout, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            detail = exc.response.text if getattr(exc, "response", None) is not None else str(exc)
            raise OpenWAError(_("OpenWA request failed: {0}").format(detail[:500])) from exc

    def _url(self, path: str) -> str:
        base = self.base_url.rstrip("/")
        if not base.endswith("/api"):
            base = base + "/api"
        clean_path = "/" + path.lstrip("/")
        if clean_path.startswith("/api/"):
            clean_path = clean_path[4:]
        return base + clean_path
