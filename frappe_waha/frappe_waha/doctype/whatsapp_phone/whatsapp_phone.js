frappe.ui.form.on("WhatsApp Phone", {
  refresh(frm) {
    if (frm.is_new()) return;

    frm.add_custom_button(__("Start / QR"), () => {
      frm.call("create_or_start_session").then(() => {
        frm.reload_doc();
        frm.trigger("show_qr_dialog");
      });
    }).addClass("btn-primary");

    frm.add_custom_button(__("Sync Status"), () => {
      frm.call("sync_status").then(() => frm.reload_doc());
    });

    if (frm.doc.session_name) {
      frm.add_custom_button(__("Show QR"), () => frm.trigger("show_qr_dialog"));
      frm.add_custom_button(__("Stop"), () => {
        frm.call("stop_session").then(() => frm.reload_doc());
      });
      frm.add_custom_button(__("Logout"), () => {
        frappe.confirm(__("Logout and expire this WhatsApp session?"), () => {
          frm.call("logout_session").then(() => frm.reload_doc());
        });
      });
    }
  },

  show_qr_dialog(frm) {
    const dialog = new frappe.ui.Dialog({
      title: __("Scan WhatsApp QR"),
      size: "small",
      fields: [{ fieldname: "qr", fieldtype: "HTML" }],
    });
    const wrapper = dialog.get_field("qr").$wrapper;
    wrapper.html(`<div class="text-muted text-center py-5">${__("Loading QR...")}</div>`);
    dialog.show();

    const render_status = () => {
      frm.call("sync_status").then((response) => {
        const doc = response.message || {};
        if (doc.session_status === "WORKING") {
          wrapper.html(`<div class="text-center text-success py-4">${__("Connected")}</div>`);
          frm.reload_doc();
          return;
        }
        setTimeout(render_status, 4000);
      });
    };

    frm.call("get_qr").then((response) => {
      const image = response.message && response.message.image;
      wrapper.html(`
        <div class="text-center">
          <img src="${image}" style="width: 280px; max-width: 100%;" />
          <div class="text-muted small mt-3">${__("Open WhatsApp on your phone and scan this QR code.")}</div>
        </div>
      `);
      render_status();
    });
  },
});

