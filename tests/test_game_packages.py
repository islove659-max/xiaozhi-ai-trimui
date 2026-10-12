"""Package fixtures contain synthetic bytes, never commercial ROMs or game data.
Chạy: python tests/test_game_packages.py   (đặt SEVENZIP=<đường dẫn 7z> nếu không chạy trên ARM64)
"""
import io,json,os,shutil,stat,subprocess,tempfile,threading,zipfile
from pathlib import Path
from unittest.mock import patch
import hashlib
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
try:import certifi  # có trong pylibs trên máy; PC thử nghiệm có thể thiếu
except ImportError:
 import types;sys.modules['certifi']=types.SimpleNamespace(where=lambda:None)
import game_packages as gp
from game_package_ai import snapshot,validate_advice
passed=0
SEVENZIP=os.environ.get('SEVENZIP') or str(Path(__file__).resolve().parents[1]/'bin/7zz.aarch64')

def check(name,condition):
 global passed
 assert condition,name
 passed+=1;print('PASS '+name,flush=True)

def rejects(name,call,text=None):
 try:call()
 except (ValueError,InterruptedError,OSError) as exc:
  if text and text not in str(exc):raise AssertionError(name+': '+str(exc))
  check(name,True);return
 raise AssertionError(name)

base=Path(tempfile.mkdtemp(prefix='game_package_tests_'));root=base/'card';root.mkdir()
for system,extensions in [('GBA','gba|zip'),('GB','gb|zip'),('ARCADE','zip'),('PORTS','sh|zip')]:
 (root/'Roms'/system).mkdir(parents=True);(root/'Emus'/system).mkdir(parents=True)
 (root/'Emus'/system/'config.json').write_text(json.dumps({'rompath':'../../Roms/'+system,'extlist':extensions}))
(root/'GamePackages').mkdir()

# Port đã cài theo đúng bố cục PortMaster trên Brick Pro: Data/ports/<dir>/port.json + Data/ports/<Script>.sh
def installed_port(directory,script,title,body,gamedata=True):
 d=root/'Data/ports'/directory;d.mkdir(parents=True)
 if gamedata:(d/'gamedata').mkdir();(d/'gamedata/.gitkeep').write_bytes(b'')
 (d/'port.json').write_text(json.dumps({'version':4,'items':[script,directory+'/'],
  'attr':{'title':title,'inst':'Copy the game data into "'+directory+'/gamedata".'}}))
 (root/'Data/ports'/script).write_text(body)
installed_port('celeste','Celeste.sh','Celeste','export gameassembly="Celeste.exe"\ncd "$gamedir/gamedata"\n'
 'rm -f System*.dll mscorlib.dll FNA.dll\n$TASKSET mono Celeste.exe 2>&1\n')
installed_port('fnagame','FnaGame.sh','Fna Game','cd "$gamedir/gamedata"\nrm -f FNA.dll SDL2.dll\nmono Other.exe\n')

def archive(name,files):
 p=base/name
 with zipfile.ZipFile(p,'w') as z:
  for n,data in files.items():z.writestr(n,data)
 return p

def folder(name,files):
 p=base/name
 for n,data in files.items():
  f=p/n;f.parent.mkdir(parents=True,exist_ok=True);f.write_bytes(data)
 return p

