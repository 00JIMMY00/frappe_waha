from __future__ import annotations

import importlib
from decimal import Decimal
from typing import Any

import frappe
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
]


def get_metric_catalog() -> dict[str, list[dict[str, Any]]]:
    rows = frappe.get_all(
        "WhatsApp Digest Metric",
        filters={"enabled": 1},
        fields=["category", "code", "title", "description", "kind", "provider_path", "display_order"],
        order_by="category asc, display_order asc, title asc",
    )
    catalog: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        catalog.setdefault(row.category or "General", []).append(row)
    return catalog


def build_metrics(subscription, selected_codes: list[str], period, comparison_period=None) -> list[dict[str, Any]]:
    if not selected_codes:
        return []

    metric_map = {
        row.code: row
        for row in frappe.get_all(
            "WhatsApp Digest Metric",
            filters={"enabled": 1, "code": ["in", selected_codes]},
            fields=["code", "title", "description", "kind", "provider_path"],
        )
    }

    results = []
    for code in selected_codes:
        metric = metric_map.get(code)
        if not metric:
            continue

        provider = import_provider(metric.provider_path)
        value = provider(subscription, period, comparison_period)
        if value is None:
            continue

        value.update(
            {
                "code": metric.code,
                "title": value.get("title") or metric.title,
                "description": value.get("description") or metric.description,
                "kind": value.get("kind") or metric.kind,
            }
        )
        results.append(value)

    return results


def import_provider(path: str):
    module_name, function_name = path.rsplit(".", 1)
    module = importlib.import_module(module_name)
    return getattr(module, function_name)


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


def revenue_metric(subscription, period, comparison_period=None):
    where, params = base_filters(subscription, period)
    value = frappe.db.sql(
        f"select coalesce(sum(si.net_total), 0) from `tabSales Invoice` si where {where}",
        params,
    )[0][0]
    return {"value": money(value, subscription)}


def total_orders_metric(subscription, period, comparison_period=None):
    where, params = base_filters(subscription, period)
    value = frappe.db.sql(
        f"select count(*) from `tabSales Invoice` si where {where}",
        params,
    )[0][0]
    return {"value": int(value or 0)}


def sold_qty_metric(subscription, period, comparison_period=None):
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


def average_sales_per_invoice_metric(subscription, period, comparison_period=None):
    where, params = base_filters(subscription, period)
    value = frappe.db.sql(
        f"select coalesce(avg(si.net_total), 0) from `tabSales Invoice` si where {where}",
        params,
    )[0][0]
    return {"value": money(value, subscription)}


def top_selling_items_metric(subscription, period, comparison_period=None):
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


def top_customers_metric(subscription, period, comparison_period=None):
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


def sales_by_time_metric(subscription, period, comparison_period=None):
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


def payment_breakdown_metric(subscription, period, comparison_period=None):
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

