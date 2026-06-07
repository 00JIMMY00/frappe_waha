import json

import frappe
from frappe import _
from frappe.utils import now_datetime
from frappe.utils.file_manager import save_file
from frappe.utils.pdf import get_pdf

from frappe_waha.digest.metrics import build_metrics, import_provider
from frappe_waha.digest.periods import get_comparison_period, get_previous_complete_period


def selected_metric_codes(subscription) -> list[str]:
    if not subscription.subscribed_metrics:
        return []

    try:
        codes = json.loads(subscription.subscribed_metrics)
    except ValueError:
        frappe.throw(_("Subscribed Metrics must be a JSON array."))

    if not isinstance(codes, list):
        frappe.throw(_("Subscribed Metrics must be a JSON array."))

    return [str(code) for code in codes if code]


def build_context(subscription, period=None, comparison_period=None) -> dict:
    period = period or get_previous_complete_period(subscription)
    comparison_period = comparison_period or get_comparison_period(
        period, subscription.compare_vs, subscription.frequency
    )
    template = get_template(subscription)

    metrics = build_metrics(subscription, selected_metric_codes(subscription), period, comparison_period)
    context = {
        "title": subscription.title,
        "company": subscription.company,
        "subscription": subscription,
        "period": period,
        "period_label": period.label,
        "comparison_period": comparison_period,
        "comparison_label": comparison_period.label if comparison_period else "",
        "metrics": metrics,
        "generated_at": now_datetime(),
    }

    if template.python_context_path:
        extra_provider = import_provider(template.python_context_path)
        extra = extra_provider(subscription, period, comparison_period) or {}
        if not isinstance(extra, dict):
            frappe.throw(_("Template Python Context Path must return a dictionary."))
        context.update(extra)

    return context


def render_html(subscription, period=None) -> tuple[str, dict]:
    period = period or get_previous_complete_period(subscription)
    comparison_period = get_comparison_period(period, subscription.compare_vs, subscription.frequency)
    template = get_template(subscription)
    context = build_context(subscription, period, comparison_period)

    body = frappe.render_template(template.html or "", context)
    css = frappe.render_template(template.css or "", context)
    html = f"<!doctype html><html><head><meta charset='utf-8'><style>{css}</style></head><body>{body}</body></html>"
    return html, context


def render_pdf(subscription, period=None) -> tuple[bytes, dict]:
    html, context = render_html(subscription, period)
    template = get_template(subscription)
    options = {
        "page-size": template.page_size or "A4",
        "orientation": template.orientation or "Portrait",
        "encoding": "UTF-8",
    }
    return get_pdf(html, options=options), context


def save_digest_pdf(run_doc, pdf_bytes: bytes, context: dict):
    safe_title = frappe.scrub(run_doc.subscription_title or run_doc.subscription)
    filename = f"{safe_title}_{run_doc.period_end}.pdf"
    return save_file(filename, pdf_bytes, run_doc.doctype, run_doc.name, is_private=1)


def get_template(subscription):
    if subscription.template:
        return frappe.get_doc("WhatsApp Digest Template", subscription.template)

    default_name = frappe.db.get_value(
        "WhatsApp Digest Template", {"enabled": 1, "is_default": 1}, "name"
    )
    if default_name:
        return frappe.get_doc("WhatsApp Digest Template", default_name)

    fallback_name = frappe.db.get_value("WhatsApp Digest Template", {"enabled": 1}, "name")
    if fallback_name:
        return frappe.get_doc("WhatsApp Digest Template", fallback_name)

    frappe.throw(_("Create at least one enabled WhatsApp Digest Template."))

