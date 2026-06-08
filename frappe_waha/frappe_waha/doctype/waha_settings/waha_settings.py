import frappe
from frappe import _
from frappe.model.document import Document
from urllib.parse import urlparse

from frappe_waha.utils.openwa_client import OpenWAClient


class WAHASettings(Document):
    def validate(self):
        parsed = urlparse(self.server_base_url or "")
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            frappe.throw(_("Server Base URL must include http:// or https://, for example https://openwa.arab-erp.com"))

    @frappe.whitelist()
    def test_connection(self):
        client = OpenWAClient.from_settings()
        sessions = client.list_sessions()
        return {"ok": True, "sessions": len(sessions or [])}
