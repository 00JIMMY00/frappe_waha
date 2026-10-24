"""Validate the supported framework boundary before installing or migrating."""

import importlib

import frappe
from frappe import _


def validate_requirements():
    installed = frappe.get_installed_apps()
    for app in ("frappe", "erpnext"):
        if app not in installed:
            frappe.throw(_("Install {0} v15 on this site before installing WhatsApp.").format(app))
        module = importlib.import_module(app)
        version = getattr(module, "__version__", "")
        if version.split(".", 1)[0] != "15":
            frappe.throw(
                _("WhatsApp requires {0} v15; found {1}.").format(app, version or "unknown")
            )
