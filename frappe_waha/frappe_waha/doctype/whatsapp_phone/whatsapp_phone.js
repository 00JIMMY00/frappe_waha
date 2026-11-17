frappe.ui.form.on("WhatsApp Phone", {
  refresh(frm) {
    if (frm.is_new()) return;

    frm.add_custom_button(__("Sync Status"), () => {
      frm.call("sync_status").then(() => frm.reload_doc());
    });

    if (frm.doc.session_name) {
      frm.add_custom_button(__("Show QR"), () => frm.trigger("show_qr_dialog")).addClass("btn-primary");
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

    let closed = false;
    let timer;
    dialog.onhide = () => {
      closed = true;
      clearTimeout(timer);
    };

    const show_error = (error) => {
      if (closed) return;
      const response = error && error.responseJSON;
      let message = error && error.message;
      try {
        const messages = JSON.parse((response && response._server_messages) || "[]");
        if (messages.length) message = JSON.parse(messages[0]).message;
      } catch (ignored) {
        // Fall back to a safe message when the server response is not JSON.
      }
      wrapper.html(
        '<div class="text-danger text-center py-4">' +
        frappe.utils.escape_html(message || __("Could not load QR code. Try Show QR again.")) +
        '</div>'
      );
    };

    const load_qr = () => {
      if (closed) return;
      frm.call("get_qr").then((response) => {
        if (closed) return;
        const result = response.message || {};
        if (result.connected) {
          wrapper.html('<div class="text-center text-success py-4">' + __("Connected") + '</div>');
          frm.reload_doc();
          return;
        }
        if (result.image) {
          wrapper.empty();
          const container = $('<div class="text-center"></div>').appendTo(wrapper);
          $("<img>").attr("src", result.image).css({width: "280px", maxWidth: "100%"}).appendTo(container);
          $('<div class="text-muted small mt-3"></div>')
            .text(__("Open WhatsApp on your phone and scan this QR code.")).appendTo(container);
        } else if (!result.pending) {
          throw new Error(__("No QR image returned from OpenWA."));
        }
        timer = setTimeout(load_qr, 4000);
      }).catch(show_error);
    };

    frm.call("create_or_start_session").then(() => load_qr()).catch(show_error);
  },
});
