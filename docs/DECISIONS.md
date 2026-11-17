# Decisions and implementation roadmap

## 2026-11-17 — Resolve provider sessions before QR setup

Show QR uses the existing write-permission-checked setup method before polling.
Resolve legacy generated names through the session list and store the returned UUID.
When a reference is missing, reuse a unique session matching the phone or create
the deterministic generated session name. Ambiguous phone matches require explicit
selection. This recovers sessions connected through OpenWA and avoids restarting
ready or initializing sessions. Handle missing sessions by HTTP status because
transport messages intentionally redact provider response details.

## 2026-10-24 — General-purpose ERPNext WhatsApp app

### Status and resume point

- Status: reusable-app boundary implemented and verified on the authorized development site; Unified execution and the invoice-PDF path implemented with mocked-provider, real database and approved live-gateway checks. The full roadmap is **not complete**.
- Completed in this session: insert-only general seeding, v15 guards/dependencies, disabled invoice preset/number field, technical-role/cutover map, opt-in durable run/per-part outbox, concurrent claim/deduplication, saved content, conservative retry/uncertainty handling, initial permission boundaries, source invoice print-PDF API integration and Desk history/queue/resend actions.
- Verification: 24 site-independent tests passed; installation without POSAwesome and repeated full migrations passed on `elsakr-dev2.arab-erp.com` (Frappe/ERPNext 15.122.0, also containing `elsakr_app` and `arab_erp_theme`). Database checks with independent connections passed concurrent enqueue/workers, partial retry/content reuse, uncertain outcome handling, cutover pause, denied execution user, rollback and stale-worker recovery. The automated concurrency suite mocks transport/rendering. Separately, the approved OpenWA gateway reported 0.25.0; real text and a committed synthetic invoice PDF were accepted, the gateway attachment matched the private PDF byte-for-byte, and the user confirmed both arrived and the PDF opens. Provider idempotent replay reused the original message. No production deployment was verified.
- Remaining gates: complete the full permission matrix, browser/Desk flow acceptance and legacy-engine retirement checks. The public development URL returned HTTP 502; the successful PDF test used a temporary localhost asset server and process-local host override. Alert remains unimplemented in Phase 2; Phases 4–7 and broader release/performance checks remain open. Synthetic test rules/invoices remain disabled/canceled and their history retained. Following the user’s activation attempt, the user-configured invoice rule is enabled and the development site now uses Unified; a real submitted invoice was accepted once and its PDF/gateway bytes verified.
- Exact next action: finish Desk and permission/cutover acceptance against the now-working development web service and managed worker, then implement Phase 4's permission-aware metric/report result contract and first verified catalog set. Continue the remaining schedule/alert, guided setup, extension and release items in phase order. Real delivery testing already has an approved configured connection and a successful text/PDF result; no new recipient should be inferred.

- No existing business rules/history were deleted or converted. No production workflow or live production site was verified.

Keep completed checklist items checked and unfinished items unchecked. After each implementation session, update this resume point with the last completed step, checks actually run, remaining work, and the exact next action. Add the dated implementation results to `PROGRESS.md` as required by `AGENTS.md`; this file retains the architectural decisions and roadmap. Never mark a phase complete solely because its code was written.

### Goal and user-confirmed choices

Build a powerful, simple WhatsApp app that different businesses can install without business-specific code in the core. Users should select useful ERPNext metrics or reports, choose recipients, and send them on a schedule or trigger. Submitting a Sales Invoice with a customer phone should support automatic delivery of its actual PDF.

The user selected:

1. **Separate ERPNext sites:** each business installs the same app on its own site, with its own configuration and WhatsApp connection. A central hosted service is outside this roadmap.
2. **Fresh configuration:** rebuild automation configuration rather than automatically translating existing rules. Retain old delivery history for reference; fresh configuration does not authorize deleting business data or history.
3. **Common core plus extensions:** deliver standard ERPNext capabilities first and allow optional POS, car-wash, crane, tire, and other industry integrations.

### Architecture decisions and intended defaults

These choices guide implementation; they describe the target, not capabilities already delivered.

