"""Opt-in durable delivery engine. Legacy records remain readable and unchanged."""

from contextlib import contextmanager
from datetime import timedelta
import hashlib
import json
from uuid import uuid4

import frappe
from frappe import _
from frappe.utils import cint, get_datetime, now_datetime
from frappe.utils.file_manager import save_file
from frappe.utils.pdf import get_pdf
from frappe.translate import print_language

from frappe_waha.digest.periods import get_previous_complete_period
from frappe_waha.digest.sender import extract_message_id, split_text_message
from frappe_waha.utils.openwa_client import OpenWAClient, OpenWAError
from frappe_waha.utils.phone import normalize_phone, phone_to_chat_id

MAX_ATTEMPTS = 3
LEASE_MINUTES = 30


def is_unified():
    return frappe.db.get_single_value("WAHA Settings", "execution_engine", cache=False) == "Unified"


def require_legacy():
    if is_unified():
        frappe.throw(_("Legacy WhatsApp execution is paused. Create a fresh Unified automation."))


@contextmanager
def execution_user(user):
    previous = frappe.session.user
    if not user or not frappe.db.get_value("User", user, "enabled") or user == "Guest":
        frappe.throw(_("Select an enabled execution user."))
    frappe.set_user(user)
    try:
        yield
    finally:
        frappe.set_user(previous)


def execution_identity(automation, event, document=None, schedule=None, period=None, resend=None):
    values = [
        automation,
        event,
        document,
        schedule,
        str(period.start_date) if period else None,
        str(period.end_date) if period else None,
        resend,
    ]
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()


def document_allows_whatsapp(document):
    if document and document.doctype == "Sales Invoice":
        choice = document.get("send_to_whatsapp")
        return choice is None or bool(cint(choice))
    return True


def eligible(automation, document=None):
    if not is_unified() or automation.engine_version != "Unified" or not automation.enabled:
        return False
    if document and document.get("company") != automation.company:
        return False
    return document_allows_whatsapp(document)


def run_eligible(run, automation, document=None):
    if not eligible(automation, document):
        return False
    if (
        automation.execution_user != run.execution_user
        or automation.company != run.company
        or automation.whatsapp_phone != run.whatsapp_phone
    ):
        return False
    if run.schedule:
        schedule = frappe.db.get_value(
            "WhatsApp Schedule", run.schedule, ["enabled", "automation"], as_dict=True
        )
        if not schedule or not schedule.enabled or schedule.automation != automation.name:
            return False
    return True


def authorize(automation, document=None):
    automation.check_permission("read")
    if not automation.company:
        frappe.throw(_("A company is required for Unified automations."))
    frappe.get_doc("Company", automation.company).check_permission("read")
    frappe.get_doc("WhatsApp Phone", automation.whatsapp_phone).check_permission("read")
    if document:
        document.check_permission("read")
        if automation.action == "Document Delivery":
            document.check_permission("print")
        if document.get("company") != automation.company:
            frappe.throw(_("The source document belongs to another company."))
    # Legacy SQL/provider/script definitions do not enforce row-level user permissions.
    # Until report adapters replace them, allow them only to unrestricted administrators.
    advanced = (
        automation.text_formatter_script
        or any(
            b.enabled and b.source in ("Built-in Preset", "Custom SQL Table", "Script")
            for b in automation.blocks
        )
        or any(c.enabled and c.condition_type == "SQL" for c in automation.conditions)
    )
    if advanced and frappe.session.user != "Administrator":
        frappe.throw(
            _(
                "Legacy providers, SQL and scripts require Administrator as execution user. Use permission-aware report or DocType blocks for other users."
            )
        )


