frappe.ui.form.on("WhatsApp Digest Run", {
  refresh(frm) {
    if (frm.doc.status === "Failed" || frm.doc.status === "Partially Sent") {
      frm.add_custom_button(__("Retry Failed"), () => {
        frappe.confirm(__("Retry failed recipients for this digest run?"), () => {
          frm.call("retry_failed").then(() => frm.reload_doc());
        });
      });
    }
  },
});

