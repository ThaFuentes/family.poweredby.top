import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.utils.mail import explain_smtp_failure, normalize_smtp_port_enc


class SmtpPortTests(unittest.TestCase):
    def test_pop3_ssl_becomes_465(self):
        port, enc, warn = normalize_smtp_port_enc(995, "ssl")
        self.assertEqual(port, 465)
        self.assertEqual(enc, "ssl")
        self.assertIn("995", warn)

    def test_imap_ssl_becomes_465(self):
        port, enc, warn = normalize_smtp_port_enc("993", "ssl")
        self.assertEqual((port, enc), (465, "ssl"))
        self.assertTrue(warn)

    def test_465_forces_ssl(self):
        port, enc, warn = normalize_smtp_port_enc(465, "tls")
        self.assertEqual((port, enc), (465, "ssl"))
        self.assertIn("465", warn)

    def test_587_ssl_becomes_starttls(self):
        port, enc, warn = normalize_smtp_port_enc(587, "ssl")
        self.assertEqual((port, enc), (587, "tls"))
        self.assertTrue(warn)

    def test_ok_combo_unchanged(self):
        self.assertEqual(normalize_smtp_port_enc(465, "ssl")[:2], (465, "ssl"))
        self.assertEqual(normalize_smtp_port_enc(587, "tls")[:2], (587, "tls"))
        self.assertIsNone(normalize_smtp_port_enc(587, "tls")[2])

    def test_dovecot_banner(self):
        msg = explain_smtp_failure(Exception("(-1, b'Dovecot ready.')"), 995)
        self.assertIn("465", msg)
        self.assertIn("587", msg)
        self.assertNotIn("Dovecot ready", msg)