def queue_execution(
    automation_name, doctype=None, name=None, force=False, schedule=None, source_event=None
):
    from frappe_waha.digest.automation import get_doc_period

    automation = frappe.get_doc("WhatsApp Automation", automation_name)
    document = frappe.get_doc(doctype, name) if doctype and name else None
    if not eligible(automation, document):
        return ""
    event = source_event or "Manual"
    # Fresh event rules observe only committed business events.
    if event not in ("Manual", "Schedule", "After Insert", "After Save", "Submit", "Cancel"):
        return ""
    schedule_doc = frappe.get_doc("WhatsApp Schedule", schedule) if schedule else None
    if schedule_doc and (not schedule_doc.enabled or schedule_doc.automation != automation.name):
        return ""
    period = (
        get_previous_complete_period(schedule_doc) if schedule_doc else get_doc_period(document)
    )
    # An explicit manual resend is a new logical execution. Repeated events are not.
    resend = str(uuid4()) if cint(force) and event == "Manual" else None
    key = execution_identity(
        automation.name,
        event,
        (
            f"{doctype}:{name}:{document.modified if event == 'After Save' else ''}"
            if document
            else None
        ),
        schedule,
        period,
        resend,
    )
    existing = frappe.db.get_value("WhatsApp Digest Run", {"execution_key": key}, "name")
    if existing:
        return existing
    run = frappe.new_doc("WhatsApp Digest Run")
    run.update(
        dict(
            engine_version="Unified",
            execution_key=key,
            automation=automation.name,
            automation_title=automation.title,
            subscription_title=automation.title,
            execution_user=automation.execution_user,
            company=automation.company,
            whatsapp_phone=automation.whatsapp_phone,
            status="Queued",
            source_event=event,
            trigger_doctype=doctype,
            trigger_document=name,
            schedule=schedule,
            period_start=period.start_date,
            period_end=period.end_date,
            period_label=period.label,
        )
    )
    frappe.db.savepoint("whatsapp_execution_insert")
    try:
        run.insert(ignore_permissions=True)
    except (frappe.DuplicateEntryError, frappe.UniqueValidationError):
        frappe.db.rollback(save_point="whatsapp_execution_insert")
        return frappe.db.get_value(
            "WhatsApp Digest Run", {"execution_key": key}, "name", for_update=True
        )
    wake_after_commit(run.name)
    return run.name


def wake_execution(run_name):
    """Best-effort RQ wake-up; the database outbox remains the source of truth."""
    if not frappe.db.exists("WhatsApp Digest Run", run_name):
        return
    try:
        frappe.enqueue(
            "frappe_waha.digest.engine.process_execution", run_name=run_name, queue="long"
        )
    except Exception:
        # A queue outage after commit must not turn a successful invoice submission into an error.
        # The scheduler will rediscover the durable Queued run when services recover.
        try:
            frappe.log_error(
                "Durable WhatsApp execution awaits outbox polling; worker queue is unavailable.",
                "WhatsApp queue wake-up deferred",
            )
        except Exception:
            pass


def wake_after_commit(run_name):
    frappe.db.after_commit.add(lambda: wake_execution(run_name))


def source_document(run):
    return (
        frappe.get_doc(run.trigger_doctype, run.trigger_document)
        if run.trigger_doctype and run.trigger_document
        else None
    )


def claim_execution(run_name):
    run = frappe.get_doc("WhatsApp Digest Run", run_name, for_update=True)
    if run.engine_version != "Unified" or run.status != "Queued" or not is_unified():
        frappe.db.commit()
        return None
    # Rendering failures require a manual retry; scheduled polling only picks Queued.
    run.db_set(
        {"status": "Processing", "claimed_at": now_datetime(), "worker_token": str(uuid4())},
        update_modified=False,
    )
    frappe.db.commit()
    return run


