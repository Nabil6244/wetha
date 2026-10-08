const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const python = process.env.WETHA_PYTHON || path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
if (!fs.existsSync(python)) {
  console.error('Python environment missing. Run the setup steps in README.md or set WETHA_PYTHON.');
  process.exit(1);
}
const testing = process.argv[2] === 'test';
const args = testing ? ['-m', 'pytest', 'tests', '-q'] : ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000'];
const child = spawn(python, args, { cwd: path.join(root, 'backend'), stdio: 'inherit', env: { ...process.env, WETHA_DATA_DIR: process.env.WETHA_DATA_DIR || path.join(root, '.local', 'data') } });
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill(signal));
child.on('error', error => { console.error(error.message); process.exitCode = 1; });
child.on('exit', (code) => { process.exitCode = code ?? 1; });