| Decision | Reason | Consequence |
| --- | --- | --- |
| Use OpenWA from `rmyndharis/OpenWA` as the gateway. | The existing client already targets this API; the WAHA naming is misleading. | Correct user-facing names and documentation. Verify compatibility with the deployed OpenWA version before integration testing. |
| Retain the technical package name `frappe_waha` during the initial restructuring. | Renaming the package and installed app adds migration work unrelated to the product behavior. | Use consistent WhatsApp/OpenWA branding in Desk; treat a later technical rename as a separate migration. |
| Use one automation engine for summaries, alerts, and document delivery. | The current digest and automation systems duplicate scheduling, rendering, and sending. | Share execution, queueing, recipient resolution, rendering, and logging. Retire old execution paths through a controlled switch. |
| Reuse ERPNext reports and accounting logic. | Financial metrics must agree with ERPNext, including historical balances, returns, and currencies. | Build adapters and metric extractors instead of maintaining a second accounting engine. Reuse a report result for related metrics within one run. |
| Keep industry integrations optional. | Standard installations must not require POSAwesome or a particular customer's custom fields and DocTypes. | Extensions register their own metrics, events, and presets only when their dependencies exist. |
| Send asynchronously after commit through one durable outbox. | External delivery must not block invoice submission, and repeated events must not create duplicate messages. | Persist execution and delivery identities, retry state, recipient results, and attachment references. Handle uncertain send outcomes explicitly. |
| Make normal setup usable without code. | Most users should not configure SQL, Python, JSON, or Jinja to send a daily summary. | Provide catalog selection, presets, supported filters, preview, and clear validation. Restrict advanced customization to administrators. |

### Pre-implementation baseline (retained for comparison)

- `hooks.py` registers both digest-subscription scheduling and automation scheduling, plus document-event dispatch and a POS closing trigger.
- The OpenWA client supports sessions, QR connection, text, and document attachments. WAHA remains in legacy names and the README.
- There are nine built-in metrics, primarily sales/POS. Query Report, DocType, SQL, script, and template facilities also exist.
- Current automation recipients are fixed phones. The generated automation PDF is not the invoice's ERPNext print PDF.
- The installer contains business-specific automation defaults and is also called after migration. Those defaults must leave the general core without copying customer details into documentation.
- Digest subscriptions use previous completed periods; automation schedules use current periods. Positive month/quarter/year-end delays are inconsistent with that automation calculation.
- Document-event dispatch does not enforce the automation's company, and automation execution lacks a durable unique run identity.
- Sales metric labels and currency handling need correction: invoice counts are labeled orders, and transaction-currency amounts are formatted as company currency.
- No app tests were found during review. The project context, decisions, and progress documents were empty before this planning entry. Deployment files described by `AGENTS.md` were not found in this checkout; do not infer a production environment from those instructions.

## Implementation checklist

### Phase 1 — Establish the reusable app boundary

- [x] Document the actual architecture, dependencies, installation process, and verified environment in `PROJECT_CONTEXT.md`; align the README with OpenWA and create `CLIENT_UPDATES.md` when recording user-facing changes.
- [x] Declare and validate Frappe/ERPNext v15 requirements. Confirm that a clean installation needs no industry app.
- [x] Remove business-specific seeding from install/migrate; seed only general catalog entries and disabled example presets. Repeated migration must preserve user configuration.
- [x] Define the cutover for fresh configuration: retain historical logs and their references, disable legacy execution when the new engine is enabled, and avoid automatically enabling outbound rules.
- [x] Map current DocTypes and callable methods to their retained, replaced, or compatibility roles before changing schema. Keep the final UI centered on Connection, Automations, Catalog/Templates, and History.

Completion check: the app boundary and cutover are documented, and clean installation/repeated migration do not create business-specific or active outbound automations.

### Phase 2 — Consolidate execution and delivery

Implementation checkpoint: Summary and Document Delivery share the Unified pipeline; Alert is not implemented. Existing Legacy execution code is retained behind the switch for rollback and has not been removed. Advanced legacy providers currently require Administrator. The full permission matrix, browser flow and legacy retirement remain open; OpenWA 0.25.0 text/document delivery and idempotent replay were verified; this phase is not marked complete.

- [ ] Establish one automation model with Summary, Alert, and Document Delivery actions; share the delivery pipeline across manual, document-event, and scheduled execution.
- [ ] Reuse the OpenWA session/client foundation and unify connection status, sender selection, phone normalization, and API error handling.
- [x] Add durable run and per-recipient delivery records. Use unique execution identities for document events and scheduled occurrences, plus concurrency protection when workers claim work.
- [x] Persist generated content/attachment references so retries reuse the original content and target only unfinished recipients. Track individual parts for split text messages.
- [x] Add bounded retries with backoff for retryable failures. Distinguish definite failure from an unknown outcome after a timeout; use provider idempotency if supported by the verified gateway version.
- [ ] Enforce company boundaries and a configured execution user's permissions in background jobs as well as previews and manual actions. Restrict connection management and advanced configuration appropriately.
- [x] Record queued, processing, provider-accepted, failed, skipped, and uncertain outcomes clearly. Use delivered/read states only when confirmed by the provider.
- [ ] Route both old entry points and new actions through the shared engine during transition; remove duplicate execution logic after the cutover checks pass.

