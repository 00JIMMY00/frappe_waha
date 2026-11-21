# Progress

## 2026-11-21 — Sales Invoice WhatsApp opt-out

- Added a checked-by-default **Send to WhatsApp** field next to Customer.
  Both engines enforce the opt-out for invoice-triggered deliveries.
- Passed 30 unit tests and JavaScript syntax checks. Migrated the development
  site and verified that a new invoice defaults to checked and repeat
  installation preserves existing automation and run counts.
- Production deployment remains pending.

## 2026-11-17 — Repair Show QR session setup (local verification)

- Changed Show QR to find/create/start the provider session directly, save its UUID,
  reuse a unique existing session matching the phone, and poll QR/connection status
  until the dialog closes. Connected sessions are reused and initializing sessions
  wait for QR readiness.
- Session names resolve through the provider list before UUID routes. Missing
  sessions use HTTP status handling. The dialog displays safe server errors.
- Checked locally with 29 passing unit tests, including five session regression
  tests, JavaScript syntax and diff whitespace checks.
- Remaining work is production release and live browser QR/scanning verification.
  This entry records local verification only.

## 2026-10-24 — Activate submitted-invoice delivery and repair its runtime

- Diagnosed a user-submitted invoice that had no delivery run: its Unified rule was enabled, but the site remained in Legacy and no RQ worker was registered. The invoice had a valid selected-contact mobile matching the previously approved test recipient. No active legacy rules/subscriptions would be paused by cutover.
- Switched the authorized development site to Unified and queued the already-submitted invoice once through the existing permission-checked invoice action. The user's configured company, execution user and sender were retained. Other historical rules were not enabled or replayed.
- Installed and enabled the local user service `frappe-bench1-long-worker.service` for this bench's long queue. Its existing queued jobs were inspected and belonged only to the authorized development site. Added the site-specific `frappe-dev2-whatsapp-outbox.timer` and oneshot service to poll durable queued/retry work once per minute without starting scheduling across the other bench sites. Both units were observed active/enabled; these are user-manager services, not a verified production startup deployment.
- Identified the PDF-network failure: Frappe expanded the configured public HTTPS host with the internal port 8000. Set the development site's public `host_name` to its explicit HTTPS port 443 so generated asset URLs use the reachable public endpoint. Stopped only the obsolete PDF subprocess belonging to this invoice job, after verifying no content/parts had reached dispatch, then retried the same failed execution under the corrected configuration.
- Observed the same execution reach Provider Accepted with a private one-page PDF, one outbound attempt and exactly one run for the invoice. The PDF contained its source invoice identity, the gateway's downloaded attachment matched the private bytes, and the gateway reported `read`. No customer names, recipient numbers, document identifiers or credentials are recorded here.
- Prevented the configuration problem from recurring: an enabled Unified rule now rejects saving in Legacy mode with a specific settings message. Moved execution user/action/print options into the main delivery section, made company/user/sender conditionally required, and hid summary-only sections for document delivery.
- Checks: **24 unit tests passed**, including the new mode-mismatch regression; changed DocType JSON order/field mapping, JavaScript syntax and `git diff --check` passed. The updated DocType was reloaded on the development site and its conditional required field observed. Public site HTTP 200, worker registration and active/enabled user units were verified. No production workflow/deployment was claimed; the larger roadmap and browser/full permission acceptance remain incomplete.


## 2026-10-24 — Follow-up outbox fixes and confirmed public 502 cause

