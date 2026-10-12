"""Local package inspection and transactional game installation. Never executes games.
Port repair requires declared requirements; uncertain requirements are not invented.
"""
import hashlib
import json
import os
import re
import shutil
import stat
import struct
import subprocess
import tempfile
import threading
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

MAX_BYTES = 16 * 1024**3
MAX_FILES = 20000
MANIFEST = 'xiaozhi-game.json'
INFER = {'.gba':'GBA','.agb':'GBA','.gb':'GB','.gbc':'GBC','.nes':'FC',
         '.sfc':'SFC','.smc':'SFC','.nds':'NDS','.cso':'PSP','.p8':'PICO8','.p8.png':'PICO8'}
ARCHIVE_ROM_SYSTEMS = {'ARCADE','CPS1','CPS2','CPS3','FBNEO','MAME','MAME2003PLUS','MAME2010','NEOGEO','PGM'}


def safe_name(name):
    if not isinstance(name,str) or not name or '\\' in name or any(ord(c)<32 for c in name):
        raise ValueError('Tên file không hợp lệ.')
    p=PurePosixPath(name)
    if p.is_absolute() or any(x in ('..','.') for x in name.split('/')) or ':' in name or name.startswith('-'):
        raise ValueError('Gói có đường dẫn vượt khỏi thư mục game.')
    if any(x.endswith((' ','.')) for x in p.parts): raise ValueError('Tên file không phù hợp thẻ FAT.')
    return p.as_posix()


def destination(root,name):
    name=safe_name(name);p=root/name
    if p.resolve()!=p.absolute(): raise ValueError('Đường dẫn đích chứa liên kết hoặc không nằm trong thẻ.')
    if root.resolve() not in p.resolve().parents:raise ValueError('Đích nằm ngoài thẻ.')
    return p


@dataclass
class Entry:
    name: str
    size: int
    folder: bool=False


