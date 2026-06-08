import frappe

from frappe_waha.digest.metrics import DEFAULT_METRICS


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
    seed_waha_settings()
    seed_default_template()
    seed_default_metrics()


def seed_waha_settings():
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
        existing = frappe.db.exists("WhatsApp Digest Metric", {"code": metric["code"]})
        if existing:
            doc = frappe.get_doc("WhatsApp Digest Metric", existing)
            changed = False
            for field in (
                "category",
                "title",
                "title_ar",
                "description",
                "description_ar",
                "kind",
                "provider_path",
                "column_labels_json",
                "display_order",
            ):
                if doc.get(field) != metric.get(field):
                    doc.set(field, metric.get(field))
                    changed = True
            if doc.source != "Built-in Provider":
                doc.source = "Built-in Provider"
                changed = True
            if changed:
                doc.save(ignore_permissions=True)
            continue

        doc = frappe.new_doc("WhatsApp Digest Metric")
        doc.update(metric)
        doc.source = "Built-in Provider"
        doc.enabled = 1
        doc.insert(ignore_permissions=True)
