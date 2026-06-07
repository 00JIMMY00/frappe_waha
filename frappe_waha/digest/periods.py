from dataclasses import dataclass

import frappe
from frappe import _
from frappe.utils import add_days, add_months, getdate, nowdate


@dataclass(frozen=True)
class DigestPeriod:
    start_date: object
    end_date: object
    label: str


def get_current_period(frequency: str, reference_date=None, weekly_day: str | None = None) -> DigestPeriod:
    date = getdate(reference_date or nowdate())
    frequency = frequency or "Daily"

    if frequency == "Daily":
        return DigestPeriod(date, date, str(date))

    if frequency == "Weekly":
        start = add_days(date, -date.weekday())
        if weekly_day:
            # The send day does not change the reported Monday-Sunday week.
            weekly_day = weekly_day
        end = add_days(start, 6)
        return DigestPeriod(start, end, f"{start} to {end}")

    if frequency == "Monthly":
        start = date.replace(day=1)
        end = add_days(add_months(start, 1), -1)
        return DigestPeriod(start, end, start.strftime("%B %Y"))

    if frequency == "Quarterly":
        quarter_month = ((date.month - 1) // 3) * 3 + 1
        start = date.replace(month=quarter_month, day=1)
        end = add_days(add_months(start, 3), -1)
        return DigestPeriod(start, end, f"Q{((date.month - 1) // 3) + 1} {date.year}")

    if frequency == "Yearly":
        start = date.replace(month=1, day=1)
        end = date.replace(month=12, day=31)
        return DigestPeriod(start, end, str(date.year))

    frappe.throw(_("Unsupported digest frequency: {0}").format(frequency))


def get_previous_complete_period(subscription, reference_date=None) -> DigestPeriod:
    current = get_current_period(subscription.frequency, reference_date, subscription.weekly_day)
    return shift_period(current, subscription.frequency, -1)


def get_comparison_period(period: DigestPeriod, compare_vs: str, frequency: str) -> DigestPeriod | None:
    if not compare_vs:
        return None

    if compare_vs.startswith("previous_"):
        return shift_period(period, frequency, -1)

    if compare_vs.endswith("_last_year"):
        return DigestPeriod(
            add_months(period.start_date, -12),
            add_months(period.end_date, -12),
            _("same period last year"),
        )

    if "last_month" in compare_vs:
        return DigestPeriod(
            add_months(period.start_date, -1),
            add_months(period.end_date, -1),
            _("same period last month"),
        )

    if "last_quarter" in compare_vs:
        return DigestPeriod(
            add_months(period.start_date, -3),
            add_months(period.end_date, -3),
            _("same period last quarter"),
        )

    return None


def shift_period(period: DigestPeriod, frequency: str, count: int) -> DigestPeriod:
    if frequency == "Daily":
        return DigestPeriod(add_days(period.start_date, count), add_days(period.end_date, count), _("previous day"))
    if frequency == "Weekly":
        return DigestPeriod(add_days(period.start_date, 7 * count), add_days(period.end_date, 7 * count), _("previous week"))
    if frequency == "Monthly":
        start = add_months(period.start_date, count)
        end = add_days(add_months(start, 1), -1)
        return DigestPeriod(start, end, start.strftime("%B %Y"))
    if frequency == "Quarterly":
        start = add_months(period.start_date, 3 * count)
        end = add_days(add_months(start, 3), -1)
        return DigestPeriod(start, end, f"Q{((start.month - 1) // 3) + 1} {start.year}")
    if frequency == "Yearly":
        start = add_months(period.start_date, 12 * count)
        end = start.replace(month=12, day=31)
        return DigestPeriod(start, end, str(start.year))
    return period

