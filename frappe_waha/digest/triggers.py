import frappe

from frappe_waha.digest.sender import enqueue_subscription


def enqueue_pos_closing_shift_subscriptions(doc, method=None):
    filters = {
        "enabled": 1,
        "channel": "WhatsApp",
        "trigger_type": "POS Closing Shift Submit",
        "company": doc.company,
    }
    subscriptions = frappe.get_all(
        "WhatsApp Digest Subscription",
        filters=filters,
        fields=["name", "pos_profile"],
    )

    for subscription in subscriptions:
        if subscription.pos_profile and subscription.pos_profile != doc.pos_profile:
            continue

        enqueue_subscription(
            subscription.name,
            force=True,
            trigger_doctype=doc.doctype,
            trigger_name=doc.name,
        )
