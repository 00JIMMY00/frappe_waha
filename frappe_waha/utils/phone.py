import re

import frappe
from frappe import _


def normalize_phone(phone: str, default_country_code: str | None = None) -> str:
    phone = (phone or "").strip()
    if not phone:
        frappe.throw(_("Phone number is required."))

    default_country_code = (default_country_code or "").strip()
    compact = re.sub(r"[\s().-]+", "", phone)

    if compact.startswith("00"):
        compact = "+" + compact[2:]

    if compact.startswith("+"):
        number = "+" + re.sub(r"\D", "", compact)
    else:
        digits = re.sub(r"\D", "", compact)
        if default_country_code:
            country_digits = re.sub(r"\D", "", default_country_code)
            country = "+" + country_digits
            if digits.startswith(country_digits):
                number = "+" + digits
            elif digits.startswith("0"):
                digits = digits[1:]
                number = country + digits
            else:
                number = country + digits
        else:
            number = "+" + digits

    if not re.fullmatch(r"\+\d{8,15}", number):
        frappe.throw(_("Invalid WhatsApp phone number: {0}").format(frappe.bold(phone)))

    return number


def phone_to_chat_id(phone: str, default_country_code: str | None = None) -> str:
    return normalize_phone(phone, default_country_code).lstrip("+") + "@c.us"


def split_recipients(raw_recipients: str, default_country_code: str | None = None) -> list[str]:
    recipients = []
    seen = set()

    for line in (raw_recipients or "").replace(",", "\n").splitlines():
        line = line.strip()
        if not line:
            continue

        phone = normalize_phone(line, default_country_code)
        if phone not in seen:
            seen.add(phone)
            recipients.append(phone)

    if not recipients:
        frappe.throw(_("Add at least one WhatsApp recipient phone number."))

    return recipients
