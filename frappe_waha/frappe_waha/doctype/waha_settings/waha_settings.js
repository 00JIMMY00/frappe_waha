frappe.ui.form.on("WAHA Settings", {
  refresh(frm) {
    frm.add_custom_button(__("Test Connection"), () => {
      frm.call("test_connection").then((response) => {
        const message = response.message || {};
        frappe.msgprint({
          title: __("OpenWA Connection"),
          indicator: "green",
          message: __("Connected. Sessions found: {0}", [message.sessions || 0]),
        });
      });
    });
  },
});
