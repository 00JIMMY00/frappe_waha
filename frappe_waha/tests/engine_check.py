"""Explicit test-site-only integration exercise; the transport is always mocked.

Fixtures are committed because the engine deliberately commits before dispatch.
All fixture records and temporary settings are removed/restored in finally.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import Mock, patch
from uuid import uuid4

import frappe
from frappe.utils import now_datetime

from frappe_waha.digest import engine
from frappe_waha.utils.openwa_client import OpenWAError


def check_engine():
    site = frappe.local.site
    sites_path = frappe.local.sites_path
    company = frappe.db.get_value("Company", {}, "name")
    assert company, "This integration check requires an ERPNext company"
    old_engine = frappe.db.get_single_value("WAHA Settings", "execution_engine")
    fixtures = []
    runs = []
    prefix = "Synthetic engine check " + uuid4().hex[:10]
    client = Mock()
    calls = []
    failed_once = set()

    def send_text(**kwargs):
        calls.append(kwargs.copy())
        key = (kwargs["chat_id"], kwargs["text"])
        if (
            kwargs["chat_id"] == "12025550101@c.us"
            and kwargs["text"] == "second"
            and key not in failed_once
        ):
            failed_once.add(key)
            raise OpenWAError("Synthetic rate limit", outcome="retryable")
        return {"id": "synthetic-accepted"}

    client.send_text.side_effect = send_text

    def in_connection(method, *args):
        frappe.init(site=site, sites_path=sites_path)
        frappe.connect()
        frappe.set_user("Administrator")
        try:
            result = method(*args)
            frappe.db.commit()
            return result
        finally:
            frappe.destroy()

    def queue(name):
        return engine.queue_execution(name, source_event="Manual")

    # No test may reach any actual HTTP connection, even through an unexpected code path.
    with (
        patch("requests.request", side_effect=AssertionError("Unexpected network request in test")),
        patch.object(engine.OpenWAClient, "from_settings", return_value=client),
        patch.object(frappe, "enqueue"),
        patch(
            "frappe_waha.digest.automation.render_automation",
            return_value=("first\n\nsecond", "<p>synthetic</p>", {}),
        ) as render,
        patch.object(engine, "split_text_message", return_value=["first", "second"]),
    ):
        try:
            frappe.db.set_single_value("WAHA Settings", "execution_engine", "Unified")
            phone = frappe.get_doc(
                {
                    "doctype": "WhatsApp Phone",
                    "phone": "+12025550199",
                    "default_country_code": "+1",
                    "status": "Active",
                    "session_status": "ready",
                    "session_name": "synthetic-no-gateway",
                }
            )
            assert not frappe.db.exists(
                "WhatsApp Phone", phone.phone
            ), "Synthetic fixture phone is already in use"
            phone.insert(ignore_permissions=True)
            fixtures.append((phone.doctype, phone.name))
            rule = frappe.get_doc(
                {
                    "doctype": "WhatsApp Automation",
                    "title": prefix,
                    "enabled": 1,
                    "company": company,
                    "execution_user": "Administrator",
                    "whatsapp_phone": phone.name,
                    "trigger_event": "Manual",
                    "action": "Summary",
                    "output_mode": "Text",
                    "recipients": [{"phone": "+12025550101"}, {"phone": "+12025550102"}],
                    "blocks": [
                        {
                            "block_key": "synthetic",
                            "source": "DocType Table",
                            "reference_doctype": "Sales Invoice",
                            "enabled": 1,
                        }
                    ],
                }
            )
            rule.insert(ignore_permissions=True)
            fixtures.append((rule.doctype, rule.name))
            frappe.db.commit()
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: in_connection(queue, rule.name), range(2)))
            assert (
                results[0] and results[0] == results[1]
            ), f"Concurrent enqueue must return the same execution: {results!r}"
            runs.append(results[0])
            assert frappe.db.count("WhatsApp Digest Run", {"automation": rule.name}) == 1
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(
                    pool.map(
                        lambda _: in_connection(engine.process_execution, results[0]), range(2)
                    )
                )
            frappe.db.commit()  # Refresh the main connection repeatable-read snapshot.
            assert (
                len(calls) == 4
            ), "One partial failure must not cause concurrent duplicate delivery"
            assert render.call_count == 1
            run = frappe.get_doc("WhatsApp Digest Run", results[0])
            assert run.status == "Queued", run.status
            parts = frappe.get_all(
                "WhatsApp Delivery", filters={"run": run.name}, fields=["name", "status", "content"]
            )
            assert sum(p.status == "Provider Accepted" for p in parts) == 3
            frappe.db.set_value(
                "WhatsApp Delivery",
                {"run": run.name, "status": "Queued"},
                "next_attempt_at",
                now_datetime() - timedelta(seconds=1),
            )
            frappe.db.commit()
            engine.process_execution(run.name)
            assert len(calls) == 5
            failed_part_calls = [
                c for c in calls if c["chat_id"] == "12025550101@c.us" and c["text"] == "second"
            ]
            assert (
                len(failed_part_calls) == 2
                and failed_part_calls[0]["idempotency_key"]
                == failed_part_calls[1]["idempotency_key"]
            )
            assert render.call_count == 1, "Retry must reuse rendered content"
            assert frappe.db.get_value(run.doctype, run.name, "status") == "Provider Accepted"
            engine.process_execution(run.name)
            assert len(calls) == 5
            # A new deliberate resend gets its own identity; uncertain outcomes never auto retry.
            client.send_text.side_effect = OpenWAError(
                "Synthetic read timeout", outcome="uncertain"
            )
            uncertain = engine.queue_execution(rule.name, force=True, source_event="Manual")
            runs.append(uncertain)
            assert uncertain != run.name
            frappe.db.commit()
            engine.process_execution(uncertain)
            assert frappe.db.get_value(run.doctype, uncertain, "status") == "Uncertain"
            attempts = client.send_text.call_count
            engine.process_execution(uncertain)
            assert client.send_text.call_count == attempts
            # Cutover is enforced at execution time for already queued jobs.
            paused = engine.queue_execution(rule.name, force=True, source_event="Manual")
            runs.append(paused)
            frappe.db.set_single_value("WAHA Settings", "execution_engine", "Legacy")
            frappe.db.commit()
            engine.process_execution(paused)
            assert client.send_text.call_count == attempts
            assert frappe.db.get_value(run.doctype, paused, "status") == "Queued"
            # A disabled execution identity must fail before any provider request.
            frappe.db.set_single_value("WAHA Settings", "execution_engine", "Unified")
            denied = engine.queue_execution(rule.name, force=True, source_event="Manual")
            runs.append(denied)
            frappe.db.set_value("WhatsApp Digest Run", denied, "execution_user", "Guest")
            frappe.db.commit()
            engine.process_execution(denied)
            assert frappe.db.get_value(run.doctype, denied, "status") == "Failed"
            assert client.send_text.call_count == attempts
            # A rolled-back business transaction must leave no durable execution.
            frappe.db.savepoint("synthetic_business_rollback")
            rolled_back = engine.queue_execution(rule.name, force=True, source_event="Manual")
            frappe.db.rollback(save_point="synthetic_business_rollback")
            assert not frappe.db.exists("WhatsApp Digest Run", rolled_back)
            # Simulate a worker crash after persisting a part's dispatch marker.
            crashed = engine.queue_execution(rule.name, force=True, source_event="Manual")
            runs.append(crashed)
            frappe.db.commit()
            crashed_run = engine.claim_execution(crashed)
            engine.prepare_execution(crashed_run, rule, None)
            first_part = frappe.db.get_value(
                "WhatsApp Delivery",
                {"run": crashed, "phone": "+12025550101", "part_index": 0},
                "name",
            )
            frappe.db.set_value(
                "WhatsApp Delivery", first_part, {"status": "Processing", "attempts": 1}
            )
            frappe.db.set_value(
                run.doctype,
                crashed,
                "claimed_at",
                now_datetime() - timedelta(minutes=engine.LEASE_MINUTES + 1),
            )
            frappe.db.commit()
            engine.poll_outbox()
            assert frappe.db.get_value("WhatsApp Delivery", first_part, "status") == "Uncertain"
            client.send_text.side_effect = send_text
            before_recovery = len(calls)
            engine.process_execution(crashed)
            recovered_calls = calls[before_recovery:]
            assert len(recovered_calls) == 2
            assert all(c["chat_id"] == "12025550102@c.us" for c in recovered_calls)
            assert frappe.db.get_value(run.doctype, crashed, "status") == "Uncertain"
            # An engine switch committed by another connection must be observed between parts.
            switching = engine.queue_execution(rule.name, force=True, source_event="Manual")
            runs.append(switching)
            frappe.db.commit()
            switched_calls = []

            def switch_to_legacy():
                frappe.db.set_single_value("WAHA Settings", "execution_engine", "Legacy")

            def pause_during_send(**kwargs):
                switched_calls.append(kwargs)
                with ThreadPoolExecutor(max_workers=1) as pool:
                    pool.submit(in_connection, switch_to_legacy).result()
                return {"id": "synthetic-accepted-before-pause"}

            client.send_text.side_effect = pause_during_send
            engine.process_execution(switching)
            assert (
                len(switched_calls) == 1
            ), "A switch in another connection must pause remaining parts"
            assert frappe.db.get_value(run.doctype, switching, "status") == "Skipped"
            return {
                "passed": True,
                "concurrent_duplicate_prevention": True,
                "partial_retry_content_reuse": True,
                "uncertain_no_auto_retry": True,
                "cutover_pauses_queued_jobs": True,
                "cross_connection_switch_pauses_remaining_parts": True,
                "denied_execution_user": True,
                "transaction_rollback": True,
                "crash_recovery_no_ambiguous_resend": True,
                "real_gateway_calls": 0,
            }
        finally:
            frappe.db.rollback()
            frappe.set_user("Administrator")
            for name in frappe.get_all(
                "WhatsApp Digest Run",
                filters={
                    "automation": [
                        "in",
                        [name for dt, name in fixtures if dt == "WhatsApp Automation"]
                        or ["nonexistent"],
                    ]
                },
                pluck="name",
            ):
                frappe.db.delete("WhatsApp Delivery", {"run": name})
                frappe.delete_doc("WhatsApp Digest Run", name, ignore_permissions=True, force=True)
            for doctype, name in reversed(fixtures):
                if frappe.db.exists(doctype, name):
                    frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
            frappe.db.set_single_value("WAHA Settings", "execution_engine", old_engine or "Legacy")
            frappe.db.commit()
