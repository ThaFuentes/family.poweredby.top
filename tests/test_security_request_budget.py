"""A household page must not sit in security logging until Cloudflare returns 522.

The guard is per process and often never fills. The request budget is what
stops device, reputation, and traffic connects from stacking past ~100s.
A full guard skips the log. Callers already continue when the connector
returns None. This does not change a ban decision the database did return.
"""
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from flask import Flask, g  # noqa: E402

import poweredbytop.core.security as security  # noqa: E402
import poweredbytop.models.connect_db as connect_db  # noqa: E402


FAKE_URI = "mysql+pymysql://household:secret@127.0.0.1:3310/family"


class RequestBudgetPlanTests(unittest.TestCase):
    def tearDown(self):
        connect_db.end_request_db_budget()

    def test_background_keeps_the_old_retry_budget(self):
        plan = connect_db.security_db_attempt_plan(None)
        self.assertEqual(plan["attempts"], 4)
        self.assertEqual(plan["connect_timeout"], 15)
        self.assertEqual(plan["read_timeout"], 35)
        self.assertEqual(plan["write_timeout"], 35)

    def test_request_plan_is_one_short_try_inside_the_budget(self):
        self.assertIsNone(connect_db.security_db_attempt_plan(0.2))
        for remaining in (2, 3, 5, 8):
            plan = connect_db.security_db_attempt_plan(remaining)
            self.assertEqual(plan["attempts"], 1)
            self.assertLessEqual(plan["connect_timeout"], 3)
            self.assertLessEqual(plan["read_timeout"], 4)
            self.assertLessEqual(plan["write_timeout"], 4)
            self.assertGreaterEqual(plan["connect_timeout"], 1)
            self.assertLessEqual(
                plan["connect_timeout"] + plan["read_timeout"],
                remaining,
            )

    def test_expired_budget_does_not_connect(self):
        connect_db.begin_request_db_budget(0)
        with patch("pymysql.connect") as connect:
            self.assertIsNone(connect_db.get_security_db())
        connect.assert_not_called()

    def test_live_request_does_not_retry_four_long_attempts(self):
        calls = []

        def hang(**kwargs):
            calls.append(kwargs)
            time.sleep(float(kwargs["connect_timeout"]))
            raise TimeoutError("origin slow")

        previous = connect_db.DATABASE_URI
        connect_db.DATABASE_URI = FAKE_URI
        connect_db.begin_request_db_budget(2.5)
        started = time.monotonic()
        try:
            with patch("pymysql.connect", side_effect=hang):
                for _ in range(5):
                    self.assertIsNone(connect_db.get_security_db())
        finally:
            connect_db.DATABASE_URI = previous
            connect_db.end_request_db_budget()
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 4.0)
        self.assertLessEqual(len(calls), 2)
        self.assertGreaterEqual(len(calls), 1)
        for kwargs in calls:
            self.assertLessEqual(kwargs["connect_timeout"], 3)
            self.assertLessEqual(kwargs["read_timeout"], 4)
            self.assertNotEqual(kwargs["connect_timeout"], 15)
            self.assertNotEqual(kwargs["read_timeout"], 35)

    def test_background_still_retries_when_no_request_is_armed(self):
        calls = []

        def fail(**kwargs):
            calls.append(kwargs)
            raise OSError("down")

        previous = connect_db.DATABASE_URI
        connect_db.DATABASE_URI = FAKE_URI
        connect_db.end_request_db_budget()
        try:
            with patch("pymysql.connect", side_effect=fail), patch.object(
                connect_db.time, "sleep"
            ):
                self.assertIsNone(connect_db.get_security_db())
        finally:
            connect_db.DATABASE_URI = previous
        self.assertEqual(len(calls), 4)
        self.assertEqual(calls[0]["connect_timeout"], 15)
        self.assertEqual(calls[0]["read_timeout"], 35)


class SharedSecurityConnectionTests(unittest.TestCase):
    def tearDown(self):
        connect_db.end_request_db_budget()

    def _fake(self, raws):
        class Fake:
            def __init__(self):
                self.closed = False
                raws.append(self)

            def cursor(self):
                return self

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def execute(self, *args, **kwargs):
                return None

            def fetchone(self):
                return {"ok": 1}

            def ping(self, reconnect=False):
                if self.closed:
                    raise RuntimeError("closed")

            def close(self):
                self.closed = True

            def rollback(self):
                return None

        return Fake

    def test_one_request_reuses_one_security_connection(self):
        raws = []
        previous = connect_db.DATABASE_URI
        connect_db.DATABASE_URI = FAKE_URI
        connect_db.begin_request_db_budget(8)
        try:
            with patch("pymysql.connect", side_effect=lambda **kwargs: self._fake(raws)()):
                first = connect_db.get_security_db()
                first.close()
                second = connect_db.get_security_db()
                connect_db.close_security_db(second)
            self.assertIs(first, second)
            self.assertEqual(len(raws), 1)
            self.assertFalse(raws[0].closed)
            connect_db.end_request_db_budget()
            self.assertTrue(raws[0].closed)
        finally:
            connect_db.DATABASE_URI = previous

    def test_background_connection_is_not_held(self):
        raws = []
        previous = connect_db.DATABASE_URI
        connect_db.DATABASE_URI = FAKE_URI
        connect_db.end_request_db_budget()
        try:
            with patch("pymysql.connect", side_effect=lambda **kwargs: self._fake(raws)()):
                db = connect_db.get_security_db()
            self.assertEqual(len(raws), 1)
            db.close()
            self.assertTrue(raws[0].closed)
            self.assertIs(db, raws[0])
        finally:
            connect_db.DATABASE_URI = previous


