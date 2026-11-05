"""Exercise recovery on disposable database files and test the rollback boundary."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from fs_checks import database_notice
from release_manager import Store, atomic
from support_tools import bundle, destination, fresh_start


class SupportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.database = self.home / 'traffic.db'
        self.support = self.home / 'support'

    def test_latest_failed_database_replaces_previous_and_is_optional(self):
        for contents in (b'first damaged database', b'second damaged database'):
            self.database.write_bytes(contents)
            database_notice(self.database).touch()
            fresh_start(self.database, self.support)
            self.assertFalse(self.database.exists())
            self.assertFalse(database_notice(self.database).exists())
        with ZipFile(self.support / 'latest-damaged.zip') as archive:
            self.assertEqual(archive.read('traffic.db'), b'second damaged database')
        with ZipFile(bundle(self.home)) as archive:
            self.assertNotIn('latest-damaged.zip', archive.namelist())
        with ZipFile(bundle(self.home, include_database=True)) as archive:
            self.assertIn('latest-damaged.zip', archive.namelist())

    def test_stale_notice_does_not_reset_healthy_database(self):
        with sqlite3.connect(self.database) as connection:
            connection.execute('CREATE TABLE traffic(id INTEGER)')
        database_notice(self.database).touch()
        with self.assertRaises(ValueError):
            fresh_start(self.database, self.support)
        self.assertTrue(self.database.exists())

    def test_rollback_requires_matching_architecture_and_is_one_way(self):
        store = Store(self.home)
        atomic(store.state_path, dict(current='new', previous='old', trial=None))
        atomic(store.release('old') / 'VERSION.json', {'data_architecture': 1})
        atomic(store.release('new') / 'VERSION.json', {'data_architecture': 2})
        with self.assertRaises(ValueError):
            store.rollback()
        self.assertEqual(store.state()['current'], 'new')
        atomic(store.release('new') / 'VERSION.json', {'data_architecture': 1})
        self.assertEqual(store.rollback()['current'], 'old')
        self.assertIsNone(store.rollback_target())

    def test_destination_rejects_batch_commands(self):
        self.assertEqual(destination('support@example.com:/incoming'),
                         'support@example.com:/incoming')
        with self.assertRaises(ValueError):
            destination('support@example.com:/incoming\nput secrets')
