# Client updates

## 2026-10-24

- Removed customer-specific setup from installation and migration. Existing rules and history are preserved; catalog/template edits are no longer overwritten.
- Added an opt-in Unified execution mode with a persistent outbox, per-recipient message parts, duplicate prevention, bounded safe retries and visible uncertain outcomes. Existing sites default to Legacy; new automations default to disabled and require Unified mode.
- Added a disabled Invoice to Customer example, an explicit invoice WhatsApp Number field, invoice print-PDF generation and WhatsApp history/queue/resend actions. The selected contact's mobile is the fallback recipient. Consolidated POS invoices are skipped.
- Added execution-user/company/report/document checks. Legacy SQL/script/built-in sources require Administrator in Unified until permission-aware metric adapters are available.
- Installed and migrated the app on the user-authorized development test site. Automated checks use a mocked gateway and synthetic fixtures. Separately, real text and a synthetic invoice PDF were tested with the user-approved connection/recipient; the user confirmed both arrived and the PDF opens. The gateway attachment matched the private PDF, and idempotent replay returned the original message without another send. Full roadmap acceptance and production deployment remain incomplete.

The approved test connection is configured in encrypted settings; all test automations are disabled and the engine is restored to Legacy. The public development URL returned HTTP 502; its web availability/browser acceptance remains unresolved. Keep the invoice preset disabled until its company, permissions, print settings and recipients are reviewed. The remaining roadmap and exact resume point are in `docs/DECISIONS.md`.

Follow-up review corrected failed-recipient history, strengthened stale-worker claims and made manual send/run actions reject disabled or unready configuration. All 23 unit checks and the mocked database-concurrency check passed. The public 502 was traced to the absent bench web process on port 8000 behind the running Cloudflare tunnel; the web service was not started or reconfigured during diagnosis.

The development invoice rule is now active in Unified mode. A missing worker and an incorrect public PDF port were corrected; the submitted invoice was sent once, with matching PDF bytes and a gateway `read` result. A managed long worker and site-specific retry/outbox timer are active. The setup form now displays required delivery fields together and rejects enabling a Unified rule while the site is in Legacy. All 24 unit checks passed. This supersedes the earlier disabled/Legacy test state; production deployment and boot/logout uptime remain unverified.
