from __future__ import annotations

import importlib
import json
from decimal import Decimal
from typing import Any

import frappe
from frappe import _
from frappe.utils import flt


DEFAULT_METRICS = [
    {
        "category": "Sales",
        "code": "revenue",
        "title": "Total Sales",
        "description": "Net grand total from submitted sales invoices in the period.",
        "kind": "card",
        "provider_path": "frappe_waha.digest.metrics.revenue_metric",
        "display_order": 10,
    },
    {
        "category": "Sales",
        "code": "total_orders",
        "title": "Total Orders",
        "description": "Count of submitted sales invoices in the period.",
        "kind": "card",
        "provider_path": "frappe_waha.digest.metrics.total_orders_metric",
        "display_order": 20,
    },
    {
        "category": "Sales",
        "code": "sold_qty",
        "title": "Units Sold",
        "description": "Total quantity sold from sales invoice items.",
        "kind": "card",
        "provider_path": "frappe_waha.digest.metrics.sold_qty_metric",
        "display_order": 30,
    },
    {
        "category": "Sales",
        "code": "average_sales_per_invoice",
        "title": "Avg Sales Per Invoice",
        "description": "Average net total per submitted sales invoice.",
        "kind": "card",
        "provider_path": "frappe_waha.digest.metrics.average_sales_per_invoice_metric",
        "display_order": 40,
    },
    {
        "category": "Sales",
        "code": "top_selling_items",
        "title": "Top Selling Items",
        "description": "Items ranked by sales amount and quantity.",
        "kind": "table",
        "provider_path": "frappe_waha.digest.metrics.top_selling_items_metric",
        "display_order": 50,
    },
    {
        "category": "Sales",
        "code": "top_customers",
        "title": "Top Customers by Sales",
        "description": "Customers ranked by total sales.",
        "kind": "table",
        "provider_path": "frappe_waha.digest.metrics.top_customers_metric",
        "display_order": 60,
    },
    {
        "category": "Sales",
        "code": "sales_by_time",
        "title": "Sales by Time",
        "description": "Daily sales trend for the period.",
        "kind": "chart",
        "provider_path": "frappe_waha.digest.metrics.sales_by_time_metric",
        "display_order": 70,
    },
    {
        "category": "Sales",
        "code": "payment_breakdown",
        "title": "Payment Breakdown",
        "description": "Sales invoice payments grouped by mode of payment.",
        "kind": "chart",
        "provider_path": "frappe_waha.digest.metrics.payment_breakdown_metric",
        "display_order": 80,
    },
    {
        "category": "POS",
        "code": "pos_closing_payment_reconciliation",
        "title": "POS Closing Payment Reconciliation",
        "title_ar": "مطابقة مدفوعات إغلاق نقطة البيع",
        "description": "Payment reconciliation rows from the submitted POS Closing Shift that triggered the digest.",
        "description_ar": "جدول مطابقة المدفوعات من مستند إغلاق نقطة البيع.",
        "kind": "table",
        "provider_path": "frappe_waha.digest.metrics.pos_closing_payment_reconciliation_metric",
        "column_labels_json": json.dumps(
            {
                "mode_of_payment": "طريقة الدفع",
                "opening_amount": "رصيد البداية",
                "expected_amount": "المتوقع",
                "closing_amount": "الفعلي",
                "difference": "الفرق",
            },
            ensure_ascii=False,
        ),
        "display_order": 90,
    },
]


def get_metric_catalog() -> dict[str, list[dict[str, Any]]]:
    rows = frappe.get_all(
        "WhatsApp Digest Metric",
        filters={"enabled": 1},
        fields=["category", "code", "title", "title_ar", "description", "description_ar", "kind", "display_order"],
        order_by="category asc, display_order asc, title asc",
    )
    catalog: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        row.title = row.title_ar or row.title
        row.description = row.description_ar or row.description
        catalog.setdefault(row.category or "General", []).append(row)
    return catalog


