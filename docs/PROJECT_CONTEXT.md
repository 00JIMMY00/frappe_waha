# Project context

## WhatsApp phone connection flow

Show QR performs session setup before polling QR readiness. Generated names resolve
through OpenWA's session list and the returned UUID is stored in session_name.
A missing reference can reuse a unique session with the same phone number.
The dialog refreshes until connected or closed. This flow has local regression
coverage; production release and browser scanning verification are pending.

## Application and supported stack

`frappe_waha` is a Frappe/ERPNext v15 app for WhatsApp reports and automation. The technical package and existing DocType names stay unchanged so installed sites and delivery-history references remain valid. Desk branding uses WhatsApp/OpenWA. This checkout is not `elsakr_app`; the latter is a separate app installed on the authorized test site.

Requirements: Python 3.10+, Frappe 15.x, ERPNext 15.x, Requests, a running bench database/cache/queue and workers, and an independently configured `rmyndharis/OpenWA` gateway. PDF rendering uses Frappe's document-print infrastructure and a patched-Qt wkhtmltopdf binary. Local validation installed wkhtmltopdf 0.12.6.1 in the user tool directory; production workers need their own verified renderer installation and PATH. POSAwesome and customer-specific fields are not installation requirements. The approved test gateway reported OpenWA 0.25.0. Its health/session/text/document routes and provider idempotent replay were exercised. A synthetic invoice PDF was inspected, matched against the gateway attachment byte-for-byte, and confirmed received/openable by the user.

Each business installs the app on its own ERPNext site and owns its settings, connection, recipients, and data. There is no central hosted service in this repository.

## Execution paths and schema roles

This map records the baseline roles and their current transition:

| Component | Current role | Intended transition |
| --- | --- | --- |
| WAHA Settings; WhatsApp Phone; `utils/openwa_client.py` | Connection settings, session lifecycle, QR, text/document transport | Retain technical names; share connection/transport across all actions |
| `utils/waha_client.py` | Legacy import compatibility | Keep as compatibility shim |
| WhatsApp Automation; its Block, Condition, Recipient, Report Filter/Column child tables | Configurable event/manual/report automation | Retained as the primary model; fresh rules use Unified with Summary/Document Delivery actions and an execution user |
| WhatsApp Schedule | Schedule linked to an automation | Retain timing configuration; unify period resolution |
| WhatsApp Digest Metric | Built-in/custom provider and report catalog | Retain as catalog, extend definitions/permission enforcement |
| WhatsApp Digest Template | HTML/CSS/Jinja templates | Retain behind advanced controls |
| WhatsApp Digest Subscription | Legacy digest configuration, including optional POS trigger | Compatibility/history only after explicit engine cutover |
| WhatsApp Digest Run; Run Recipient | Shared automation and subscription history and attachment references | Retained records/links; extended with a unique execution key, engine/user/event, fixed period, content/attachment snapshots and worker claims |
| WhatsApp Delivery; `digest/engine.py` | New per-message-part outbox and claiming/retry/recovery pipeline | Unified execution only; links to retained run history |
| `digest/automation.py` | Event dispatcher, automation renderer/sender/scheduler | Transition entry points to the shared engine |
| `digest/sender.py`; `scheduler.py`; `triggers.py` | Digest delivery, scheduler, optional POS event | Compatibility entry points; disable legacy execution at cutover |
| Workspace, number cards and dashboard chart | Desk navigation and history summaries | Evolve around Connection, Automations, Catalog/Templates, History |

Current callable Desk methods include Automation `send_now`/`load_report_metadata`, Schedule `run_now`, Subscription `get_available_metrics`/`preview_digest`/`send_now`, and Run `retry_failed`. Keep route names compatible during the transition, with explicit eligibility and permission checks. The module-level `send_whatsapp_automation` is also whitelisted and must be covered by the cutover.

`hooks.py` currently registers both schedulers and wildcard document-event dispatch, plus a POS Closing Shift submit hook. The explicit site execution-engine switch selects Legacy or Unified. Legacy subscription/event/manual/retry entry points reject execution in Unified mode. Unified rules reject Legacy mode, including queued workers. `poll_outbox` recovers pending/stale work; durable identities and database locks handle repeated/concurrent triggers. A best-effort queue wake-up runs after commit and cannot propagate queue outages into invoice submission; polling recovers queued work. A processing marker is committed before a provider call; ambiguous requests become Uncertain, not safe retries. `digest/metrics.py` currently has eight general sales/payment providers and one optional POS Closing Shift provider; it is not the planned 40-entry financial catalog.

## Installation and migration

From a bench with Frappe/ERPNext v15 available, obtain this repository with `bench get-app <repository-url>`, then run:

```sh
bench --site <site> install-app erpnext  # if not installed already
bench --site <site> install-app frappe_waha
bench --site <site> migrate
bench build --app frappe_waha
```

The app declares ERPNext as required and rejects unsupported framework/ERPNext major versions before install/migration. Install and migrate seed connection-mode defaults, an absent default template, missing catalog entries, the Sales Invoice WhatsApp Number custom field and a disabled Invoice to Customer preset. They do not create active outbound rules, recipients or schedules. Existing catalog records, templates, settings, disabled choices, and existing business rules are preserved. The optional POS catalog entry is created only when its source DocType exists. Removing the old customer-specific seeder does not remove or disable rules it previously created.

