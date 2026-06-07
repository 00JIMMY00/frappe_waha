import frappe
from frappe import _
from frappe.model.document import Document

from frappe_waha.digest.metrics import get_metric_catalog
from frappe_waha.digest.periods import get_current_period
from frappe_waha.digest.renderer import render_html, selected_metric_codes
from frappe_waha.digest.sender import enqueue_subscription
from frappe_waha.utils.phone import split_recipients


COMPARE_DEFAULTS = {
    "Daily": "previous_day",
    "Weekly": "previous_week",
    "Monthly": "previous_month",
    "Quarterly": "previous_quarter",
    "Yearly": "previous_year",
}


class WhatsAppDigestSubscription(Document):
    def validate(self):
        self.channel = "WhatsApp"
        self.compare_vs = self.compare_vs or COMPARE_DEFAULTS.get(self.frequency)
        self.set_sender_country_code()
        self.validate_metrics()
        split_recipients(self.recipients, self.default_country_code)

    def set_sender_country_code(self):
        if self.whatsapp_phone:
            self.default_country_code = frappe.db.get_value(
                "WhatsApp Phone", self.whatsapp_phone, "default_country_code"
            )
        if not self.default_country_code:
            self.default_country_code = frappe.get_single("WAHA Settings").default_country_code

    def validate_metrics(self):
        if not self.subscribed_metrics:
            return

        codes = selected_metric_codes(self)
        valid_codes = {
            row.name
            for row in frappe.get_all("WhatsApp Digest Metric", filters={"enabled": 1}, fields=["name"])
        }
        invalid = [code for code in codes if code not in valid_codes]
        if invalid:
            frappe.throw(_("Unknown digest metrics: {0}").format(", ".join(invalid)))

    def validate_send_ready(self):
        if not self.enabled:
            frappe.throw(_("Digest Subscription is disabled."))

        if not self.whatsapp_phone:
            frappe.throw(_("Select a WhatsApp Phone."))

        phone_status = frappe.db.get_value(
            "WhatsApp Phone", self.whatsapp_phone, ["status", "session_status", "session_name"], as_dict=True
        )
        if not phone_status or phone_status.status != "Active" or phone_status.session_status != "WORKING":
            frappe.throw(_("WhatsApp Phone must be Active and WORKING before sending."))

        if not phone_status.session_name:
            frappe.throw(_("WhatsApp Phone has no WAHA session name."))

        split_recipients(self.recipients, self.default_country_code)

    @frappe.whitelist()
    def get_available_metrics(self):
        return get_metric_catalog()

    @frappe.whitelist()
    def preview_digest(self, start_date=None):
        self.check_permission("read")
        period = get_current_period(self.frequency, start_date, self.weekly_day) if start_date else None
        html, context = render_html(self, period)
        return {
            "html": html,
            "period_label": context.get("period_label"),
            "comparison_label": context.get("comparison_label"),
        }

    @frappe.whitelist()
    def send_now(self):
        self.check_permission("write")
        self.validate_send_ready()
        job = enqueue_subscription(self.name, force=True)
        return {"queued": True, "job": getattr(job, "id", None)}
