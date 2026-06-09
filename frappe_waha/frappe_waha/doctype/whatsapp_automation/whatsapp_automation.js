frappe.ui.form.on("WhatsApp Automation", {
  refresh(frm) {
    if (frm.is_new()) return;

    frm.add_custom_button(__("Send Now"), () => {
      frappe.confirm(__("Queue this automation for WhatsApp delivery now?"), () => {
        frm.call("send_now").then(() => {
          frappe.show_alert({ message: __("Automation queued"), indicator: "green" });
        });
      });
    }).addClass("btn-primary");

    frm.add_custom_button(__("Load Report Metadata"), () => frm.trigger("load_report_metadata"));
  },

  load_report_metadata(frm) {
    const blocks = (frm.doc.blocks || []).filter((row) => row.source === "Query Report" && row.report_name);
    if (!blocks.length) {
      frappe.msgprint(__("Add a Query Report block first."));
      return;
    }

    const dialog = new frappe.ui.Dialog({
      title: __("Load Report Metadata"),
      fields: [
        {
          fieldname: "block_key",
          fieldtype: "Select",
          label: __("Block"),
          options: blocks.map((row) => row.block_key).join("\n"),
          reqd: 1,
        },
      ],
      primary_action_label: __("Load"),
      primary_action(values) {
        dialog.hide();
        frm.call("load_report_metadata", { block_key: values.block_key }).then(() => {
          frappe.show_alert({ message: __("Report fields loaded"), indicator: "green" });
          frm.reload_doc();
        });
      },
    });
    dialog.show();
  },
});