Completion check: duplicate/concurrent triggers produce one logical delivery, partial failure retries preserve successful recipients, and unauthorized company/report/document access is rejected.

### Phase 3 — Deliver submitted Sales Invoice PDFs

Implementation checkpoint: the PDF API call, recipient resolution, private-file pipeline, cancellation skip and separate resend contract have unit coverage. A real committed synthetic invoice PDF was rendered, inspected, accepted by the gateway, downloaded byte-for-byte and confirmed received/openable by the user. Real invoice lifecycle checks passed missing-phone skip, submit rollback and cancellation-before-dispatch without network calls; one real render failure was recorded without an outbound attachment. Desk/browser acceptance remains open; consolidated POS invoices currently produce a visible skipped outcome.

- [x] Provide a disabled Invoice to Customer preset and a simple customer WhatsApp-number field/mapping. Default resolution: explicit invoice WhatsApp number, then the selected contact's mobile; do not broadcast to every contact.
- [x] On Sales Invoice submission, queue after commit and recheck that the document is still submitted before dispatch. Missing/invalid phones create a visible skipped result without failing submission.
- [x] Render through Frappe's document-print PDF API with the selected invoice print format, language, and letterhead. Do not replace the invoice with a metric-summary PDF.
- [x] Send the private PDF attachment through the shared delivery pipeline and link the result to the invoice.
- [x] Add invoice delivery status/history and permission-checked retry. Any deliberate resend must be explicit and recorded separately from retrying an uncertain or failed attempt.
- [x] Keep standard Sales Invoice delivery independent of POS extensions; separately account for POS workflows and consolidated invoices to avoid duplicate customer documents.

Completion check: a committed submitted invoice with a valid number queues the correct PDF once; rollback, cancellation before dispatch, missing phones, print errors, and gateway outages behave predictably without breaking invoice submission.

### Phase 4 — Build and verify the common metric/report catalog

- [ ] Define a shared metric result containing raw values, units/currency, display metadata, and optional table/chart data. Apply formatting only when rendering.
- [ ] Record each metric's source, calculation, permitted filters, return/cancellation behavior, currency basis, and whether it covers a date range or a balance as of a date.
- [ ] Implement adapters for financial statements, GL, AR/AP, sales/purchases, orders, and stock. Use supported report APIs and avoid summing detail rows together with report totals.
- [ ] Deliver a first verified set: net sales, invoice count, average invoice, returns, outstanding/overdue AR, outstanding/overdue AP, income, operating expenses, net profit, and cash/bank balances. Track each metric separately as the remaining catalog is implemented.
- [ ] Complete the 40-entry target catalog below, matching ERPNext under identical filters. Offer branch, cost center, warehouse, POS, or other dimensions only where the source supports them.
- [ ] Support full PDF reports for General Ledger, Trial Balance, P&L, Balance Sheet, Accounts Receivable, Accounts Payable, and Stock Balance, alongside short metric summaries.
- [ ] Handle empty data, zero values, multiple currencies, credit notes, historical balances, and optional modules explicitly. Define sales/POS inclusion rules to prevent consolidated invoice double counting.

Target catalog; these are planned entries, not implemented metrics:

| IDs | Category | Entries |
| --- | --- | --- |
| 01–08 | Sales | Net invoiced sales; invoice count; average invoice value; returns value; discounts; daily sales trend; top customers; top items/services |
| 09–13 | Receivables | Outstanding receivables; overdue receivables; ageing breakdown; largest debtors; amounts due in the next seven days |
| 14–18 | Payables | Outstanding payables; overdue payables; ageing breakdown; largest creditors; amounts due in the next seven days |
| 19–24 | Profit and expenses | Accounting income; cost of goods sold; gross profit; operating expenses; net profit/loss; expenses by account |
| 25–29 | Cash and bank | Cash balances; bank balances; customer receipts; supplier payments; cash/bank movement |
| 30–33 | Purchasing | Net purchases; purchase returns; top suppliers; purchase orders awaiting receipt |
| 34–38 | Stock | Stock value; stock by warehouse; reorder shortages; out-of-stock items; stock ageing |
| 39–40 | Sales orders | Unbilled order value; undelivered order value |

Completion check: every shipped metric has a documented definition and evidence of agreement with its ERPNext source; financial totals are not inferred from formatted text or inconsistent currencies.