Before enabling any existing rule, inspect its recipients, company, sender, triggers, and schedule. Technical cutover and rollback requirements are in `DECISIONS.md`. The switch defaults to Legacy; fresh rules default to disabled Unified configuration. No legacy rules or history are automatically converted/deleted.

Unified scheduled runs currently use the previous complete period and persist it at enqueue time. The full schedule/threshold-alert roadmap is incomplete. Text/PDF/Both summaries reuse the current renderer. Legacy built-in metrics, SQL conditions/blocks and scripts are restricted to Administrator as execution user; other users can use permission-aware report/DocType blocks. Report company filters are pinned and saved custom-report defaults cannot override them, DocType blocks require a company field or a permission-checked source child table, and source/sender/company checks run again before delivery. The 40-entry financial catalog and guided preview/setup remain unimplemented.

Sales Invoice submit delivery queues after commit, rechecks submission status and skips consolidated POS invoices. Recipients resolve from the explicit invoice WhatsApp Number, otherwise the selected contact's mobile. The worker calls Frappe's invoice print-PDF API with format/language/letterhead options and saves a private attachment. The invoice's WhatsApp menu links to history and offers deduplicated queueing or an explicit separate resend. Run history links to Delivery Parts. Provider Accepted describes gateway acceptance only. Uncertain parts have no automatic resend or reconciliation UI yet.

## Observed environment and deployment boundary

On 2026-10-24 the local bench at `/home/xxx/bench1/my-bench` imported Frappe and ERPNext 15.122.0. The user authorized `elsakr-dev2.arab-erp.com` as the disposable validation site. Before installing this app, it listed Frappe, ERPNext, `elsakr_app` and `arab_erp_theme`, with no POSAwesome. This validates installation without an industry app, not a pristine site containing only Frappe/ERPNext.

Other sites are present but are not authorized test targets. No `apps.yaml`, `.github/workflows/ci.yml`, or `deploy/` files were found in this checkout. Production hosting and the release workflow have not been identified. The approved test gateway connection is configured with its key stored in the Frappe Password field, not in source or documentation. The public development URL returned HTTP 502. Follow-up inspection confirmed its Cloudflare tunnel forwards to `http://localhost:8000` and logs connection refusal because no bench web process listens on port 8000; the tunnel and bench Redis services are running. Actual invoice-PDF validation used a temporary HTTP asset server bound to localhost and a process-local host-name override; no public routing/deployment configuration was changed. Local/test-site checks do not establish a production deployment or a verified public ERPNext endpoint.

## Checks

Run site-independent installer tests with the bench environment:

```sh
../../env/bin/python -m unittest frappe_waha.tests.test_install frappe_waha.tests.test_engine -v
```

On an explicitly authorized disposable site without the POS extension:

```sh
bench --site <site> execute frappe_waha.tests.installation_check.check_installation
```

The integration check creates temporary catalog/template customizations, reruns the seeder twice, verifies preservation and outbound-record counts, and rolls back those edits. It never invokes the gateway. Run full migration separately and sequentially; do not run this check during schema updates.

For explicit database/worker-concurrency checks on that disposable site:

```sh
bench --site <site> execute frappe_waha.tests.engine_check.check_engine
```

This check blocks real HTTP, mocks the gateway/summary renderer, commits synthetic fixtures to exercise independent database connections and crash recovery, then removes its fixture records and restores the engine setting. It requires an existing company and an unused reserved synthetic fixture phone; it never sends a message. Run it without outbound workers to avoid another process claiming fixtures while temporary Unified mode is active. This is a development check, not a production command.


## Current authorized development runtime (2026-10-24)

The user enabled/configured Invoice to Customer and requested delivery for a submitted invoice. The development site is now **Unified**, with that user-configured invoice rule enabled; this supersedes the earlier test cleanup state of Legacy with all rules disabled. The approved connection is still stored in encrypted settings. No existing legacy rules were active at cutover.

The public site was subsequently observed returning HTTP 200 with the bench web process listening on port 8000. Its `host_name` now includes explicit public HTTPS port 443. Frappe v15 otherwise appended the bench's internal `webserver_port` to the public origin, producing unreachable PDF asset URLs. The web listener remains on 8000; the public Cloudflare origin remains HTTPS. Real invoice printing and gateway attachment equality were verified using the corrected public URLs, without the earlier temporary asset server/host override.

Local user units under `~/.config/systemd/user/` provide the long worker and site-specific outbox polling:

```sh
systemctl --user status frappe-bench1-long-worker.service
systemctl --user status frappe-dev2-whatsapp-outbox.timer
```

The worker consumes this bench's shared long queue. The outbox oneshot calls only this development site's `frappe_waha.digest.engine.poll_outbox`, once per minute; the full bench scheduler was not started. These units restart/activate under the current user's service manager. User lingering is not enabled, and boot/logout uptime has not been verified. Redis and the web server remain separate prerequisites. Production hosting/startup still needs its own agreed deployment process.
