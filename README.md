# Frappe WAHA

Standalone Frappe app for WhatsApp digest delivery through WAHA.

The app keeps the full flow inside Frappe:

- Configure WAHA base URL and API key.
- Register WhatsApp sender phones by scanning a QR code in Desk.
- Build digest subscriptions from ERPNext/POSAwesome metrics.
- Render customizable HTML/CSS/Jinja digests into private PDF files.
- Send PDFs to WhatsApp phone recipients and log every run.

WAHA authentication uses the `X-Api-Key` header.

