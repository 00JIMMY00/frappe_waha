import frappe
from frappe.model.document import Document

from frappe_waha.utils.waha_client import WAHAClient


class WAHASettings(Document):
    @frappe.whitelist()
    def test_connection(self):
        client = WAHAClient.from_settings()
        sessions = client.list_sessions()
        return {"ok": True, "sessions": len(sessions or [])}

