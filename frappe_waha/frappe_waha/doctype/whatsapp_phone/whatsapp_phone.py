import hashlib

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from frappe_waha.utils.phone import normalize_phone
from frappe_waha.utils.waha_client import WAHAClient


class WhatsAppPhone(Document):
    def validate(self):
        settings = frappe.get_single("WAHA Settings")
        self.default_country_code = self.default_country_code or settings.default_country_code
        self.phone = normalize_phone(self.phone, self.default_country_code)
        self.session_name = self.session_name or self.make_session_name()
        self.status = self.status or "Pending"

    def make_session_name(self) -> str:
        digest = hashlib.sha1(self.phone.encode()).hexdigest()[:10]
        return f"wa_{digest}"

    @frappe.whitelist()
    def create_or_start_session(self):
        self.check_permission("write")
        client = WAHAClient.from_settings()
        if not self.session_name:
            self.session_name = self.make_session_name()
            self.save()

        try:
            client.create_session(self.session_name, start=True)
        except Exception:
            try:
                client.start_session(self.session_name)
            except Exception:
                raise

        return self.sync_from_waha(client=client, save=True)

    @frappe.whitelist()
    def get_qr(self):
        self.check_permission("read")
        if not self.session_name:
            frappe.throw(_("Create the WAHA session first."))
        return {"image": WAHAClient.from_settings().get_qr_image_data_url(self.session_name)}

    @frappe.whitelist()
    def sync_status(self):
        self.check_permission("read")
        return self.sync_from_waha(save=True)

    @frappe.whitelist()
    def stop_session(self):
        self.check_permission("write")
        WAHAClient.from_settings().stop_session(self.session_name)
        return self.sync_from_waha(save=True)

    @frappe.whitelist()
    def logout_session(self):
        self.check_permission("write")
        WAHAClient.from_settings().logout_session(self.session_name)
        self.status = "Expired"
        self.session_status = "STOPPED"
        self.save(ignore_permissions=True)
        return self.as_dict()

    def sync_from_waha(self, client=None, save=False):
        client = client or WAHAClient.from_settings()
        session = client.get_session(self.session_name)
        self.session_status = session.get("status")
        self.whatsapp_id = (session.get("me") or {}).get("id")
        self.last_synced_at = now_datetime()
        if self.session_status == "WORKING":
            self.status = "Active"
        elif self.session_status in ("STARTING", "SCAN_QR_CODE"):
            self.status = "Waiting For Activation"
        elif self.session_status == "FAILED":
            self.status = "Expired"
        elif self.status != "Expired":
            self.status = "Pending"

        if save:
            self.save(ignore_permissions=True)
            frappe.db.commit()
        return self.as_dict()

