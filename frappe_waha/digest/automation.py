from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from html import escape
from typing import Any

import frappe
from frappe import _
from frappe.desk.query_report import run as run_query_report
from frappe.utils import add_days, get_datetime, get_time, now_datetime, today
from frappe.utils.file_manager import save_file
from frappe.utils.pdf import get_pdf
from frappe.utils.safe_exec import safe_exec

from frappe_waha.digest.metrics import (
    build_metrics,
    columns_from_keys,
    limit_rows,
    normalize_report_columns,
    normalize_report_rows,
)
from frappe_waha.digest.periods import DigestPeriod, get_comparison_period, get_current_period
from frappe_waha.digest.renderer import format_metric_as_arabic_text, get_template
from frappe_waha.digest.sender import (
    extract_message_id,
    send_text_summary,
    split_text_message,
)
from frappe_waha.utils.openwa_client import OpenWAClient
from frappe_waha.utils.phone import phone_to_chat_id


EVENT_MAP = {
    "validate": "Validate",
    "before_save": "Before Save",
    "after_insert": "After Insert",
    "on_update": "After Save",
    "on_submit": "Submit",
    "on_cancel": "Cancel",
    "on_trash": "Delete",
}

SUCCESS_STATUSES = ("Sent", "Partially Sent")


@dataclass
class AutomationPeriod:
    start_date: Any
    end_date: Any
    label: str


def dispatch_doc_event(doc, method=None):
    if getattr(frappe.flags, "in_migrate", False) or getattr(frappe.flags, "in_install", False):
        return
    trigger_event = EVENT_MAP.get(method)
    if not trigger_event or not getattr(doc, "doctype", None):
        return
    if not frappe.db.table_exists("WhatsApp Automation"):
        return

    names = frappe.get_all(
        "WhatsApp Automation",
        filters={
            "enabled": 1,
            "trigger_doctype": doc.doctype,
            "trigger_event": trigger_event,
        },
        pluck="name",
    )
    for name in names:
        try:
            automation = frappe.get_doc("WhatsApp Automation", name)
            if not conditions_match(automation, doc):
                continue
            enqueue_automation(automation.name, doctype=doc.doctype, name=doc.name, source_event=trigger_event)
        except Exception:
            frappe.log_error(frappe.get_traceback(), _("WhatsApp Automation dispatch failed"))


def enqueue_automation(
    automation_name: str,
    doctype: str | None = None,
    name: str | None = None,
    force: bool = False,
    schedule: str | None = None,
    source_event: str | None = None,
):
    return frappe.enqueue(
        "frappe_waha.digest.automation.send_whatsapp_automation",
        queue="long",
        job_name=f"whatsapp_automation:{automation_name}",
        automation_name=automation_name,
        doctype=doctype,
        name=name,
        force=force,
        schedule=schedule,
        source_event=source_event,
        enqueue_after_commit=True,
    )


@frappe.whitelist()
def send_whatsapp_automation(
    automation_name: str,
    doctype: str | None = None,
    name: str | None = None,
    force: bool = False,
    schedule: str | None = None,
    source_event: str | None = None,
) -> str:
    automation = frappe.get_doc("WhatsApp Automation", automation_name)
    automation.check_permission("read")
    automation.validate_send_ready()
    trigger_doc = frappe.get_doc(doctype, name) if doctype and name else None

    if not force and not conditions_match(automation, trigger_doc):
        return ""

    schedule_doc = frappe.get_doc("WhatsApp Schedule", schedule) if schedule else None
    period = get_schedule_period(schedule_doc) if schedule_doc else get_doc_period(trigger_doc)
    run_doc = create_automation_run(automation, period, trigger_doc, schedule)

    try:
        run_doc.db_set("status", "Rendering", update_modified=False)
        text, html, context = render_automation(automation, period, trigger_doc, schedule_doc)
        if automation.output_mode == "Text":
            send_automation_run(run_doc.name, text_message=text)
        else:
            pdf_bytes = get_pdf(html, options={"page-size": "A4", "orientation": "Portrait", "encoding": "UTF-8"})
            file_doc = save_file(run_doc.pdf_filename(), pdf_bytes, run_doc.doctype, run_doc.name, is_private=1)
            run_doc.db_set("pdf_file", file_doc.file_url, update_modified=False)
            send_automation_run(run_doc.name, pdf_bytes=pdf_bytes, text_message=text)
    except Exception:
        run_doc.db_set("status", "Failed", update_modified=False)
        run_doc.db_set("error", frappe.get_traceback(), update_modified=False)
        frappe.log_error(run_doc.error, _("WhatsApp Automation generation failed"))
        raise

    return run_doc.name


