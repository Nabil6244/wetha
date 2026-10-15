const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawnSync } = require('node:child_process');
const root = path.resolve(__dirname, '..');
const requested = process.argv[2] || process.platform;
function fail(message) {console.error(message);process.exit(1);}
if (requested !== process.platform) fail('Build on the target OS with its native runtime. Use the Windows packaging workflow for a Windows EXE.');
const runtime = path.join(root, 'backend-runtime');
const python = path.join(runtime, process.platform === 'win32' ? 'python.exe' : 'bin/python3');
const manifestPath = path.join(runtime,'bundle-manifest.json');
if (!fs.existsSync(python) || !fs.existsSync(manifestPath)) fail('Standalone runtime is missing. Run scripts/prepare-standalone.py on this platform first.');
const manifest=JSON.parse(fs.readFileSync(manifestPath,'utf8'));
if(manifest.platform!==`${process.platform}-${process.arch}`) fail('The bundled runtime architecture does not match this Electron build.');
for(const [relative,digest] of Object.entries(manifest.files)) {
  const file=path.join(runtime,relative);
  if(!fs.existsSync(file)||crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')!==digest)fail('Bundled component missing or changed: '+relative);
}
if(process.platform==='win32')for(const name of ['msvcp140.dll','vcruntime140.dll','vcruntime140_1.dll'])if(!fs.existsSync(path.join(runtime,name)))fail('App-local Windows C++ runtime is incomplete: '+name);
for(const name of ['ffmpeg','ffprobe']) {
  const executable=path.join(runtime,'tools',name+(process.platform==='win32'?'.exe':''));
  const result=spawnSync(executable,['-version'],{encoding:'utf8'});
  if(result.status!==0)fail('Bundled '+name+' cannot run on this platform.');
}
for(const name of ['config.json','model.bin','tokenizer.json','vocabulary.txt'])if(!fs.existsSync(path.join(runtime,'speech-model',name)))fail('Bundled speech model is incomplete: '+name);
const env={...process.env,PYTHONNOUSERSITE:'1',PYTHONHOME:runtime};delete env.PYTHONPATH;
const check=spawnSync(python,['-c','import fastapi,uvicorn,httpx,platformdirs,sqlite3; from PIL import Image; import av,ctranslate2,faster_whisper,onnxruntime; print("Standalone backend, rendering tools and speech model available")'],{env,stdio:'inherit'});
process.exit(check.status??1);
