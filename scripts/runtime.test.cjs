const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');const os=require('node:os');const path=require('node:path');
const {packagedEnvironment}=require('../desktop/electron/runtime.cjs');
test('packaged app uses its own Python, render binaries and offline model',()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'wetha-runtime-'));
 try {
  for(const file of ['bin/python3','tools/ffmpeg','tools/ffprobe','speech-model/config.json','speech-model/model.bin','speech-model/tokenizer.json','speech-model/vocabulary.txt']){
   const target=path.join(root,'backend-runtime',file);fs.mkdirSync(path.dirname(target),{recursive:true});fs.writeFileSync(target,'fixture');
  }
  const env=packagedEnvironment(root,'darwin',{PATH:'/developer/tools',Path:'/other/tools',PYTHONHOME:'/wrong',PYTHONPATH:'/wrong-packages',WETHA_SPEECH_MODEL_PATH:'/wrong-model'});
  assert.equal(env.PATH,path.join(root,'backend-runtime/tools')+path.delimiter+'/usr/bin:/bin');
  assert.equal(env.PYTHONHOME,path.join(root,'backend-runtime'));assert.equal(env.PYTHONPATH,undefined);assert.equal(env.Path,undefined);
  assert.equal(env.WETHA_SPEECH_MODEL_PATH,path.join(root,'backend-runtime/speech-model'));
  fs.unlinkSync(path.join(root,'backend-runtime/tools/ffprobe'));assert.throws(()=>packagedEnvironment(root,'darwin',{}),/incomplete/);
 } finally {fs.rmSync(root,{recursive:true,force:true});}
});