def process_execution(run_name):
    from frappe_waha.digest.automation import conditions_match

    run = claim_execution(run_name)
    if not run:
        return
    token = run.worker_token
    try:
        automation = frappe.get_doc("WhatsApp Automation", run.automation)
        with execution_user(run.execution_user):
            document = source_document(run)
            if not document_allows_whatsapp(document):
                finish(run, "Skipped", "WhatsApp delivery is disabled on the source invoice.")
                return
            if not run_eligible(run, automation, document):
                finish(run, "Skipped", "Automation paused or source company changed.")
                return
            authorize(automation, document)
            if automation.action == "Document Delivery" and (
                not document
                or document.doctype != "Sales Invoice"
                or document.docstatus != 1
                or document.get("is_consolidated")
            ):
                finish(
                    run,
                    "Skipped",
                    "Source invoice is not submitted or is a consolidated POS invoice.",
                )
                return
            if not conditions_match(automation, document):
                finish(run, "Skipped", "Conditions did not match committed state.")
                return
            if not run.prepared:
                prepare_execution(run, automation, document)
                if run.status == "Skipped":
                    return
            # Rendering and content snapshots are committed before any external request.
            frappe.db.commit()
            deliveries = frappe.get_all(
                "WhatsApp Delivery",
                filters={"run": run.name},
                pluck="name",
                order_by="part_index asc, creation asc",
            )
            for delivery_name in deliveries:
                if frappe.db.get_value(run.doctype, run.name, "worker_token") != token:
                    return
                automation.reload()
                document = source_document(run)
                if not document_allows_whatsapp(document):
                    finish(run, "Skipped", "WhatsApp delivery is disabled on the source invoice.")
                    return
                if not run_eligible(run, automation, document):
                    finish(run, "Skipped", "Automation paused before delivery.")
                    return
                authorize(automation, document)
                if automation.action == "Document Delivery" and (
                    document.docstatus != 1 or document.get("is_consolidated")
                ):
                    finish(run, "Skipped", "Invoice cancelled before delivery.")
                    return
                send_delivery(run, automation, delivery_name)
            summarize(run)
    except Exception:
        frappe.db.rollback()
        current = frappe.get_doc(run.doctype, run.name, for_update=True)
        if current.worker_token != token:
            frappe.db.commit()
            return
        # Error detail stays inside permission-protected history, never returned to customers.
        processing = frappe.db.exists(
            "WhatsApp Delivery", {"run": run.name, "status": "Processing"}
        )
        if processing:
            frappe.db.set_value(
                "WhatsApp Delivery",
                {"run": run.name, "status": "Processing"},
                {
                    "status": "Uncertain",
                    "error": "Worker failed after dispatch; reconcile before resending.",
                },
                update_modified=False,
            )
        finish(
            run,
            "Uncertain" if processing else "Failed",
            "Rendering, permission or connection validation failed. Review the error log.",
        )
        frappe.log_error(frappe.get_traceback(), "WhatsApp Unified execution failed")


def finish(run, status, error=None):
    # An expired worker must not overwrite a newer worker's result.
    current = frappe.db.get_value(run.doctype, run.name, "worker_token", for_update=True)
    if current != run.worker_token:
        return
    run.db_set({"status": status, "error": error}, update_modified=False)
    frappe.db.commit()


def invoice_recipient(document, country_code):
    phone = document.get("whatsapp_number")
    if not phone and document.get("contact_person"):
        contact = frappe.get_doc("Contact", document.get("contact_person"))
        contact.check_permission("read")
        phone = contact.get("mobile_no")
    if not phone:
        return None
    try:
        return normalize_phone(phone, country_code)
    except frappe.ValidationError:
        return None


def prepare_execution(run, automation, document):
    from frappe_waha.digest.automation import render_automation
    from frappe_waha.digest.periods import DigestPeriod

    sender = frappe.get_doc("WhatsApp Phone", automation.whatsapp_phone)
    run.sender_session = sender.session_name
    run.caption = automation.message_caption or automation.title
    if automation.action == "Document Delivery":
        document.check_permission("print")
        recipient = invoice_recipient(document, sender.default_country_code)
        if not recipient:
            finish(
                run, "Skipped", "Invoice has no valid WhatsApp number or selected contact mobile."
            )
            run.status = "Skipped"
            return
        recipients = [recipient]
        with print_language(automation.language or "en"):
            pdf = frappe.get_print(
                document.doctype,
                document.name,
                print_format=automation.print_format or None,
                doc=document,
                as_pdf=True,
                letterhead=automation.letter_head or None,
            )
        text = None
    else:
        recipients = list(
            dict.fromkeys(
                normalize_phone(r.phone, sender.default_country_code) for r in automation.recipients
            )
        )
        if not recipients:
            frappe.throw(_("Add at least one recipient."))
        schedule = frappe.get_doc("WhatsApp Schedule", run.schedule) if run.schedule else None
        text, html, _context = render_automation(
            automation,
            DigestPeriod(run.period_start, run.period_end, run.period_label),
            document,
            schedule,
        )
        pdf = get_pdf(html) if automation.output_mode in ("PDF", "Both") else None
    if pdf:
        file = save_file(run.pdf_filename(), pdf, run.doctype, run.name, is_private=1)
        run.pdf_file = file.file_url
    current = frappe.get_doc(run.doctype, run.name, for_update=True)
    if current.worker_token != run.worker_token:
        frappe.throw(_("Execution lease expired during rendering."))
    run.content_text = text
    run.set("recipients", [])
    for phone in recipients:
        run.append("recipients", {"phone": phone, "status": "Queued"})
        parts = (
            [("Text", chunk) for chunk in split_text_message(text)]
            if text and automation.output_mode in ("Text", "Both")
            else []
        )
        if pdf:
            parts.append(("PDF", None))
        for index, (kind, content) in enumerate(parts):
            delivery = frappe.new_doc("WhatsApp Delivery")
            delivery.update(
                dict(
                    run=run.name,
                    company=run.company,
                    phone=phone,
                    part_index=index,
                    kind=kind,
                    content=content,
                    status="Queued",
                )
            )
            delivery.insert(ignore_permissions=True)
    run.prepared = 1
    run.save(ignore_permissions=True)