class DbGuardTests(unittest.TestCase):
    def tearDown(self):
        connect_db.end_request_db_budget()

    def test_free_guard_runs_the_log(self):
        @security.with_db_guard
        def write_log():
            return "logged"

        self.assertEqual(write_log(), "logged")

    def test_full_guard_skips_the_log_and_returns(self):
        held = 0
        while security._db_semaphore.acquire(blocking=False):
            held += 1
            if held > 1000:
                break
        previous_wait = security.DB_GUARD_ACQUIRE_SECONDS
        security.DB_GUARD_ACQUIRE_SECONDS = 0.05
        calls = []

        @security.with_db_guard
        def write_log():
            calls.append(1)
            return "logged"

        started = time.monotonic()
        try:
            self.assertGreater(held, 0)
            self.assertIsNone(write_log())
            self.assertEqual(calls, [])
            self.assertLess(time.monotonic() - started, 1.0)
        finally:
            security.DB_GUARD_ACQUIRE_SECONDS = previous_wait
            for _ in range(held):
                security._db_semaphore.release()

    def test_spent_budget_skips_before_waiting(self):
        connect_db.begin_request_db_budget(0)
        calls = []

        @security.with_db_guard
        def write_log():
            calls.append(1)
            return "logged"

        started = time.monotonic()
        self.assertIsNone(write_log())
        self.assertEqual(calls, [])
        self.assertLess(time.monotonic() - started, 0.5)

    def test_permanent_error_still_raises_and_releases_the_guard(self):
        @security.with_db_guard
        def write_log():
            raise RuntimeError("syntax error near")

        with self.assertRaises(RuntimeError):
            write_log()
        self.assertTrue(security._db_semaphore.acquire(blocking=False))
        security._db_semaphore.release()

    def test_retry_wait_does_not_hold_the_guard(self):
        seen_free = []

        def sleeper(_seconds):
            free = security._db_semaphore.acquire(blocking=False)
            seen_free.append(free)
            if free:
                security._db_semaphore.release()

        @security.with_db_guard
        def write_log():
            raise ConnectionError("MySQL server has gone away")

        with patch.object(security.time, "sleep", sleeper):
            self.assertIsNone(write_log())
        self.assertTrue(seen_free)
        self.assertTrue(all(seen_free))


class SecurityHookBudgetTests(unittest.TestCase):
    def tearDown(self):
        connect_db.end_request_db_budget()

    def test_before_request_arms_the_budget_and_teardown_clears_it(self):
        app = Flask(__name__)
        app.config["SECRET_KEY"] = "test"
        with patch.object(security, "run_full_security_pipeline", return_value=True):
            with app.test_request_context("/groceries/list", method="GET"):
                security.before_request_security()
                left = connect_db.request_db_seconds_left()
                self.assertIsNotNone(left)
                self.assertLess(left, connect_db.REQUEST_DB_BUDGET_SECONDS + 0.1)
                self.assertGreater(left, 5)
                security.teardown_security(None)
                self.assertIsNone(connect_db.request_db_seconds_left())

    def test_bot_teardown_return_still_clears_the_budget(self):
        app = Flask(__name__)
        app.config["SECRET_KEY"] = "test"
        with app.test_request_context("/api/v1/helper"):
            connect_db.begin_request_db_budget(8)
            g.pbt_bot_api = True
            security.teardown_security(None)
            self.assertIsNone(connect_db.request_db_seconds_left())

    def test_logged_in_rate_limit_return_still_clears_the_budget(self):
        app = Flask(__name__)
        app.config["SECRET_KEY"] = "test"
        with app.test_request_context("/groceries/list.json"):
            connect_db.begin_request_db_budget(8)
            g.rate_limited = True
            with patch.object(security, "_is_logged_in", return_value=True):
                security.teardown_security(None)
            self.assertIsNone(connect_db.request_db_seconds_left())


if __name__ == "__main__":
    unittest.main()
