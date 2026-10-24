import frappe

from frappe_waha.digest.metrics import DEFAULT_METRICS
from frappe_waha.requirements import validate_requirements


DEFAULT_TEMPLATE_HTML = """
<div class="digest">
  <header class="digest-header">
    <div>
      <p class="eyebrow">{{ company }}</p>
      <h1>{{ title }}</h1>
    </div>
    <div class="period">{{ period_label }}</div>
  </header>

  {% if comparison_label %}
  <p class="comparison">Compared with {{ comparison_label }}</p>
  {% endif %}

  {% for metric in metrics %}
    <section class="metric metric-{{ metric.kind }}">
      <h2>{{ metric.title }}</h2>
      {% if metric.description %}<p class="description">{{ metric.description }}</p>{% endif %}

      {% if metric.kind == "card" %}
        <div class="card-value">{{ metric.value }}</div>
        {% if metric.delta_label %}<div class="delta">{{ metric.delta_label }}</div>{% endif %}
      {% elif metric.kind == "table" %}
        <table>
          <thead>
            <tr>
              {% for column in metric.columns %}
                <th>{{ column.label }}</th>
              {% endfor %}
            </tr>
          </thead>
          <tbody>
            {% for row in metric.rows %}
              <tr>
                {% for column in metric.columns %}
                  <td>{{ row.get(column.fieldname) }}</td>
                {% endfor %}
              </tr>
            {% endfor %}
          </tbody>
        </table>
      {% elif metric.kind == "chart" %}
        <table>
          <thead>
            <tr><th>Label</th><th>Value</th></tr>
          </thead>
          <tbody>
            {% for point in metric.points %}
              <tr><td>{{ point.label }}</td><td>{{ point.value }}</td></tr>
            {% endfor %}
          </tbody>
        </table>
      {% else %}
        {{ (metric.html or "") | safe }}
      {% endif %}
    </section>
  {% endfor %}
</div>
""".strip()

DEFAULT_TEMPLATE_CSS = """
body { font-family: Arial, sans-serif; color: #17202a; font-size: 12px; }
.digest-header { display: flex; justify-content: space-between; border-bottom: 2px solid #128c7e; padding-bottom: 14px; margin-bottom: 16px; }
.eyebrow { margin: 0 0 4px; color: #128c7e; text-transform: uppercase; font-size: 10px; letter-spacing: .08em; }
h1 { margin: 0; font-size: 26px; }
.period { font-size: 13px; color: #566573; }
.comparison { color: #566573; margin-bottom: 18px; }
.metric { page-break-inside: avoid; margin: 0 0 18px; }
.metric h2 { font-size: 16px; margin: 0 0 4px; }
.description { color: #566573; margin: 0 0 8px; }
.card-value { font-size: 24px; font-weight: 700; color: #128c7e; }
.delta { color: #566573; }
table { width: 100%; border-collapse: collapse; margin-top: 8px; }
th, td { border: 1px solid #d6dbdf; padding: 7px; text-align: left; }
th { background: #f4f6f7; font-weight: 700; }
""".strip()


def after_install():
    validate_requirements()
    seed_openwa_settings()
    seed_default_template()
    seed_default_metrics()
    seed_invoice_preset()


def seed_openwa_settings():
    if not frappe.db.get_single_value("WAHA Settings", "media_delivery_mode"):
        frappe.db.set_single_value("WAHA Settings", "media_delivery_mode", "PDF Attachment")


def seed_default_template():
    if frappe.db.exists("WhatsApp Digest Template", "Default WhatsApp Digest"):
        return

    doc = frappe.new_doc("WhatsApp Digest Template")
    doc.title = "Default WhatsApp Digest"
    doc.enabled = 1
    doc.is_default = 1
    doc.html = DEFAULT_TEMPLATE_HTML
    doc.css = DEFAULT_TEMPLATE_CSS
    doc.page_size = "A4"
    doc.orientation = "Portrait"
    doc.insert(ignore_permissions=True)


def seed_default_metrics():
    for metric in DEFAULT_METRICS:
        if metric["category"] == "POS" and not frappe.db.exists("DocType", "POS Closing Shift"):
            continue
        existing = frappe.db.exists("WhatsApp Digest Metric", {"code": metric["code"]})
        if existing:
            # Catalog entries are user configuration, not fixtures to overwrite on migrate.
            continue

        doc = frappe.new_doc("WhatsApp Digest Metric")
        doc.update(metric)
        doc.source = "Built-in Provider"
        doc.enabled = 1
        doc.insert(ignore_permissions=True)


def seed_invoice_preset():
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

    if not frappe.get_meta("Sales Invoice").has_field("whatsapp_number"):
        create_custom_fields(
            {
                "Sales Invoice": [
                    {
                        "fieldname": "whatsapp_number",
                        "label": "WhatsApp Number",
                        "fieldtype": "Phone",
                        "insert_after": "contact_mobile",
                        "no_copy": 1,
                        "description": "Optional explicit recipient for this invoice. Otherwise use the selected contact mobile number.",
                    }
                ]
            }
        )
    title = "Invoice to Customer"
    if frappe.db.exists("WhatsApp Automation", {"title": title}):
        return
    automation = frappe.new_doc("WhatsApp Automation")
    automation.update(
        {
            "title": title,
            "enabled": 0,
            "engine_version": "Unified",
            "action": "Document Delivery",
            "trigger_doctype": "Sales Invoice",
            "trigger_event": "Submit",
            "output_mode": "PDF",
        }
    )
    automation.insert(ignore_permissions=True)
