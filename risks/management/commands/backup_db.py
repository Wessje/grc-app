"""
Writes a dated backup copy of the database, e.g. backups/grc-2026-10-05-1400.db.

Run with: python manage.py backup_db

Uses SQLite's built-in backup feature, which takes a consistent copy even
while the app is running (a plain file copy could catch a half-written save).
The backups/ folder is excluded from git. Backups are not encrypted, so the
files are made readable by your Mac user account only; rely on FileVault for
disk encryption.

To restore a backup: stop the app (Ctrl + C), copy the backup file over
grc.db, and start the app again.
"""

import os
import sqlite3
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone

DEFAULT_BACKUP_FOLDER = settings.BASE_DIR / "backups"

# Owner may read and write; nobody else may do anything (like `chmod 600`).
OWNER_ONLY_FILE = 0o600
# Owner may open and list the folder; nobody else (like `chmod 700`).
OWNER_ONLY_FOLDER = 0o700


def backup_file_path(folder, now):
    """
    Choose the file name for a new backup.

    Inputs: the backup folder and the current local date and time.
    Output: a path like backups/grc-2026-10-05-1400.db. If a backup from the
    same minute already exists, "-2", "-3", … is added so it is never
    overwritten.
    """
    base_name = f"grc-{now:%Y-%m-%d-%H%M}"
    path = folder / f"{base_name}.db"
    counter = 2
    while path.exists():
        path = folder / f"{base_name}-{counter}.db"
        counter += 1
    return path


def check_backup_is_readable(path):
    """
    Open a backup and run SQLite's own integrity check on it.

    Input: the backup file path. Output: nothing if the file is sound;
    raises CommandError otherwise.
    """
    backup = sqlite3.connect(path)
    try:
        result = backup.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        backup.close()
    if result != "ok":
        raise CommandError(f"Backup {path} failed its integrity check: {result}")


class Command(BaseCommand):
    help = "Write a dated, consistent backup copy of the database to backups/."

    def add_arguments(self, parser):
        """Allow a different backup folder (used by the automated tests)."""
        parser.add_argument(
            "--folder", type=Path, default=DEFAULT_BACKUP_FOLDER,
            help="Folder to write the backup to (default: backups/).",
        )

    def handle(self, *args, **options):
        """Create the backup, check it, restrict its permissions and report where it is."""
        folder = options["folder"]
        folder.mkdir(parents=True, exist_ok=True)
        os.chmod(folder, OWNER_ONLY_FOLDER)

        path = backup_file_path(folder, timezone.localtime())

        # Copy through Django's own database connection, using SQLite's
        # backup feature.
        connection.ensure_connection()
        destination = sqlite3.connect(path)
        try:
            connection.connection.backup(destination)
        finally:
            destination.close()
        os.chmod(path, OWNER_ONLY_FILE)

        check_backup_is_readable(path)
        size_kb = path.stat().st_size / 1024
        self.stdout.write(self.style.SUCCESS(f"Backup written: {path} ({size_kb:.0f} KB)"))
