import frappe
from frappe import _
from frappe.utils import get_url, now_datetime

from frappe_waha.digest.periods import DigestPeriod, get_previous_complete_period
from frappe_waha.digest.renderer import render_pdf, render_text, save_digest_pdf
from frappe_waha.utils.phone import phone_to_chat_id, split_recipients
from frappe_waha.utils.openwa_client import OpenWAClient, OpenWAError


SUCCESS_STATUSES = ("Sent", "Partially Sent")
TEXT_MESSAGE_LIMIT = 3500


def enqueue_subscription(
    subscription_name: str,
    force: bool = False,
    trigger_doctype: str | None = None,
    trigger_name: str | None = None,
):
    return frappe.enqueue(
        "frappe_waha.digest.sender.generate_and_send",
        queue="long",
        job_name=f"whatsapp_digest:{subscription_name}",
        subscription_name=subscription_name,
        force=force,
        trigger_doctype=trigger_doctype,
        trigger_name=trigger_name,
        enqueue_after_commit=True,
    )


def generate_and_send(
    subscription_name: str,
    force: bool = False,
    trigger_doctype: str | None = None,
    trigger_name: str | None = None,
) -> str:
    subscription = frappe.get_doc("WhatsApp Digest Subscription", subscription_name)
    subscription.check_permission("read")
    subscription.validate_send_ready()
    trigger_doc = get_trigger_doc(trigger_doctype, trigger_name)

    period = get_trigger_period(trigger_doc) if trigger_doc else get_previous_complete_period(subscription)
    existing = find_existing_successful_run(subscription.name, period.end_date)
    if existing and not force:
        return existing

    run_doc = create_run(subscription, period, trigger_doc)
    try:
        run_doc.db_set("status", "Rendering", update_modified=False)
        media_delivery_mode = frappe.db.get_single_value("WAHA Settings", "media_delivery_mode") or "PDF Attachment"
        if media_delivery_mode == "Text Summary":
            text_message, context = render_text(subscription, period, trigger_doc)
            send_run(run_doc.name, text_message=text_message)
        else:
            pdf_bytes, context = render_pdf(subscription, period, trigger_doc)
            file_doc = save_digest_pdf(run_doc, pdf_bytes, context)
            run_doc.db_set("pdf_file", file_doc.file_url, update_modified=False)
            send_run(run_doc.name, pdf_bytes=pdf_bytes)
    except Exception:
        run_doc.db_set("status", "Failed", update_modified=False)
        run_doc.db_set("error", frappe.get_traceback(), update_modified=False)
        frappe.log_error(run_doc.error, _("WhatsApp Digest generation failed"))
        raise
    return run_doc.name


def send_run(run_name: str, pdf_bytes: bytes | None = None, text_message: str | None = None):
    run_doc = frappe.get_doc("WhatsApp Digest Run", run_name)
    subscription = frappe.get_doc("WhatsApp Digest Subscription", run_doc.subscription)
    sender_phone = frappe.get_doc("WhatsApp Phone", run_doc.whatsapp_phone)
    client = OpenWAClient.from_settings()
    media_delivery_mode = frappe.db.get_single_value("WAHA Settings", "media_delivery_mode") or "PDF Attachment"

    if media_delivery_mode == "Text Summary" and not text_message:
        text_message, _context = render_text(subscription, get_period_from_run(run_doc), get_run_trigger_doc(run_doc))

    if media_delivery_mode != "Text Summary" and not pdf_bytes:
        pdf_bytes = run_doc.get_pdf_bytes()

    run_doc.db_set("status", "Sending", update_modified=False)
    successes = 0
    failures = 0

    for row in run_doc.recipients:
        if row.status == "Sent":
            successes += 1
            continue

        try:
            chat_id = phone_to_chat_id(row.phone, sender_phone.default_country_code)
            if media_delivery_mode == "Text Summary":
                response = send_text_summary(
                    client=client,
                    session=sender_phone.session_name,
                    chat_id=chat_id,
                    text=text_message or "",
                )
                row.status = "Sent"
                row.sent_at = now_datetime()
                row.message_id = extract_message_id(response)
                row.error = None
                successes += 1
                continue

            response = client.send_pdf_file(
                session=sender_phone.session_name,
                chat_id=chat_id,
                filename=run_doc.pdf_filename(),
                pdf_bytes=pdf_bytes,
                caption=subscription.message_caption or subscription.title,
            )
            row.status = "Sent"
            row.sent_at = now_datetime()
            row.message_id = extract_message_id(response)
            row.error = None
            successes += 1
        except OpenWAError:
            if media_delivery_mode != "Text Link Fallback":
                row.status = "Failed"
                row.error = frappe.get_traceback()
                row.retry_count = (row.retry_count or 0) + 1
                failures += 1
                frappe.log_error(row.error, _("WhatsApp Digest recipient send failed"))
                continue

            try:
                response = client.send_text(
                    session=sender_phone.session_name,
                    chat_id=chat_id,
                    text=build_file_fallback_message(subscription, run_doc),
                )
                row.status = "Sent"
                row.sent_at = now_datetime()
                row.message_id = extract_message_id(response)
                row.error = None
                successes += 1
            except Exception:
                row.status = "Failed"
                row.error = frappe.get_traceback()
                row.retry_count = (row.retry_count or 0) + 1
                failures += 1
                frappe.log_error(row.error, _("WhatsApp Digest text fallback failed"))
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