### Phase 5 — Unify schedules and triggers

- [ ] Use one scheduler and period resolver; separate when to send from the data period. Default scheduled summaries to the previous complete period, with explicit current-to-date/custom-range choices.
- [ ] Support daily, weekly, monthly, quarterly, yearly, and one-time dated runs using the site's timezone; support send time/day, period-end delays, and prior-period comparisons.
- [ ] Calculate and persist occurrence dates and periods consistently for preview, dispatch, and retry. Handle month/year boundaries, leap days, delayed workers, and site timezone changes.
- [ ] Support document-event conditions using committed document state and company filtering. Prefer relevant persisted events over sending from validation/before-save hooks.
- [ ] Add threshold alerts evaluated on a configured schedule, with numeric comparisons, repeat limits/cooldown, and rearming after recovery. Distinguish a continuing breach from a new occurrence.
- [ ] Pause disabled rules, prevent overlapping claims, and recheck rule eligibility before sending. Document missed-run behavior; initially process only the latest due occurrence rather than replaying a backlog automatically.

Completion check: calendar boundaries, positive period-end delays, repeated scheduler ticks, worker delays, and persistent threshold breaches produce the expected period and message count.

### Phase 6 — Simplify setup and message presentation

- [ ] Build the guided flow: choose content, choose timing/trigger, choose recipients, preview, test to an explicitly selected recipient, and enable.
- [ ] Provide disabled starter presets: Daily Owner Summary, Weekly Collections, Monthly Financial Summary, and Invoice to Customer.
- [ ] Offer text, PDF, or both per automation, with Arabic/English rendering and appropriate RTL/LTR layout. Use one formatting/template pipeline for summaries and alerts.
- [ ] Support fixed management recipients for summaries and document-derived recipients for customer documents. Show resolved recipients and filters clearly in previews.
- [ ] Keep advanced report/template customization behind administrator controls and reuse the catalog rather than duplicating data-source definitions in each automation.
- [ ] Provide one searchable history view with source links, recipient results, attachments, attempts, errors, and permission-checked retries. Keep private files private; an inaccessible private URL is not a customer delivery fallback.

Completion check: a normal user can configure and preview the common presets without writing code, and history explains missing, failed, or uncertain deliveries.

### Phase 7 — Establish optional industry extensions

- [ ] Define a small extension registration contract for metrics, presets, and event adapters, with dependency detection and no business-specific defaults in core.
- [ ] Move reusable POS-specific behavior behind an optional adapter; verify that the core still installs and runs without POSAwesome/custom POS fields.
- [ ] Document future pack boundaries: car-wash throughput/service metrics, crane utilization/hire metrics, and tire sales/service reminders. Implement each pack later against its verified source app and separately agreed requirements.

Completion check: optional integrations are unavailable gracefully when dependencies are missing; no industry package is required for the common core.

### Phase 8 — Validate, document, and prepare release

- [ ] Run focused automated checks as each phase changes behavior; add meaningful tests for scheduling, permissions, financial calculations, duplicate prevention, recipient resolution, and retries.
- [ ] Verify clean Frappe/ERPNext v15 installation and repeated migration, plus upgrade/cutover from the existing schema with history retained and only one execution engine active.
- [ ] Exercise text and actual invoice-PDF delivery in an explicitly configured test environment; verify attachment contents and recipient results rather than assuming API success means customer delivery.
- [ ] Check performance for larger reports, multiple rules sharing report inputs, queued attachments, provider pacing, and disconnected sessions.
- [ ] Update `PROJECT_CONTEXT.md`, this file, `PROGRESS.md`, `README.md`, and `CLIENT_UPDATES.md` to reflect only implemented and observed behavior.
- [ ] Prepare release/cutover and rollback instructions. Identify the real deployment workflow and target before making production-impacting changes; record local checks separately from production verification.
- [ ] If deployment is requested, verify both workflow completion and the live site before marking anything deployed. Keep newly configured outbound automations disabled until their intended settings and recipients are reviewed.

Completion check: the release has reproducible validation, a documented cutover/rollback path, and an accurate remaining-work checkpoint. Optional future industry packs are tracked separately from common-core completion.

## 2026-10-24 — Schema roles and staged execution cutover

The component/DocType/callable map in `PROJECT_CONTEXT.md` is the baseline for schema work. Retain WhatsApp Automation as the main rule model and WhatsApp Digest Run as the shared history record, including all legacy links. Add a separate per-message-part delivery record so a successful text part or PDF can be persisted independently before attempting another part.

