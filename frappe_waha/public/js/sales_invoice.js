frappe.ui.form.on("Sales Invoice", {
  refresh(frm) {
    if (frm.is_new()) return;
    frm.add_custom_button(__("WhatsApp History"), () => {
      frappe.set_route("List", "WhatsApp Digest Run", {
        trigger_doctype: "Sales Invoice", trigger_document: frm.doc.name
      });
    }, __("WhatsApp"));
    if (frm.doc.docstatus !== 1) return;
    const queue = (resend) => {
      frappe.prompt([{
        fieldname: "automation", fieldtype: "Link", options: "WhatsApp Automation",
        label: __("Invoice Delivery Automation"), reqd: 1,
        get_query: () => ({ filters: { enabled: 1, engine_version: "Unified", action: "Document Delivery", company: frm.doc.company } })
      }], (values) => {
        frappe.call({
          method: "frappe_waha.digest.invoice.queue_invoice",
          args: { invoice_name: frm.doc.name, automation_name: values.automation, resend: resend ? 1 : 0 }
        }).then((r) => frappe.set_route("Form", "WhatsApp Digest Run", r.message.run));
      }, resend ? __("Create Separate WhatsApp Resend") : __("Queue Invoice PDF"));
    };
    frm.add_custom_button(__("Queue Invoice PDF"), () => queue(false), __("WhatsApp"));
    frm.add_custom_button(__("Resend Invoice PDF"), () => {
      frappe.confirm(__("Create a separate delivery? This may send the invoice again, including when an earlier result is uncertain."), () => queue(true));
    }, __("WhatsApp"));
  }
});
