import frappe
from frappe import _
from frappe.model.document import Document

from frappe_waha.digest.metrics import import_provider, parse_json_field


class WhatsAppDigestMetric(Document):
    def validate(self):
        self.code = frappe.scrub(self.code)
        self.source = self.source or "Built-in Provider"
        if self.source == "Built-in Provider":
            if not self.provider_path or "." not in self.provider_path:
                frappe.throw(_("Built-in metrics must have an internal provider."))
            import_provider(self.provider_path)
            return

        if self.source == "DocType Table":
            if not self.reference_doctype:
                frappe.throw(_("DocType Table metrics need a Reference DocType."))
            if not self.selected_fields:
                frappe.throw(_("DocType Table metrics need Selected Fields."))
            parse_json_field(self.selected_fields, "Selected Fields", expected_type=list)
            parse_json_field(self.filters_json, "Filters JSON", expected_type=dict, allow_empty=True)

        if self.source == "Query Report":
            if not self.report_name:
                frappe.throw(_("Query Report metrics need a Report."))
            parse_json_field(self.report_filters_json, "Report Filters JSON", expected_type=dict, allow_empty=True)

        parse_json_field(self.column_labels_json, "Arabic Column Labels", expected_type=dict, allow_empty=True)

        if self.source == "Custom HTML" and not self.custom_html:
            frappe.throw(_("Custom HTML metrics need Custom HTML."))

        if self.source == "Custom SQL Table" and not self.custom_sql:
            frappe.throw(_("Custom SQL Table metrics need Custom SQL."))
