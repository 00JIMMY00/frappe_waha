import hashlib

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from frappe_waha.utils.phone import normalize_phone
from frappe_waha.utils.openwa_client import OpenWAClient, OpenWAError


ACTIVE_SESSION_STATUSES = {"ready", "connected", "CONNECTED", "WORKING"}
WAITING_SESSION_STATUSES = {
    "created",
    "initializing",
    "qr_ready",
    "SCAN_QR",
    "SCAN_QR_CODE",
    "CONNECTING",
    "STARTING",
}
FAILED_SESSION_STATUSES = {"error", "failed", "FAILED"}


class WhatsAppPhone(Document):
    def validate(self):
        settings = frappe.get_single("WAHA Settings")
        self.default_country_code = self.default_country_code or settings.default_country_code
        self.phone = normalize_phone(self.phone, self.default_country_code)
        self.session_name = self.session_name or self.make_session_name()
        self.status = self.status or "Pending"

    def make_session_name(self) -> str:
        digest = hashlib.sha1(self.phone.encode()).hexdigest()[:10]
        return f"wa-{digest}"

    @frappe.whitelist()
    def create_or_start_session(self):
        self.check_permission("write")
        client = OpenWAClient.from_settings()
        if not self.session_name:
            self.session_name = self.make_session_name()
            self.save()

        session = client.create_session(self.provider_session_name or self.session_name)
        self.apply_openwa_session(session)
        self.save(ignore_permissions=True)

        client.start_session(self.session_name)

        return self.sync_from_openwa(client=client, save=True)

    @frappe.whitelist()
    def get_qr(self):
        self.check_permission("read")
        if not self.session_name:
            frappe.throw(_("Create the OpenWA session first."))
        try:
            return {"image": OpenWAClient.from_settings().get_qr_image_data_url(self.session_name)}
        except OpenWAError as exc:
            if "already authenticated" in str(exc).lower():
                return {"connected": True}
            raise

    @frappe.whitelist()
    def sync_status(self):
        self.check_permission("read")
        return self.sync_from_openwa(save=True)

    @frappe.whitelist()
    def stop_session(self):
        self.check_permission("write")
        OpenWAClient.from_settings().stop_session(self.session_name)
        return self.sync_from_openwa(save=True)

    @frappe.whitelist()
    def logout_session(self):
        self.check_permission("write")
        OpenWAClient.from_settings().logout_session(self.session_name)
        self.status = "Expired"
        self.session_status = "stopped"
        self.save(ignore_permissions=True)
        return self.as_dict()

    def sync_from_waha(self, client=None, save=False):
        return self.sync_from_openwa(client=client, save=save)

    def sync_from_openwa(self, client=None, save=False):
        client = client or OpenWAClient.from_settings()
        try:
            session = client.get_session(self.session_name)
        except OpenWAError as exc:
            if "not found" not in str(exc).lower():
                raise
            self.session_status = None
            self.status = "Pending"
            self.last_synced_at = now_datetime()
            if save:
                self.save(ignore_permissions=True)
                frappe.db.commit()
            return self.as_dict()

        self.apply_openwa_session(session)
        self.last_synced_at = now_datetime()

        status = self.session_status
        if status in ACTIVE_SESSION_STATUSES:
            self.status = "Active"
        elif status in WAITING_SESSION_STATUSES:
            self.status = "Waiting For Activation"
        elif status in FAILED_SESSION_STATUSES:
            self.status = "Expired"
        elif self.status != "Expired":
            self.status = "Pending"

        if save:
            self.save(ignore_permissions=True)
            frappe.db.commit()
        return self.as_dict()

    def apply_openwa_session(self, session):
        if not session:
            return
        self.session_name = session.get("id") or self.session_name
        self.provider_session_name = session.get("name") or self.provider_session_name
        self.session_status = session.get("status")
        self.whatsapp_id = session.get("phone") or session.get("phoneNumber") or self.whatsapp_id
