import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from maintenance import cleanup as c


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=c.ROOT / 'maintenance')
        self.root = Path(self.tmp.name).resolve()
        self.backups = self.root / 'backups'
        self.backups.mkdir()
        self.patches = [patch.object(c, 'ROOT', self.root), patch.object(c, 'BACKUPS', self.backups)]
        for p in self.patches:
            p.start()
        self.report = {'deleted_backups': []}
        for i in range(4):
            (self.backups / f'labels_20261020T120000{i:06d}.csv').write_bytes(b'\xef\xbb\xbfimage,label\r\na,none\r\n')
        (self.backups / 'labels_before_review.csv').write_bytes(b'important')

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def test_archive_keep_special_verify_and_rerun(self):
        selected, retained, special = c.backup_plan(2)
        self.assertEqual((len(selected), len(retained), len(special)), (2, 2, 1))
        c.archive_backups(selected, 'fixture', self.report, lambda: None)
        archive = self.backups / 'archives/labels_archive_fixture.zip'
        self.assertEqual(len(c.verify_zip(archive)), 2)
        self.assertEqual(len(self.report['deleted_backups']), 2)
        self.assertTrue(special[0].exists())
        self.assertEqual(c.backup_plan(2)[0], [])
        with zipfile.ZipFile(archive) as z:
            row = json.loads(z.read('MANIFEST.json'))['files'][0]
            # Simulate interruption after ZIP verified but before CSV removed.
            (self.backups / row['name']).write_bytes(z.read(row['name']))
        c.archive_backups(c.backup_plan(2)[0], 'resume', self.report, lambda: None)
        self.assertEqual(len(list((self.backups / 'archives').glob('*.zip'))), 1)
        self.assertFalse((self.backups / row['name']).exists())

    def test_failed_verification_deletes_nothing(self):
        selected = c.backup_plan(2)[0]
        with patch.object(c, 'verify_zip', side_effect=ValueError('corrupt ZIP')):
            with self.assertRaises(ValueError):
                c.archive_backups(selected, 'bad', self.report, lambda: None)
        self.assertTrue(all(p.exists() for p in selected))
        self.assertEqual(self.report['deleted_backups'], [])

    def test_corrupt_member_detected(self):
        c.archive_backups(c.backup_plan(2)[0], 'fixture', self.report, lambda: None)
        archive = self.backups / 'archives/labels_archive_fixture.zip'
        with zipfile.ZipFile(archive) as z:
            members = {n: z.read(n) for n in z.namelist()}
        name = next(n for n in members if n.endswith('.csv'))
        members[name] = b'tampered'
        with zipfile.ZipFile(archive, 'w') as z:
            for n, data in members.items():
                z.writestr(n, data)
        with self.assertRaises(ValueError):
            c.verify_zip(archive)

    def test_containment_and_no_match_for_special_names(self):
        with self.assertRaises(ValueError):
            c.safe(self.root.parent / 'outside.csv')
        with self.assertRaises(ValueError):
            c.safe(self.root)
        self.assertFalse(c.AUTO.fullmatch('labels_20261020T120000000000_important.csv'))

    @unittest.skipUnless(c.os.name == 'nt', 'Windows handle check')
    def test_active_handle_prevents_cache_deletion(self):
        p = self.root / 'cache.bin'
        p.write_bytes(b'cache')
        with p.open('rb'):
            with self.assertRaises(OSError):
                c.idle_handles([p])
        handles, close = c.idle_handles([p])
        try:
            p.unlink()
        finally:
            for h in handles:
                close(h)
        self.assertFalse(p.exists())

    def test_shared_review_lock(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dataset_generate'))
        import waste_workflow as w
        with patch.object(w, 'WORK', self.root):
            with w.lock():
                with self.assertRaises(RuntimeError):
                    with w.lock():
                        self.fail('Concurrent lock unexpectedly acquired')
            self.assertFalse((self.root / '.workflow.lock').exists())

    def test_hardlinked_cache_is_retained(self):
        import os
        import time
        cache = self.root / 'cache'
        cache.mkdir()
        installed = self.root / 'installed.pyd'
        installed.write_bytes(b'synthetic installed module')
        os.utime(installed, (time.time() - 3600, time.time() - 3600))
        os.link(installed, cache / 'module.pyd')
        with patch.object(c, 'CACHES', ('cache',)), patch.object(c, 'processes', return_value=[]):
            plan = c.cache_plan()[0]
        self.assertFalse(plan['eligible'])
        self.assertIn('hardlinks', ' '.join(plan['reasons']))
        self.assertEqual(installed.read_bytes(), b'synthetic installed module')


if __name__ == '__main__':
    unittest.main()