- Completed the pending review fixes: recipient history now reports a blocking failed part as Failed rather than Queued; each part claim locks/rechecks the run's worker token before claiming the delivery and refreshes its lease; manual automation/schedule actions validate eligibility and sender readiness before reporting queue success. Disabled schedules reject manual execution and schedule actions require write permission on the linked automation.
- Verification: **23 unit tests passed**, including the new failed-recipient, expired-worker, manual validation and disabled-schedule regressions. The authorized development site's mocked-transport database/concurrency check passed again, including cross-connection cutover and stale-worker recovery. Python parsing and `git diff --check` passed. No additional live WhatsApp messages were sent and no production deployment was performed.
- Diagnosed the public development site's HTTP 502 using the public response, local listeners and Cloudflare tunnel journal. The tunnel forwards the domain to `http://localhost:8000`; its journal reports `127.0.0.1:8000: connect: connection refused`. No web process is listening on port 8000. The tunnel and bench Redis services are running. No public routing or service configuration was changed during diagnosis.
- Remaining: start/restore the bench web service through the environment's intended process manager and verify the public URL, then continue browser/permission acceptance and the remaining roadmap. The full roadmap is still incomplete.


## 2026-10-24 — Reusable app boundary, opt-in outbox and initial invoice delivery

Implemented the reusable-app boundary and substantial parts of the Phase 2/3 execution and invoice path. The full roadmap is not complete; individual checkboxes and the exact resume point are in `DECISIONS.md`.

Changes:

- Declared ERPNext/Frappe v15 dependencies and install/migration guards; retained the technical package/DocType names. Documented schema/callable roles, environments, installation and the reversible cutover.
- Removed customer-specific install/migrate seeding. Existing catalog/template configuration is preserved; missing general entries are inserted, and optional POS catalog seeding checks its source DocType. Only a disabled Invoice to Customer preset is added; existing business rules/history are not converted/deleted/enabled.
- Added the Legacy/Unified site switch. Existing rules remain Legacy; fresh automations are disabled Unified rules. Legacy entry points/retries pause in Unified mode, and Unified workers pause in Legacy mode. The test site is left in Legacy with no enabled outbound rules.
- Added durable unique run identities and per-message-part WhatsApp Delivery records, database claims/worker tokens, saved text/private-PDF/recipient/session snapshots, safe bounded retries, persisted provider idempotency keys, per-part outcomes and stale-worker recovery. A switch committed in another database connection was also observed between message parts, pausing remaining dispatch; the switch deliberately bypasses the per-request Single-value cache. Provider acceptance is separate from delivered/read confirmation. Unknown outcomes are not automatically resent. Best-effort after-commit RQ wake-up cannot propagate a queue outage into invoice submission; polling recovers durable work.
- Added configured-user/company/source checks and permission-aware DocType/report queries. Report company filters cannot be replaced by saved custom-report defaults. Legacy SQL/provider/script sources require Administrator in Unified until permission-aware financial adapters replace them.
- Added the invoice WhatsApp Number field, selected-contact mobile fallback, Frappe document-print PDF integration with print format/language/letterhead, private attachments and invoice history/queue/explicit-resend actions. Submitted state and eligibility are rechecked before dispatch; consolidated POS invoices and absent/invalid recipient numbers produce skipped results. History links to per-part outcomes; dashboard counts provider-accepted recipients alongside legacy accepted records.
- Aligned README, client updates, project context and the implementation roadmap with these implemented capabilities and limits.

Observed local/development verification:

