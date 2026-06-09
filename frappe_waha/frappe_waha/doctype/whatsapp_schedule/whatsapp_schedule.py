import frappe
from frappe import _
from frappe.model.document import Document

from frappe_waha.digest.automation import enqueue_automation


class WhatsAppSchedule(Document):
    def validate(self):
        self.frequency = self.frequency or "Daily"
        if not frappe.db.get_value("WhatsApp Automation", self.automation, "enabled"):
            frappe.throw(_("Select an enabled WhatsApp Automation."))

    @frappe.whitelist()
    def run_now(self):
        self.check_permission("write")
        job = enqueue_automation(self.automation, force=True, schedule=self.name, source_event="Schedule")
        return {"queued": True, "job": getattr(job, "id", None)}
