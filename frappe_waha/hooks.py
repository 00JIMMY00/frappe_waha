app_name = "frappe_waha"
app_title = "Frappe OpenWA"
app_publisher = "Arab ERP"
app_description = "WhatsApp digest delivery through OpenWA"
app_email = "support@arab-erp.com"
app_license = "MIT"

after_install = "frappe_waha.install.after_install"
after_migrate = "frappe_waha.install.after_install"

doc_events = {
    "*": {
        "validate": "frappe_waha.digest.automation.dispatch_doc_event",
        "before_save": "frappe_waha.digest.automation.dispatch_doc_event",
        "after_insert": "frappe_waha.digest.automation.dispatch_doc_event",
        "on_update": "frappe_waha.digest.automation.dispatch_doc_event",
        "on_submit": "frappe_waha.digest.automation.dispatch_doc_event",
        "on_cancel": "frappe_waha.digest.automation.dispatch_doc_event",
        "on_trash": "frappe_waha.digest.automation.dispatch_doc_event",
    },
    "POS Closing Shift": {
        "on_submit": "frappe_waha.digest.triggers.enqueue_pos_closing_shift_subscriptions",
    },
}

scheduler_events = {
    "all": [
        "frappe_waha.digest.scheduler.enqueue_due_subscriptions",
        "frappe_waha.digest.automation.enqueue_due_schedules",
        "frappe_waha.digest.scheduler.sync_active_phone_statuses",
    ],
}