def send_automation_run(run_name: str, pdf_bytes: bytes | None = None, text_message: str | None = None):
    run_doc = frappe.get_doc("WhatsApp Digest Run", run_name)
    automation = frappe.get_doc("WhatsApp Automation", run_doc.automation)
    sender_phone = frappe.get_doc("WhatsApp Phone", run_doc.whatsapp_phone)
    client = OpenWAClient.from_settings()

    if automation.output_mode == "PDF" and not pdf_bytes:
        pdf_bytes = run_doc.get_pdf_bytes()

    if automation.output_mode == "Text" and not text_message:
        text_message, _html, _context = render_automation(
            automation,
            AutomationPeriod(run_doc.period_start, run_doc.period_end, run_doc.period_label),
            get_run_trigger_doc(run_doc),
            run_doc.schedule,
        )

    run_doc.db_set("status", "Sending", update_modified=False)
    successes = 0
    failures = 0

    for row in run_doc.recipients:
        if row.status == "Sent":
            successes += 1
            continue
        try:
            chat_id = phone_to_chat_id(row.phone, sender_phone.default_country_code)
            if automation.output_mode == "Text":
                response = send_text_summary(client, sender_phone.session_name, chat_id, text_message or "")
            else:
                response = client.send_pdf_file(
                    session=sender_phone.session_name,
                    chat_id=chat_id,
                    filename=run_doc.pdf_filename(),
                    pdf_bytes=pdf_bytes or b"",
                    caption=automation.message_caption or automation.title,
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
            frappe.log_error(row.error, _("WhatsApp Automation recipient send failed"))

    run_doc.status = "Sent" if successes and not failures else "Partially Sent" if successes else "Failed"
    run_doc.sent_at = now_datetime() if successes else None
    run_doc.save(ignore_permissions=True)
    if successes:
        automation.db_set("last_sent_at", now_datetime(), update_modified=False)
        if run_doc.schedule:
            frappe.db.set_value(
                "WhatsApp Schedule",
                run_doc.schedule,
                {
                    "last_sent_at": now_datetime(),
                    "last_sent_period_end": run_doc.period_end,
                },
                update_modified=False,
            )
    frappe.db.commit()


def create_automation_run(automation, period, trigger_doc=None, schedule=None):
    run_doc = frappe.new_doc("WhatsApp Digest Run")
    run_doc.automation = automation.name
    run_doc.automation_title = automation.title
    run_doc.subscription_title = automation.title
    run_doc.status = "Pending"
    run_doc.company = automation.company
    run_doc.whatsapp_phone = automation.whatsapp_phone
    run_doc.period_start = period.start_date
    run_doc.period_end = period.end_date
    run_doc.period_label = period.label
    run_doc.schedule = schedule
    if trigger_doc:
        run_doc.trigger_doctype = trigger_doc.doctype
        run_doc.trigger_document = trigger_doc.name
    for recipient in automation.recipients:
        run_doc.append("recipients", {"phone": recipient.phone, "status": "Pending"})
    run_doc.insert(ignore_permissions=True)
    return run_doc


def conditions_match(automation, doc=None) -> bool:
    enabled = [row for row in automation.conditions if row.enabled]
    if not enabled:
        return True
    results = []
    for condition in enabled:
        try:
            results.append(evaluate_condition(condition, automation, doc))
        except Exception:
            frappe.log_error(frappe.get_traceback(), _("WhatsApp Automation condition failed"))
            results.append(False)
    return all(results) if automation.condition_mode != "Any" else any(results)


def evaluate_condition(condition, automation, doc=None) -> bool:
    if condition.condition_type == "SQL":
        actual = evaluate_sql_condition(condition, automation, doc)
    elif condition.condition_type == "Child Aggregate":
        actual = evaluate_child_aggregate(condition, doc)
    else:
        actual = doc.get(condition.fieldname) if doc and condition.fieldname else None
    expected = render_value(condition.value, automation, doc)
    return compare_values(actual, condition.operator, expected)


def evaluate_child_aggregate(condition, doc=None):
    if not doc or not condition.child_table_field:
        return None
    rows = doc.get(condition.child_table_field) or []
    if condition.aggregate_function == "count":
        return len(rows)
    if condition.aggregate_function == "any":
        return any(bool(row.get(condition.aggregate_field)) for row in rows)
    values = [to_number(row.get(condition.aggregate_field)) for row in rows]
    if not values:
        return 0
    if condition.aggregate_function == "min":
        return min(values)
    if condition.aggregate_function == "max":
        return max(values)
    return sum(values)


def evaluate_sql_condition(condition, automation, doc=None):
    sql = (condition.sql_condition or "").strip()
    if not re.match(r"(?is)^select\s+", sql) or re.search(r"(?is);\s*\S", sql):
        frappe.throw(_("SQL conditions must be a single SELECT statement."))
    params = safe_params(automation, doc)
    result = frappe.db.sql(sql, params, as_dict=True)
    if not result:
        return None
    first = result[0]
    if not first:
        return None
    return next(iter(first.values()))


def compare_values(actual, operator, expected) -> bool:
    if operator == "Is Set":
        return actual not in (None, "")
    if operator == "Is Not Set":
        return actual in (None, "")
    actual_cmp, expected_cmp = coerce_pair(actual, expected)
    if operator == "Equals":
        return actual_cmp == expected_cmp
    if operator == "Not Equals":
        return actual_cmp != expected_cmp
    if operator == "Greater Than":
        return actual_cmp > expected_cmp
    if operator == "Greater Than Or Equal":
        return actual_cmp >= expected_cmp
    if operator == "Less Than":
        return actual_cmp < expected_cmp
    if operator == "Less Than Or Equal":
        return actual_cmp <= expected_cmp
    if operator == "Contains":
        return str(expected or "") in str(actual or "")
    if operator == "Not Contains":
        return str(expected or "") not in str(actual or "")
    return False


def render_automation(automation, period, trigger_doc=None, schedule=None):
    comparison_period = get_comparison_period(period, getattr(schedule, "compare_vs", None), getattr(schedule, "frequency", "Daily")) if schedule else None
    context = build_automation_context(automation, period, comparison_period, trigger_doc, schedule)
    if automation.template:
        template = get_template(automation)
        body = frappe.render_template(template.html or "", context)
        metric_css = "\n".join(block.get("css") or "" for block in context.get("metrics") or [])
        css = frappe.render_template((template.css or "") + "\n" + metric_css, context)
        html = f"<!doctype html><html><head><meta charset='utf-8'><style>{css}</style></head><body>{body}</body></html>"
        if getattr(template, "text_template", None):
            text = frappe.render_template(template.text_template, context).strip()
        else:
            text = build_automation_text(context)
        return text, html, context
    text = build_automation_text(context)
    html = build_automation_html(context)
    return text, html, context


def build_automation_context(automation, period, comparison_period=None, trigger_doc=None, schedule=None):
    blocks = build_automation_blocks(automation, period, comparison_period, trigger_doc)
    return {
        "frappe": frappe,
        "_": _,
        "title": automation.title,
        "company": automation.company,
        "automation": automation,
        "subscription": automation,
        "schedule": schedule,
        "doc": trigger_doc,
        "trigger_doc": trigger_doc,
        "period": period,
        "period_label": period.label,
        "comparison_period": comparison_period,
        "comparison_label": comparison_period.label if comparison_period else "",
        "metrics": blocks,
        "generated_at": now_datetime(),
    }


def build_automation_blocks(automation, period, comparison_period=None, trigger_doc=None):
    blocks = []
    for block in automation.blocks:
        if not block.enabled:
            continue
        if block.source == "Built-in Preset":
            blocks.extend(build_builtin_block(automation, block, period, comparison_period, trigger_doc))
        elif block.source == "Query Report":
            blocks.append(build_report_block(automation, block, period, trigger_doc))
        elif block.source == "DocType Table":
            blocks.append(build_doctype_block(automation, block, period, trigger_doc))
        elif block.source == "Custom SQL Table":
            blocks.append(build_sql_block(automation, block, period, trigger_doc))
        elif block.source == "Script":
            blocks.append(build_script_block(automation, block, period, comparison_period, trigger_doc, blocks))
    return blocks


def build_builtin_block(automation, block, period, comparison_period=None, trigger_doc=None):
    if not block.builtin_metric:
        return []
    return build_metrics(automation, [block.builtin_metric], period, comparison_period, trigger_doc)


def build_report_block(automation, block, period, trigger_doc=None):
    filters = block_filters(automation, block.block_key, trigger_doc, period)
    result = run_query_report(block.report_name, filters=filters, ignore_prepared_report=True)
    all_columns = normalize_report_columns(result.get("columns") or [])
    all_rows = normalize_report_rows(result.get("result") or [], all_columns)
    configured = [row for row in automation.report_columns if row.block_key == block.block_key and row.include]
    if configured:
        selected = [row.fieldname for row in configured]
        columns = [
            {
                "fieldname": row.fieldname,
                "label": row.label_ar or row.label or frappe.unscrub(row.fieldname),
                "format": row.format,
            }
            for row in configured
        ]
    else:
        selected = [column["fieldname"] for column in all_columns]
        columns = all_columns
    rows = [{fieldname: row.get(fieldname) for fieldname in selected} for row in all_rows]
    return metric_block(block, columns, limit_rows(rows, block.row_limit))


def build_doctype_block(automation, block, period, trigger_doc=None):
    selected = [row.fieldname for row in automation.report_columns if row.block_key == block.block_key and row.include]
    if not selected:
        frappe.throw(_("Select at least one column for block {0}.").format(block.block_key))
    labels = {
        row.fieldname: row.label_ar or row.label or frappe.unscrub(row.fieldname)
        for row in automation.report_columns
        if row.block_key == block.block_key
    }
    if trigger_doc and trigger_doc.doctype == block.reference_doctype and block.child_table_field:
        rows = [{fieldname: row.get(fieldname) for fieldname in selected} for row in (trigger_doc.get(block.child_table_field) or [])]
    else:
        filters = block_filters(automation, block.block_key, trigger_doc, period)
        if block.date_field:
            filters[block.date_field] = ["between", [period.start_date, period.end_date]]
        rows = frappe.get_all(block.reference_doctype, filters=filters, fields=selected, limit_page_length=block.row_limit or 20)
    return metric_block(block, columns_from_keys(selected, labels), limit_rows(rows, block.row_limit))


def build_sql_block(automation, block, period, trigger_doc=None):
    sql = (block.custom_sql or "").strip()
    if not re.match(r"(?is)^select\s+", sql) or re.search(r"(?is);\s*\S", sql):
        frappe.throw(_("Custom SQL blocks must be a single SELECT statement."))
    rows = frappe.db.sql(sql, safe_params(automation, trigger_doc, period), as_dict=True)
    columns = columns_from_keys(rows[0].keys()) if rows else []
    return metric_block(block, columns, limit_rows(rows, block.row_limit))


def build_script_block(automation, block, period, comparison_period=None, trigger_doc=None, previous_blocks=None):
    result = execute_automation_script(
        block.script,
        automation,
        period,
        comparison_period=comparison_period,
        trigger_doc=trigger_doc,
        blocks=previous_blocks or [],
        script_filename=f"WhatsApp Automation Block {automation.name}:{block.block_key}",
    ).get("result")
    return normalize_script_block_result(block, result)


def metric_block(block, columns, rows):
    return {
        "code": block.block_key,
        "title": block.title_ar or block.title or block.block_key,
        "kind": "table",
        "columns": columns,
        "rows": rows,
    }


def normalize_script_block_result(block, result):
    if result is None:
        frappe.throw(_("Script block {0} must set result.").format(block.block_key))
    if isinstance(result, str):
        result = {"text": result}
    if not isinstance(result, dict):
        frappe.throw(_("Script block {0} result must be a dictionary or text.").format(block.block_key))

    title = result.get("title") or block.title_ar or block.title or block.block_key
    if result.get("text") is not None:
        return {
            "code": block.block_key,
            "title": title,
            "kind": "text",
            "text": str(result.get("text") or ""),
        }

    rows = result.get("rows") or []
    if not isinstance(rows, list):
        frappe.throw(_("Script block {0} rows must be a list.").format(block.block_key))
    rows = [frappe._dict(row) if isinstance(row, dict) else row for row in rows]
    columns = normalize_script_columns(result.get("columns"), rows)
    return {
        "code": block.block_key,
        "title": title,
        "kind": "table",
        "columns": columns,
        "rows": limit_rows(rows, block.row_limit),
    }


def normalize_script_columns(columns, rows):
    if columns:
        normalized = []
        for column in columns:
            if isinstance(column, dict):
                fieldname = column.get("fieldname") or frappe.scrub(column.get("label") or "")
                label = column.get("label") or frappe.unscrub(fieldname)
            else:
                fieldname = str(column)
                label = frappe.unscrub(fieldname)
            if fieldname:
                normalized.append({"fieldname": fieldname, "label": label})
        return normalized
    if rows and isinstance(rows[0], dict):
        keys = list(rows[0].keys())
        if keys == ["label", "value"]:
            return columns_from_keys(keys, {"label": "البند", "value": "القيمة"})
        if keys == ["key", "value"]:
            return columns_from_keys(keys, {"key": "البند", "value": "القيمة"})
        return columns_from_keys(rows[0].keys())
    return []


def block_filters(automation, block_key, trigger_doc=None, period=None):
    context = template_context(automation, trigger_doc, period)
    filters = {}
    for row in automation.report_filters:
        if row.block_key == block_key and row.fieldname:
            filters[row.fieldname] = frappe.render_template(row.value or "", context)
    return filters


def build_automation_text(context):
    formatter_message = run_text_formatter_script(context)
    if formatter_message is not None:
        return formatter_message

    lines = [
        f"*{context.get('title') or _('WhatsApp Automation')}*",
    ]
    if context.get("company"):
        lines.append(f"الشركة: {context.get('company')}")
    if context.get("period_label"):
        lines.append(f"الفترة: {context.get('period_label')}")
    if context.get("trigger_doc"):
        doc = context["trigger_doc"]
        lines.append(f"المستند: {doc.doctype} {doc.name}")
    for block in context.get("metrics") or []:
        lines.append("")
        if block.get("kind") == "text":
            lines.append(f"*{block.get('title') or block.get('code') or _('Block')}*")
            if block.get("text"):
                lines.append(str(block.get("text")))
        else:
            lines.extend(format_metric_as_arabic_text(block))
    return "\n".join(lines).strip()


def build_automation_html(context):
    rows = []
    rows.append("<!doctype html><html><head><meta charset='utf-8'><style>")
    rows.append(DEFAULT_AUTOMATION_CSS)
    rows.append("</style></head><body><main class='automation'>")
    rows.append(f"<h1>{escape(str(context.get('title') or ''))}</h1>")
    if context.get("company"):
        rows.append(f"<p class='muted'>{escape(str(context.get('company')))}</p>")
    if context.get("period_label"):
        rows.append(f"<p class='muted'>{escape(str(context.get('period_label')))}</p>")
    for block in context.get("metrics") or []:
        rows.append(f"<section><h2>{escape(str(block.get('title') or ''))}</h2>")
        if block.get("kind") == "text":
            rows.append(f"<p>{escape(str(block.get('text') or ''))}</p>")
            rows.append("</section>")
            continue
        columns = block.get("columns") or []
        data = block.get("rows") or []
        if data:
            rows.append("<table><thead><tr>")
            for column in columns:
                rows.append(f"<th>{escape(str(column.get('label') or column.get('fieldname') or ''))}</th>")
            rows.append("</tr></thead><tbody>")
            for data_row in data:
                rows.append("<tr>")
                for column in columns:
                    rows.append(f"<td>{escape(str(data_row.get(column.get('fieldname')) or ''))}</td>")
                rows.append("</tr>")
            rows.append("</tbody></table>")
        else:
            rows.append("<p>لا توجد بيانات.</p>")
        rows.append("</section>")
    rows.append("</main></body></html>")
    return "".join(rows)


def run_text_formatter_script(context):
    automation = context.get("automation")
    script = getattr(automation, "text_formatter_script", None)
    if not script:
        return None
    result = execute_automation_script(
        script,
        automation,
        context.get("period"),
        comparison_period=context.get("comparison_period"),
        trigger_doc=context.get("trigger_doc"),
        blocks=context.get("metrics") or [],
        script_filename=f"WhatsApp Automation Formatter {automation.name}",
    )
    message = result.get("message")
    return str(message).strip() if message is not None else None


def execute_automation_script(
    script,
    automation,
    period,
    comparison_period=None,
    trigger_doc=None,
    blocks=None,
    script_filename=None,
):
    if not script:
        return {}
    locals_dict = {
        "doc": trigger_doc,
        "trigger_doc": trigger_doc,
        "doc_name": getattr(trigger_doc, "name", None),
        "doctype": getattr(trigger_doc, "doctype", None),
        "automation": automation,
        "period": period,
        "comparison_period": comparison_period,
        "company": automation.company,
        "blocks": blocks or [],
        "result": None,
        "message": None,
        "run_report": script_run_report,
        "format_value": script_format_value,
    }
    exec_globals, exec_locals = safe_exec(
        script,
        _globals=locals_dict,
        _locals={},
        restrict_commit_rollback=True,
        script_filename=script_filename,
    )
    exec_locals = exec_locals or {}
    return {
        "result": exec_locals.get("result", exec_globals.get("result")),
        "message": exec_locals.get("message", exec_globals.get("message")),
    }


def script_run_report(report_name, filters=None):
    report = run_query_report(report_name, filters=filters or {}, ignore_prepared_report=True)
    columns = normalize_report_columns(report.get("columns") or [])
    rows = normalize_report_rows(report.get("result") or [], columns)
    return {"columns": columns, "rows": rows, "raw": report}


def script_format_value(value, fieldtype=None, **kwargs):
    df = {"fieldtype": fieldtype} if fieldtype else None
    return frappe.format_value(value, df=df, **kwargs)


DEFAULT_AUTOMATION_CSS = """
body { font-family: Arial, sans-serif; color: #17202a; font-size: 12px; direction: rtl; }
.automation { padding: 18px; }
h1 { font-size: 24px; margin: 0 0 8px; }
h2 { font-size: 16px; margin: 18px 0 8px; }
.muted { color: #566573; margin: 0 0 4px; }
table { width: 100%; border-collapse: collapse; margin-top: 8px; direction: rtl; }
th, td { border: 1px solid #d6dbdf; padding: 7px; text-align: right; }
th { background: #f4f6f7; font-weight: 700; }
""".strip()


def get_doc_period(doc=None):
    if not doc:
        date = today()
        return AutomationPeriod(date, date, _("manual"))
    start = getattr(doc, "period_start_date", None) or getattr(doc, "posting_date", None) or today()
    end = getattr(doc, "period_end_date", None) or getattr(doc, "posting_date", None) or start
    return AutomationPeriod(start, end, f"{doc.doctype} {doc.name}")


def get_schedule_period(schedule):
    period = get_current_period(schedule.frequency, weekly_day=schedule.weekly_day)
    return DigestPeriod(period.start_date, period.end_date, period.label)


def get_run_trigger_doc(run_doc):
    if not run_doc.trigger_doctype or not run_doc.trigger_document:
        return None
    return frappe.get_doc(run_doc.trigger_doctype, run_doc.trigger_document)


def render_value(value, automation, doc=None, period=None):
    if value is None:
        return None
    return frappe.render_template(str(value), template_context(automation, doc, period))


def template_context(automation, doc=None, period=None):
    return {
        "doc": doc,
        "automation": automation,
        "company": automation.company,
        "doctype": getattr(doc, "doctype", None),
        "doc_name": getattr(doc, "name", None),
        "trigger_name": getattr(doc, "name", None),
        "today": today(),
        "start_date": getattr(period, "start_date", None),
        "end_date": getattr(period, "end_date", None),
    }


def safe_params(automation, doc=None, period=None):
    return {
        "company": automation.company,
        "doctype": getattr(doc, "doctype", None),
        "doc_name": getattr(doc, "name", None),
        "trigger_name": getattr(doc, "name", None),
        "start_date": getattr(period, "start_date", None),
        "end_date": getattr(period, "end_date", None),
        "today": today(),
    }


def coerce_pair(left, right):
    left_num = try_number(left)
    right_num = try_number(right)
    if left_num is not None and right_num is not None:
        return left_num, right_num
    return str(left or ""), str(right or "")


def try_number(value):
    try:
        if value in (None, ""):
            return None
        return Decimal(str(value))
    except Exception:
        return None


def to_number(value):
    number = try_number(value)
    return number if number is not None else Decimal(0)


def enqueue_due_schedules():
    now = now_datetime()
    schedules = frappe.get_all(
        "WhatsApp Schedule",
        filters={"enabled": 1},
        fields=[
            "name",
            "automation",
            "frequency",
            "send_time",
            "weekly_day",
            "last_sent_period_end",
            "send_after_month_end_days",
            "send_after_quarter_end_days",
            "send_after_year_end_days",
        ],
    )
    for row in schedules:
        if is_schedule_due(row, now):
            enqueue_automation(row.automation, force=False, schedule=row.name, source_event="Schedule")


def is_schedule_due(schedule, now=None):
    now = now or now_datetime()
    if schedule.send_time and get_time(now) < get_time(schedule.send_time):
        return False
    period = get_current_period(schedule.frequency, get_datetime(now).date(), schedule.weekly_day)
    if str(schedule.last_sent_period_end or "") == str(period.end_date):
        return False
    if schedule.frequency == "Monthly" and schedule.send_after_month_end_days:
        if get_datetime(now).date() < add_days(period.end_date, schedule.send_after_month_end_days):
            return False
    if schedule.frequency == "Quarterly" and schedule.send_after_quarter_end_days:
        if get_datetime(now).date() < add_days(period.end_date, schedule.send_after_quarter_end_days):
            return False
    if schedule.frequency == "Yearly" and schedule.send_after_year_end_days:
        if get_datetime(now).date() < add_days(period.end_date, schedule.send_after_year_end_days):
            return False
    if schedule.frequency == "Weekly" and schedule.weekly_day:
        if get_datetime(now).strftime("%A") != schedule.weekly_day:
            return False
    return True
