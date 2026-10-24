frappe.ui.form.on("WhatsApp Digest Run", {
  refresh(frm) {
    if (frm.doc.engine_version === "Unified") {
      frm.add_custom_button(__("Delivery Parts"), () => {
        frappe.set_route("List", "WhatsApp Delivery", { run: frm.doc.name });
      });
    }
    if (frm.doc.status === "Failed" || frm.doc.status === "Partially Sent" || (frm.doc.engine_version === "Unified" && frm.doc.status === "Skipped")) {
      frm.add_custom_button(__("Retry Failed"), () => {
        frappe.confirm(__("Retry failed recipients for this digest run?"), () => {
          frm.call("retry_failed").then(() => frm.reload_doc());
        });
      });
    }
  },
});

