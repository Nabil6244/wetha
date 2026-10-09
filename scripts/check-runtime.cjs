const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const root = path.resolve(__dirname, '..');
const requested = process.argv[2] || process.platform;
if (requested !== process.platform) {
  console.error('Build on the target OS with a matching Python runtime. Cross-built installers have not been validated.');
  process.exit(1);
}
const python = path.join(root, 'backend-runtime', process.platform === 'win32' ? 'python.exe' : 'bin/python3');
if (!fs.existsSync(python)) {
  console.error('Packaging requires a redistributable, platform-native Python runtime at backend-runtime/ with dependencies from backend/requirements.lock. See docs/PACKAGING.md.');
  process.exit(1);
}
const check = spawnSync(python, ['-c', 'import fastapi,uvicorn,httpx,platformdirs,sqlite3; print("Backend runtime available")'], { stdio: 'inherit' });
process.exit(check.status ?? 1);
