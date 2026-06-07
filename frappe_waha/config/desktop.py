from frappe import _


def get_data():
    return [
        {
            "module_name": "Frappe Waha",
            "category": "Modules",
            "label": _("WhatsApp"),
            "color": "#128C7E",
            "icon": "octicon octicon-comment-discussion",
            "type": "module",
            "description": _("WAHA WhatsApp phones, digest templates, subscriptions, and run logs"),
        }
    ]

