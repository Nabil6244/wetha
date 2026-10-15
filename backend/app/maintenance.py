"""Conservative cleanup of regenerable files; project records and exports are never candidates."""
import os
import re
import shutil
import time
from pathlib import Path

CACHE_FILE = re.compile(r'(?:scene|body|fade)-\d+\.mp4|mix\.wav|voice\.wav|bed\.wav|effects\.wav|concat\.txt')
CACHE_DIR = re.compile(r'frames-\d+')


def files_under(root):
    if not root.exists() or root.is_symlink():
        return
    for base, directories, files in os.walk(root, followlinks=False):
        directories[:] = [d for d in directories if not (Path(base) / d).is_symlink()]
        for name in files:
            path = Path(base) / name
            if path.is_file() and not path.is_symlink():
                yield path


def cache_files(store):
    root = store.path.parent / 'production' / 'renders'
    if root.is_symlink() or not root.exists() or not root.resolve().is_relative_to(store.path.parent.resolve()):
        return
    with store.connection() as conn:
        terminal = {r['id'] for r in conn.execute("SELECT id FROM production_renders WHERE status NOT IN ('queued','running')")}
    for identity in terminal:
        # IDs are data, never accepted as filesystem paths.
        if not re.fullmatch(r'[a-zA-Z0-9-]+', identity):
            continue
        directory = root / identity
        if directory.is_symlink() or not directory.is_dir():
            continue
        for child in directory.iterdir():
            if child.is_symlink():
                continue
            if child.is_file() and CACHE_FILE.fullmatch(child.name):
                yield child
            elif child.is_dir() and CACHE_DIR.fullmatch(child.name):
                yield from files_under(child)


def temporary_files(store):
    # An interrupted import's temporary file; completed library files have no .upload marker.
    cutoff = time.time() - 86400
    for path in files_under(store.path.parent / 'production' / 'media'):
        if '.upload.' in path.name and path.stat().st_mtime < cutoff:
            yield path
    for path in files_under(store.path.parent / 'production' / 'observations'):
        if path.suffix == '.part' and path.stat().st_mtime < cutoff:
            yield path


def summary(store):
    base = store.path.parent
    sizes = {}
    for folder in ('media', 'renders', 'observations', 'storyboards', 'quarantine'):
        sizes[folder] = sum(p.stat().st_size for p in files_under(base / 'production' / folder))
    sizes['manual_footage'] = sum(p.stat().st_size for p in files_under(base / 'manual-footage'))
    sizes['alignment'] = sum(p.stat().st_size for p in files_under(base / 'alignments'))
    sizes['database'] = sum(p.stat().st_size for p in (store.path, Path(str(store.path)+'-wal'), Path(str(store.path)+'-shm')) if p.exists())
    with store.connection() as conn:
        cached = conn.execute('SELECT coalesce(sum(length(CAST(body AS BLOB))),0) FROM http_cache').fetchone()[0]
        assets = conn.execute('SELECT coalesce(sum(length(body)),0) FROM visual_assets').fetchone()[0]
        reclaimable = conn.execute('PRAGMA freelist_count').fetchone()[0] * conn.execute('PRAGMA page_size').fetchone()[0]
    return {'categories': sizes, 'total_bytes': sum(sizes.values()), 'scene_cache_bytes': sum(p.stat().st_size for p in cache_files(store)),
            'temporary_bytes': sum(p.stat().st_size for p in temporary_files(store)), 'response_cache_bytes': cached,
            'weather_asset_bytes': assets, 'database_reclaimable_bytes': reclaimable, 'free_bytes': shutil.disk_usage(base).free,
            'data_directory': str(base), 'retention_days': 30}


def cleanup(store, kind, older_than_days=0):
    if kind not in ('scene_cache', 'temporary', 'source_responses', 'compact'):
        raise ValueError('Unknown storage cleanup option.')
    removed = size = 0
    if kind in ('scene_cache', 'temporary'):
        paths = cache_files(store) if kind == 'scene_cache' else temporary_files(store)
        cutoff = time.time() - older_than_days * 86400
        for path in paths:
            try:
                if not path.resolve().is_relative_to(store.path.parent.resolve()):
                    continue
                info = path.stat()
                if info.st_mtime > cutoff:
                    continue
                path.unlink();removed += 1;size += info.st_size
            except FileNotFoundError:
                pass
    elif kind == 'source_responses':
        with store.connection() as conn:
            size = conn.execute('SELECT coalesce(sum(length(CAST(body AS BLOB))),0) FROM http_cache').fetchone()[0]
            removed = conn.execute('SELECT count(*) FROM http_cache').fetchone()[0]
            conn.execute('DELETE FROM http_cache')
    else:
        # VACUUM cannot run within a transaction; SQLite holds its own exclusive writer lock.
        before = store.path.stat().st_size
        with store.connection() as conn:
            conn.execute('VACUUM')
            conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        size = max(0, before - store.path.stat().st_size)
    return {'removed_files': removed, 'reclaimed_bytes': size, 'kind': kind}
