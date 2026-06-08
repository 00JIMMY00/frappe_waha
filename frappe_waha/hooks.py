app_name = "frappe_waha"
app_title = "Frappe OpenWA"
app_publisher = "Arab ERP"
app_description = "WhatsApp digest delivery through OpenWA"
app_email = "support@arab-erp.com"
app_license = "MIT"

after_install = "frappe_waha.install.after_install"
after_migrate = "frappe_waha.install.after_install"

doc_events = {
    "POS Closing Shift": {
        "on_submit": "frappe_waha.digest.triggers.enqueue_pos_closing_shift_subscriptions",
    },
}

scheduler_events = {
    "all": [
        "frappe_waha.digest.scheduler.enqueue_due_subscriptions",
        "frappe_waha.digest.scheduler.sync_active_phone_statuses",
    ],
}
