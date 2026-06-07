import base64
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import frappe
import requests
from frappe import _
from frappe.utils.password import get_decrypted_password


class WAHAError(frappe.ValidationError):
    pass


@dataclass
class WAHAClient:
    base_url: str
    api_key: str | None = None
    timeout: int = 20

    @classmethod
    def from_settings(cls) -> "WAHAClient":
        settings = frappe.get_single("WAHA Settings")
        if not settings.server_base_url:
            frappe.throw(_("Set Server Base URL in WAHA Settings."))

        api_key = get_decrypted_password("WAHA Settings", "WAHA Settings", "api_key", raise_exception=False)
        return cls(
            base_url=settings.server_base_url,
            api_key=api_key,
            timeout=settings.request_timeout or 20,
        )

    def list_sessions(self) -> list[dict[str, Any]]:
        return self.request("GET", "/api/sessions")

    def create_session(self, session_name: str, start: bool = True) -> dict[str, Any]:
        return self.request("POST", "/api/sessions", json={"name": session_name, "start": start})

    def start_session(self, session_name: str) -> dict[str, Any]:
        return self.request("POST", f"/api/sessions/{session_name}/start")

    def stop_session(self, session_name: str) -> dict[str, Any]:
        return self.request("POST", f"/api/sessions/{session_name}/stop")

    def logout_session(self, session_name: str) -> dict[str, Any]:
        return self.request("POST", f"/api/sessions/{session_name}/logout")

    def get_session(self, session_name: str) -> dict[str, Any]:
        return self.request("GET", f"/api/sessions/{session_name}")

    def get_qr_image_data_url(self, session_name: str) -> str:
        path = f"/api/{session_name}/auth/qr?{urlencode({'format': 'image'})}"
        response = self.raw_request("GET", path)
        content_type = response.headers.get("content-type") or "image/png"
        data = base64.b64encode(response.content).decode()
        return f"data:{content_type};base64,{data}"

    def send_pdf_file(
        self,
        *,
        session: str,
        chat_id: str,
        filename: str,
        pdf_bytes: bytes,
        caption: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "session": session,
            "chatId": chat_id,
            "caption": caption or "",
            "file": {
                "mimetype": "application/pdf",
                "filename": filename,
                "data": base64.b64encode(pdf_bytes).decode(),
            },
        }
        return self.request("POST", "/api/sendFile", json=payload)

    def request(self, method: str, path: str, **kwargs) -> Any:
        response = self.raw_request(method, path, **kwargs)
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError:
            return {"raw": response.text}

    def raw_request(self, method: str, path: str, **kwargs) -> requests.Response:
        url = self._url(path)
        headers = kwargs.pop("headers", {}) or {}
        headers.setdefault("Accept", "application/json")
        if self.api_key:
            headers["X-Api-Key"] = self.api_key

        try:
            response = requests.request(method, url, headers=headers, timeout=self.timeout, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            detail = getattr(exc.response, "text", "") if getattr(exc, "response", None) else str(exc)
            raise WAHAError(_("WAHA request failed: {0}").format(detail[:500])) from exc

    def _url(self, path: str) -> str:
        base = self.base_url.rstrip("/")
        clean_path = "/" + path.lstrip("/")
        return base + clean_path

