# Frappe WhatsApp / OpenWA

WhatsApp automation for **Frappe and ERPNext v15**, using the session/text/document API of `rmyndharis/OpenWA`. The installed package remains `frappe_waha`; `WAHA Settings` is a retained technical DocType name. This client does not target the WAHA gateway API.

Each business installs the app on its own ERPNext site. POSAwesome and industry-specific customizations are optional. Requirements, installation commands, schema roles and the verified test environment are documented in [PROJECT_CONTEXT.md](docs/PROJECT_CONTEXT.md).

The app currently includes two explicitly separated execution modes:

- **Legacy** preserves existing digest subscriptions and automation execution. It is the upgrade default.
- **Unified** uses fresh WhatsApp Automation rules and a durable outbox in WhatsApp Digest Run and WhatsApp Delivery. Legacy execution and retries pause in this mode. Newly created rules start disabled and cannot run in Legacy mode.

Unified supports Summary and Sales Invoice Document Delivery actions. It persists execution identities, rendered text/private PDFs, normalized recipients, individual message parts and provider idempotency keys. OpenWA 0.25.0 replay behavior was verified on the configured test gateway. Successful parts are preserved on retry. Safe transient failures have a maximum of three attempts with backoff. Timeouts and worker crashes after dispatch are recorded as uncertain and are not automatically resent. **Provider Accepted** means the gateway accepted the request; it does not confirm delivery or reading.

Install/migrate adds only missing general catalog entries, a missing default template and a disabled **Invoice to Customer** example. It preserves existing configuration and history. It no longer creates or rewrites business-specific outbound rules. Existing rules previously created by the old installer are preserved and must be reviewed before use.

To configure invoice delivery on a test site:

1. Configure the OpenWA URL/API key in OpenWA Settings, save a WhatsApp Phone, press **Show QR**, and scan it using WhatsApp Linked Devices. The app creates/starts the session automatically, refreshes the QR while the dialog is open, and shows Connected for an existing connected session. Authentication uses `X-API-Key`. Verify the actual gateway version/API compatibility.
2. Open the disabled Invoice to Customer automation. Set company, execution user, sender, optional print format, language and letterhead. Review these settings, set Execution Engine to Unified in OpenWA Settings, then enable the rule. Enabled Unified rules cannot be saved while the site uses Legacy.
3. **Send to WhatsApp** is checked by default on Sales Invoice. Clear it on the draft to skip WhatsApp automation, manual queueing, and resends for that invoice. A submitted invoice with the checkbox enabled uses its explicit **WhatsApp Number**, otherwise the selected contact's mobile number. Missing/invalid numbers create a skipped history result. Consolidated POS invoices are skipped.
4. Delivery queues after commit and rechecks submission/company/permissions in the worker. PDF rendering calls Frappe's invoice print API and saves a private attachment. No private URL is sent as a substitute for the PDF.
5. Use the invoice's WhatsApp menu for history, deduplicated queueing or an explicitly separate resend. Manual send/run actions reject disabled rules/schedules and validate the sender before reporting queue success. Use Retry Failed in history for eligible failed/skipped work; inspect Delivery Parts for per-part outcomes. Uncertain results require reconciliation before a deliberate resend.

Unified executes under the configured enabled user and checks company, source document and report access. DocType blocks use permission-aware queries; report company filters are pinned to the automation company. Legacy built-in providers, SQL conditions/blocks and scripts currently require **Administrator** as execution user in Unified because those sources do not implement row-level permissions. Prefer report or DocType blocks for other execution users. Connection/rule management remains restricted to System Manager.

Scheduled Unified summaries use the previous complete period and persist that period at enqueue time. Full schedule consolidation, threshold alerts, the verified 40-entry financial catalog, guided setup and industry extension packs remain roadmap work. Existing sales providers retain their legacy accounting/currency limitations; they are not a verified financial catalog.

See [DECISIONS.md](docs/DECISIONS.md) for the implementation checklist and cutover/rollback requirements, [PROGRESS.md](docs/PROGRESS.md) for observed checks, and [CLIENT_UPDATES.md](CLIENT_UPDATES.md) for operational changes. Real text and a synthetic submitted-invoice PDF were accepted by OpenWA 0.25.0; the gateway attachment matched the private PDF byte-for-byte, and the user confirmed receipt and that it opens correctly. The public development URL returned HTTP 502, so browser acceptance and production deployment remain unverified. Local PDF validation used a temporary asset server and the locally installed patched-Qt wkhtmltopdf renderer.


The development runtime and worker/outbox service commands are recorded in PROJECT_CONTEXT.md. With Frappe v15 behind a tunnel, verify that generated PDF asset URLs use the public HTTPS port rather than appending the internal bench web port.
