import frappe
from frappe import _
from frappe.model.document import Document

from frappe_waha.digest.automation import enqueue_automation, send_whatsapp_automation
from frappe_waha.utils.phone import normalize_phone


class WhatsAppAutomation(Document):
    def validate(self):
        self.trigger_event = self.trigger_event or "Manual"
        self.condition_mode = self.condition_mode or "All"
        self.output_mode = self.output_mode or "PDF"
        if self.trigger_event != "Manual" and not self.trigger_doctype:
            frappe.throw(_("Trigger DocType is required for event automations."))
        if not self.recipients:
            frappe.throw(_("Add at least one recipient."))
        if not self.blocks:
            frappe.throw(_("Add at least one data block."))
        if any(row.enabled and row.condition_type == "SQL" for row in self.conditions) and "System Manager" not in frappe.get_roles():
            frappe.throw(_("Only System Manager can save SQL conditions."))
        if self.text_formatter_script and "System Manager" not in frappe.get_roles():
            frappe.throw(_("Only System Manager can save Text Formatter Script."))
        default_country_code = frappe.db.get_value("WhatsApp Phone", self.whatsapp_phone, "default_country_code")
        for row in self.recipients:
            row.phone = normalize_phone(row.phone, default_country_code)
        self.validate_blocks()

    def validate_blocks(self):
        keys = set()
        for block in self.blocks:
            if not block.block_key:
                block.block_key = frappe.scrub(block.title or block.source or f"block_{block.idx}")
            if block.block_key in keys:
                frappe.throw(_("Block Key must be unique: {0}").format(block.block_key))
            keys.add(block.block_key)
            if block.source == "Built-in Preset" and not block.builtin_metric:
                frappe.throw(_("Built-in Preset blocks need a Built-in Preset."))
            if block.source == "Query Report" and not block.report_name:
                frappe.throw(_("Query Report blocks need a Report."))
            if block.source == "DocType Table" and not block.reference_doctype:
                frappe.throw(_("DocType Table blocks need a Reference DocType."))
            if block.source == "Custom SQL Table" and not block.custom_sql:
                frappe.throw(_("Custom SQL Table blocks need Custom SQL."))
            if block.source == "Custom SQL Table" and "System Manager" not in frappe.get_roles():
                frappe.throw(_("Only System Manager can save Custom SQL Table blocks."))
            if block.source == "Script" and not block.script:
                frappe.throw(_("Script blocks need a Script."))
            if block.source == "Script" and "System Manager" not in frappe.get_roles():
                frappe.throw(_("Only System Manager can save Script blocks."))

    def validate_send_ready(self):
        if not self.enabled:
            frappe.throw(_("WhatsApp Automation is disabled."))
        phone_status = frappe.db.get_value(
            "WhatsApp Phone",
            self.whatsapp_phone,
            ["status", "session_status", "session_name", "default_country_code"],
            as_dict=True,
        )
        if not phone_status or phone_status.status != "Active" or phone_status.session_status not in (
            "ready",
            "connected",
            "CONNECTED",
            "WORKING",
        ):
            frappe.throw(_("WhatsApp Phone must be Active and connected before sending."))
        if not phone_status.session_name:
            frappe.throw(_("WhatsApp Phone has no OpenWA session ID."))

    @frappe.whitelist()
    def send_now(self):
        self.check_permission("write")
        job = enqueue_automation(self.name, force=True, source_event="Manual")
        return {"queued": True, "job": getattr(job, "id", None)}

    @frappe.whitelist()
    def load_report_metadata(self, block_key):
        self.check_permission("write")
        block = next((row for row in self.blocks if row.block_key == block_key), None)
        if not block or block.source != "Query Report" or not block.report_name:
            frappe.throw(_("Select a Query Report block first."))
        from frappe.desk.query_report import get_script
        from frappe.desk.query_report import run as run_report

        existing_filters = {(row.block_key, row.fieldname) for row in self.report_filters}
        existing_columns = {(row.block_key, row.fieldname) for row in self.report_columns}

        try:
            report_doc = frappe.get_doc("Report", block.report_name)
            script = get_script(block.report_name)
            filters = script.get("filters") if isinstance(script, dict) else []
        except Exception:
            filters = []

        for field in filters or []:
            fieldname = field.get("fieldname")
            if fieldname and (block_key, fieldname) not in existing_filters:
                self.append("report_filters", {
                    "block_key": block_key,
                    "fieldname": fieldname,
                    "label": field.get("label") or frappe.unscrub(fieldname),
                })

        report_filters = {
            row.fieldname: frappe.render_template(
                row.value or "",
                {
                    "company": self.company,
                    "start_date": frappe.utils.today(),
                    "end_date": frappe.utils.today(),
                    "doc": None,
                },
            )
            for row in self.report_filters
            if row.block_key == block_key and row.fieldname and row.value
        }

        try:
            result = run_report(block.report_name, filters=report_filters, ignore_prepared_report=True)
            columns = result.get("columns") or []
        except Exception:
            columns = []

        for column in columns:
            if isinstance(column, dict):
                fieldname = column.get("fieldname") or frappe.scrub(column.get("label") or "")
                label = column.get("label") or frappe.unscrub(fieldname)
            else:
                label = str(column).split(":")[0]
                fieldname = frappe.scrub(label)
            if fieldname and (block_key, fieldname) not in existing_columns:
                self.append("report_columns", {
                    "include": 1,
                    "block_key": block_key,
                    "fieldname": fieldname,
                    "label": label,
                })
        self.save()
        return True

    @frappe.whitelist()
    def send_direct(self, doctype=None, name=None, force=False):
        self.check_permission("write")
        return send_whatsapp_automation(self.name, doctype=doctype, name=name, force=force)
