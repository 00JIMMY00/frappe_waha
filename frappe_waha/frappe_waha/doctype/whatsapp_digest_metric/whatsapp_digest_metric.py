import frappe
from frappe import _
from frappe.model.document import Document

from frappe_waha.digest.metrics import import_provider


class WhatsAppDigestMetric(Document):
    def validate(self):
        self.code = frappe.scrub(self.code)
        if not self.provider_path or "." not in self.provider_path:
            frappe.throw(_("Provider Path must be a dotted Python path."))
        import_provider(self.provider_path)