try:
 # ---------- ROM ----------
 p=archive('gba.zip',{'test.gba':b'fixture-not-real-rom'})
 plan=gp.preview(p,root);check('ZIP detects installed GBA destination',plan['system']=='GBA' and plan['items'][0]['target']=='Roms/GBA/test.gba')
 check('preview changes no game files',not (root/'Roms/GBA/test.gba').exists())
 gp.install(plan);check('ZIP copies bytes to correct directory',(root/'Roms/GBA/test.gba').read_bytes()==b'fixture-not-real-rom')
 rejects('existing ROM is never overwritten',lambda:gp.preview(p,root),'không ghi đè')
 gp.install(gp.preview(folder('unpacked',{'sub/folder.gb':b'folder-fixture'}),root))
 check('unpacked folder installs GB (flattened into system folder)',(root/'Roms/GB/folder.gb').is_file())
 single=root/'GamePackages/single.gba';single.write_bytes(b'single-rom')
 gp.install(gp.preview(single,root));check('single ROM file installs',(root/'Roms/GBA/single.gba').read_bytes()==b'single-rom')
 p=archive('ambiguous.zip',{'one.bin':b'a','two.bin':b'b'});plan=gp.preview(p,root)
 check('ambiguous archive requires manual system',plan['needs_system'])
 check('manual choice lists installed ports by title','port:celeste' in plan['systems'] and plan['labels']['port:celeste']=='PORT: Celeste')
 gp.install(gp.preview(p,root,'ARCADE'));check('Arcade retains ZIP intact',(root/'Roms/ARCADE/ambiguous.zip').read_bytes()==p.read_bytes())
 p=archive('rooted.zip',{'Roms/GBA/nested/root.gba':b'rooted'})
 gp.install(gp.preview(p,root));check('structured package retains correct folders',(root/'Roms/GBA/nested/root.gba').read_bytes()==b'rooted')
 rejects('rooted package cannot write System via Data',lambda:gp.preview(archive('dsys.zip',{'Data/x/y.bin':b'x'}),root))
 # ---------- an toàn ----------
 rejects('ZIP traversal rejected',lambda:gp.preview(archive('escape.zip',{'../outside.gba':b'x'}),root))
 rejects('case collisions rejected for FAT',lambda:gp.preview(archive('case.zip',{'a.gba':b'x','A.gba':b'y'}),root))
 link=base/'links';link.mkdir()
 try:os.symlink(str(base/'gba.zip'),link/'bad.gba');can_link=True
 except OSError:can_link=False
 if can_link:rejects('unpacked symlinks rejected',lambda:gp.preview(link,root))
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
 payload=b'fixture-download';digest=hashlib.sha256(payload).hexdigest()
 manifest={'format':1,'system':'GBA','required_files':[{'path':'Roms/GBA/download.gba','url':'https://example.com/fixture','sha256':digest,'size':len(payload)}]}
 p=archive('download.zip',{'local.gba':b'local',gp.MANIFEST:json.dumps(manifest)});plan=gp.preview(p,root)
 rejects('repair requires explicit confirmation',lambda:gp.install(plan))
 class Response(io.BytesIO):url='https://example.com/fixture'
 with patch.object(gp.urllib.request,'urlopen',lambda *a,**k:Response(payload)):gp.install(plan,allow_repairs=True)
 check('missing file repaired only after size and SHA256 verification',(root/'Roms/GBA/download.gba').read_bytes()==payload)
 manifest['required_files'][0]['path']='Roms/GBA/bad-download.gba';manifest['required_files'][0]['sha256']='0'*64
 p=archive('bad-download.zip',{'other.gba':b'other',gp.MANIFEST:json.dumps(manifest)});plan=gp.preview(p,root)
 with patch.object(gp.urllib.request,'urlopen',lambda *a,**k:Response(payload)):rejects('incorrect downloaded hash blocks all installation',lambda:gp.install(plan,allow_repairs=True))
 check('bad download leaves neither game nor partial dependency',not (root/'Roms/GBA/other.gba').exists() and not (root/'Roms/GBA/bad-download.gba').exists())
 # ---------- Port PortMaster ----------
 pm={'Demo.sh':b'#!/bin/bash\necho demo\n','demo/port.json':json.dumps({'version':4,'items':['Demo.sh','demo/']}).encode(),'demo/demo.bin':b'bin'}
 p=archive('demo.zip',pm);plan=gp.preview(p,root)
 check('PortMaster zip goes to autoinstall',plan['kind']=='portmaster' and plan['items'][0]['target']=='Data/ports/autoinstall/demo.zip')
 gp.install(plan);check('PortMaster zip copied byte-for-byte',(root/'Data/ports/autoinstall/demo.zip').read_bytes()==p.read_bytes())
 plan=gp.preview(folder('Demo2',{k.replace('demo','demo2').replace('Demo','Demo2'):v for k,v in pm.items()}),root)
 gp.install(plan)
 with zipfile.ZipFile(root/'Data/ports/autoinstall/Demo2.zip') as z:
  check('unpacked PortMaster folder repacked as valid zip',sorted(z.namelist())==['Demo2.sh','demo2/demo2.bin','demo2/port.json'] and z.read('demo2/demo2.bin')==b'bin')
 # ---------- Dữ liệu game cho port đã cài ----------
 data={'Celeste Linux/Celeste.exe':b'exe','Celeste Linux/Content/Maps/a.bin':b'map','Celeste Linux/FNA.dll':b'fna','readme.txt':b'top'}
 p=archive('celeste-data.zip',data);plan=gp.preview(p,root)
 targets=sorted(i['target'] for i in plan['items'])
 check('game data matched to installed port by script evidence',plan['kind']=='port_data' and plan['port_dir']=='celeste')
 check('wrapper folder stripped, data placed in gamedata',targets==['Data/ports/celeste/gamedata/Celeste.exe','Data/ports/celeste/gamedata/Content/Maps/a.bin','Data/ports/celeste/gamedata/FNA.dll'])
 gp.install(plan);check('port data installed with exact bytes',(root/'Data/ports/celeste/gamedata/Content/Maps/a.bin').read_bytes()==b'map')
 rejects('reinstalling identical data needs nothing',lambda:gp.preview(p,root),'đã có sẵn')
 data['Celeste Linux/Content/Maps/b.bin']=b'new';plan=gp.preview(archive('celeste-data2.zip',data),root)
 check('identical existing files skipped, only new file copied',[i['target'] for i in plan['items']]==['Data/ports/celeste/gamedata/Content/Maps/b.bin'] and any('Bỏ qua 3' in n for n in plan['notes']))
 data['Celeste Linux/Celeste.exe']=b'different-exe'
 rejects('different existing data is never overwritten',lambda:gp.preview(archive('celeste-data3.zip',data),root),'không ghi đè')
 plan=gp.preview(archive('engine-only.zip',{'Unknown/FNA.dll':b'f','Unknown/SDL2.dll':b's','Unknown/Game.exe':b'g'}),root)
 check('shared engine files alone never pick a port',plan.get('needs_system'))
 installed_port('iosas','Isles.sh','Isles of Sea and Sky','cd $GAMEDIR/gamedata\nzip -r game.droid data.win\n')
 installed_port('pvznd','PvZ.sh','Plants vs Zombies ND','cd $GAMEDIR\n[ -f data.win ] && mv data.win game.droid\n',gamedata=False)
 plan=gp.preview(archive('Isles of Sea and Sky (Linux).zip',{'data.win':b'w','audio.dat':b'a'}),root)
 check('shared GameMaker names resolved by package name',plan['kind']=='port_data' and plan['port_dir']=='iosas' and plan['items'][0]['target'].startswith('Data/ports/iosas/gamedata/'))
 plan=gp.preview(archive('mystery.zip',{'data.win':b'w'}),root)
 check('shared GameMaker names without name match ask user',plan.get('needs_system'))
 plan=gp.preview(archive('pvz.zip',{'PvZ ND/data.win':b'w'}),root,'port:pvznd')
 check('port without gamedata folder receives files at port root',[i['target'] for i in plan['items']]==['Data/ports/pvznd/data.win'])
 plan=gp.preview(archive('forced.zip',{'Pack/Other.exe':b'o','Pack/data/x.bin':b'x'}),root,'port:fnagame')
 check('manual port choice strips common folder',sorted(i['target'] for i in plan['items'])==['Data/ports/fnagame/gamedata/Other.exe','Data/ports/fnagame/gamedata/data/x.bin'])
 # ---------- 7z thật ----------
 if Path(SEVENZIP).is_file():
  try:Path(SEVENZIP).chmod(0o755)
  except OSError:pass
  src=folder('seven',{'seven.gb':b'sevenzip-fixture'})
  p=base/'seven.7z';subprocess.run([SEVENZIP,'a','-t7z',str(p),'seven.gb'],cwd=src,stdout=subprocess.DEVNULL,check=True)
  gp.install(gp.preview(p,root,sevenzip=SEVENZIP));check('real 7z installs verified bytes',(root/'Roms/GB/seven.gb').read_bytes()==b'sevenzip-fixture')
  src=folder('seven-port',{'Game/Other.exe':b'other','Game/data/1.bin':b'1'*5000,'Game/data/2.bin':b'2'*7000})
  p=base/'other.7z';subprocess.run([SEVENZIP,'a','-t7z','-ms=on',str(p),'Game'],cwd=src,stdout=subprocess.DEVNULL,check=True)
  plan=gp.preview(p,root,sevenzip=SEVENZIP);check('solid 7z game data matched to port',plan['kind']=='port_data' and plan['port_dir']=='fnagame')
  gp.install(plan);check('solid 7z extracted once and verified',(root/'Data/ports/fnagame/gamedata/data/2.bin').read_bytes()==b'2'*7000)
 else:print('SKIP 7z tests: no binary at '+SEVENZIP)
 # ---------- Gemini / xoá gói ----------
 p=archive('ai.zip',{'Celeste.exe':b'x','gemini_key.txt':'PRIVATE_FAKE_KEY','settings.json':'{"token":"FAKE_SECRET","width":640}'})
 evidence=snapshot(p,root)
 check('Gemini evidence excludes private key content','PRIVATE_FAKE_KEY' not in json.dumps(evidence) and 'FAKE_SECRET' not in json.dumps(evidence))
 check('Gemini evidence carries matched port install instructions',evidence.get('matched_port',{}).get('directory')=='celeste' and 'gamedata' in evidence['matched_port']['install_instructions'])
 advice=validate_advice({'summary':'May need a file','suggestions':['run dangerous command'],'uncertainties':['unknown']},evidence)
 check('Gemini cannot convert guesses into executable repairs',advice['verified'] is False and not advice['executable_actions'] and not advice['verified_missing'])
 rejects('source removal limited to GamePackages',lambda:gp.remove_source(base/'gba.zip',root))
 gp.remove_source(single,root);check('installed source removed from GamePackages',not single.exists())
 check('all temporary install folders removed',not list(root.glob('.xiaozhi-install-*')))
 print('SUMMARY pass=%d fail=0'%passed,flush=True)
finally:shutil.rmtree(base,ignore_errors=True)
