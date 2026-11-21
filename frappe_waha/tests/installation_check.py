"""Explicitly invoked integration checks for the authorized disposable test site.

bench --site SITE execute frappe_waha.tests.installation_check.check_installation
No outbound connection is made. Temporary configuration edits are rolled back.
"""

import frappe

from frappe_waha.install import after_install
from frappe_waha.requirements import validate_requirements


def check_installation():
    validate_requirements()
    outbound_doctypes = (
        "WhatsApp Automation",
        "WhatsApp Schedule",
        "WhatsApp Digest Subscription",
        "WhatsApp Digest Run",
    )
    before = {doctype: frappe.db.count(doctype) for doctype in outbound_doctypes}
    metrics = frappe.get_all("WhatsApp Digest Metric", fields=["name", "code"])
    assert metrics, "Installation must create the general catalog"
    assert not any(
        row.code == "pos_closing_payment_reconciliation" for row in metrics
    ), "This check expects a site without the POS extension"
    frappe.db.savepoint("whatsapp_installation_check")
    try:
        metric = frappe.get_doc("WhatsApp Digest Metric", metrics[0].name)
        metric.title = "Installation check: preserve custom title"
        metric.enabled = 0
        metric.save(ignore_permissions=True)
        template = frappe.get_doc("WhatsApp Digest Template", "Default WhatsApp Digest")
        template.css = "/* Installation check: preserve custom CSS */"
        template.save(ignore_permissions=True)
        expected_metric = frappe.get_doc(metric.doctype, metric.name).as_dict()
        expected_template = frappe.get_doc(template.doctype, template.name).as_dict()
        for _ in range(2):
            after_install()
            assert frappe.get_doc(metric.doctype, metric.name).as_dict() == expected_metric
            assert frappe.get_doc(template.doctype, template.name).as_dict() == expected_template
            assert {dt: frappe.db.count(dt) for dt in outbound_doctypes} == before
        field = frappe.get_meta("Sales Invoice").get_field("send_to_whatsapp")
        assert field and field.fieldtype == "Check" and field.default == "1"
        assert frappe.new_doc("Sales Invoice").send_to_whatsapp == 1
        return {
            "passed": True,
            "general_metrics": len(metrics),
            "outbound_counts": before,
            "repeat_seed_passes": 2,
            "enabled_automations": frappe.db.count("WhatsApp Automation", {"enabled": 1}),
            "engine": frappe.db.get_single_value("WAHA Settings", "execution_engine") or "Legacy",
            "invoice_number_field": bool(
                frappe.get_meta("Sales Invoice").has_field("whatsapp_number")
            ),
            "invoice_send_default": field.default,
        }
    finally:
        frappe.db.rollback(save_point="whatsapp_installation_check")
