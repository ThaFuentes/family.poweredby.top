"""Photos and PDFs on shared notes stay on the note and can be opened later."""
from __future__ import annotations

import io
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.chdir(ROOT)


def _png() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
        b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def _pdf() -> bytes:
    return b"%PDF-1.1\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


class NoteFileHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from dotenv import load_dotenv

        load_dotenv(os.path.join(ROOT, ".env"))
        from app import create_app

        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()
        cls.suffix = os.urandom(3).hex()
        with cls.app.app_context():
            from app.utils.access import mint_service_pass

            cls.service_key = mint_service_pass(max_uses=20, days=30, label="note-file-tests").code

    def _csrf(self, html):
        text = html.decode("utf-8", "replace") if isinstance(html, (bytes, bytearray)) else html
        m = re.search(r'name="csrf-token"\s+content="([^"]+)"', text)
        if m:
            return m.group(1)
        m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', text)
        return m.group(1) if m else ""

    def _logout(self):
        self.client.get("/auth/logout", follow_redirects=True)

    def _register(self, username, household=None, invite="", name=None):
        self._logout()
        r = self.client.get("/auth/register")
        if r.status_code == 302:
            self._logout()
            r = self.client.get("/auth/register")
        data = {
            "name": name or username,
            "username": username,
            "email": f"{username}@family.test",
            "password": "FamilyTest1!",
            "household_name": household or "",
            "family_key": invite,
            "invite_code": invite,
            "service_key": "" if invite else self.service_key,
        }
        return self.client.post("/auth/register", data=data, follow_redirects=True)

    def _login(self, username):
        return self.client.post(
            "/auth/login",
            data={"username": username, "password": "FamilyTest1!"},
            follow_redirects=True,
        )

    def _invite_member(self, username, name="Spouse"):
        token = self._csrf(self.client.get("/members/").data)
        inv = self.client.post(
            "/members/invite",
            data={
                "role": "member",
                "csrf_token": token,
                "next": "sheet",
                "panel": "keys",
            },
            headers={"X-CSRF-Token": token},
            follow_redirects=True,
        )
        self.assertEqual(inv.status_code, 200)
        m = re.search(r"Family key ([A-Z0-9-]+)", inv.data.decode("utf-8", "replace"))
        self.assertIsNotNone(m, inv.data[-800:])
        self._register(username, invite=m.group(1), name=name)

    def test_household_note_keeps_photo_and_pdf(self):
        admin = f"nf_a_{self.suffix}"
        member = f"nf_m_{self.suffix}"
        outsider = f"nf_o_{self.suffix}"
        self._register(admin, household=f"Notes {self.suffix}", name="Pat")
        page = self.client.get("/notes/")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'accept="image/*"', page.data)
        self.assertIn(b".pdf", page.data)
        token = self._csrf(page.data)
        created = self.client.post(
            "/notes/add",
            data={
                "title": "Deck rebuild",
                "body": "Ledger board and the county permit",
                "visibility": "household",
                "file": (io.BytesIO(_png()), "ledger.png"),
                "csrf_token": token,
            },
            content_type="multipart/form-data",
            headers={"X-CSRF-Token": token},
            follow_redirects=True,
        )
        self.assertEqual(created.status_code, 200)
        self.assertIn(b"Deck rebuild", created.data)
        self.assertIn(b"ledger.png", created.data)

        with self.app.app_context():
            from app.builddb.table_note_files import NoteFile
            from app.builddb.table_notes import Note
            from app.builddb.table_users import User

            owner = User.query.filter_by(username=admin).first()
            self.assertIsNotNone(owner)
            note = next(
                (
                    n
                    for n in Note.query.filter_by(household_id=owner.household_id).all()
                    if n.title == "Deck rebuild"
                ),
                None,
            )
            self.assertIsNotNone(note)
            note_id = note.id
            photo = NoteFile.query.filter_by(note_id=note_id).first()
            self.assertIsNotNone(photo)
            photo_id = photo.id

        img = self.client.get(f"/notes/file/{photo_id}")
        self.assertEqual(img.status_code, 200)
        self.assertTrue(img.data.startswith(b"\x89PNG"))
        disp = img.headers.get("Content-Disposition") or ""
        self.assertIn("ledger.png", disp)

        token = self._csrf(self.client.get("/notes/").data)
        attached = self.client.post(
            f"/notes/{note_id}/file",
            data={
                "file": (io.BytesIO(_pdf()), "permit.pdf"),
                "caption": "County permit",
                "csrf_token": token,
            },
            content_type="multipart/form-data",
            headers={"X-CSRF-Token": token},
            follow_redirects=True,
        )
        self.assertEqual(attached.status_code, 200)
        self.assertIn(b"permit.pdf", attached.data)
        self.assertIn(b"Open PDF", attached.data)

        with self.app.app_context():
            from app.builddb.table_note_files import NoteFile

            pdf_row = NoteFile.query.filter_by(note_id=note_id, original_name="permit.pdf").first()
            self.assertIsNotNone(pdf_row)
            pdf_id = pdf_row.id

        pdf = self.client.get(f"/notes/file/{pdf_id}")
        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.data.startswith(b"%PDF"))
        self.assertIn("permit.pdf", pdf.headers.get("Content-Disposition") or "")

        found = self.client.get("/find/?q=permit.pdf")
        self.assertEqual(found.status_code, 200)
        self.assertIn(b"Deck rebuild", found.data)
        self.assertIn(f"#note-{note_id}".encode(), found.data)

        token = self._csrf(self.client.get("/notes/").data)
        personal = self.client.post(
            "/notes/add",
            data={
                "title": "Private connector",
                "body": "Just for me",
                "visibility": "personal",
                "file": (io.BytesIO(_png()), "secret.png"),
                "csrf_token": token,
            },
            content_type="multipart/form-data",
            headers={"X-CSRF-Token": token},
            follow_redirects=True,
        )
        self.assertEqual(personal.status_code, 200)
        with self.app.app_context():
            from app.builddb.table_note_files import NoteFile
            from app.builddb.table_notes import Note
            from app.builddb.table_users import User

            owner = User.query.filter_by(username=admin).first()
            priv = next(
                (
                    n
                    for n in Note.query.filter_by(household_id=owner.household_id).all()
                    if n.title == "Private connector"
                ),
                None,
            )
            self.assertIsNotNone(priv)
            priv_file = NoteFile.query.filter_by(note_id=priv.id).first()
            self.assertIsNotNone(priv_file)
            priv_file_id = priv_file.id

        self._invite_member(member, name="Sam")
        house = self.client.get("/notes/?scope=household")
        self.assertEqual(house.status_code, 200)
        self.assertIn(b"Deck rebuild", house.data)
        self.assertIn(b"ledger.png", house.data)
        self.assertIn(b"permit.pdf", house.data)
        self.assertNotIn(b"Private connector", house.data)
        shared_img = self.client.get(f"/notes/file/{photo_id}")
        self.assertEqual(shared_img.status_code, 200)
        self.assertTrue(shared_img.data.startswith(b"\x89PNG"))
        blocked = self.client.get(f"/notes/file/{priv_file_id}")
        self.assertEqual(blocked.status_code, 404)

        self._register(outsider, household=f"Other {self.suffix}", name="Other")
        sneak = self.client.get(f"/notes/file/{photo_id}")
        self.assertIn(sneak.status_code, (403, 404))
        other_notes = self.client.get("/notes/")
        self.assertNotIn(f"note-{note_id}".encode(), other_notes.data)
        self.assertNotIn(b"ledger.png", other_notes.data)
        self.assertIn(b"No notes yet", other_notes.data)

        self._logout()
        self._login(admin)
        token = self._csrf(self.client.get("/notes/").data)
        removed = self.client.post(
            f"/notes/file/{pdf_id}/delete",
            data={"csrf_token": token},
            headers={"X-CSRF-Token": token},
            follow_redirects=True,
        )
        self.assertEqual(removed.status_code, 200)
        self.assertNotIn(b"permit.pdf", removed.data)
        gone = self.client.get(f"/notes/file/{pdf_id}")
        self.assertEqual(gone.status_code, 404)

        token = self._csrf(self.client.get("/notes/").data)
        bad = self.client.post(
            f"/notes/{note_id}/file",
            data={
                "file": (io.BytesIO(b"not a picture"), "virus.exe"),
                "csrf_token": token,
            },
            content_type="multipart/form-data",
            headers={"X-CSRF-Token": token},
            follow_redirects=True,
        )
        self.assertEqual(bad.status_code, 200)
        self.assertIn(b"Attach a photo or PDF", bad.data)


if __name__ == "__main__":
    unittest.main()
