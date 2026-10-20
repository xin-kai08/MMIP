"""Project-local, verified backup archival and conservative cache maintenance.

Default is dry-run. Only --apply permits deletion; no third-party dependencies.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BACKUPS = ROOT / 'dataset_generate/dataset_workflow/backups'
AUTO = re.compile(r'labels_\d{8}T\d{12}\.csv\Z')
CACHES = ('website/.cache/npm', 'website/.cache/uv',
          'website/.cache/browser', '.cache/browser')
FOCUS = ('dataset_generate/dataset_workflow/backups', 'website/.cache',
         'website/.tools', 'website/frontend/node_modules', 'website/frontend/dist',
         'training/runs')


def safe(path: Path) -> Path:
    """Resolve every component, rejecting links/reparse points, including junctions."""
    path = Path(os.path.abspath(path))
    if not path.is_relative_to(ROOT) or path == ROOT:
        raise ValueError(f'Outside project or project root: {path}')
    for node in (path, *path.parents):
        if node == ROOT:
            break
        if node.is_symlink() or node.is_junction():
            raise ValueError(f'Link/junction refused: {node}')
    resolved = path.resolve()
    if not resolved.is_relative_to(ROOT) or resolved == ROOT:
        raise ValueError(f'Resolved outside project: {resolved}')
    return resolved


def digest(path):
    with safe(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def write_json(path, data):
    safe(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def tree_files(folder):
    files = []
    for base, dirs, names in os.walk(safe(folder), followlinks=False):
        safe(Path(base))
        for name in dirs:
            safe(Path(base) / name)
        for name in names:
            p = Path(base) / name
            if p.is_symlink() or p.is_junction():
                raise ValueError(f'Linked file refused: {p}')
            files.append(p)
    return sorted(files)


def inventory():
    sizes, counts = {}, {}
    for base, dirs, names in os.walk(ROOT, followlinks=False):
        if Path(base) != ROOT:
            safe(Path(base))
        for name in dirs:
            safe(Path(base) / name)
        for name in names:
            p = Path(base) / name
            if p.is_symlink() or p.is_junction():
                raise ValueError(f'Linked file refused: {p}')
            rel = p.relative_to(ROOT).as_posix()
            keys = {rel.split('/')[0]} | {k for k in FOCUS if rel.startswith(k + '/')}
            n = p.stat().st_size
            for key in keys:
                sizes[key] = sizes.get(key, 0) + n
                counts[key] = counts.get(key, 0) + 1
    return {'bytes': sizes, 'files': counts,
            'total_bytes': sum(n for k, n in sizes.items() if '/' not in k),
            'volume_free_bytes': shutil.disk_usage(ROOT).free}


def protected_inventory():
    """Hash protected user/model/data files; environment and build outputs use metadata."""
    result = {}
    for folder in ('dataset', 'training', 'uploads', 'website/data',
                   'website/.cache/ui-test', '.venv', 'website/.tools',
                   'website/frontend/node_modules', 'website/frontend/dist', '.git'):
        p = ROOT / folder
        if not p.exists():
            continue
        for f in tree_files(p):
            # Imports can create pyc; these are not scientific/user artifacts.
            if '__pycache__' in f.parts:
                continue
            st = f.stat()
            record = {'bytes': st.st_size, 'mtime_ns': st.st_mtime_ns}
            if folder not in ('.venv', 'website/.tools', 'website/frontend/node_modules', '.git'):
                try:
                    record['sha256'] = digest(f)
                except PermissionError:
                    # Live backend worker locks are deliberately not readable.
                    # Retain them, compare metadata, and explicitly report the limit.
                    record['hash_unavailable'] = 'permission/active exclusive handle; retained'
            result[f.relative_to(ROOT).as_posix()] = record
    return result


def backup_plan(keep):
    safe(BACKUPS)
    automatic, special = [], []
    for p in sorted(BACKUPS.iterdir()):
        safe(p)
        if p.is_file() and p.suffix.lower() == '.csv':
            (automatic if AUTO.fullmatch(p.name) else special).append(p)
    return automatic[:-keep], automatic[-keep:], special


def verify_zip(path):
    """Read and SHA-256 every decompressed byte, not just the ZIP CRC directory."""
    with zipfile.ZipFile(safe(path)) as z:
        names = z.namelist()
        if len(names) != len(set(names)):
            raise ValueError(f'Duplicate ZIP member: {path}')
        manifest = json.loads(z.read('MANIFEST.json'))
        rows = manifest['files']
        expected = [r['name'] for r in rows]
        if len(expected) != len(set(expected)) or set(names) != set(expected + ['MANIFEST.json', 'SHA256SUMS.txt']):
            raise ValueError(f'ZIP member count mismatch: {path}')
        sums = ''.join(f"{r['sha256']}  {r['name']}\n" for r in rows)
        if z.read('SHA256SUMS.txt').decode('utf-8') != sums:
            raise ValueError('SHA256SUMS differs from manifest')
        for r in rows:
            if not AUTO.fullmatch(r['name']):
                raise ValueError('Nonautomatic backup in archive')
            with z.open(r['name']) as f:
                actual = hashlib.file_digest(f, 'sha256').hexdigest()
            if actual != r['sha256'] or z.getinfo(r['name']).file_size != r['bytes']:
                raise ValueError(f"Decompressed SHA/size mismatch: {r['name']}")
        return rows


def archive_backups(selected, run_id, report, save):
    if not selected:
        return
    archives = safe(BACKUPS / 'archives')
    archives.mkdir(exist_ok=True)
    wanted = {p.name: p for p in selected}
    covered = {}
    # Recover an interrupted run from its already-verified final ZIP; never rearchive.
    for archive in sorted(archives.glob('labels_archive_*.zip')):
        if archive.name.endswith('.partial.zip'):
            continue
        rows = verify_zip(archive)  # corrupt archive aborts before ANY source deletion
        for row in rows:
            if row['name'] in wanted:
                if digest(wanted[row['name']]) != row['sha256']:
                    raise ValueError(f"Previously archived filename changed: {row['name']}")
                covered[row['name']] = (row, archive)
    new = [p for p in selected if p.name not in covered]
    if new:
        rows = [{'name': p.name, 'bytes': p.stat().st_size, 'sha256': digest(p)} for p in new]
        partial = safe(archives / f'labels_archive_{run_id}.partial.zip')
        final = safe(archives / f'labels_archive_{run_id}.zip')
        manifest = {'schema_version': 1, 'created_utc': datetime.now(timezone.utc).isoformat(),
                    'source': BACKUPS.relative_to(ROOT).as_posix(), 'files': rows}
        with partial.open('xb') as output:
            with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
                z.writestr('MANIFEST.json', json.dumps(manifest, ensure_ascii=False, indent=2))
                z.writestr('SHA256SUMS.txt', ''.join(f"{r['sha256']}  {r['name']}\n" for r in rows))
                for i, p in enumerate(new, 1):
                    z.write(safe(p), p.name)
                    if i % 250 == 0:
                        print(f'Compressed {i}/{len(new)} backups; originals retained.', flush=True)
            output.flush()
            os.fsync(output.fileno())
        verify_zip(partial)
        print(f'ZIP decompressed SHA-256 verified: {len(rows)} files.', flush=True)
        # Windows rename refuses an existing destination (never replace).
        if final.exists():
            raise FileExistsError(final)
        partial.rename(final)
        for row in rows:
            covered[row['name']] = (row, final)
    report['archives'] = sorted({str(p.relative_to(ROOT)) for _, p in covered.values()})
    report['zip_verified_members'] = len(covered)
    # Recheck ALL source hashes after compression; no partial deletion on validation error.
    for p in selected:
        row, _ = covered[p.name]
        if p.stat().st_size != row['bytes'] or digest(p) != row['sha256']:
            raise ValueError(f'Source changed after archive: {p}')
    report['archive_validation'] = 'all_decompressed_SHA256_and_source_SHA256_passed'
    save()
    for p in selected:
        row, archive = covered[p.name]
        # Exact allowlist, canonical project containment, and final immediate hash check.
        p = safe(p)
        if p.parent != safe(BACKUPS) or not AUTO.fullmatch(p.name) or digest(p) != row['sha256']:
            raise ValueError(f'Unsafe/changed deletion target: {p}')
        p.unlink()
        report['deleted_backups'].append({'path': str(p.relative_to(ROOT)), **row,
                                         'archive': str(archive.relative_to(ROOT))})
    save()


def processes():
    if os.name != 'nt':
        raise RuntimeError('Cache checks currently require Windows process/handle checks')
    command = ('Get-CimInstance Win32_Process -ErrorAction Stop | '
               'Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress')
    p = subprocess.run(['powershell.exe', '-NoProfile', '-Command', command],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    if p.returncode:
        raise RuntimeError('Process query denied; caches will be retained')
    return json.loads(p.stdout)


def idle_handles(files):
    """Hold read handles denying other readers/writers; allow our exact unlink only."""
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    held = []
    try:
        for p in files:
            # GENERIC_READ, FILE_SHARE_DELETE only, OPEN_EXISTING, normal attribute.
            h = create(str(safe(p)), 0x80000000, 4, None, 3, 0x80, None)
            if h == ctypes.c_void_p(-1).value:
                raise OSError(ctypes.get_last_error(), f'In use or inaccessible: {p}')
            held.append(h)
        return held, close
    except BaseException:
        for h in held:
            close(h)
        raise


def cache_plan():
    proc = processes()
    result = []
    own = {os.getpid(), os.getppid()}
    for rel in CACHES:
        folder = safe(ROOT / rel)
        if not folder.exists():
            continue
        files = tree_files(folder)
        reasons = []
        for p in proc:
            if p['ProcessId'] in own:
                continue
            command = (p.get('CommandLine') or '').lower().replace('/', '\\')
            name = (p.get('Name') or '').lower()
            # Any installer/browser referring to this cache blocks it; uv/npm installs
            # are conservative global blockers even if the cache path was implicit.
            if str(folder).lower() in command or (name in ('uv.exe', 'npm.exe', 'npm.cmd') or
                    (name == 'node.exe' and ('npm-cli' in command or 'verify_browser' in command))):
                reasons.append(f"active process {p['ProcessId']} ({name})")
        if any(time.time() - p.stat().st_mtime < 600 for p in files):
            reasons.append('files modified in last 10 minutes')
        if any(p.suffix.lower() in ('.sqlite', '.sqlite3', '.db') for p in files):
            reasons.append('database inside candidate: retain')
        if any(p.stat().st_nlink > 1 for p in files):
            # uv cache wheels can share NTFS file identities with the live venv.
            # DLL mapping is not reliably detectable with a normal open probe.
            reasons.append('hardlinks to other files (possibly live environment): retain')
        if not reasons:
            try:
                handles, close = idle_handles(files)
                for h in handles:
                    close(h)
            except OSError as e:
                reasons.append(str(e))
        result.append({'path': rel, 'eligible': not reasons, 'reasons': reasons,
                       'files': [{'path': p.relative_to(ROOT).as_posix(),
                                  'bytes': p.stat().st_size, 'mtime_ns': p.stat().st_mtime_ns,
                                  'sha256': digest(p)} for p in files] if not reasons else [],
                       'file_count': len(files), 'bytes': sum(p.stat().st_size for p in files)})
    return result


def clear_caches(plans, report, save):
    if not plans:
        return
    fresh = {p['path']: p for p in cache_plan()}
    for plan in plans:
        current = fresh.get(plan['path'])
        if not plan['eligible'] or not current or not current['eligible'] or current['files'] != plan['files']:
            report['cache_skipped'].append({'path': plan['path'], 'reason': 'in use, changed, or not eligible'})
            continue
        folder = safe(ROOT / plan['path'])
        if plan['path'] not in CACHES:
            raise ValueError('Not a rebuildable cache allowlist entry')
        files = [safe(ROOT / f['path']) for f in plan['files']]
        # Hold every file open against reads/writes until unlink completes.
        try:
            held, close = idle_handles(files)
        except OSError as e:
            report['cache_skipped'].append({'path': plan['path'], 'reason': str(e)})
            continue
        try:
            for p, row in zip(files, plan['files']):
                if not p.is_relative_to(folder) or p.stat().st_mtime_ns != row['mtime_ns']:
                    raise ValueError('Cache changed after planning')
            for p, row in zip(files, plan['files']):
                try:
                    safe(p).unlink()
                except PermissionError as e:
                    # A mapped DLL or a late-arriving OS lock must never be forced.
                    report['cache_skipped'].append({'path': row['path'], 'reason': str(e)})
                    continue
                report['deleted_cache_files'].append(row)
        finally:
            for h in held:
                close(h)
            save()
        # Leave empty directories/cache roots; never recursively delete a live tree.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='actually archive/delete; otherwise dry-run')
    parser.add_argument('--keep', type=int, default=20)
    parser.add_argument('--caches', action='store_true', help='inspect/reclaim known idle caches too')
    parser.add_argument('--verify', type=Path, help='verify an archive without deleting/restoring files')
    args = parser.parse_args()
    if args.keep < 1:
        parser.error('--keep must be >= 1')
    if args.verify:
        rows = verify_zip(args.verify)
        print(json.dumps({'verified_files': len(rows), 'archive': str(args.verify)}))
        return
    sys.path.insert(0, str(ROOT / 'dataset_generate'))
    from waste_workflow import lock
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '_' + uuid.uuid4().hex[:8]
    reports = safe(ROOT / 'maintenance/reports')
    reports.mkdir(parents=True, exist_ok=True)
    report_path = reports / f'cleanup_{run_id}.json'
    report = {'run_id': run_id, 'apply': args.apply, 'keep': args.keep,
              'deleted_backups': [], 'deleted_cache_files': [], 'cache_skipped': [],
              'status': 'planning'}
    def save():
        write_json(report_path, report)
    # Same O_EXCL lock as the review UI; never remove someone else's lock.
    with lock():
        report['before'] = inventory()
        protected = protected_inventory()
        selected, retained, special = backup_plan(args.keep)
        report['backup_plan'] = {'archive_names': [p.name for p in selected],
                                 'retained_auto': [p.name for p in retained],
                                 'retained_special': [p.name for p in special]}
        report['cache_plan'] = []
        if args.caches:
            try:
                report['cache_plan'] = cache_plan()
            except Exception as e:
                report['cache_skipped'].append({'path': 'all', 'reason': str(e)})
        report['protected_before'] = protected
        save()
        try:
            if args.apply:
                report['status'] = 'applying'
                save()
                archive_backups(selected, run_id, report, save)
                clear_caches(report['cache_plan'], report, save)
            after_protected = protected_inventory()
            report['protected_changes'] = [p for p in sorted(protected.keys() | after_protected.keys())
                                           if protected.get(p) != after_protected.get(p)]
            report['after'] = inventory()
            report['net_logical_bytes_reclaimed'] = report['before']['total_bytes'] - report['after']['total_bytes']
            report['volume_free_delta_bytes'] = report['after']['volume_free_bytes'] - report['before']['volume_free_bytes']
            report['status'] = 'completed' if args.apply else 'dry_run'
        except BaseException as e:
            report['status'] = 'failed_originals_retained_unless_already_verified'
            report['error'] = repr(e)
            raise
        finally:
            save()
    print(json.dumps({'report': str(report_path), 'status': report['status'],
                      'backup_candidates': len(selected), 'deleted_backups': len(report['deleted_backups']),
                      'deleted_cache_files': len(report['deleted_cache_files']),
                      'net_logical_bytes_reclaimed': report.get('net_logical_bytes_reclaimed'),
                      'protected_changes': report.get('protected_changes')}, indent=2))


if __name__ == '__main__':
    main()
