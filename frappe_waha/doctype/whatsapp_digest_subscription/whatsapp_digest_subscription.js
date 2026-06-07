frappe.ui.form.on("WhatsApp Digest Subscription", {
  setup(frm) {
    frm._compare_defaults = {
      Daily: "previous_day",
      Weekly: "previous_week",
      Monthly: "previous_month",
      Quarterly: "previous_quarter",
      Yearly: "previous_year",
    };
    frm._compare_options = {
      Daily: ["previous_day", "same_day_last_week", "same_day_last_month", "same_day_last_year"],
      Weekly: ["previous_week", "same_week_last_month", "same_week_last_quarter", "same_week_last_year"],
      Monthly: ["previous_month", "same_month_last_quarter", "same_month_last_year"],
      Quarterly: ["previous_quarter", "same_quarter_last_year"],
      Yearly: ["previous_year"],
    };
  },

  refresh(frm) {
    frm.trigger("setup_actions");
    frm.trigger("setup_compare_options");
    frm.trigger("setup_metrics_selector");
  },

  frequency(frm) {
    frm.set_value("compare_vs", frm._compare_defaults[frm.doc.frequency]);
    frm.trigger("setup_compare_options");
  },

  whatsapp_phone(frm) {
    if (!frm.doc.whatsapp_phone) return;
    frappe.db.get_value("WhatsApp Phone", frm.doc.whatsapp_phone, "default_country_code").then((response) => {
      frm.set_value("default_country_code", response.message.default_country_code);
    });
  },

  setup_actions(frm) {
    if (frm.is_new()) return;

    frm.add_custom_button(__("Preview"), () => frm.trigger("preview_digest")).addClass("btn-primary");
    frm.add_custom_button(__("Send Now"), () => {
      frappe.confirm(__("Queue this digest for WhatsApp delivery now?"), () => {
        frm.call("send_now").then(() => {
          frappe.show_alert({ message: __("Digest queued"), indicator: "green" });
        });
      });
    });
  },

  setup_compare_options(frm) {
    const options = frm._compare_options[frm.doc.frequency] || [];
    frm.set_df_property("compare_vs", "options", options.join("\n"));
    if (options.length && !options.includes(frm.doc.compare_vs)) {
      frm.set_value("compare_vs", options[0]);
    }
  },

  setup_metrics_selector(frm) {
    const render = (catalog) => {
      const selected = new Set(parse_metrics(frm.doc.subscribed_metrics));
      const wrapper = frm.get_field("metrics_selector_html").$wrapper.empty();
      const root = $(`<div class="whatsapp-digest-metrics"></div>`).appendTo(wrapper);

      Object.keys(catalog || {}).forEach((category) => {
        const group = $(`<div class="metric-group"></div>`).appendTo(root);
        $(`<h4>${frappe.utils.escape_html(category)}</h4>`).appendTo(group);
        (catalog[category] || []).forEach((metric) => {
          const id = `metric-${Math.random().toString(36).slice(2, 10)}`;
          const checked = selected.has(metric.code) ? "checked" : "";
          const row = $(`
            <label class="metric-option" for="${id}">
              <input id="${id}" type="checkbox" data-code="${frappe.utils.escape_html(metric.code)}" ${checked}>
              <span>
                <strong>${frappe.utils.escape_html(metric.title)}</strong>
                <small>${frappe.utils.escape_html(metric.description || "")}</small>
              </span>
            </label>
          `).appendTo(group);
          row.find("input").on("change", () => {
            const codes = [];
            root.find("input:checked").each((_, input) => codes.push(input.dataset.code));
            frm.set_value("subscribed_metrics", JSON.stringify(codes));
          });
        });
      });
    };

    if (frm._metric_catalog) {
      render(frm._metric_catalog);
      return;
    }

    frm.call("get_available_metrics").then((response) => {
      frm._metric_catalog = response.message || {};
      render(frm._metric_catalog);
    });
  },

  preview_digest(frm) {
    const dialog = new frappe.ui.Dialog({
      title: __("Digest Preview"),
      size: "extra-large",
      fields: [{ fieldname: "preview", fieldtype: "HTML" }],
    });
    dialog.get_field("preview").$wrapper.html(`<div class="text-muted text-center py-5">${__("Loading preview...")}</div>`);
    dialog.show();

    frm.call("preview_digest").then((response) => {
      const payload = response.message || {};
      const frame = $(`<iframe class="digest-preview-frame" title="${__("Digest Preview")}"></iframe>`);
      dialog.get_field("preview").$wrapper.empty().append(frame);
      const doc = frame[0].contentDocument;
      doc.open();
      doc.write(payload.html || "");
      doc.close();
    });
  },
});

function parse_metrics(value) {
  try {
    const parsed = JSON.parse(value || "[]");
    return Array.isArray(parsed) ? parsed : [];
  } catch (e) {
    return [];
  }
}
