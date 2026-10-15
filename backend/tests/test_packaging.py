"""Build-host PowerShell modules must not leak between PowerShell editions."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace


def test_windows_signature_check_uses_matching_shell_without_inherited_modules(tmp_path,monkeypatch):
    spec=importlib.util.spec_from_file_location('standalone_builder',Path(__file__).resolve().parents[2]/'scripts/prepare-standalone.py')
    builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
    vs=tmp_path/'Microsoft Visual Studio/Installer/vswhere.exe';vs.parent.mkdir(parents=True);vs.write_text('fixture')
    installation=tmp_path/'VS';crt=installation/'VC/Redist/MSVC/14.50.0/x64/Microsoft.VC145.CRT';crt.mkdir(parents=True)
    (crt/'msvcp140.dll').write_bytes(b'test fixture; signature verifier is mocked')
    runtime=tmp_path/'runtime';(runtime/'notices').mkdir(parents=True)
    monkeypatch.setattr(builder,'sys',SimpleNamespace(platform='win32'))
    monkeypatch.setenv('ProgramFiles(x86)',str(tmp_path));monkeypatch.setenv('PSModulePath','incompatible PowerShell modules')
    monkeypatch.setattr(builder.shutil,'which',lambda name:'pwsh.exe' if name=='pwsh' else None)
    monkeypatch.setattr(builder.subprocess,'check_output',lambda *args,**kwargs:str(installation))
    calls=[]
    monkeypatch.setattr(builder.subprocess,'run',lambda command,**kwargs:calls.append((command,kwargs)))
    result=builder.bundle_windows_crt(runtime)
    assert calls[0][0][0]=='pwsh.exe'
    assert 'PSModulePath' not in calls[0][1]['env']
    assert 'Get-AuthenticodeSignature' in calls[0][0][-1] and calls[0][1]['check'] is True
    assert result[0]['file']=='msvcp140.dll' and (runtime/'msvcp140.dll').exists()
