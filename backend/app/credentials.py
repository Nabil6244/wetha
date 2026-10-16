"""Footage provider API keys, stored privately in the app data folder.

Keys are written to credentials.json beside the database with owner-only permissions (0600). The data
folder lives outside the repository (or in the git-ignored .local/ folder during development). Keys are
never returned by the API, written to logs, or included in errors; only whether each one is set is
reported. An environment variable with the same name overrides the saved value.
"""
import json
import os
import re
import tempfile
from pathlib import Path

NAMES = {'pexels': 'PEXELS_API_KEY', 'pixabay': 'PIXABAY_API_KEY'}
SHAPE = re.compile(r'[A-Za-z0-9_-]{16,128}')


class Credentials:
    def __init__(self, folder):
        self.path = Path(folder) / 'credentials.json'

    def _read(self):
        try:
            return json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}

    def get(self, provider):
        name = NAMES[provider]
        return os.environ.get(name) or self._read().get(name) or None

    def status(self):
        saved = self._read()
        return {provider: {'configured': bool(os.environ.get(name) or saved.get(name)),
                           'source': 'environment' if os.environ.get(name) else 'saved in app' if saved.get(name) else None}
                for provider, name in NAMES.items()}

    def update(self, values):
        """Set (non-empty string) or clear (empty string) keys. Unknown or malformed keys are refused without echoing them."""
        saved = self._read()
        for provider, value in values.items():
            if provider not in NAMES or value is None:
                continue
            value = value.strip()
            if not value:
                saved.pop(NAMES[provider], None)
            elif not SHAPE.fullmatch(value):
                raise ValueError(f'That does not look like a {provider.capitalize()} API key (letters, numbers and dashes only).')
            else:
                saved[NAMES[provider]] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Write to an owner-only temporary file, then replace, so the file is never briefly world-readable.
        handle, temporary = tempfile.mkstemp(dir=self.path.parent, prefix='.credentials-')
        try:
            if hasattr(os, 'fchmod'):  # Not available on Windows, where the user's profile folder is already private.
                os.fchmod(handle, 0o600)
            with os.fdopen(handle, 'w') as output:
                json.dump(saved, output)
            os.replace(temporary, self.path)
        finally:
            try:
                os.close(handle)  # Already closed after a normal write; closing a leaked handle lets Windows delete the file.
            except OSError:
                pass
            if os.path.exists(temporary):
                os.unlink(temporary)
        return self.status()
