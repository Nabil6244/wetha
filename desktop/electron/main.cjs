const { app, BrowserWindow, dialog, shell } = require('electron');
const { spawn } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');
const net = require('node:net');
let backend;
let quitting = false;

function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.on('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const port = server.address().port;
      server.close(() => resolve(port));
    });
  });
}

async function startBackend() {
  const root = app.isPackaged ? process.resourcesPath : path.resolve(__dirname, '../..');
  const python = app.isPackaged
    ? path.join(root, 'backend-runtime', process.platform === 'win32' ? 'python.exe' : 'bin/python3')
    : process.env.WETHA_PYTHON || path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  if (!fs.existsSync(python)) throw new Error('Python runtime is missing. Follow README.md for development setup. Packaged apps require a platform-native backend-runtime bundle.');
  const port = await freePort();
  const endpoint = `http://127.0.0.1:${port}`;
  // The backend origin guard needs the chosen loopback origin too.
  backend = spawn(python, ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(port)], {
    cwd: path.join(root, 'backend'), env: { ...process.env, WETHA_DATA_DIR: path.join(app.getPath('userData'), 'data'), WETHA_UI_DIR: path.join(root, app.isPackaged ? 'ui' : 'dist'), WETHA_DESKTOP_ORIGIN: endpoint },
    stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true,
  });
  const log = fs.createWriteStream(path.join(app.getPath('userData'), 'backend.log'), { flags: 'a' });
  backend.stdout.pipe(log); backend.stderr.pipe(log);
  let startupError;
  backend.on('error', error => { startupError = error; });
  backend.on('exit', code => { if (!quitting && code !== 0) dialog.showErrorBox('Backend stopped', 'The local service stopped. Restart the application and inspect backend.log.'); });
  for (let attempt = 0; attempt < 80; attempt++) {
    if (startupError) throw startupError;
    if (backend.exitCode !== null) throw new Error('Backend failed to start. Inspect backend.log in application data.');
    try {
      const result = await fetch(`${endpoint}/api/health`, { signal: AbortSignal.timeout(500) });
      if (result.ok) return endpoint;
    } catch {}
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  throw new Error('Backend did not become ready within 20 seconds.');
}

async function launch() {
  const endpoint = await startBackend();
  const win = new BrowserWindow({ width: 1500, height: 960, minWidth: 1000, minHeight: 700, backgroundColor: '#0b1118', title: 'Weather Intelligence Studio',
    webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true } });
  const uiURL = endpoint;
  win.webContents.setWindowOpenHandler(({ url }) => {
    const target = new URL(url);
    if (target.protocol === 'https:' && ['www.nhc.noaa.gov', 'api.weather.gov', 'www.weather.gov', 'www.star.nesdis.noaa.gov'].includes(target.hostname)) shell.openExternal(url);
    return { action: 'deny' };
  });
  win.webContents.on('will-navigate', (event, url) => { if (new URL(url).origin !== uiURL) event.preventDefault(); });
  await win.loadURL(uiURL);
}

if (!app.requestSingleInstanceLock()) app.quit();
else app.whenReady().then(launch).catch(error => { dialog.showErrorBox('Startup failed', error.message); app.quit(); });
app.on('before-quit', () => { quitting = true; if (backend) backend.kill(); });
app.on('window-all-closed', () => app.quit());
