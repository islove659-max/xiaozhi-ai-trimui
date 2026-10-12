"""Package fixtures contain synthetic bytes, never commercial ROMs."""
import io,json,os,shutil,stat,subprocess,tempfile,threading,zipfile
from pathlib import Path
from unittest.mock import patch
import hashlib
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import game_packages as gp
from game_package_ai import snapshot,validate_advice
passed=0

def check(name,condition):
 global passed
 assert condition,name
 passed+=1;print('PASS '+name,flush=True)

def rejects(name,call):
 try:call()
 except (ValueError,InterruptedError,OSError):check(name,True);return
 raise AssertionError(name)

base=Path(tempfile.mkdtemp(prefix='game_package_tests_'));root=base/'card';root.mkdir()
for system,extensions in [('GBA','gba|zip'),('GB','gb|zip'),('ARCADE','zip'),('PORTS','sh|zip')]:
 (root/'Roms'/system).mkdir(parents=True);(root/'Emus'/system).mkdir(parents=True)
 (root/'Emus'/system/'config.json').write_text(json.dumps({'rompath':'../../Roms/'+system,'extlist':extensions}))

def archive(name,files):
 p=base/name
 with zipfile.ZipFile(p,'w') as z:
  for n,data in files.items():z.writestr(n,data)
 return p

def make_port(name,config=True):
 data={'format':1,'kind':'port','port':{'directory':name,'executable':'game.sh','launcher':name+'.sh','runtime':'native'},
 'required_files':[{'path':'Ports/'+name+'/game.sh'},{'path':'Ports/'+name+'/config.json'},{'path':'Roms/PORTS/'+name+'.sh'}]}
 if config:data['config_files']=[{'path':'Ports/'+name+'/config.json','content':{'width':1024,'height':768}}]
 return data

