"""Site-independent checks: run with the bench environment's unittest runner."""

import copy
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from frappe_waha import install, requirements


class TestInstallation(unittest.TestCase):
    def setUp(self):
        translation = patch.object(requirements, "_", side_effect=lambda text: text)
        translation.start()
        self.addCleanup(translation.stop)

    def test_seed_catalog_is_insert_only_and_industry_optional(self):
        stored = {}
        inserted = []

        def exists(doctype, filters):
            if doctype == "DocType":
                return False
            return stored.get(filters["code"])

        def new_doc(doctype):
            self.assertEqual(doctype, "WhatsApp Digest Metric")
            doc = Mock()
            doc.update.side_effect = lambda data: setattr(doc, "data", copy.deepcopy(data))

            def insert(**kwargs):
                inserted.append(doc)
                stored[doc.data["code"]] = doc.data["code"]

            doc.insert.side_effect = insert
            return doc

        with (
            patch.object(install.frappe, "db", SimpleNamespace(exists=exists)),
            patch.object(install.frappe, "new_doc", side_effect=new_doc),
            patch.object(install.frappe, "get_doc") as get_doc,
        ):
            install.seed_default_metrics()
            first_count = len(inserted)
            self.assertGreater(first_count, 0)
            self.assertTrue(all(doc.data["category"] != "POS" for doc in inserted))
            install.seed_default_metrics()
            self.assertEqual(len(inserted), first_count)
            get_doc.assert_not_called()  # Existing, possibly customized entries stay untouched.

    def test_installer_only_seeds_catalog_template_and_connection_defaults(self):
        with (
            patch.object(install, "validate_requirements") as validate,
            patch.object(install, "seed_openwa_settings") as settings,
            patch.object(install, "seed_default_template") as template,
            patch.object(install, "seed_default_metrics") as metrics,
            patch.object(install, "seed_invoice_preset") as invoice,
            patch.object(install.frappe, "new_doc") as new_doc,
        ):
            install.after_install()
            validate.assert_called_once()
            settings.assert_called_once()
            template.assert_called_once()
            metrics.assert_called_once()
            invoice.assert_called_once()
            new_doc.assert_not_called()  # No outbound rules, recipients, or schedules.

    def test_supported_versions_and_no_industry_requirement(self):
        with (
            patch.object(
                requirements.frappe, "get_installed_apps", return_value=["frappe", "erpnext"]
            ),
            patch.object(
                requirements.importlib,
                "import_module",
                return_value=SimpleNamespace(__version__="15.122.0"),
            ),
        ):
            requirements.validate_requirements()

    def test_missing_erpnext_and_unsupported_versions_fail(self):
        def reject(message):
            raise ValueError(message)

        with (
            patch.object(requirements.frappe, "throw", side_effect=reject),
            patch.object(requirements.frappe, "get_installed_apps", return_value=["frappe"]),
        ):
            with self.assertRaisesRegex(ValueError, "erpnext"):
                requirements.validate_requirements()
        with (
            patch.object(requirements.frappe, "throw", side_effect=reject),
            patch.object(
                requirements.frappe, "get_installed_apps", return_value=["frappe", "erpnext"]
            ),
            patch.object(
                requirements.importlib,
                "import_module",
                return_value=SimpleNamespace(__version__="16.0.0"),
            ),
        ):
            with self.assertRaisesRegex(ValueError, "v15"):
                requirements.validate_requirements()