def build_metrics(
    subscription,
    selected_codes: list[str],
    period,
    comparison_period=None,
    trigger_doc=None,
) -> list[dict[str, Any]]:
    if not selected_codes:
        return []

    metric_map = {
        row.code: row
        for row in frappe.get_all(
            "WhatsApp Digest Metric",
            filters={"enabled": 1, "code": ["in", selected_codes]},
            fields=[
                "code",
                "title",
                "title_ar",
                "description",
                "description_ar",
                "kind",
                "source",
                "reference_doctype",
                "child_table_field",
                "date_field",
                "selected_fields",
                "filters_json",
                "row_limit",
                "report_name",
                "report_filters_json",
                "report_selected_fields",
                "column_labels_json",
                "provider_path",
                "custom_html",
                "custom_css",
                "custom_sql",
            ],
        )
    }

    results = []
    for code in selected_codes:
        metric = metric_map.get(code)
        if not metric:
            continue

        if metric.source and metric.source != "Built-in Provider":
            value = custom_metric(metric, subscription, period, comparison_period, trigger_doc)
        else:
            provider = import_provider(metric.provider_path)
            value = provider(subscription, period, comparison_period, trigger_doc=trigger_doc)
        if value is None:
            continue

        value.update(
            {
                "code": metric.code,
                "title": value.get("title") or metric.title_ar or metric.title,
                "description": value.get("description") or metric.description_ar or metric.description,
                "kind": value.get("kind") or metric.kind,
            }
        )
        results.append(value)

    return results


def import_provider(path: str):
    module_name, function_name = path.rsplit(".", 1)
    module = importlib.import_module(module_name)
    return getattr(module, function_name)


def custom_metric(metric, subscription, period, comparison_period=None, trigger_doc=None):
    rows: list[dict[str, Any]] = []
    columns: list[dict[str, str]] = []
    params = {
        "company": subscription.company,
        "pos_profile": subscription.pos_profile,
        "start_date": period.start_date,
        "end_date": period.end_date,
        "trigger_doctype": getattr(trigger_doc, "doctype", None),
        "trigger_name": getattr(trigger_doc, "name", None),
    }
    column_labels = parse_json_field(
        metric.column_labels_json,
        "Arabic Column Labels",
        expected_type=dict,
        allow_empty=True,
    )

    if metric.source == "DocType Table":
        rows, columns = get_doctype_rows(metric, period, params, trigger_doc)
    elif metric.source == "Query Report":
        rows, columns = get_report_rows(metric, params, column_labels)
    elif metric.custom_sql:
        rows = frappe.db.sql(metric.custom_sql, params, as_dict=True)
        if rows:
            columns = columns_from_keys(rows[0].keys(), column_labels)

    context = {
        "frappe": frappe,
        "_": _,
        "subscription": subscription,
        "period": period,
        "comparison_period": comparison_period,
        "doc": trigger_doc,
        "trigger_doc": trigger_doc,
        "metric": metric,
        "rows": rows,
        "columns": columns,
        "params": params,
    }

    try:
        html = frappe.render_template(metric.custom_html or "", context) if metric.custom_html else ""
        css = frappe.render_template(metric.custom_css or "", context) if metric.custom_css else ""
    except Exception:
        frappe.log_error(frappe.get_traceback(), _("WhatsApp custom metric render failed"))
        return {
            "kind": "table",
            "columns": [{"fieldname": "error", "label": "خطأ"}],
            "rows": [{"error": _("Custom metric template failed. Check the metric configuration.")}],
        }
    if html:
        return {"kind": "html", "html": html, "css": css, "rows": rows, "columns": columns}

    if not columns and rows:
        columns = columns_from_keys(rows[0].keys(), column_labels)

    return {"kind": "table", "rows": rows, "columns": columns}


