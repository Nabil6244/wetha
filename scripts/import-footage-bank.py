#!/usr/bin/env python3
"""Validate and import the reviewed local footage bank into a running app."""
import argparse, hashlib, json, sys
from pathlib import Path
from urllib.parse import quote, urlsplit
import httpx
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.contracts import MediaImportMetadata, MediaCatalogRequest
from app.production import probe


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api', required=True, help='Running local backend URL, e.g. http://127.0.0.1:57070')
    parser.add_argument('--catalog', type=Path, default=ROOT / 'docs/FLORIDA_FOOTAGE_BANK.json')
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    url = urlsplit(args.api)
    if url.scheme != 'http' or url.hostname != '127.0.0.1' or not url.port or url.path not in ('', '/') or url.username or url.password or url.query or url.fragment:
        parser.error('--api must be an HTTP loopback URL with an explicit port')
    bank = json.loads(args.catalog.read_text())
    ready = []
    # Validate every byte and contract before making any changes.
    for asset in bank['assets']:
        path = (ROOT / asset['path']).resolve()
        if not path.is_relative_to(ROOT / '.local'):
            raise ValueError('Footage must be in the project .local directory')
        if path.stat().st_size > 250 * 1048576:
            raise ValueError(f'{path.name}: exceeds import limit')
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != asset['checksum']:
            raise ValueError(f'{path.name}: checksum changed')
        metadata = MediaImportMetadata.model_validate(asset['metadata'])
        catalog = MediaCatalogRequest.model_validate(asset['catalog'])
        info = probe(path)
        duration = float(info['format']['duration'])
        for shot in asset['shots']:
            if not 0 <= shot['start'] < shot['start'] + shot['seconds'] <= duration or not 3 <= shot['seconds'] <= 4:
                raise ValueError(f'{path.name}: invalid short cut')
        ready.append((asset, path, metadata, catalog))
    if args.check_only:
        print(f'Validated {len(ready)} files and {sum(len(a[0]["shots"]) for a in ready)} cut ranges')
        return
    result = []
    with httpx.Client(base_url=args.api.rstrip('/'), timeout=120, trust_env=False) as client:
        for asset, path, metadata, catalog in ready:
            with path.open('rb') as data:
                response = client.post('/api/production/media', content=data,
                    headers={'Content-Type': 'application/octet-stream', 'X-Media-Metadata': quote(metadata.model_dump_json())})
            response.raise_for_status()
            media = response.json()
            response = client.put(f'/api/production/media/{media["id"]}/catalog', json=catalog.model_dump(mode='json'))
            response.raise_for_status()
            result.append({'source_id': asset['id'], 'media_id': media['id'], 'duplicate': media.get('duplicate', False)})
            print(asset['id'], media['id'], flush=True)
    output = ROOT / '.local/footage-expansion/import-result.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
