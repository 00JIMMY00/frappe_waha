"""Permission-checked Desk actions for submitted invoice delivery."""

import frappe
from frappe import _

from frappe_waha.digest.engine import is_unified, queue_execution


@frappe.whitelist()
def queue_invoice(invoice_name, automation_name, resend=False):
    invoice = frappe.get_doc("Sales Invoice", invoice_name)
    invoice.check_permission("write")
    invoice.check_permission("print")
    automation = frappe.get_doc("WhatsApp Automation", automation_name)
    automation.check_permission("write")
    if (
        not is_unified()
        or automation.engine_version != "Unified"
        or automation.action != "Document Delivery"
    ):
        frappe.throw(_("Select an enabled Unified invoice delivery automation."))
    if invoice.docstatus != 1 or invoice.company != automation.company:
        frappe.throw(_("The invoice must be submitted and belong to the automation company."))
    from frappe.utils import cint

    resend = bool(cint(resend))
    run = queue_execution(
        automation.name,
        doctype=invoice.doctype,
        name=invoice.name,
        force=resend,
        source_event="Manual" if resend else "Submit",
    )
    if not run:
        frappe.throw(_("The invoice delivery automation is paused."))
    return {"run": run}


@frappe.whitelist()
def invoice_history(invoice_name):
    invoice = frappe.get_doc("Sales Invoice", invoice_name)
    invoice.check_permission("read")
    return frappe.get_list(
        "WhatsApp Digest Run",
        filters={"trigger_doctype": "Sales Invoice", "trigger_document": invoice.name},
        fields=["name", "status", "creation", "source_event", "error"],
        order_by="creation desc",
        limit_page_length=50,
    )