def create_run(subscription, period, trigger_doc=None):
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
    if trigger_doc:
        run_doc.trigger_doctype = trigger_doc.doctype
        run_doc.trigger_document = trigger_doc.name
    for phone in recipients:
        run_doc.append("recipients", {"phone": phone, "status": "Pending"})
    run_doc.insert(ignore_permissions=True)
    return run_doc


def get_trigger_doc(trigger_doctype: str | None, trigger_name: str | None):
    if not trigger_doctype or not trigger_name:
        return None
    return frappe.get_doc(trigger_doctype, trigger_name)


def get_trigger_period(trigger_doc):
    start = getattr(trigger_doc, "period_start_date", None) or getattr(trigger_doc, "posting_date", None)
    end = getattr(trigger_doc, "period_end_date", None) or getattr(trigger_doc, "posting_date", None) or start
    return DigestPeriod(start, end, f"{trigger_doc.doctype} {trigger_doc.name}")


def get_period_from_run(run_doc):
    return DigestPeriod(run_doc.period_start, run_doc.period_end, run_doc.period_label)


def get_run_trigger_doc(run_doc):
    if not run_doc.trigger_doctype or not run_doc.trigger_document:
        return None
    return frappe.get_doc(run_doc.trigger_doctype, run_doc.trigger_document)


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
    if isinstance(response, list):
        ids = [extract_message_id(item) for item in response]
        ids = [message_id for message_id in ids if message_id]
        if not ids:
            return None
        suffix = f" (+{len(ids) - 1} parts)" if len(ids) > 1 else ""
        return (ids[0] + suffix)[:140]

    if isinstance(response, dict):
        message_id = response.get("id") or response.get("messageId") or response.get("_data", {}).get("id")
        if isinstance(message_id, dict):
            return message_id.get("_serialized") or message_id.get("id")
        return str(message_id) if message_id else None
    return str(response) if response else None


def send_text_summary(client: OpenWAClient, session: str, chat_id: str, text: str):
    responses = []
    for chunk in split_text_message(text):
        responses.append(client.send_text(session=session, chat_id=chat_id, text=chunk))
    return responses


def split_text_message(text: str) -> list[str]:
    text = (text or "").strip()
    if not text:
        return [_("لا توجد بيانات لإرسالها.")]

    chunks = []
    current = ""
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        candidate = f"{current}\n\n{block}".strip() if current else block
        if len(candidate) <= TEXT_MESSAGE_LIMIT:
            current = candidate
            continue
        if current:
            chunks.append(current)
        if len(block) <= TEXT_MESSAGE_LIMIT:
            current = block
        else:
            chunks.extend(block[i : i + TEXT_MESSAGE_LIMIT] for i in range(0, len(block), TEXT_MESSAGE_LIMIT))
            current = ""

    if current:
        chunks.append(current)

    return chunks


def build_file_fallback_message(subscription, run_doc) -> str:
    caption = subscription.message_caption or subscription.title
    file_url = get_url(run_doc.pdf_file) if run_doc.pdf_file else ""
    return _("{0}\n\nتعذر إرسال ملف PDF كمرفق. تم إنشاء الملف في النظام:\n{1}").format(
        caption,
        file_url,
    )
