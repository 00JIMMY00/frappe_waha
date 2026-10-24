import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from frappe_waha.digest import engine
from frappe_waha.digest.periods import DigestPeriod
from frappe_waha.utils.openwa_client import OpenWAClient, OpenWAError
import requests


class TestEngine(unittest.TestCase):
    def test_execution_identity_deduplicates_events_and_separates_resends(self):
        period = DigestPeriod("2026-10-01", "2026-10-31", "October")
        args = ("rule", "Submit", "Sales Invoice:synthetic", None, period)
        self.assertEqual(engine.execution_identity(*args), engine.execution_identity(*args))
        self.assertNotEqual(
            engine.execution_identity(*args), engine.execution_identity(*args, resend="new")
        )
        self.assertNotEqual(
            engine.execution_identity(*args),
            engine.execution_identity("rule", "Submit", "Sales Invoice:other", None, period),
        )

    def test_unknown_outcomes_take_precedence(self):
        self.assertEqual(engine.aggregate_status(["Provider Accepted", "Uncertain"]), "Uncertain")
        self.assertEqual(engine.aggregate_status(["Provider Accepted", "Failed"]), "Failed")
        self.assertEqual(engine.aggregate_status(["Provider Accepted"]), "Provider Accepted")
        self.assertEqual(engine.aggregate_status([]), "Skipped")

    def test_invoice_selects_explicit_number_then_selected_contact_only(self):
        doc = {"whatsapp_number": "+12025550101", "contact_person": "selected"}
        with patch.object(engine.frappe, "get_doc") as get_doc:
            self.assertEqual(engine.invoice_recipient(doc, "+1"), "+12025550101")
            get_doc.assert_not_called()
        contact = Mock()
        contact.get.return_value = "+12025550102"
        with patch.object(engine.frappe, "get_doc", return_value=contact) as get_doc:
            self.assertEqual(
                engine.invoice_recipient({"contact_person": "selected"}, "+1"), "+12025550102"
            )
            get_doc.assert_called_once_with("Contact", "selected")
            contact.check_permission.assert_called_once_with("read")
        self.assertIsNone(engine.invoice_recipient({}, "+1"))

    def test_raw_transport_retries_only_safe_failures_and_redacts_response(self):
        client = OpenWAClient("https://gateway.invalid", "synthetic")
        cases = [
            (requests.ConnectTimeout("secret"), "retryable"),
            (requests.ReadTimeout("secret"), "uncertain"),
        ]
        for status, expected in [
            (429, "retryable"),
            (403, "failed"),
            (409, "uncertain"),
            (503, "uncertain"),
        ]:
            response = Mock(status_code=status, text="private provider detail")
            cases.append((requests.HTTPError(response=response), expected))
        for exception, expected in cases:
            with (
                self.subTest(expected=expected),
                patch("requests.request", side_effect=exception),
                patch("frappe_waha.utils.openwa_client._", side_effect=lambda text: text),
            ):
                with self.assertRaises(OpenWAError) as caught:
                    client.raw_request("POST", "/messages/send-text")
                self.assertEqual(caught.exception.outcome, expected)
                self.assertNotIn("secret", str(caught.exception))
                self.assertNotIn("private provider detail", str(caught.exception))

    def test_invoice_uses_document_print_pdf_and_private_attachment(self):
        from contextlib import nullcontext
        import frappe

        document = frappe._dict(
            doctype="Sales Invoice", name="synthetic-invoice", whatsapp_number="+12025550101"
        )
        document.check_permission = Mock()
        automation = frappe._dict(
            action="Document Delivery",
            language="ar",
            print_format="Synthetic format",
            letter_head="Synthetic letterhead",
            output_mode="PDF",
            whatsapp_phone="synthetic",
            message_caption="Invoice",
            title="Invoice",
        )
        sender = frappe._dict(session_name="synthetic", default_country_code="+1")
        run = Mock(
            doctype="WhatsApp Digest Run",
            name="synthetic-run",
            company="synthetic-company",
            worker_token="token",
        )
        run.pdf_filename.return_value = "invoice.pdf"
        delivery = Mock()
        with (
            patch.object(engine.frappe, "get_doc", side_effect=[sender, run]),
            patch.object(engine.frappe, "get_print", return_value=b"%PDF-synthetic") as print_pdf,
            patch.object(engine, "print_language", return_value=nullcontext()) as language,
            patch.object(
                engine,
                "save_file",
                return_value=frappe._dict(file_url="/private/files/synthetic.pdf"),
            ) as save_file,
            patch.object(engine.frappe, "new_doc", return_value=delivery),
        ):
            engine.prepare_execution(run, automation, document)
            print_pdf.assert_called_once_with(
                "Sales Invoice",
                "synthetic-invoice",
                print_format="Synthetic format",
                doc=document,
                as_pdf=True,
                letterhead="Synthetic letterhead",
            )
            language.assert_called_once_with("ar")
            self.assertEqual(save_file.call_args.kwargs["is_private"], 1)
            self.assertEqual(save_file.call_args.args[1], b"%PDF-synthetic")
            self.assertEqual(run.pdf_file, "/private/files/synthetic.pdf")
            self.assertEqual(delivery.update.call_args.args[0]["kind"], "PDF")
            document.check_permission.assert_called_once_with("print")

    def test_cancelled_invoice_is_skipped_before_render_or_transport(self):
        from contextlib import nullcontext
        import frappe

        run = Mock(automation="synthetic", execution_user="Administrator", worker_token="token")
        automation = frappe._dict(
            action="Document Delivery",
            enabled=1,
            engine_version="Unified",
            execution_user="Administrator",
            company="synthetic",
            whatsapp_phone="synthetic",
        )
        run.company = "synthetic"
        run.whatsapp_phone = "synthetic"
        run.schedule = None
        document = frappe._dict(doctype="Sales Invoice", docstatus=2, company="synthetic")
        with (
            patch.object(engine, "claim_execution", return_value=run),
            patch.object(engine.frappe, "get_doc", return_value=automation),
            patch.object(engine, "execution_user", return_value=nullcontext()),
            patch.object(engine, "source_document", return_value=document),
            patch.object(engine, "is_unified", return_value=True),
            patch.object(engine, "authorize"),
            patch.object(engine, "finish") as finish,
            patch.object(engine, "prepare_execution") as prepare,
        ):
            engine.process_execution("synthetic-run")
            self.assertEqual(finish.call_args.args[1], "Skipped")
            prepare.assert_not_called()

    def test_company_boundary_checked_for_event_eligibility(self):
        import frappe

        automation = frappe._dict(enabled=1, engine_version="Unified", company="A")
        with patch.object(engine, "is_unified", return_value=True):
            self.assertFalse(engine.eligible(automation, frappe._dict(company="B")))
            self.assertTrue(engine.eligible(automation, frappe._dict(company="A")))

    def test_permissions_reject_company_access_before_source_render(self):
        import frappe

        automation = Mock(company="restricted", whatsapp_phone="sender")
        company = Mock()
        company.check_permission.side_effect = frappe.PermissionError("Synthetic denied company")
        with (
            patch.object(engine.frappe, "get_doc", return_value=company),
            self.assertRaises(frappe.PermissionError),
        ):
            engine.authorize(automation)
        automation.check_permission.assert_called_once_with("read")

    def test_unified_report_cannot_override_company_filter(self):
        import frappe
        from frappe_waha.digest import automation as renderer

        rule = frappe._dict(engine_version="Unified", company="allowed", report_columns=[])
        block = frappe._dict(block_key="synthetic", report_name="Synthetic", row_limit=20)
        with (
            patch.object(renderer, "block_filters", return_value={"company": "other"}),
            patch.object(
                renderer,
                "run_query_report",
                side_effect=frappe.PermissionError("Synthetic denied report"),
            ) as report,
            self.assertRaises(frappe.PermissionError),
        ):
            renderer.build_report_block(
                rule, block, DigestPeriod("2026-01-01", "2026-01-31", "January")
            )
        self.assertEqual(report.call_args.kwargs["filters"]["company"], "allowed")
        self.assertFalse(report.call_args.kwargs["are_default_filters"])

    def test_previous_complete_period_and_positive_end_delay(self):
        import datetime
        import frappe
        from frappe_waha.digest import automation, periods

        schedule = frappe._dict(
            frequency="Monthly",
            send_time="09:00:00",
            weekly_day=None,
            send_after_month_end_days=4,
            last_sent_period_end=None,
        )
        with (
            patch.object(automation, "_", side_effect=lambda value: value),
            patch.object(periods, "_", side_effect=lambda value: value),
            patch.object(engine, "is_unified", return_value=True),
        ):
            period = periods.get_previous_complete_period(schedule, "2024-03-04")
            self.assertEqual(str(period.start_date), "2024-02-01")
            self.assertEqual(str(period.end_date), "2024-02-29")
            self.assertFalse(
                automation.is_schedule_due(schedule, datetime.datetime(2024, 3, 3, 10))
            )
            self.assertTrue(automation.is_schedule_due(schedule, datetime.datetime(2024, 3, 4, 10)))

    def test_invalid_explicit_invoice_number_is_skipped_without_contact_broadcast(self):
        import frappe

        with (
            patch.object(
                engine,
                "normalize_phone",
                side_effect=frappe.ValidationError("Synthetic invalid phone"),
            ),
            patch.object(engine.frappe, "get_doc") as contact,
        ):
            self.assertIsNone(
                engine.invoice_recipient(
                    {"whatsapp_number": "bad", "contact_person": "selected"}, "+1"
                )
            )
            contact.assert_not_called()

    def test_print_error_is_recorded_by_worker_without_sending(self):
        from contextlib import nullcontext
        import frappe

        run = Mock(
            automation="synthetic",
            execution_user="Administrator",
            worker_token="token",
            prepared=False,
        )
        current = Mock(worker_token="token")
        rule = frappe._dict(action="Document Delivery")
        document = frappe._dict(doctype="Sales Invoice", docstatus=1)
        with (
            patch.object(engine, "claim_execution", return_value=run),
            patch.object(engine.frappe, "get_doc", side_effect=[rule, current]),
            patch.object(engine, "execution_user", return_value=nullcontext()),
            patch.object(engine, "source_document", return_value=document),
            patch.object(engine, "run_eligible", return_value=True),
            patch.object(engine, "authorize"),
            patch("frappe_waha.digest.automation.conditions_match", return_value=True),
            patch.object(
                engine, "prepare_execution", side_effect=RuntimeError("Synthetic print error")
            ),
            patch.object(
                engine.frappe,
                "db",
                SimpleNamespace(rollback=Mock(), exists=Mock(return_value=False)),
            ),
            patch.object(engine, "finish") as finish,
            patch.object(engine.frappe, "log_error"),
            patch.object(engine, "send_delivery") as send,
        ):
            engine.process_execution("synthetic-run")
            self.assertEqual(finish.call_args.args[1], "Failed")
            send.assert_not_called()

    def test_queue_outage_after_commit_does_not_escape_into_invoice_submission(self):
        with (
            patch.object(engine.frappe, "db", SimpleNamespace(exists=Mock(return_value=True))),
            patch.object(
                engine.frappe, "enqueue", side_effect=ConnectionError("Synthetic queue outage")
            ),
            patch.object(engine.frappe, "log_error"),
        ):
            engine.wake_execution("synthetic-run")

    def test_phone_normalization_rejects_letters_instead_of_changing_recipient(self):
        import frappe
        from frappe_waha.utils import phone

        def reject(message):
            raise frappe.ValidationError(message)

        self.assertEqual(phone.normalize_phone("+1 (202) 555-0101", "+1"), "+12025550101")
        self.assertEqual(phone.normalize_phone("0012025550101", "+1"), "+12025550101")
        with (
            patch.object(phone, "_", side_effect=lambda text: text),
            patch.object(phone.frappe, "throw", side_effect=reject),
        ):
            for invalid in ("+1202555O101", "12025550101 ext 2", "++12025550101"):
                with self.subTest(invalid=invalid), self.assertRaises(frappe.ValidationError):
                    phone.normalize_phone(invalid, "+1")

    def test_transport_forwards_persisted_idempotency_key_for_text_and_pdf(self):
        client = OpenWAClient("https://gateway.invalid", "synthetic")
        with (
            patch.object(OpenWAClient, "resolve_session_id", return_value="synthetic-session"),
            patch.object(OpenWAClient, "request", return_value={}) as request,
        ):
            client.send_text(
                session="synthetic",
                chat_id="synthetic@c.us",
                text="synthetic",
                idempotency_key="stable-text",
            )
            self.assertEqual(request.call_args.kwargs["headers"]["Idempotency-Key"], "stable-text")
            client.send_pdf_file(
                session="synthetic",
                chat_id="synthetic@c.us",
                filename="synthetic.pdf",
                pdf_bytes=b"%PDF",
                idempotency_key="stable-pdf",
            )
            self.assertEqual(request.call_args.kwargs["headers"]["Idempotency-Key"], "stable-pdf")

    def test_failed_part_blocks_recipient_instead_of_showing_queued(self):
        self.assertEqual(
            engine.aggregate_status(["Provider Accepted", "Failed", "Queued"]), "Failed"
        )
        self.assertEqual(engine.aggregate_status(["Uncertain", "Failed", "Queued"]), "Uncertain")

    def test_expired_worker_cannot_claim_another_part(self):
        run = Mock(doctype="WhatsApp Digest Run", name="synthetic", worker_token="expired")
        replacement = Mock(worker_token="new-owner", status="Processing")
        with (
            patch.object(engine.frappe, "get_doc", return_value=replacement) as get_doc,
            patch.object(engine.frappe, "db", SimpleNamespace(commit=Mock())),
            patch.object(engine.OpenWAClient, "from_settings") as client,
        ):
            engine.send_delivery(run, Mock(), "synthetic-part")
            get_doc.assert_called_once_with(run.doctype, run.name, for_update=True)
            client.assert_not_called()

    def test_manual_send_validation_failure_never_reports_queued(self):
        from frappe_waha.frappe_waha.doctype.whatsapp_automation import whatsapp_automation

        rule = Mock(action="Summary")
        rule.validate_send_ready.side_effect = ValueError("Synthetic disabled rule")
        with (
            patch.object(whatsapp_automation, "enqueue_automation") as enqueue,
            self.assertRaises(ValueError),
        ):
            from inspect import unwrap

            unwrap(whatsapp_automation.WhatsAppAutomation.send_now)(rule)
        enqueue.assert_not_called()

    def test_disabled_schedule_cannot_queue_a_manual_run(self):
        from inspect import unwrap
        from frappe_waha.frappe_waha.doctype.whatsapp_schedule import whatsapp_schedule

        schedule = Mock(enabled=False)

        def reject(message):
            raise ValueError(message)

        with (
            patch.object(whatsapp_schedule, "_", side_effect=lambda text: text),
            patch.object(whatsapp_schedule.frappe, "throw", side_effect=reject),
            patch.object(whatsapp_schedule, "enqueue_automation") as enqueue,
            self.assertRaisesRegex(ValueError, "disabled"),
        ):
            unwrap(whatsapp_schedule.WhatsAppSchedule.run_now)(schedule)
        enqueue.assert_not_called()

    def test_enabled_unified_rule_rejects_legacy_site_mode(self):
        from frappe_waha.frappe_waha.doctype.whatsapp_automation import whatsapp_automation

        rule = Mock(
            engine_version="Unified",
            action="Document Delivery",
            enabled=True,
            trigger_event="Submit",
            trigger_doctype="Sales Invoice",
            execution_user="Administrator",
            company="synthetic",
            whatsapp_phone="synthetic",
        )
        rule.is_new.return_value = False
        rule.has_value_changed.return_value = False

        def reject(message):
            raise ValueError(message)

        with (
            patch.object(engine, "is_unified", return_value=False),
            patch.object(whatsapp_automation, "_", side_effect=lambda text: text),
            patch.object(whatsapp_automation.frappe, "throw", side_effect=reject),
            self.assertRaisesRegex(ValueError, "Execution Engine to Unified"),
        ):
            whatsapp_automation.WhatsAppAutomation.validate(rule)
