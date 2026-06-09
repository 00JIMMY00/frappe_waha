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
    seed_openwa_settings()
    seed_default_template()
    seed_default_metrics()
    seed_business_day_pdf_automation()


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


def seed_business_day_pdf_automation():
    if not frappe.db.table_exists("WhatsApp Automation") or not frappe.db.exists("Branch", "we1"):
        return

    sender = "01503194714"
    if not frappe.db.exists("WhatsApp Phone", sender):
        sender = frappe.db.get_value("WhatsApp Phone", {"phone": "+201503194714"}, "name")
    if not sender:
        return

    title = "تقرير نهاية يوم العمل - we1"
    automation = get_or_create_doc("WhatsApp Automation", {"title": title})
    automation.update(
        {
            "title": title,
            "enabled": 1,
            "trigger_event": "Manual",
            "condition_mode": "All",
            "company": "we" if frappe.db.exists("Company", "we") else None,
            "whatsapp_phone": sender,
            "output_mode": "PDF",
            "message_caption": "تقرير نهاية يوم العمل",
        }
    )
    automation.set("conditions", [])
    automation.append(
        "conditions",
        {
            "enabled": 1,
            "condition_type": "SQL",
            "operator": "Equals",
            "value": "1",
            "sql_condition": BUSINESS_DAY_SQL_CONDITION,
        },
    )
    automation.set("recipients", [{"label": "الإدارة", "phone": "+201097072200"}])
    automation.set(
        "blocks",
        [
            {
                "enabled": 1,
                "block_key": "business_day_sessions",
                "source": "Script",
                "title_ar": "جلسات يوم العمل",
                "row_limit": 200,
                "script": BUSINESS_DAY_SCRIPT,
            }
        ],
    )
    if automation.is_new():
        automation.insert(ignore_permissions=True)
    else:
        automation.save(ignore_permissions=True)

    schedule_title = "تشغيل تقرير نهاية يوم العمل - we1"
    schedule = get_or_create_doc("WhatsApp Schedule", {"title": schedule_title})
    schedule.update(
        {
            "title": schedule_title,
            "enabled": 1,
            "automation": automation.name,
            "frequency": "Daily",
            "compare_vs": "No Comparison",
        }
    )
    if schedule.is_new():
        schedule.insert(ignore_permissions=True)
    else:
        schedule.save(ignore_permissions=True)


def get_or_create_doc(doctype, filters):
    name = frappe.db.exists(doctype, filters)
    return frappe.get_doc(doctype, name) if name else frappe.new_doc(doctype)


BUSINESS_DAY_SQL_CONDITION = """
select case
    when exists (
        select 1
        from `tabPOSA Branch Working Hour` wh
        where wh.parent = 'we1'
          and wh.weekday = dayname(curdate())
          and ifnull(wh.is_closed, 0) = 0
          and time(now()) >= wh.closing_time
    )
    and not exists (
        select 1
        from `tabPOS Opening Shift` os
        inner join `tabPOS Profile` pp on pp.name = os.pos_profile
        where os.docstatus = 1
          and os.posa_business_date = %(start_date)s
          and pp.posa_branch = 'we1'
          and ifnull(os.pos_closing_shift, '') = ''
    )
    and exists (
        select 1
        from `tabPOS Closing Shift` cs
        inner join `tabPOS Profile` pp on pp.name = cs.pos_profile
        where cs.docstatus = 1
          and cs.posa_business_date = %(start_date)s
          and pp.posa_branch = 'we1'
    )
    then 1 else 0 end as ready
""".strip()


BUSINESS_DAY_SCRIPT = r"""
branch = "we1"
payment_labels = {
    "Cash": "نقدي",
    "Credit Card": "بطاقة بنكية",
    "Bank Draft": "تحويل بنكي",
    "Wire Transfer": "تحويل بنكي",
    "Cheque": "شيك",
}

def money(value):
    if value is None:
        value = 0
    return "%.2f ج.م" % float(value)

def user_first_name(user_id):
    if not user_id:
        return "-"
    user_doc = frappe.get_doc("User", user_id)
    return user_doc.get("first_name") or user_doc.get("full_name") or user_id

rows = []
total_pulled = 0
total_difference = 0
closing_count = 0
business_date = period.start_date

closings = frappe.get_all(
    "POS Closing Shift",
    filters={"docstatus": 1, "posa_business_date": business_date},
    fields=["name", "pos_opening_shift", "pos_profile", "user", "posa_business_date"],
    order_by="name asc",
)

for closing in closings:
    pos_profile = frappe.get_doc("POS Profile", closing.get("pos_profile"))
    if pos_profile.get("posa_branch") != branch:
        continue

    closing_count = closing_count + 1
    closing_doc = frappe.get_doc("POS Closing Shift", closing.get("name"))
    cashier = user_first_name(closing_doc.get("user"))
    payment_rows = closing_doc.get("payment_reconciliation") or []

    if not payment_rows:
        rows.append({
            "closing_shift": closing_doc.name,
            "cashier": cashier,
            "mode_of_payment": "-",
            "pulled_amount": money(0),
            "difference": money(0),
        })
        continue

    for payment in payment_rows:
        pulled = payment.get("pulled_amount") or 0
        difference = payment.get("difference") or 0
        mode = payment.get("mode_of_payment") or "-"
        total_pulled = total_pulled + pulled
        total_difference = total_difference + difference
        rows.append({
            "closing_shift": closing_doc.name,
            "cashier": cashier,
            "mode_of_payment": payment_labels.get(mode, mode),
            "pulled_amount": money(pulled),
            "difference": money(difference),
        })

rows.append({
    "closing_shift": "الإجمالي",
    "cashier": str(closing_count) + " جلسة",
    "mode_of_payment": "-",
    "pulled_amount": money(total_pulled),
    "difference": money(total_difference),
})

result = {
    "title": "تقرير نهاية يوم العمل",
    "columns": [
        {"fieldname": "closing_shift", "label": "جلسة الإغلاق"},
        {"fieldname": "cashier", "label": "الكاشير"},
        {"fieldname": "mode_of_payment", "label": "طريقة الدفع"},
        {"fieldname": "pulled_amount", "label": "المبلغ المسحوب"},
        {"fieldname": "difference", "label": "الفرق"},
    ],
    "rows": rows,
}
"""