try:
 p=archive('gba.zip',{'test.gba':b'fixture-not-real-rom'})
 plan=gp.preview(p,root);check('ZIP detects installed GBA destination',plan['system']=='GBA' and plan['items'][0]['target']=='Roms/GBA/test.gba')
 check('preview changes no game files',not (root/'Roms/GBA/test.gba').exists())
 result=gp.install(plan);check('ZIP copies bytes to correct directory',(root/'Roms/GBA/test.gba').read_bytes()==b'fixture-not-real-rom')
 rejects('existing games are never overwritten',lambda:gp.preview(p,root))
 folder=base/'unpacked';folder.mkdir();(folder/'folder.gb').write_bytes(b'folder-fixture')
 gp.install(gp.preview(folder,root));check('unpacked folder installs GB',(root/'Roms/GB/folder.gb').is_file())
 p=archive('ambiguous.zip',{'one.bin':b'a','two.bin':b'b'})
 check('ambiguous archive requires manual system',gp.preview(p,root)['needs_system'])
 gp.install(gp.preview(p,root,'ARCADE'));check('Arcade retains ZIP intact',(root/'Roms/ARCADE/ambiguous.zip').read_bytes()==p.read_bytes())
 p=archive('rooted.zip',{'Roms/GBA/nested/root.gba':b'rooted'})
 gp.install(gp.preview(p,root));check('structured package retains correct folders',(root/'Roms/GBA/nested/root.gba').read_bytes()==b'rooted')
 rejects('ZIP traversal rejected',lambda:gp.preview(archive('escape.zip',{'../outside.gba':b'x'}),root))
 rejects('case collisions rejected for FAT',lambda:gp.preview(archive('case.zip',{'a.gba':b'x','A.gba':b'y'}),root))
 link=base/'links';link.mkdir();os.symlink('/etc/passwd',link/'bad.gba')
 rejects('unpacked symlinks rejected',lambda:gp.preview(link,root))
 p=base/'link.zip'
 with zipfile.ZipFile(p,'w') as z:
  i=zipfile.ZipInfo('link.gba');i.external_attr=(stat.S_IFLNK|0o777)<<16;z.writestr(i,'/etc/passwd')
 rejects('ZIP symlinks rejected',lambda:gp.preview(p,root))
 bad={'format':1,'system':'GBA','required_files':[{'path':'System/bin/unsafe','url':'https://example.com/x','sha256':'a'*64,'size':1}]}
 rejects('repair cannot modify System',lambda:gp.preview(archive('system.zip',{'x.gba':b'x',gp.MANIFEST:json.dumps(bad)}),root))
 p=archive('change.zip',{'change.gb':b'initial'});plan=gp.preview(p,root);p.write_bytes(p.read_bytes()+b'changed')
 rejects('changed source must be reviewed again',lambda:gp.install(plan))
 p=archive('cancel.zip',{'cancel.gb':b'test'});plan=gp.preview(p,root);event=threading.Event();event.set()
 rejects('cancel aborts before writing game',lambda:gp.install(plan,event))
 check('cancel cleans staging and game paths',not list(root.glob('.xiaozhi-install-*')) and not (root/'Roms/GB/cancel.gb').exists())
 p=archive('rollback.zip',{'Roms/GB/rollback/a.gb':b'a','Roms/GB/rollback/b.gb':b'b'})
 plan=gp.preview(p,root);original=gp.os.replace;calls=[0]
 def fail_second(a,b):
  calls[0]+=1
  if calls[0]==2:raise OSError('injected commit failure')
  return original(a,b)
 with patch.object(gp.os,'replace',fail_second):rejects('commit failure rolls back',lambda:gp.install(plan))
 check('rollback preserves unrelated games and removes partial game',not (root/'Roms/GB/rollback').exists() and (root/'Roms/GBA/test.gba').exists())
 missing={'format':1,'system':'GBA','required_files':[{'path':'Roms/GBA/missing.gba'}]}
 rejects('missing data without proven source blocks install',lambda:gp.preview(archive('missing.zip',{'another.gba':b'x',gp.MANIFEST:json.dumps(missing)}),root))
 rejects('unknown Port requirements are not guessed',lambda:gp.preview(archive('unknown-port.zip',{'Ports/unknown/main':b'x'}),root))
 name='safe-demo';manifest=make_port(name);p=archive('port.zip',{'game.sh':b'#!/bin/sh\nexit 0\n',gp.MANIFEST:json.dumps(manifest)})
 plan=gp.preview(p,root);check('Port reports exact config and launcher repairs',len(plan['repairs'])==2)
 rejects('repair requires explicit confirmation',lambda:gp.install(plan))
 gp.install(plan,allow_repairs=True)
 check('declared JSON config generated correctly',json.loads((root/'Ports'/name/'config.json').read_text())=={'width':1024,'height':768})
 launcher=(root/'Roms/PORTS'/('safe-demo.sh')).read_text();check('launcher uses exact Port directory and entrypoint','/mnt/SDCARD/Ports/safe-demo' in launcher and './game.sh' in launcher)
 check('installation never executes game',not (root/'GAME_EXECUTED').exists())
 payload=b'fixture-download';digest=hashlib.sha256(payload).hexdigest()
 manifest={'format':1,'system':'GBA','required_files':[{'path':'Roms/GBA/download.gba','url':'https://example.com/fixture','sha256':digest,'size':len(payload)}]}
 p=archive('download.zip',{'local.gba':b'local',gp.MANIFEST:json.dumps(manifest)});plan=gp.preview(p,root)
 class Response(io.BytesIO):url='https://example.com/fixture'
 with patch.object(gp.urllib.request,'urlopen',lambda *a,**k:Response(payload)):gp.install(plan,allow_repairs=True)
 check('missing file repaired only after size and SHA256 verification',(root/'Roms/GBA/download.gba').read_bytes()==payload)
 manifest['required_files'][0]['path']='Roms/GBA/bad-download.gba';manifest['required_files'][0]['sha256']='0'*64
 p=archive('bad-download.zip',{'other.gba':b'other',gp.MANIFEST:json.dumps(manifest)});plan=gp.preview(p,root)
 with patch.object(gp.urllib.request,'urlopen',lambda *a,**k:Response(payload)):rejects('incorrect downloaded hash blocks all installation',lambda:gp.install(plan,allow_repairs=True))
 check('bad download leaves neither game nor partial dependency',not (root/'Roms/GBA/other.gba').exists() and not (root/'Roms/GBA/bad-download.gba').exists())
 # Use actual bundled ARM64 7-Zip, not mocked archive parsing.
 source=base/'seven';source.mkdir();(source/'seven.gb').write_bytes(b'sevenzip-fixture')
 binary=Path(__file__).resolve().parents[1]/'bin/7zz.aarch64';binary.chmod(0o755)
 p=base/'seven.7z';subprocess.run([str(binary),'a','-t7z',str(p),'seven.gb'],cwd=source,stdout=subprocess.DEVNULL,check=True)
 gp.install(gp.preview(p,root));check('real 7z installs verified bytes',(root/'Roms/GB/seven.gb').read_bytes()==b'sevenzip-fixture')
 p=archive('ai.zip',{'ai.gb':b'x','gemini_key.txt':'PRIVATE_FAKE_KEY','settings.json':'{"token":"FAKE_SECRET","width":640}'})
 evidence=snapshot(p,root);check('Gemini evidence excludes private key content','PRIVATE_FAKE_KEY' not in json.dumps(evidence) and 'FAKE_SECRET' not in json.dumps(evidence))
 advice=validate_advice({'summary':'May need a file','suggestions':['run dangerous command'],'uncertainties':['unknown']},evidence)
 check('Gemini cannot convert guesses into executable repairs',advice['verified'] is False and not advice['executable_actions'] and not advice['verified_missing'])
 check('all temporary install folders removed',not list(root.glob('.xiaozhi-install-*')))
 print('SUMMARY pass=%d fail=0'%passed,flush=True)
finally:shutil.rmtree(base)
