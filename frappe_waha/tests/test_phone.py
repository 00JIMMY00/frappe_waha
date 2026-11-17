import unittest
from unittest.mock import Mock, patch

from frappe_waha.utils.openwa_client import OpenWAClient, OpenWAError
from frappe_waha.frappe_waha.doctype.whatsapp_phone.whatsapp_phone import WhatsAppPhone


class TestPhone(unittest.TestCase):
    def test_name_lookup_uses_list_without_uuid_route(self):
        client = OpenWAClient("https://gateway.invalid")
        session = {"id": "00000000-0000-4000-8000-000000000001", "name": "wa-example"}
        with patch.object(OpenWAClient, "request", return_value=[session]) as request:
            self.assertEqual(client.get_session("wa-example"), session)
            request.assert_called_once_with("GET", "/sessions")

    def test_missing_name_is_structured_404(self):
        client = OpenWAClient("https://gateway.invalid")
        with patch.object(OpenWAClient, "request", return_value=[]):
            with self.assertRaises(OpenWAError) as caught:
                client.get_session("wa-missing")
            self.assertEqual(caught.exception.status_code, 404)

    def test_setup_creates_missing_session_or_reuses_connected_phone(self):
        for existing in (False, True):
            with self.subTest(existing=existing):
                doc = Mock(session_name="wa-example", provider_session_name=None,
                           phone="+12025550101", session_status="ready" if existing else "created")
                doc.make_session_name.return_value = "wa-example"
                client = Mock()
                client.get_session.side_effect = OpenWAError("HTTP 404", status_code=404)
                session = {"id": "provider-id", "phone": "12025550101", "status": "ready"}
                client.list_sessions.return_value = [session] if existing else []
                client.create_session.return_value = session
                def apply(value):
                    doc.session_name = value["id"]
                doc.apply_openwa_session.side_effect = apply
                with patch.object(OpenWAClient, "from_settings", return_value=client):
                    WhatsAppPhone.create_or_start_session.__wrapped__(doc)
                if existing:
                    client.create_session.assert_not_called()
                    client.start_session.assert_not_called()
                else:
                    client.create_session.assert_called_once_with("wa-example")
                    client.start_session.assert_called_once_with("provider-id")
                doc.check_permission.assert_called_once_with("write")

    def test_sync_handles_redacted_404(self):
        doc = Mock()
        client = Mock()
        client.get_session.side_effect = OpenWAError("OpenWA request failed (HTTP 404).", status_code=404)
        with patch("frappe_waha.frappe_waha.doctype.whatsapp_phone.whatsapp_phone.now_datetime"):
            WhatsAppPhone.sync_from_openwa(doc, client=client)
        self.assertEqual(doc.status, "Pending")

    def test_auth_failure_does_not_create_session(self):
        doc = Mock(session_name="wa-example")
        client = Mock()
        client.get_session.side_effect = OpenWAError("HTTP 401", status_code=401)
        with patch.object(OpenWAClient, "from_settings", return_value=client):
            with self.assertRaises(OpenWAError):
                WhatsAppPhone.create_or_start_session.__wrapped__(doc)
        client.create_session.assert_not_called()