def get_doctype_rows(metric, period, params, trigger_doc=None):
    fields = parse_selected_fields(metric.selected_fields)
    column_labels = parse_json_field(
        metric.column_labels_json,
        "Arabic Column Labels",
        expected_type=dict,
        allow_empty=True,
    )

    if trigger_doc and metric.reference_doctype == trigger_doc.doctype and metric.child_table_field:
        rows = []
        for row in trigger_doc.get(metric.child_table_field) or []:
            rows.append({field: row.get(field) for field in fields})
        return limit_rows(rows, metric.row_limit), columns_from_keys(fields, column_labels)

    if metric.child_table_field:
        return get_child_table_rows(metric, period, params, fields, column_labels)

    filters = render_json_templates(
        parse_json_field(metric.filters_json, "Filters JSON", expected_type=dict, allow_empty=True),
        params,
    )
    if metric.date_field:
        filters[metric.date_field] = ["between", [period.start_date, period.end_date]]

    rows = frappe.get_all(
        metric.reference_doctype,
        filters=filters,
        fields=fields,
        limit_page_length=metric.row_limit or 20,
        order_by="modified desc",
    )
    return rows, columns_from_keys(fields, column_labels)


def get_child_table_rows(metric, period, params, fields, column_labels):
    parent_meta = frappe.get_meta(metric.reference_doctype)
    child_field = parent_meta.get_field(metric.child_table_field)
    if not child_field or not child_field.options:
        frappe.throw(_("Child Table Field {0} was not found on {1}.").format(
            metric.child_table_field,
            metric.reference_doctype,
        ))

    parent_filters = render_json_templates(
        parse_json_field(metric.filters_json, "Filters JSON", expected_type=dict, allow_empty=True),
        params,
    )
    if metric.date_field:
        parent_filters[metric.date_field] = ["between", [period.start_date, period.end_date]]

    parent_names = frappe.get_all(metric.reference_doctype, filters=parent_filters, pluck="name")
    if not parent_names:
        return [], columns_from_keys(fields, column_labels)

    filters = {
        "parenttype": metric.reference_doctype,
        "parentfield": metric.child_table_field,
        "parent": ["in", parent_names],
    }
    rows = frappe.get_all(
        child_field.options,
        filters=filters,
        fields=fields,
        limit_page_length=metric.row_limit or 20,
        order_by="parent desc, idx asc",
    )
    return rows, columns_from_keys(fields, column_labels)


def get_report_rows(metric, params, column_labels=None):
    from frappe.desk.query_report import run

    filters = render_json_templates(
        parse_json_field(metric.report_filters_json, "Report Filters JSON", expected_type=dict, allow_empty=True),
        params,
    )
    result = run(metric.report_name, filters=filters, ignore_prepared_report=True)
    columns = normalize_report_columns(result.get("columns") or [])
    rows = normalize_report_rows(result.get("result") or [], columns)
    selected_fields = parse_optional_selected_fields(metric.report_selected_fields)
    if selected_fields:
        columns = [column for column in columns if column.get("fieldname") in selected_fields]
        rows = [{fieldname: row.get(fieldname) for fieldname in selected_fields} for row in rows]
    if column_labels:
        for column in columns:
            column["label"] = column_labels.get(column.get("fieldname")) or column.get("label")
    return limit_rows(rows, metric.row_limit), columns


def normalize_report_columns(columns):
    normalized = []
    for column in columns:
        if isinstance(column, dict):
            fieldname = column.get("fieldname") or frappe.scrub(column.get("label") or "")
            label = column.get("label") or frappe.unscrub(fieldname)
        else:
            label = str(column).split(":")[0]
            fieldname = frappe.scrub(label)
        normalized.append({"fieldname": fieldname, "label": label})
    return normalized


def normalize_report_rows(rows, columns):
    normalized = []
    fieldnames = [column["fieldname"] for column in columns]
    for row in rows:
        if isinstance(row, dict):
            normalized.append(row)
        else:
            normalized.append({fieldname: row[index] if index < len(row) else None for index, fieldname in enumerate(fieldnames)})
    return normalized


def parse_selected_fields(value):
    fields = parse_json_field(value, "Selected Fields", expected_type=list)
    normalized = normalize_selected_fields(fields)
    if not normalized:
        frappe.throw(_("Selected Fields must include at least one field."))
    return normalized