class Package:
    def __init__(self,path,sevenzip=None):
        self.path=Path(path).absolute();self.sevenzip=str(sevenzip or Path(__file__).parent/'bin/7zz.aarch64')
        if self.path.is_symlink():raise ValueError('Không đọc gói qua symlink.')
        self.kind='folder' if self.path.is_dir() else self.path.suffix.lower().lstrip('.')
        if self.kind not in ('folder','zip','7z'):raise ValueError('Chỉ nhận ZIP, 7z hoặc thư mục.')
        self.signature=self.stamp()
        self.entries=self.list()
        names=[e.name.casefold() for e in self.entries]
        if len(names)!=len(set(names)):raise ValueError('Gói có tên file trùng trên thẻ FAT.')
        if len(names)>MAX_FILES or sum(e.size for e in self.entries)>MAX_BYTES:raise ValueError('Gói vượt giới hạn 20.000 file / 16 GiB.')
        self.by_name={e.name:e for e in self.entries}
    def stamp(self):
        s=self.path.stat();return (s.st_size,s.st_mtime_ns)
    def list(self):
        out=[]
        if self.kind=='folder':
            for base,dirs,files in os.walk(self.path,followlinks=False):
                for n in dirs+files:
                    p=Path(base)/n
                    if p.is_symlink():raise ValueError('Gói chứa symlink.')
                for n in files:
                    p=Path(base)/n
                    if not p.is_file():raise ValueError('Gói chứa file đặc biệt.')
                    out.append(Entry(safe_name(p.relative_to(self.path).as_posix()),p.stat().st_size))
        elif self.kind=='zip':
            with zipfile.ZipFile(self.path) as z:
                for i in z.infolist():
                    name=safe_name(i.filename.rstrip('/'))
                    mode=i.external_attr>>16
                    if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0,stat.S_IFREG,stat.S_IFDIR)):
                        raise ValueError('ZIP chứa liên kết/file đặc biệt.')
                    if i.flag_bits&1:raise ValueError('Không hỗ trợ gói có mật khẩu.')
                    if not i.is_dir():out.append(Entry(name,i.file_size))
        else:
            if not Path(self.sevenzip).is_file():raise ValueError('Thiếu bộ giải nén 7z ARM64.')
            p=subprocess.run([self.sevenzip,'l','-slt','-ba','-sccUTF-8','-p-',str(self.path)],capture_output=True,timeout=60)
            if p.returncode:raise ValueError('Không đọc được 7z, có thể gói hỏng hoặc có mật khẩu.')
            for block in p.stdout.decode('utf-8',errors='strict').strip().split('\n\n'):
                fields={}
                for line in block.splitlines():
                    if ' = ' not in line:raise ValueError('Danh sách 7z không hợp lệ.')
                    k,v=line.split(' = ',1)
                    if k in fields:raise ValueError('Danh sách 7z không rõ ràng.')
                    fields[k]=v
                if not fields:continue
                name=safe_name(fields['Path'])
                if any('link' in k.lower() for k in fields) or fields.get('Encrypted')=='+':
                    raise ValueError('7z chứa liên kết hoặc có mật khẩu.')
                if fields.get('Folder')!='+' and not fields.get('Attributes','').startswith('D'):
                    out.append(Entry(name,int(fields['Size'])))
        if not out:raise ValueError('Gói trống.')
        return out
    def copy(self,name,output,cancel=None):
        entry=self.by_name[name];count=0;digest=hashlib.sha256()
        def transfer(stream):
            nonlocal count
            while True:
                if cancel and cancel.is_set():raise InterruptedError('Đã hủy cài đặt.')
                data=stream.read(1024*1024)
                if not data:break
                count+=len(data)
                if count>entry.size:raise ValueError('Kích thước file vượt thông tin gói.')
                output.write(data);digest.update(data)
        if self.kind=='folder':
            path=self.path/name
            if path.is_symlink() or self.path not in path.resolve().parents:raise ValueError('Nguồn đã thay đổi.')
            with path.open('rb') as f:transfer(f)
        elif self.kind=='zip':
            with zipfile.ZipFile(self.path) as z,z.open(name) as f:transfer(f)
        else:
            # stdout-only extraction: archive can never choose a filesystem destination.
            with tempfile.TemporaryFile() as errors:
                p=subprocess.Popen([self.sevenzip,'x','-so','-spd','-p-',str(self.path),name],stdout=subprocess.PIPE,stderr=errors)
                timer=threading.Timer(300,p.kill);timer.start()
                watcher_stop=threading.Event()
                def watch_cancel():
                    while not watcher_stop.wait(.1):
                        if cancel and cancel.is_set():
                            if p.poll() is None:p.kill()
                            return
                watcher=threading.Thread(target=watch_cancel,daemon=True);watcher.start()
                try:
                    transfer(p.stdout)
                    if p.wait(timeout=5):raise ValueError('Không giải nén được file 7z.')
                finally:
                    timer.cancel();watcher_stop.set();watcher.join(timeout=1)
                    if p.poll() is None:p.kill();p.wait()
                    p.stdout.close()
        if count!=entry.size:raise ValueError('Gói bị thiếu/truncated file.')
        return digest.hexdigest()
    def read(self,name,limit=256*1024):
        import io
        if self.by_name[name].size>limit:raise ValueError('Thông tin gói quá lớn.')
        out=io.BytesIO();self.copy(name,out);return out.getvalue()


def systems(root):
    result={}
    for p in (root/'Emus').glob('*/config.json'):
        try:
            data=json.loads(p.read_text(encoding='utf-8-sig'));rom=(p.parent/data['rompath']).resolve()
            if rom.parent==root/'Roms' and rom.is_dir():result[rom.name]=set(data.get('extlist','').lower().split('|'))
        except (OSError,ValueError,KeyError,TypeError):continue
    return result


