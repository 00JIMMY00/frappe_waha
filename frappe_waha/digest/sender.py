import frappe
from frappe import _
from frappe.utils import now_datetime

from frappe_waha.digest.periods import get_previous_complete_period
from frappe_waha.digest.renderer import render_pdf, save_digest_pdf
from frappe_waha.utils.phone import phone_to_chat_id, split_recipients
from frappe_waha.utils.waha_client import WAHAClient


SUCCESS_STATUSES = ("Sent", "Partially Sent")


def enqueue_subscription(subscription_name: str, force: bool = False):
    return frappe.enqueue(
        "frappe_waha.digest.sender.generate_and_send",
        queue="long",
        job_name=f"whatsapp_digest:{subscription_name}",
        subscription_name=subscription_name,
        force=force,
        enqueue_after_commit=True,
    )


def generate_and_send(subscription_name: str, force: bool = False) -> str:
    subscription = frappe.get_doc("WhatsApp Digest Subscription", subscription_name)
    subscription.check_permission("read")
    subscription.validate_send_ready()

    period = get_previous_complete_period(subscription)
    existing = find_existing_successful_run(subscription.name, period.end_date)
    if existing and not force:
        return existing

    run_doc = create_run(subscription, period)
    try:
        run_doc.db_set("status", "Rendering", update_modified=False)
        pdf_bytes, context = render_pdf(subscription, period)
        file_doc = save_digest_pdf(run_doc, pdf_bytes, context)
        run_doc.db_set("pdf_file", file_doc.file_url, update_modified=False)
        send_run(run_doc.name, pdf_bytes)
    except Exception:
        run_doc.db_set("status", "Failed", update_modified=False)
        run_doc.db_set("error", frappe.get_traceback(), update_modified=False)
        frappe.log_error(run_doc.error, _("WhatsApp Digest generation failed"))
        raise
    return run_doc.name


def send_run(run_name: str, pdf_bytes: bytes | None = None):
    run_doc = frappe.get_doc("WhatsApp Digest Run", run_name)
    subscription = frappe.get_doc("WhatsApp Digest Subscription", run_doc.subscription)
    sender_phone = frappe.get_doc("WhatsApp Phone", run_doc.whatsapp_phone)
    client = WAHAClient.from_settings()

    if not pdf_bytes:
        pdf_bytes = run_doc.get_pdf_bytes()

    run_doc.db_set("status", "Sending", update_modified=False)
    successes = 0
    failures = 0

    for row in run_doc.recipients:
        if row.status == "Sent":
            successes += 1
            continue

        try:
            response = client.send_pdf_file(
                session=sender_phone.session_name,
                chat_id=phone_to_chat_id(row.phone, sender_phone.default_country_code),
                filename=run_doc.pdf_filename(),
                pdf_bytes=pdf_bytes,
                caption=subscription.message_caption or subscription.title,
            )
            row.status = "Sent"
            row.sent_at = now_datetime()
            row.message_id = extract_message_id(response)
            row.error = None
            successes += 1
        except Exception as exc:
            row.status = "Failed"
            row.error = frappe.get_traceback()
            row.retry_count = (row.retry_count or 0) + 1
            failures += 1
            frappe.log_error(row.error, _("WhatsApp Digest recipient send failed"))

    if successes and not failures:
        run_doc.status = "Sent"
    elif successes:
        run_doc.status = "Partially Sent"
    else:
        run_doc.status = "Failed"

    run_doc.sent_at = now_datetime() if successes else None
    run_doc.save(ignore_permissions=True)

    if successes:
        subscription.db_set("last_sent_at", now_datetime(), update_modified=False)
        subscription.db_set("last_sent_period_end", run_doc.period_end, update_modified=False)
    frappe.db.commit()


def create_run(subscription, period):
    recipients = split_recipients(subscription.recipients, subscription.default_country_code)
    run_doc = frappe.new_doc("WhatsApp Digest Run")
    run_doc.subscription = subscription.name
    run_doc.subscription_title = subscription.title
    run_doc.status = "Pending"
    run_doc.company = subscription.company
    run_doc.whatsapp_phone = subscription.whatsapp_phone
    run_doc.period_start = period.start_date
    run_doc.period_end = period.end_date
    run_doc.period_label = period.label
    for phone in recipients:
        run_doc.append("recipients", {"phone": phone, "status": "Pending"})
    run_doc.insert(ignore_permissions=True)
    return run_doc


def find_existing_successful_run(subscription_name: str, period_end) -> str | None:
    return frappe.db.get_value(
        "WhatsApp Digest Run",
        {
            "subscription": subscription_name,
            "period_end": period_end,
            "status": ["in", SUCCESS_STATUSES],
        },
        "name",
    )


def extract_message_id(response):
    if isinstance(response, dict):
        return response.get("id") or response.get("messageId") or response.get("_data", {}).get("id")
    return None