def parse_optional_selected_fields(value):
    fields = parse_json_field(value, "Report Selected Columns", expected_type=list, allow_empty=True)
    return normalize_selected_fields(fields)


def normalize_selected_fields(fields):
    normalized = []
    for field in fields:
        if isinstance(field, dict):
            fieldname = field.get("fieldname")
        else:
            fieldname = str(field)
        if fieldname:
            normalized.append(fieldname)
    return normalized


def parse_json_field(value, label, expected_type=None, allow_empty=False):
    if not value:
        if allow_empty:
            return {} if expected_type is dict else [] if expected_type is list else None
        frappe.throw(_("{0} is required.").format(label))
    try:
        parsed = json.loads(value)
    except Exception:
        frappe.throw(_("{0} must be valid JSON.").format(label))
    if expected_type and not isinstance(parsed, expected_type):
        frappe.throw(_("{0} has invalid JSON type.").format(label))
    return parsed


def render_json_templates(value, context):
    rendered = {}
    for key, item in (value or {}).items():
        if isinstance(item, str):
            rendered[key] = frappe.render_template(item, context)
        else:
            rendered[key] = item
    return rendered


def columns_from_keys(keys, labels=None):
    labels = labels or {}
    return [{"fieldname": key, "label": labels.get(key) or frappe.unscrub(key)} for key in keys]


def limit_rows(rows, limit):
    if not limit:
        return rows
    return rows[: int(limit)]


def base_filters(subscription, period) -> tuple[str, dict[str, Any]]:
    where = ["si.docstatus = 1", "si.posting_date between %(start_date)s and %(end_date)s"]
    params = {
        "start_date": period.start_date,
        "end_date": period.end_date,
        "company": subscription.company,
    }

    if subscription.company:
        where.append("si.company = %(company)s")

    if getattr(subscription, "pos_profile", None):
        where.append("si.pos_profile = %(pos_profile)s")
        params["pos_profile"] = subscription.pos_profile

    return " and ".join(where), params


def currency(subscription) -> str | None:
    if not subscription.company:
        return None
    return frappe.get_cached_value("Company", subscription.company, "default_currency")


def money(value, subscription) -> str:
    return frappe.format_value(value or 0, {"fieldtype": "Currency", "options": currency(subscription)})


def number(value) -> str:
    if isinstance(value, Decimal):
        value = float(value)
    return frappe.format_value(value or 0, {"fieldtype": "Float", "precision": 2})


def revenue_metric(subscription, period, comparison_period=None, trigger_doc=None):
    where, params = base_filters(subscription, period)
    value = frappe.db.sql(
        f"select coalesce(sum(si.net_total), 0) from `tabSales Invoice` si where {where}",
        params,
    )[0][0]
    return {"value": money(value, subscription)}


def total_orders_metric(subscription, period, comparison_period=None, trigger_doc=None):
    where, params = base_filters(subscription, period)
    value = frappe.db.sql(
        f"select count(*) from `tabSales Invoice` si where {where}",
        params,
    )[0][0]
    return {"value": int(value or 0)}


def sold_qty_metric(subscription, period, comparison_period=None, trigger_doc=None):
    where, params = base_filters(subscription, period)
    value = frappe.db.sql(
        f"""
        select coalesce(sum(item.qty), 0)
        from `tabSales Invoice` si
        inner join `tabSales Invoice Item` item on item.parent = si.name
        where {where}
        """,
        params,
    )[0][0]
    return {"value": number(value)}


def average_sales_per_invoice_metric(subscription, period, comparison_period=None, trigger_doc=None):
    where, params = base_filters(subscription, period)
    value = frappe.db.sql(
        f"select coalesce(avg(si.net_total), 0) from `tabSales Invoice` si where {where}",
        params,
    )[0][0]
    return {"value": money(value, subscription)}