def preview(path,root=Path('/mnt/SDCARD'),system=None,sevenzip=None):
    root=Path(root).resolve();pkg=Package(path,sevenzip);available=systems(root)
    manifest=json.loads(pkg.read(MANIFEST).decode('utf-8-sig')) if MANIFEST in pkg.by_name else None
    if manifest and manifest.get('format')!=1:raise ValueError('Phiên bản thông tin gói không hỗ trợ.')
    files=[e for e in pkg.entries if e.name!=MANIFEST]
    rooted=all(e.name.split('/')[0] in ('Roms','Ports','Imgs') for e in files)
    is_port=any(e.name.startswith('Ports/') or e.name.startswith('Roms/PORTS/') for e in files) or bool(manifest and manifest.get('kind')=='port')
    if is_port and not (manifest and isinstance(manifest.get('required_files'),list) and manifest['required_files']):
        raise ValueError('Chưa xác định yêu cầu của Port. Cần xiaozhi-game.json khai báo file bắt buộc và thông tin chạy.')
    system=system or (manifest or {}).get('system')
    if not rooted and not is_port and not system:
        candidates={INFER.get('.p8.png' if e.name.lower().endswith('.p8.png') else Path(e.name).suffix.lower()) for e in files}
        candidates.discard(None)
        if len(candidates)==1:system=candidates.pop()
    if not rooted and not is_port and system not in available:
        return {'source':str(pkg.path),'needs_system':True,'systems':sorted(k for k in available if k!='PORTS'),'reason':'Gói chưa rõ hệ máy. Chọn đúng hệ máy trước khi xem nơi cài.'}
    items=[]
    if not rooted and not is_port and system in ARCHIVE_ROM_SYSTEMS:
        if pkg.kind!='zip':raise ValueError('ROM Arcade cần ZIP gốc của ROM set; không tự chuyển 7z/thư mục thành ROM set.')
        items=[{'source':None,'target':'Roms/'+system+'/'+pkg.path.name,'size':pkg.path.stat().st_size,'copy_archive':True}]
    else:
        for e in files:
            if rooted:target=e.name
            elif is_port:
                directory=(manifest.get('port') or {}).get('directory')
                if not directory:raise ValueError('Thiếu tên thư mục Port.')
                target='Ports/'+safe_name(directory)+'/'+e.name
            else:
                suffix=Path(e.name).suffix.lower().lstrip('.')
                if suffix not in available[system]:continue
                target='Roms/'+system+'/'+e.name
            items.append({'source':e.name,'target':target,'size':e.size})
    def allowed(target):
        parts=PurePosixPath(safe_name(target)).parts
        if len(parts)<3 or parts[0] not in ('Roms','Ports','Imgs'):raise ValueError('Gói yêu cầu ghi ngoài thư mục game.')
        if parts[0] in ('Roms','Imgs') and parts[1] not in available:raise ValueError('Hệ máy/emulator đích chưa có trên thẻ.')
        destination(root,target)
    for item in items:allowed(item['target'])
    repairs=[];targets={i['target'] for i in items}
    declared_configs={c['path'] for c in (manifest or {}).get('config_files',[])}
    port_info=(manifest or {}).get('port') or {}
    generated_launcher='Roms/PORTS/'+port_info.get('launcher',port_info.get('directory','')+'.sh') if port_info else None
    for requirement in (manifest or {}).get('required_files',[]):
        target=requirement['path'];allowed(target)
        if target in targets or destination(root,target).is_file():
            if requirement.get('size') is not None:
                size=next((i['size'] for i in items if i['target']==target),None)
                if size is None:size=destination(root,target).stat().st_size
                if size!=requirement['size']:raise ValueError('File sai kích thước: '+target)
            continue
        if target in declared_configs or target==generated_launcher:continue
        url=requirement.get('url');digest=requirement.get('sha256');size=requirement.get('size')
        if not url or not digest or not re.fullmatch('[0-9a-fA-F]{64}',digest) or not isinstance(size,int) or size<0:
            raise ValueError('Thiếu '+target+'; chưa có nguồn HTTPS/SHA256/kích thước xác định. Không tự đoán.')
        if not url.startswith('https://'):raise ValueError('Nguồn bổ sung phải là HTTPS.')
        repairs.append({'target':target,'url':url,'sha256':digest.lower(),'size':size})
    for config in (manifest or {}).get('config_files',[]):
        target=config['path'];allowed(target)
        if target in targets or destination(root,target).exists():continue
        if not target.endswith('.json') or not isinstance(config.get('content'),dict):raise ValueError('Chỉ tạo cấu hình JSON đã khai báo rõ nội dung.')
        data=(json.dumps(config['content'],ensure_ascii=False,indent=2)+'\n').encode()
        if len(data)>65536:raise ValueError('Cấu hình quá lớn.')
        repairs.append({'target':target,'data':data,'size':len(data)})
    port=(manifest or {}).get('port')
    if is_port and port:
        directory=safe_name(port['directory']);entry=safe_name(port['executable']);launcher=safe_name(port.get('launcher',directory+'.sh'))
        if '/' in directory or '/' in launcher or not launcher.endswith('.sh'):raise ValueError('Tên Port/launcher không hợp lệ.')
        executable='Ports/'+directory+'/'+entry;target='Roms/PORTS/'+launcher;allowed(target)
        known=targets|{x['target'] for x in repairs}
        if executable not in known and not destination(root,executable).is_file():raise ValueError('Thiếu chương trình chạy '+executable)
        if target not in known and not destination(root,target).exists():
            import shlex
            runtime=port.get('runtime','native')
            if runtime not in ('native','armhf_glremote'):raise ValueError('Chưa biết runtime của Port.')
            if runtime=='armhf_glremote' and not (Path('/usr/bin/glremote_run').exists() or (root/'System/bin/glremote_run').exists()):
                raise ValueError('Máy thiếu glremote_run cho Port ARMHF.')
            command=('glremote_run ' if runtime=='armhf_glremote' else '')+shlex.quote('./'+entry)
            data=('#!/bin/sh\n. /mnt/SDCARD/System/etc/ex_config\ncd '+shlex.quote('/mnt/SDCARD/Ports/'+directory)+' || exit 1\nexec '+command+'\n').encode()
            repairs.append({'target':target,'data':data,'size':len(data),'executable':True})
    allitems=items+repairs
    if not items:raise ValueError('Không tìm thấy file game phù hợp.')
    names=[x['target'].casefold() for x in allitems]
    if len(names)!=len(set(names)):raise ValueError('Đích bị trùng.')
    total=sum(x['size'] for x in allitems)
    if total>MAX_BYTES:raise ValueError('Gói quá lớn.')
    for x in allitems:
        if destination(root,x['target']).exists():raise ValueError('Đã có '+x['target']+'. Không ghi đè game hiện có.')
    if shutil.disk_usage(root).free<2*total+32*1024**2:raise ValueError('Thẻ không đủ dung lượng để cài và giữ bản tạm.')
    return {'source':str(pkg.path),'root':str(root),'system':system,'kind':'port' if is_port else 'rom','items':items,'repairs':repairs,'bytes':total,'stamp':pkg.signature,'sevenzip':pkg.sevenzip,'port':port,'certainty':'Đối chiếu danh sách bắt buộc của gói' if manifest else 'Nhận diện nơi cài ROM; chưa xác nhận toàn bộ yêu cầu chơi game'}


