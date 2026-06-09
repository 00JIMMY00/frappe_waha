import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils.file_manager import get_file

from frappe_waha.digest.sender import send_run
from frappe_waha.digest.automation import send_automation_run


class WhatsAppDigestRun(Document):
    def before_save(self):
        self.set_counts()

    def set_counts(self):
        # Placeholder for future summary counters without changing the persisted schema.
        return

    def get_pdf_bytes(self) -> bytes:
        if not self.pdf_file:
            frappe.throw(_("Digest run has no PDF file."))
        _filename, content = get_file(self.pdf_file)
        return content

    def pdf_filename(self) -> str:
        title = frappe.scrub(self.automation_title or self.subscription_title or self.automation or self.subscription or self.name)
        return f"{title}_{self.period_end}.pdf"

    @frappe.whitelist()
    def retry_failed(self):
        self.check_permission("read")
        if self.automation:
            send_automation_run(self.name)
            return True
        if not self.pdf_file:
            frappe.throw(_("Digest run has no PDF file to retry."))
        send_run(self.name)
        return True
