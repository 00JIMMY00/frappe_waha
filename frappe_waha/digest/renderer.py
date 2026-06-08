import json
import re
from html import unescape

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


def build_context(subscription, period=None, comparison_period=None, trigger_doc=None) -> dict:
    period = period or get_previous_complete_period(subscription)
    comparison_period = comparison_period or get_comparison_period(
        period, subscription.compare_vs, subscription.frequency
    )
    template = get_template(subscription)

    metrics = build_metrics(subscription, selected_metric_codes(subscription), period, comparison_period, trigger_doc)
    context = {
        "frappe": frappe,
        "_": _,
        "title": subscription.title,
        "company": subscription.company,
        "subscription": subscription,
        "doc": trigger_doc,
        "trigger_doc": trigger_doc,
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


def render_html(subscription, period=None, trigger_doc=None) -> tuple[str, dict]:
    period = period or get_previous_complete_period(subscription)
    comparison_period = get_comparison_period(period, subscription.compare_vs, subscription.frequency)
    template = get_template(subscription)
    context = build_context(subscription, period, comparison_period, trigger_doc)

    body = frappe.render_template(template.html or "", context)
    metric_css = "\n".join(metric.get("css") or "" for metric in context.get("metrics") or [])
    css = frappe.render_template((template.css or "") + "\n" + metric_css, context)
    html = f"<!doctype html><html><head><meta charset='utf-8'><style>{css}</style></head><body>{body}</body></html>"
    return html, context


def render_pdf(subscription, period=None, trigger_doc=None) -> tuple[bytes, dict]:
    html, context = render_html(subscription, period, trigger_doc)
    template = get_template(subscription)
    options = {
        "page-size": template.page_size or "A4",
        "orientation": template.orientation or "Portrait",
        "encoding": "UTF-8",
    }
    return get_pdf(html, options=options), context


def render_text(subscription, period=None, trigger_doc=None) -> tuple[str, dict]:
    period = period or get_previous_complete_period(subscription)
    comparison_period = get_comparison_period(period, subscription.compare_vs, subscription.frequency)
    template = get_template(subscription)
    context = build_context(subscription, period, comparison_period, trigger_doc)

    if getattr(template, "text_template", None):
        return frappe.render_template(template.text_template, context).strip(), context

    return build_arabic_text_summary(context), context


def build_arabic_text_summary(context: dict) -> str:
    lines = [
        f"*{context.get('title') or _('WhatsApp Digest')}*",
        f"الشركة: {context.get('company') or '-'}",
        f"الفترة: {context.get('period_label') or '-'}",
    ]

    if context.get("comparison_label"):
        lines.append(f"المقارنة: {context.get('comparison_label')}")

    if context.get("trigger_doc"):
        trigger_doc = context["trigger_doc"]
        lines.append(f"المستند: {trigger_doc.doctype} {trigger_doc.name}")

    for metric in context.get("metrics") or []:
        lines.append("")
        lines.extend(format_metric_as_arabic_text(metric))

    return "\n".join(lines).strip()


def format_metric_as_arabic_text(metric: dict) -> list[str]:
    title = metric.get("title") or metric.get("code") or _("Metric")
    lines = [f"*{title}*"]

    if metric.get("description"):
        lines.append(str(metric.get("description")))

    if metric.get("kind") == "card" or metric.get("value") is not None:
        lines.append(f"{title}: {metric.get('value') or '-'}")
        if metric.get("delta_label"):
            lines.append(f"التغيير: {metric.get('delta_label')}")
        return lines

    if metric.get("kind") == "chart":
        for point in metric.get("points") or []:
            lines.append(f"- {point.get('label')}: {point.get('value')}")
        return lines

    if metric.get("kind") == "html" and metric.get("html"):
        text = html_to_text(metric.get("html") or "")
        if text:
            lines.append(text)

    rows = metric.get("rows") or []
    columns = metric.get("columns") or infer_columns(rows)
    if rows:
        for index, row in enumerate(rows, start=1):
            values = []
            for column in columns:
                fieldname = column.get("fieldname")
                label = column.get("label") or frappe.unscrub(fieldname or "")
                values.append(f"{label}: {row.get(fieldname)}")
            lines.append(f"{index}. " + " | ".join(values))

    if len(lines) == 1:
        lines.append("-")

    return lines


def infer_columns(rows: list[dict]) -> list[dict]:
    if not rows:
        return []
    return [{"fieldname": key, "label": frappe.unscrub(key)} for key in rows[0].keys()]


def html_to_text(html: str) -> str:
    text = re.sub(r"(?i)<br\\s*/?>", "\n", html)
    text = re.sub(r"(?i)</(p|div|tr|li|h[1-6])>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    lines = [line.strip() for line in unescape(text).splitlines()]
    return "\n".join(line for line in lines if line)


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
