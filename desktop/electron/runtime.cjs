const fs = require('node:fs');
const path = require('node:path');
function packagedEnvironment(root, platform, inherited) {
  const runtime = path.join(root,'backend-runtime');
  const tools = path.join(runtime,'tools');
  const required = [platform==='win32'?'python.exe':'bin/python3',
    ...['ffmpeg','ffprobe'].map(name=>'tools/'+name+(platform==='win32'?'.exe':'')),
    ...['config.json','model.bin','tokenizer.json','vocabulary.txt'].map(name=>'speech-model/'+name)];
  if(required.some(file=>!fs.existsSync(path.join(runtime,file))))
    throw new Error('This app bundle is incomplete. Re-download the complete application.');
  const environment={...inherited};
  for(const key of Object.keys(environment))
    if(['PATH','PYTHONHOME','PYTHONPATH','WETHA_SPEECH_CACHE','WETHA_SPEECH_MODEL_PATH'].includes(key.toUpperCase()))delete environment[key];
  environment.PATH=tools+path.delimiter+(platform==='win32'?path.join(inherited.SystemRoot||'C:\\Windows','System32'):'/usr/bin:/bin');
  environment.PYTHONHOME=runtime;environment.PYTHONNOUSERSITE='1';
  environment.WETHA_SPEECH_MODEL_PATH=path.join(runtime,'speech-model');
  environment.WETHA_PACKAGED='1';
  return environment;
}
module.exports={packagedEnvironment};