def send_delivery(run, automation, delivery_name):
    # Lock in the same order as stale-worker recovery: run, then message part.
    # Ownership must still be valid at the moment the part is claimed.
    current = frappe.get_doc(run.doctype, run.name, for_update=True)
    if current.worker_token != run.worker_token or current.status != "Processing":
        frappe.db.commit()
        return
    delivery = frappe.get_doc("WhatsApp Delivery", delivery_name, for_update=True)
    if delivery.status != "Queued" or (
        delivery.next_attempt_at and get_datetime(delivery.next_attempt_at) > now_datetime()
    ):
        frappe.db.commit()
        return
    # Stop after any failed/uncertain earlier part to avoid sending a broken sequence.
    previous = frappe.get_all(
        "WhatsApp Delivery",
        filters={
            "run": run.name,
            "phone": delivery.phone,
            "part_index": ["<", delivery.part_index],
        },
        pluck="status",
    )
    if any(status != "Provider Accepted" for status in previous):
        frappe.db.commit()
        return
    automation.validate_send_ready()
    if (
        frappe.db.get_value("WhatsApp Phone", automation.whatsapp_phone, "session_name")
        != run.sender_session
    ):
        frappe.throw(_("The sender session changed; create a new execution."))
    client = OpenWAClient.from_settings()
    if not delivery.provider_idempotency_key:
        delivery.provider_idempotency_key = hashlib.sha256(
            f"{frappe.local.site}:{run.execution_key}:{delivery.name}".encode()
        ).hexdigest()
    delivery.attempts += 1
    delivery.status = "Processing"
    delivery.claimed_at = now_datetime()
    frappe.db.set_value(
        run.doctype, run.name, "claimed_at", delivery.claimed_at, update_modified=False
    )
    delivery.save(ignore_permissions=True)
    frappe.db.commit()  # A crash after this point has an unknown outcome, not a safe retry.
    try:
        if delivery.kind == "Text":
            response = client.send_text(
                session=run.sender_session,
                chat_id=phone_to_chat_id(delivery.phone),
                text=delivery.content,
                idempotency_key=delivery.provider_idempotency_key,
            )
        else:
            response = client.send_pdf_file(
                session=run.sender_session,
                chat_id=phone_to_chat_id(delivery.phone),
                filename=run.pdf_filename(),
                pdf_bytes=run.get_pdf_bytes(),
                caption=run.caption,
                idempotency_key=delivery.provider_idempotency_key,
            )
        delivery.status = "Provider Accepted"
        delivery.message_id = extract_message_id(response)
        delivery.accepted_at = now_datetime()
        delivery.error = None
    except OpenWAError as exc:
        if exc.outcome == "retryable" and delivery.attempts < MAX_ATTEMPTS:
            delivery.status = "Queued"
            delivery.next_attempt_at = now_datetime() + timedelta(minutes=2**delivery.attempts)
        else:
            delivery.status = "Uncertain" if exc.outcome == "uncertain" else "Failed"
        delivery.error = "OpenWA request outcome: " + exc.outcome
    except Exception:
        delivery.status = "Uncertain"
        delivery.error = "Unexpected failure after dispatch; do not retry automatically."
    delivery.save(ignore_permissions=True)
    frappe.db.commit()