Introduce an explicit site execution-engine switch with Legacy as the upgrade default. New automation configuration belongs to Unified; existing rules remain Legacy. Unified mode must reject legacy subscriptions, automation dispatch, direct execution and retry paths. Legacy mode must reject Unified rules. Changing the switch does not delete, convert, enable or disable configuration/history; it changes eligibility at enqueue and worker execution. A switch back to Legacy pauses Unified work, including already queued jobs. Never replay a legacy rule automatically through Unified. Fresh rules require a configured execution user, company and sender before enabling.

This makes cutover reversible while preserving historical references. Before switching, review pending jobs, recipient settings and company/user permissions, and keep fresh rules disabled until reviewed. An in-flight provider request cannot be recalled; pause workers and drain/inspect in-flight jobs before switching. Rollback must not automatically retry uncertain provider outcomes.

## 2026-10-24 — Conservative transport outcomes and initial permission boundary

The initial conservative implementation preceded gateway verification. Later in this session the approved gateway reported OpenWA 0.25.0 and its idempotency behavior was verified, as recorded below. The Unified engine therefore persists per-part dispatch markers before the network call. Only connect timeouts and explicit HTTP 429 rejections are automatically retryable, with a maximum of three attempts and exponential backoff. Other HTTP 4xx responses except ambiguous HTTP 409 conflicts are treated as failures; read timeouts, server/connection failures and crashes after dispatch are uncertain and cannot trigger automatic resend. Successful parts retain their original content/attachment and are never replayed by ordinary retry. A new manual resend has a separate execution identity. Provider acceptance does not establish delivered/read status.

Execution uses a configured enabled user and rechecks rule/company/source/sender eligibility before each part. Existing built-in SQL providers and administrator scripts are not permission-aware financial adapters. Unified restricts those sources to Administrator until Phase 4 replaces them; other execution users can use report APIs or permission-aware DocType blocks. This is an interim restriction, not a claim that the financial catalog or general-user setup is complete.

Invoice Document Delivery handles submitted Sales Invoices and deliberately skips consolidated POS invoices. Dedicated POS receipt delivery and matching consolidated-invoice policy remain optional-adapter work. The explicit invoice number takes precedence over the selected contact's mobile; it never enumerates all customer contacts. Print options are passed to Frappe's document-print PDF API. Unit tests verify the API contract with mocks; the subsequent approved live test also verified a real synthetic invoice PDF, gateway attachment equality and user-confirmed receipt/opening.


## 2026-10-24 — Verified OpenWA idempotency and local PDF environment

The approved gateway health API reported OpenWA **0.25.0**, matching the documented API version. Both send-text and send-document support `Idempotency-Key`; the [upstream API contract](https://github.com/rmyndharis/OpenWA/blob/main/openapi.json) documents a 24-hour response replay window and explicit unknown/in-progress conflicts. Unified persists a key per message part before dispatch and passes the same key/body on safe retry. Replaying the approved synthetic PDF request returned `Idempotent-Replayed: true` and the original message ID. This supersedes the earlier unverified-provider assumption; uncertain outcomes still require explicit reconciliation rather than automatic resend, including outside the provider's retention window.

The local bench lacked a PDF executable. Validation installed the official patched-Qt wkhtmltopdf 0.12.6.1 package into the local user's tools, without changing production deployment files. The public development URL returned HTTP 502 and initially caused a real PDF rendering network failure; the failed run was recorded without sending an attachment. A temporary localhost-only asset server and a process-local host override allowed Frappe's normal invoice print API to render and deliver the synthetic PDF. The generated invoice content and gateway attachment bytes were verified, and the user confirmed the PDF opens. This validates the local backend/print/transport path; it does not establish that public web routing or production PDF dependencies work.


## 2026-10-24 — Prevent mode-mismatched activation and separate public PDF origin from backend port

Enabled Unified rules must now be saved with the site's execution engine set to Unified. Previously the form could appear enabled while the Legacy dispatcher silently skipped it. Disabled drafts and explicit site rollback remain possible; an already paused enabled Unified rule must be disabled or the site switched back to Unified before editing/saving it.

The authorized development site's public origin uses explicit HTTPS port 443 because this Frappe v15 bench otherwise appends its internal webserver port 8000 to generated asset URLs. This fixes actual PDF generation through the public endpoint without changing the local web listener or rewriting the application's public host to localhost.

A user-managed long worker and a site-specific outbox timer were selected for the development runtime. Polling only this site's outbox avoids starting unrelated schedules across the multi-site bench while still recovering durable deliveries/retries. This is an observed development configuration; it does not replace production service/startup design or establish reboot/logout availability.