def install(plan,cancel=None,progress=None,allow_repairs=False):
    if plan.get('needs_system'):raise ValueError('Chưa chọn hệ máy.')
    if plan['repairs'] and not allow_repairs:raise ValueError('Cần xác nhận tải/tạo các file bổ sung trước.')
    root=Path(plan['root']);pkg=Package(plan['source'],plan['sevenzip'])
    if pkg.signature!=tuple(plan['stamp']):raise ValueError('Nguồn đã đổi sau khi xem trước. Hãy đọc lại gói.')
    cancel=cancel or threading.Event();progress=progress or (lambda text:None)
    entries=plan['items']+plan['repairs'];total=sum(x['size'] for x in entries)
    if shutil.disk_usage(root).free<2*total+32*1024**2:raise ValueError('Thẻ không đủ dung lượng cho cài đặt an toàn.')
    stage=Path(tempfile.mkdtemp(prefix='.xiaozhi-install-',dir=root));committed=[];created_dirs=[]
    try:
        for index,item in enumerate(entries):
            if cancel.is_set():raise InterruptedError('Đã hủy cài đặt.')
            progress('Chuẩn bị %d/%d: %s'%(index+1,len(entries),Path(item['target']).name))
            target=destination(root,item['target'])
            if target.exists():raise ValueError('Đích đã tồn tại. Không ghi đè.')
            temp=stage/str(index)
            with temp.open('wb') as f:
                if 'data' in item:f.write(item['data'])
                elif 'url' in item:
                    from src.utils.tls import client_ssl_context
                    request=urllib.request.Request(item['url'],headers={'User-Agent':'Xiaozhi-TrimUI-GameInstaller'})
                    with urllib.request.urlopen(request,timeout=15,context=client_ssl_context()) as response:
                        if not response.url.startswith('https://'):raise ValueError('Nguồn tải chuyển sang kết nối không bảo mật.')
                        count=0;digest=hashlib.sha256()
                        while True:
                            if cancel.is_set():raise InterruptedError('Đã hủy tải.')
                            chunk=response.read(1024*1024)
                            if not chunk:break
                            count+=len(chunk)
                            if count>item['size']:raise ValueError('File tải vượt kích thước khai báo.')
                            digest.update(chunk);f.write(chunk)
                        if count!=item['size'] or digest.hexdigest()!=item['sha256']:raise ValueError('File tải sai kích thước/SHA256; không cài.')
                elif item.get('copy_archive'):
                    with pkg.path.open('rb') as inp:
                        while True:
                            if cancel.is_set():raise InterruptedError('Đã hủy cài đặt.')
                            chunk=inp.read(1024*1024)
                            if not chunk:break
                            f.write(chunk)
                else:pkg.copy(item['source'],f,cancel)
                f.flush();os.fsync(f.fileno())
            if temp.stat().st_size!=item['size']:raise ValueError('Kích thước file không khớp.')
        # Validate the declared entry point without ever running an untrusted program.
        port=plan.get('port')
        if port:
            executable='Ports/'+port['directory']+'/'+port['executable']
            pos=next((i for i,x in enumerate(entries) if x['target']==executable),None)
            program=stage/str(pos) if pos is not None else destination(root,executable)
            with program.open('rb') as f:header=f.read(64)
            if header.startswith(b'\x7fELF'):
                if len(header)<20 or header[5]!=1:raise ValueError('ELF không hợp lệ hoặc endian không phù hợp.')
                machine=struct.unpack_from('<H',header,18)[0]
                expected=40 if port.get('runtime')=='armhf_glremote' else 183
                if machine!=expected:raise ValueError('Chương trình không đúng kiến trúc ARM của máy.')
            elif not header.startswith(b'#!/bin/sh'):
                raise ValueError('Chưa xác định cách chạy chương trình Port. Không tạo launcher đoán.')
            if pos is not None:entries[pos]['executable']=True
        # No destination is modified until all files/download hashes are validated.
        for index,item in enumerate(entries):
            if cancel.is_set():raise InterruptedError('Đã hủy cài đặt.')
            target=destination(root,item['target'])
            parents=[];p=target.parent
            while not p.exists():parents.append(p);p=p.parent
            for p in reversed(parents):p.mkdir();created_dirs.append(p)
            with target.open('xb'):pass
            committed.append(target)
            os.replace(stage/str(index),target)
            if item.get('executable') or target.suffix=='.sh':target.chmod(0o755)
        progress('Đã cài. Về menu game và làm mới danh sách để mở.')
        return [str(x.relative_to(root)) for x in committed]
    except BaseException:
        for p in reversed(committed):p.unlink(missing_ok=True)
        for p in reversed(created_dirs):
            try:p.rmdir()
            except OSError:pass
        raise
    finally:shutil.rmtree(stage)