def aggregate_status(statuses):
    if not statuses:
        return "Skipped"
    if "Uncertain" in statuses or "Processing" in statuses:
        return "Uncertain"
    if "Failed" in statuses:
        return "Failed"
    if "Queued" in statuses:
        return "Queued"
    return "Provider Accepted" if all(s == "Provider Accepted" for s in statuses) else "Skipped"


def summarize(run):
    current = frappe.get_doc(run.doctype, run.name, for_update=True)
    if current.worker_token != run.worker_token:
        frappe.db.commit()
        return
    parts = frappe.get_all(
        "WhatsApp Delivery",
        filters={"run": run.name},
        fields=["phone", "status", "message_id", "attempts", "part_index", "error", "accepted_at"],
    )
    run.reload()
    for row in run.recipients:
        matching = [p for p in parts if p.phone == row.phone]
        row.status = aggregate_status([p.status for p in matching])
        row.retry_count = max((p.attempts - 1 for p in matching), default=0)
        row.message_id = next((p.message_id for p in matching if p.message_id), None)
        row.error = "; ".join(dict.fromkeys(p.error for p in matching if p.error)) or None
        row.sent_at = max((p.accepted_at for p in matching if p.accepted_at), default=None)
    runnable = [
        p
        for p in parts
        if p.status == "Queued"
        and not any(
            earlier.phone == p.phone
            and earlier.part_index < p.part_index
            and earlier.status in ("Failed", "Uncertain")
            for earlier in parts
        )
    ]
    run.status = (
        "Queued"
        if runnable and not any(p.status == "Uncertain" for p in parts)
        else aggregate_status([p.status for p in parts if p.status != "Queued"])
    )

    if run.status == "Provider Accepted":
        run.error = None
    run.save(ignore_permissions=True)
    frappe.db.commit()


def poll_outbox():
    if not is_unified():
        return
    cutoff = now_datetime() - timedelta(minutes=LEASE_MINUTES)
    stale = frappe.get_all(
        "WhatsApp Digest Run",
        filters={"engine_version": "Unified", "status": "Processing", "claimed_at": ["<", cutoff]},
        pluck="name",
    )
    for name in stale:
        run = frappe.get_doc("WhatsApp Digest Run", name, for_update=True)
        if run.status != "Processing" or get_datetime(run.claimed_at) >= cutoff:
            continue
        frappe.db.set_value(run.doctype, name, "worker_token", str(uuid4()), update_modified=False)
        frappe.db.set_value(
            "WhatsApp Delivery",
            {"run": name, "status": "Processing"},
            {"status": "Uncertain", "error": "Worker lease expired after dispatch."},
            update_modified=False,
        )
        frappe.db.set_value(run.doctype, name, "status", "Queued", update_modified=False)
    frappe.db.commit()
    for name in frappe.get_all(
        "WhatsApp Digest Run",
        filters={"engine_version": "Unified", "status": "Queued"},
        pluck="name",
        limit_page_length=100,
    ):
        wake_execution(name)


def retry_execution(run):
    run.check_permission("read")
    automation = frappe.get_doc("WhatsApp Automation", run.automation)
    automation.check_permission("write")
    if not eligible(automation) or run.status not in ("Failed", "Skipped"):
        frappe.throw(
            _(
                "Only failed or skipped Unified runs can be retried. Uncertain outcomes need reconciliation; a deliberate resend must be a new execution."
            )
        )
    # Permission/rendering fixes may retry the same execution; content is never regenerated once prepared.
    for delivery in frappe.get_all(
        "WhatsApp Delivery",
        filters={"run": run.name, "status": "Failed"},
        fields=["name", "attempts"],
    ):
        if delivery.attempts < MAX_ATTEMPTS:
            frappe.db.set_value(
                "WhatsApp Delivery",
                delivery.name,
                {"status": "Queued", "next_attempt_at": None},
                update_modified=False,
            )
    run.db_set("status", "Queued", update_modified=False)
    wake_after_commit(run.name)
    return True