def top_selling_items_metric(subscription, period, comparison_period=None, trigger_doc=None):
    where, params = base_filters(subscription, period)
    rows = frappe.db.sql(
        f"""
        select item.item_code, item.item_name,
               coalesce(sum(item.qty), 0) as qty,
               coalesce(sum(item.net_amount), 0) as amount
        from `tabSales Invoice` si
        inner join `tabSales Invoice Item` item on item.parent = si.name
        where {where}
        group by item.item_code, item.item_name
        order by amount desc
        limit 10
        """,
        params,
        as_dict=True,
    )
    return {
        "columns": [
            {"fieldname": "item_name", "label": "Item"},
            {"fieldname": "qty", "label": "Qty"},
            {"fieldname": "amount", "label": "Amount"},
        ],
        "rows": [
            {"item_name": row.item_name or row.item_code, "qty": flt(row.qty, 2), "amount": money(row.amount, subscription)}
            for row in rows
        ],
    }


def top_customers_metric(subscription, period, comparison_period=None, trigger_doc=None):
    where, params = base_filters(subscription, period)
    rows = frappe.db.sql(
        f"""
        select si.customer, si.customer_name,
               count(*) as orders,
               coalesce(sum(si.net_total), 0) as amount
        from `tabSales Invoice` si
        where {where}
        group by si.customer, si.customer_name
        order by amount desc
        limit 10
        """,
        params,
        as_dict=True,
    )
    return {
        "columns": [
            {"fieldname": "customer_name", "label": "Customer"},
            {"fieldname": "orders", "label": "Orders"},
            {"fieldname": "amount", "label": "Amount"},
        ],
        "rows": [
            {"customer_name": row.customer_name or row.customer, "orders": row.orders, "amount": money(row.amount, subscription)}
            for row in rows
        ],
    }


def sales_by_time_metric(subscription, period, comparison_period=None, trigger_doc=None):
    where, params = base_filters(subscription, period)
    rows = frappe.db.sql(
        f"""
        select si.posting_date as label, coalesce(sum(si.net_total), 0) as value
        from `tabSales Invoice` si
        where {where}
        group by si.posting_date
        order by si.posting_date asc
        """,
        params,
        as_dict=True,
    )
    return {"points": [{"label": str(row.label), "value": money(row.value, subscription)} for row in rows]}


def payment_breakdown_metric(subscription, period, comparison_period=None, trigger_doc=None):
    where, params = base_filters(subscription, period)
    rows = frappe.db.sql(
        f"""
        select pay.mode_of_payment as label, coalesce(sum(pay.amount), 0) as value
        from `tabSales Invoice` si
        inner join `tabSales Invoice Payment` pay on pay.parent = si.name
        where {where}
        group by pay.mode_of_payment
        order by value desc
        """,
        params,
        as_dict=True,
    )
    return {"points": [{"label": row.label, "value": money(row.value, subscription)} for row in rows]}


def pos_closing_payment_reconciliation_metric(subscription, period, comparison_period=None, trigger_doc=None):
    if not trigger_doc or trigger_doc.doctype != "POS Closing Shift":
        return {
            "columns": [
                {"fieldname": "message", "label": "Message"},
            ],
            "rows": [
                {"message": _("This metric is available when triggered by a POS Closing Shift.")},
            ],
        }

    columns = [
        {"fieldname": "mode_of_payment", "label": "طريقة الدفع"},
        {"fieldname": "opening_amount", "label": "رصيد البداية"},
        {"fieldname": "expected_amount", "label": "المتوقع"},
        {"fieldname": "closing_amount", "label": "الفعلي"},
        {"fieldname": "difference", "label": "الفرق"},
    ]
    rows = []
    for row in trigger_doc.get("payment_reconciliation") or []:
        rows.append(
            {
                "mode_of_payment": row.mode_of_payment,
                "opening_amount": money(row.opening_amount, subscription),
                "expected_amount": money(row.expected_amount, subscription),
                "closing_amount": money(row.closing_amount, subscription),
                "difference": money(row.difference, subscription),
            }
        )

    return {"columns": columns, "rows": rows}
