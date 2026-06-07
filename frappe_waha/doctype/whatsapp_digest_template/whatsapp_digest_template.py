import frappe
from frappe import _
from frappe.model.document import Document

from frappe_waha.digest.metrics import import_provider


class WhatsAppDigestTemplate(Document):
    def validate(self):
        if self.python_context_path:
            import_provider(self.python_context_path)

        if self.is_default:
            existing = frappe.db.get_value(
                "WhatsApp Digest Template",
                {"is_default": 1, "name": ["!=", self.name]},
                "name",
            )
            if existing:
                frappe.db.set_value("WhatsApp Digest Template", existing, "is_default", 0)

