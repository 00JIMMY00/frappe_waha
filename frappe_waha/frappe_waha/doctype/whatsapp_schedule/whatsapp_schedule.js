frappe.ui.form.on("WhatsApp Schedule", {
  refresh(frm) {
    if (frm.is_new()) return;
    frm.add_custom_button(__("Run Now"), () => {
      frappe.confirm(__("Queue this scheduled automation now?"), () => {
        frm.call("run_now").then(() => {
          frappe.show_alert({ message: __("Schedule queued"), indicator: "green" });
        });
      });
    }).addClass("btn-primary");
  },
});
