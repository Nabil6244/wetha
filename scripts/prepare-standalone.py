#!/usr/bin/env python3
"""Build-time only: provision verified, relocatable native runtime resources."""
import argparse, hashlib, json, os, platform, shutil, subprocess, sys, tarfile, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / '.local' / 'standalone-downloads'
SOURCES = json.loads((ROOT/'scripts/standalone-sources.json').read_text())

def fetch(row, name):
    CACHE.mkdir(parents=True, exist_ok=True)
    target=CACHE/name
    if not target.exists() or hashlib.file_digest(target.open('rb'),'sha256').hexdigest()!=row['sha256']:
        part=target.with_suffix('.part')
        print('Downloading',name,flush=True)
        with urllib.request.urlopen(urllib.request.Request(row['url'],headers={'User-Agent':'WeatherIntelligenceStudio-Packaging'}),timeout=120) as source, part.open('wb') as output:
            shutil.copyfileobj(source,output)
        if hashlib.file_digest(part.open('rb'),'sha256').hexdigest()!=row['sha256']:
            part.unlink();raise RuntimeError('Checksum mismatch: '+name)
        part.replace(target)
    return target

def bundle_windows_crt(runtime):
    """Use app-local redistributable DLLs, never require a recipient-side installer."""
    if sys.platform!='win32':return []
    vswhere=Path(os.environ.get('ProgramFiles(x86)','C:/Program Files (x86)'))/'Microsoft Visual Studio/Installer/vswhere.exe'
    if not vswhere.exists():raise RuntimeError('Windows packaging needs Visual Studio redistributable files on the build host. GitHub Windows runners provide these; recipients do not install them.')
    installation=Path(subprocess.check_output([str(vswhere),'-latest','-products','*','-property','installationPath'],text=True).strip())
    redist=installation/'VC/Redist/MSVC'
    versions=sorted((v for v in redist.iterdir() if v.is_dir() and v.name[:1].isdigit()),key=lambda v:tuple(int(n) for n in v.name.split('.')))
    if not versions:raise RuntimeError('Visual Studio redistributable directory is empty.')
    root=versions[-1]/'x64'
    dlls=list(root.glob('Microsoft.VC*.CRT/*.dll'))+list(root.glob('Microsoft.VC*.OpenMP/*.dll'))
    if not any(d.name.lower()=='msvcp140.dll' for d in dlls):raise RuntimeError('App-local MSVC C++ runtime is missing.')
    records=[]
    for source in dlls:
        quoted=str(source).replace("'","''")
        command="$s=Get-AuthenticodeSignature -LiteralPath '"+quoted+"'; if($s.Status -ne 'Valid' -or $s.SignerCertificate.Subject -notmatch 'Microsoft'){exit 1}"
        shell=shutil.which('pwsh') or shutil.which('powershell.exe')
        if not shell:raise RuntimeError('PowerShell is required to verify Microsoft runtime signatures.')
        shell_env=os.environ.copy();shell_env.pop('PSModulePath',None)
        subprocess.run([shell,'-NoProfile','-NonInteractive','-Command',command],env=shell_env,check=True)
        shutil.copy2(source,runtime/source.name)
        records.append({'file':source.name,'version':versions[-1].name,'source':'Visual Studio app-local redistributables','sha256':hashlib.file_digest(source.open('rb'),'sha256').hexdigest()})
    notices=runtime/'notices'
    for license_file in [redist/'REDIST.txt',installation/'License.rtf',installation/'license.txt']:
        if license_file.exists():shutil.copy2(license_file,notices/('VisualStudio-'+license_file.name))
    (notices/'VisualStudio-runtime.txt').write_text('App-local Microsoft C++ runtime DLLs copied from the licensed Visual Studio build environment. No separate redistributable installer is run on recipient computers. Source/deployment documentation: https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files\n')
    return records

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--refresh',action='store_true');args=parser.parse_args()
    system='win32' if sys.platform=='win32' else 'darwin' if sys.platform=='darwin' else sys.platform
    machine=platform.machine().lower();arch='arm64' if machine in ('arm64','aarch64') else 'x64' if machine in ('amd64','x86_64') else machine
    key=system+'-'+arch
    if key not in SOURCES:raise SystemExit('Unsupported native build platform: '+key)
    destination=ROOT/'backend-runtime'
    if destination.exists() and not args.refresh:
        print('Runtime already present. Use --refresh to explicitly replace the generated bundle.');return
    stage=ROOT/'.local'/('standalone-stage-'+key)
    if stage.exists():shutil.rmtree(stage)
    stage.mkdir(parents=True)
    rows=SOURCES[key]
    archive=fetch(rows['python'],key+'-python.tar.gz')
    with tarfile.open(archive,'r:gz') as tar:tar.extractall(stage,filter='data')
    runtime=stage/'python'
    tools=runtime/'tools';tools.mkdir()
    notices=runtime/'notices';notices.mkdir()
    for executable in ('ffmpeg','ffprobe'):
        downloaded=fetch(rows[executable],key+'-'+executable)
        target=tools/(executable+'.exe' if system=='win32' else executable)
        shutil.copy2(downloaded,target);target.chmod(0o755)
    for field in ('ffmpeg_license','ffmpeg_readme'):
        shutil.copy2(fetch(rows[field],key+'-'+field),notices/(field+'.txt'))
    model=runtime/'speech-model';model.mkdir()
    existing=ROOT/'.local/speech-model/models--Systran--faster-whisper-base.en/snapshots'/SOURCES['speech_model']['revision']
    for name,row in SOURCES['speech_model']['files'].items():
        local=existing/name
        if local.exists() and hashlib.file_digest(local.open('rb'),'sha256').hexdigest()==row['sha256']:source=local
        else:source=fetch(row,'speech-'+name)
        shutil.copy2(source,model/name)
    native_crt=bundle_windows_crt(runtime)
    python=runtime/('python.exe' if system=='win32' else 'bin/python3')
    environment={**os.environ,'PYTHONNOUSERSITE':'1','PIP_DISABLE_PIP_VERSION_CHECK':'1','PIP_NO_INPUT':'1'}
    environment.pop('PYTHONHOME',None);environment.pop('PYTHONPATH',None)
    subprocess.run([str(python),'-m','pip','install','--require-hashes','--only-binary=:all:','-r',str(ROOT/'backend/requirements-standalone.lock')],env=environment,check=True)
    manifest={'platform':key,'windows_native_runtime':native_crt,'sources':rows,'speech_model':SOURCES['speech_model'],'files':{}}
    for p in list(tools.iterdir())+list(model.iterdir())+list(runtime.glob('*.dll')):manifest['files'][str(p.relative_to(runtime))]=hashlib.file_digest(p.open('rb'),'sha256').hexdigest()
    manifest['dependencies']=json.loads(subprocess.check_output([str(python),'-m','pip','list','--format=json'],env=environment,text=True))
    (runtime/'bundle-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    (notices/'README.txt').write_text('Python: Astral python-build-standalone; runtime licenses accompany this distribution.\nFFmpeg and FFprobe: eugeneware/ffmpeg-static; license and build/source notes included.\nSpeech model: Systran/faster-whisper-base.en, MIT; pinned revision and source URLs in bundle-manifest.json.\nDependency licenses are in site-packages/*dist-info/licenses or their package metadata.\n')
    if destination.exists():shutil.rmtree(destination)
    runtime.replace(destination)
    shutil.rmtree(stage)
    print('Standalone resources prepared:',key,flush=True)

if __name__=='__main__':main()
