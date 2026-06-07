app_name = "frappe_waha"
app_title = "Frappe WAHA"
app_publisher = "Arab ERP"
app_description = "WhatsApp digest delivery through WAHA"
app_email = "support@arab-erp.com"
app_license = "MIT"

after_install = "frappe_waha.install.after_install"

scheduler_events = {
    "all": [
        "frappe_waha.digest.scheduler.enqueue_due_subscriptions",
        "frappe_waha.digest.scheduler.sync_active_phone_statuses",
    ],
}

