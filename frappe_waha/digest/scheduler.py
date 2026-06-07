import frappe
from frappe.utils import add_days, get_datetime, get_time, now_datetime

from frappe_waha.digest.periods import get_previous_complete_period
from frappe_waha.digest.sender import enqueue_subscription, find_existing_successful_run
from frappe_waha.utils.waha_client import WAHAClient


def enqueue_due_subscriptions():
    now = now_datetime()
    rows = frappe.get_all(
        "WhatsApp Digest Subscription",
        filters={"enabled": 1, "channel": "WhatsApp"},
        fields=["name", "frequency", "send_time", "last_sent_period_end"],
    )
    for row in rows:
        subscription = frappe.get_doc("WhatsApp Digest Subscription", row.name)
        if is_due(subscription, now):
            enqueue_subscription(subscription.name)


def is_due(subscription, now=None) -> bool:
    now = now or now_datetime()
    if subscription.send_time and get_time(now) < get_time(subscription.send_time):
        return False

    period = get_previous_complete_period(subscription, now.date())
    if find_existing_successful_run(subscription.name, period.end_date):
        return False

    if subscription.frequency == "Monthly" and subscription.send_after_month_end_days:
        if get_datetime(now).date() < add_days(period.end_date, subscription.send_after_month_end_days):
            return False

    if subscription.frequency == "Quarterly" and subscription.send_after_quarter_end_days:
        if get_datetime(now).date() < add_days(period.end_date, subscription.send_after_quarter_end_days):
            return False

    if subscription.frequency == "Yearly" and subscription.send_after_year_end_days:
        if get_datetime(now).date() < add_days(period.end_date, subscription.send_after_year_end_days):
            return False

    if subscription.frequency == "Weekly" and subscription.weekly_day:
        if get_datetime(now).strftime("%A") != subscription.weekly_day:
            return False

    return True


def sync_active_phone_statuses():
    phone_names = frappe.get_all(
        "WhatsApp Phone",
        filters={"session_name": ["is", "set"], "status": ["!=", "Expired"]},
        pluck="name",
    )
    if not phone_names:
        return

    client = WAHAClient.from_settings()
    for name in phone_names:
        try:
            doc = frappe.get_doc("WhatsApp Phone", name)
            doc.sync_from_waha(client=client, save=True)
        except Exception:
            frappe.log_error(frappe.get_traceback(), "WAHA phone status sync failed")