- The user authorized `elsakr-dev2.arab-erp.com` as the disposable test site. Before installation it listed Frappe/ERPNext 15.122.0, `elsakr_app` and `arab_erp_theme`; POSAwesome was absent. This was a new installation of this app, not a pristine Frappe/ERPNext-only site.
- `bench --site elsakr-dev2.arab-erp.com install-app frappe_waha` succeeded. Initially it created eight general catalog records and no outbound configuration/history. Later migrations added the disabled invoice example and invoice field.
- Full `bench --site elsakr-dev2.arab-erp.com migrate --skip-search-index` completed repeatedly. Initial attempts exposed stopped Redis services; the local bench cache/queue services were started for verification. No delivery worker or scheduler process was started.
- `../../env/bin/python -m unittest frappe_waha.tests.test_engine frappe_waha.tests.test_install -v`: **19 passed**. Coverage includes dependency/version boundaries, insert-only seeding, execution identity, company/report rejection, previous-period/leap-day/month-end-delay behavior, recipient resolution/invalid numbers, cancellation skip, invoice print/private-file contract, print failure handling, transport classification/redaction, stable idempotency-key forwarding, strict phone parsing and queue-outage containment.
- `frappe_waha.tests.installation_check.check_installation`: verified repeat seeding twice preserves a customized disabled metric and customized template and does not add/change outbound-record counts; temporary edits are rolled back.
- `frappe_waha.tests.engine_check.check_engine`: passed on real database connections with a mocked gateway and renderer. Two concurrent enqueues produced one run, two workers produced one logical send, partial failures retried only unfinished content, uncertain outcomes did not auto retry, cutover paused queued work, a denied execution user failed without dispatch, transaction rollback discarded the run, and expired dispatch markers recovered without ambiguous resend. Synthetic records were removed and the engine setting restored. **Zero real gateway calls.**
- `bench build --app frappe_waha` completed. Changed JavaScript passed `node --check`; app Python/JSON parsing and `git diff --check` passed. No browser acceptance or public-site availability was verified.


Approved live integration and environment checks later in the session:

- Saved the user-provided gateway key in Frappe's encrypted Password field. No key or recipient number is recorded in source/documentation. The gateway health API reported OpenWA 0.25.0 with one ready session matching the explicitly approved test number; no other recipients were inferred or contacted.
- A labeled synthetic text run reached Provider Accepted and its exact message was found in the gateway store.
- The first committed synthetic invoice submitted successfully but PDF rendering failed with a network error while the public development URL returned HTTP 502. The run failed without sending an attachment and the synthetic invoice was canceled. This is an observed rendering failure, not a successful delivery.
- Installed official patched-Qt wkhtmltopdf 0.12.6.1 in the local user's tool directory (`~/.local/opt/wkhtmltox-0.12.6.1-3`, linked from `~/.local/bin/wkhtmltopdf`). Production PDF dependencies remain a separate deployment requirement.
- Using a temporary asset server bound only to localhost and a process-local host-name override, a second committed synthetic Sales Invoice triggered exactly one Document Delivery run. Frappe's selected invoice print format generated a one-page private PDF; its invoice identity and synthetic content were extracted and checked. The gateway stored it as a document and the downloaded attachment's bytes matched the private PDF. The gateway's message status was `read`; the app continues to report Provider Accepted unless provider-confirmation handling is implemented.
- The user explicitly confirmed both the text and PDF arrived and that the PDF opens correctly. Replaying the PDF request with its persisted idempotency key returned `Idempotent-Replayed: true` and the original message ID, rather than a new send.
- Additional real invoice lifecycle checks, with HTTP blocked, passed missing-phone skip without a PDF, full submit-transaction rollback discarding both invoice and run, and cancellation-before-dispatch skip. The actual print failure, missing-phone and accepted-delivery history were retained. Committed synthetic invoices were canceled, synthetic customers/items disabled, test automations disabled, and the engine restored to Legacy. Existing business records/history were not removed.
- The real-gateway checks were separate from the automated concurrency suite, which still made zero real gateway calls. These are authorized development-site checks, not a production deployment or public-browser acceptance.

Remaining work:

- Finish the full permission matrix, Desk/browser acceptance and legacy retirement checks. The approved real connection and recipient have now passed text/PDF acceptance as recorded below. The public development URL returned HTTP 502; do not equate successful local backend tests with public-site availability.
- Complete Alert actions, the shared permission-aware metric/report contract and verified 40-entry financial catalog, full schedule/threshold behavior, guided setup/preview/presets, extension registration and release/cutover/rollback validation. Existing legacy financial/currency limitations remain; no catalog agreement with ERPNext is claimed.
- No production deployment workflow has been identified or executed. No live production site or real customer receipt has been verified. This entry records local code and authorized development-site checks only.
