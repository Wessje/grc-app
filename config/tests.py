"""
Automated checks for the project-wide setup (Step 1 of docs/plan.md):
the .env reader, database name, user-account table, time zone and date format.

Run with: python manage.py test
"""

import datetime
import os
import runpy
import tempfile
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from django.utils.formats import date_format

from config.env import load_env_file, read_bool


class EnvFileTests(SimpleTestCase):
    """Checks that secret settings are read correctly from a .env file."""

    def write_env_file(self, contents):
        """Write `contents` to a temporary .env file and return its path."""
        folder = tempfile.mkdtemp()
        env_path = Path(folder) / ".env"
        env_path.write_text(contents)
        return env_path

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_reads_values_and_skips_comments_and_blank_lines(self):
        env_path = self.write_env_file(
            "# a comment\n\nSECRET_KEY=abc123\nDEBUG = true\nQUOTED=\"hello\"\n"
        )
        load_env_file(env_path)
        self.assertEqual(os.environ["SECRET_KEY"], "abc123")
        self.assertEqual(os.environ["DEBUG"], "true")
        self.assertEqual(os.environ["QUOTED"], "hello")
        self.assertNotIn("# a comment", os.environ)

    @mock.patch.dict(os.environ, {"SECRET_KEY": "from-terminal"}, clear=True)
    def test_existing_environment_value_is_not_overwritten(self):
        env_path = self.write_env_file("SECRET_KEY=from-file\n")
        load_env_file(env_path)
        self.assertEqual(os.environ["SECRET_KEY"], "from-terminal")

    def test_missing_file_is_ignored(self):
        load_env_file(Path(tempfile.mkdtemp()) / "does-not-exist")

    @mock.patch.dict(os.environ, {"FLAG": "TRUE", "TYPO": "ture"}, clear=True)
    def test_read_bool(self):
        self.assertTrue(read_bool("FLAG"))
        self.assertFalse(read_bool("TYPO"))
        self.assertFalse(read_bool("NOT_SET"))
        self.assertTrue(read_bool("NOT_SET", default=True))


class ProjectSettingsTests(TestCase):
    """Checks the project-wide settings chosen in Step 1."""

    def test_database_file_is_grc_db(self):
        # Must end in .db so .gitignore keeps it out of git. The settings file
        # is read afresh because tests run against a temporary in-memory
        # database, which replaces the name in the active settings.
        settings_file = runpy.run_path(str(settings.BASE_DIR / "config" / "settings.py"))
        database_name = Path(settings_file["DATABASES"]["default"]["NAME"]).name
        self.assertEqual(database_name, "grc.db")

    def test_custom_user_account_table_is_used(self):
        user = get_user_model().objects.create_user(username="w", password="x-Long-pw-123")
        self.assertEqual(user._meta.label, "accounts.User")

    def test_time_zone_is_amsterdam(self):
        self.assertEqual(settings.TIME_ZONE, "Europe/Amsterdam")
        # 12:00 UTC in October (summer time) is 14:00 in Amsterdam.
        moment = datetime.datetime(2026, 10, 5, 12, 0, tzinfo=datetime.UTC)
        self.assertEqual(timezone.localtime(moment).hour, 14)

    def test_dates_are_shown_day_month_year(self):
        self.assertEqual(date_format(datetime.date(2026, 10, 5)), "5 Oct 2026")
