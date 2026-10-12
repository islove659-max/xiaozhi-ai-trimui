"""Local package inspection and transactional game installation. Never executes games.

Nguồn: ZIP, 7z, thư mục đã giải nén hoặc một file ROM lẻ trong thư mục CHEP_GAME_VAO_DAY ở gốc thẻ nhớ
(tên tự giải thích cho người mới; vẫn đọc thư mục cũ GamePackages).
Nơi cài được suy ra từ chính thẻ nhớ:
  - ROM          -> Roms/<HỆ>/            (Emus/*/config.json: rompath + extlist)
  - Port PortMaster (có <dir>/port.json) -> Apps/PortMaster/PortMaster/autoinstall/<tên>.zip, PortMaster tự cài khi mở
  - Dữ liệu game của Port đã cài -> Data/ports/<dir>/gamedata/ (đối chiếu tên file với script của port)
  - Gói đã sắp sẵn thư mục gốc thẻ (Roms/, Imgs/, Data/ports/) -> giữ nguyên đường dẫn
Không ghi đè file khác nội dung; yêu cầu không rõ thì báo, không tự đoán.
"""
import hashlib
import json
import os
import re
import shutil
import stat
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
         '.sfc':'SFC','.smc':'SFC','.nds':'NDS','.cso':'PSP','.p8':'PICO8','.p8.png':'PICO8',
         '.n64':'N64','.z64':'N64','.v64':'N64','.gg':'GG','.a26':'ATARI2600','.a78':'ATARI7800','.lnx':'LYNX',
         '.gdi':'DC','.cdi':'DC','.md':'MD','.gen':'MD','.smd':'MD','.sms':'MS','.pce':'PCE','.ngp':'NGP','.ngc':'NGP',
         '.ws':'WS','.wsc':'WS'}
# File đi kèm ROM, không phải game: không chép vào thư mục ROM (emulator không khai báo extlist nhận mọi file)
JUNK_EXT = {'txt','nfo','url','md5','sfv','jpg','jpeg','png','gif','bmp','pdf','htm','html','db','ini','json','xml','diz','doc','docx','lnk'}
# Tên dễ hiểu cho người mới (thư mục Roms/<HỆ> của TrimUI Stock)
SYSTEM_NAMES = {'ARCADE':'Arcade','ATARI2600':'Atari 2600','ATARI7800':'Atari 7800','CPS1':'Capcom CPS1','CPS2':'Capcom CPS2',
    'CPS3':'Capcom CPS3','DC':'Sega Dreamcast','EASYRPG':'RPG Maker 2000/2003','FBNEO':'Arcade FinalBurn Neo','FC':'NES / Famicom',
    'FFMPEG':'Video','GB':'Game Boy','GBA':'Game Boy Advance','GBC':'Game Boy Color','GG':'Sega Game Gear','GW':'Game & Watch',
    'LYNX':'Atari Lynx','MAME':'Arcade MAME','MAME2003PLUS':'Arcade MAME 2003+','MAME2010':'Arcade MAME 2010','MD':'Sega Mega Drive / Genesis',
    'MS':'Sega Master System','N64':'Nintendo 64','NDS':'Nintendo DS','NEOGEO':'Neo Geo','NGP':'Neo Geo Pocket','OPENBOR':'OpenBOR',
    'PCE':'PC Engine / TurboGrafx','PGM':'Arcade PGM','PICO8':'PICO-8','PS':'PlayStation 1','PSP':'PlayStation Portable',
    'SFC':'SNES / Super Famicom','SS':'Sega Saturn','WS':'WonderSwan','WSC':'WonderSwan Color','JAVA':'Java (J2ME)'}


def system_label(code):
    name=SYSTEM_NAMES.get(code)
    return name+' ('+code+')' if name else code


ARCHIVE_ROM_SYSTEMS = {'ARCADE','CPS1','CPS2','CPS3','FBNEO','MAME','MAME2003PLUS','MAME2010','NEOGEO','PGM'}
PORTS_DIR = 'Data/ports'
# PortMaster đọc 2 thư mục autoinstall; thư mục trong Data/ports dùng $directory="mnt/SDCARD/Data" (thiếu / đầu)
# nên chọn thư mục của chính PortMaster (đường dẫn tuyệt đối, luôn có).
PORTMASTER_DIR = 'Apps/PortMaster/PortMaster'
AUTOINSTALL_DIR = PORTMASTER_DIR + '/autoinstall'
ROOTED_TOPS = ('Roms','Imgs','Data')
# Thư mục người dùng chép game vào (gốc thẻ). Thư mục đầu là thư mục chính, các thư mục sau vẫn được đọc.
PACKAGE_DIRS = ('CHEP_GAME_VAO_DAY', 'GamePackages')
README_NAME = 'HUONG_DAN.txt'
README_TEXT = '''CHÉP GAME VÀO ĐÂY — Xiaozhi AI tự nhận diện và cài vào đúng chỗ
================================================================

1. Cắm thẻ nhớ vào máy tính. Mở thư mục này (CHEP_GAME_VAO_DAY, nằm ngoài cùng thẻ).
2. Chép game vào đây. Dạng nào cũng được:
     - file nén .zip hoặc .7z (không cần giải nén)
     - thư mục game đã giải nén
     - file ROM lẻ (.gba, .sfc, .n64, .nds ...)
     - gói port PortMaster (.zip có file .sh và thư mục port)
     - dữ liệu game cho port (ví dụ file .pck/.exe của game mua trên Steam, itch.io)
3. Cắm thẻ lại máy. Mở app Xiaozhi AI, bấm R1 để sang tab "Cài gói game".
4. Chọn gói bằng phím lên/xuống, bấm A để xem trước, bấm A lần nữa để cài.
   - App tự biết game của máy nào. Chưa nhận ra thì AI (Gemini) chọn giúp.
   - Game port: cài gói port trước, mở app PortMaster cho nó cài xong,
     rồi mới cài gói dữ liệu game.
5. Cài xong bấm X để xoá gói gốc trong thư mục này cho đỡ tốn chỗ.

App không ghi đè game đang có và không tự chạy game.
'''


def package_folders(root=Path('/mnt/SDCARD')):
    """Tạo thư mục chép game (kèm hướng dẫn) nếu chưa có; trả các thư mục gói đang có trên thẻ."""
    root=Path(root);main=root/PACKAGE_DIRS[0]
    try:
        main.mkdir(exist_ok=True)
        if not (main/README_NAME).exists():(main/README_NAME).write_text(README_TEXT,encoding='utf-8')
    except OSError:pass
    return [root/d for d in PACKAGE_DIRS if (root/d).is_dir()]


def list_packages(root=Path('/mnt/SDCARD')):
    """Các gói người dùng đã chép (bỏ file hướng dẫn, file/thư mục ẩn)."""
    out=[]
    for folder in package_folders(root):
        for p in folder.iterdir():
            if p.is_symlink() or p.name.startswith(('.','_')) or p.name==README_NAME:continue
            out.append(p)
    return sorted(out,key=lambda p:p.name.casefold())
# Đuôi file dữ liệu game hay được script port nhắc tới (dùng để đối chiếu gói với port).
DATA_EXT = ('exe','dll','pck','win','apk','data','pak','wad','bin','dat','assets','resource','json','xnb',
            'unx','ios','droid','zip','gma','big','rpa','rgssad','rgss3a','arc','pk3','grp','mpq','cfg','ini')
SCRIPT_REF = re.compile(r'(?<![A-Za-z0-9_.+\-])[A-Za-z0-9_][A-Za-z0-9_.+\-]*\.(?:%s)\b' % '|'.join(DATA_EXT), re.I)
# File engine dùng chung giữa nhiều game: trùng tên không chứng minh gói thuộc port nào.
WEAK = re.compile(r'^(system|mono|microsoft|mscorlib|fna|sdl2|steam_api|libsteam|openal|fmod|monogame|xna|netstandard|newtonsoft|unity|d3d|x3daudio|xinput|'
                  r'mmloader|parisengine|gmloader|data\.win|game\.(droid|apk|unx|ios|win)|config\.(dat|cfg|ini)|options\.ini)', re.I)


def _norm(text):
    return re.sub(r'[^a-z0-9]','',text.casefold())


# Từ chung trong tên gói/thư mục, không nói lên đó là game nào
GENERIC_LABELS = {'game','games','data','gamedata','files','steam','linux','windows','win','itch','itchio','gog','port','ports',
                  'portmaster','full','demo','setup','install','content','assets','release','version','english','viethoa'}


def _name_match(directory,title,labels):
    """Tên port (thư mục hoặc tiêu đề) có nằm trong tên gói/thư mục gốc của gói không."""
    keys={k for k in (_norm(directory),_norm(title)) if len(k)>=4 and k not in GENERIC_LABELS}
    labels={l for l in labels if l not in GENERIC_LABELS}
    return any(k in l or (len(l)>=6 and l in k) for k in keys for l in labels)
# Tên chung chung, không dùng làm bằng chứng nhận diện game.
GENERIC = {'port.json','gameinfo.xml','config.json','settings.json','options.ini','config.ini','log.txt',
           'control.txt','data.zip','game.zip','libs.zip','patch.zip','mono.dll','mscorlib.dll'}


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
        suffix=self.path.suffix.lower().lstrip('.')
        if self.path.is_dir():self.kind='folder'
        elif suffix in ('zip','7z'):self.kind=suffix
        elif self.path.is_file():self.kind='file'
        else:raise ValueError('Chỉ nhận ZIP, 7z, thư mục hoặc file ROM.')
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
        if self.kind=='file':
            out.append(Entry(safe_name(self.path.name),self.path.stat().st_size))
        elif self.kind=='folder':
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
            p=subprocess.run([self.sevenzip,'l','-slt','-ba','-sccUTF-8','-p-',str(self.path)],capture_output=True,timeout=120)
            if p.returncode:raise ValueError('Không đọc được 7z, có thể gói hỏng hoặc có mật khẩu.')
            for block in p.stdout.decode('utf-8',errors='strict').replace('\r\n','\n').strip().split('\n\n'):
                fields={}
                for line in block.splitlines():
                    if ' = ' not in line:
                        if line.endswith(' ='):line+=' '   # trường rỗng, ví dụ "Attributes ="
                        else:raise ValueError('Danh sách 7z không hợp lệ.')
                    k,v=line.split(' = ',1)
                    if k in fields:raise ValueError('Danh sách 7z không rõ ràng.')
                    fields[k]=v
                if not fields:continue
                path=fields['Path']
                if os.sep=='\\':path=path.replace('\\','/')   # 7z.exe trên PC thử nghiệm; trên máy giữ chặn '\'
                name=safe_name(path)
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
        if self.kind=='file':
            with self.path.open('rb') as f:transfer(f)
        elif self.kind=='folder':
            path=self.path/name
            if path.is_symlink() or self.path.resolve() not in path.resolve().parents:raise ValueError('Nguồn đã thay đổi.')
            with path.open('rb') as f:transfer(f)
        elif self.kind=='zip':
            with zipfile.ZipFile(self.path) as z,z.open(name) as f:transfer(f)
        else:
            # stdout-only extraction: archive can never choose a filesystem destination.
            with tempfile.TemporaryFile() as errors:
                p=subprocess.Popen([self.sevenzip,'x','-so','-spd','-p-',str(self.path),name],stdout=subprocess.PIPE,stderr=errors)
                stop=_kill_on_cancel(p,cancel,300)
                try:
                    transfer(p.stdout)
                    if p.wait(timeout=5):raise ValueError('Không giải nén được file 7z.')
                finally:
                    stop()
                    p.stdout.close()
        if count!=entry.size:raise ValueError('Gói bị thiếu/truncated file.')
        return digest.hexdigest()
    def extract_7z(self,target,cancel=None):
        """Giải nén cả gói 7z một lần (7z solid giải từng file sẽ rất chậm), rồi đối chiếu
        đúng danh sách đã xem trước: không thừa file, không thiếu, đúng kích thước."""
        target.mkdir()
        with tempfile.TemporaryFile() as errors:
            # -snl không bật: 7-Zip không tạo symlink; -spe tắt; danh sách đã loại link ở list().
            p=subprocess.Popen([self.sevenzip,'x','-y','-bd','-bso0','-bsp0','-p-','-o'+str(target),str(self.path)],
                               stdout=subprocess.DEVNULL,stderr=errors)
            stop=_kill_on_cancel(p,cancel,3600)
            try:
                if p.wait():
                    if cancel and cancel.is_set():raise InterruptedError('Đã hủy cài đặt.')
                    raise ValueError('Không giải nén được 7z (thiếu dung lượng hoặc gói hỏng).')
            finally:stop()
        found={}
        for base,dirs,files in os.walk(target,followlinks=False):
            for n in dirs+files:
                p=Path(base)/n
                if p.is_symlink():raise ValueError('7z tạo ra liên kết; dừng cài.')
            for n in files:
                p=Path(base)/n;found[p.relative_to(target).as_posix()]=p.stat().st_size
        expected={e.name:e.size for e in self.entries}
        if found!=expected:raise ValueError('Nội dung 7z sau khi giải nén khác danh sách gói.')
    def read(self,name,limit=256*1024):
        import io
        if self.by_name[name].size>limit:raise ValueError('Thông tin gói quá lớn.')
        out=io.BytesIO();self.copy(name,out);return out.getvalue()


def _kill_on_cancel(p,cancel,timeout):
    timer=threading.Timer(timeout,p.kill);timer.start()
    stop=threading.Event()
    def watch():
        while not stop.wait(.1):
            if cancel and cancel.is_set():
                if p.poll() is None:p.kill()
                return
    watcher=threading.Thread(target=watch,daemon=True);watcher.start()
    def finish():
        timer.cancel();stop.set();watcher.join(timeout=1)
        if p.poll() is None:p.kill();p.wait()
    return finish


def systems(root):
    result={}
    for p in (root/'Emus').glob('*/config.json'):
        try:
            data=json.loads(p.read_text(encoding='utf-8-sig'));rom=(p.parent/data['rompath']).resolve()
            # Không khai báo extlist (N64, NDS, PPSSPP, DC...) = MainUI nhận mọi file → None
            ext=data.get('extlist')
            if rom.parent==root/'Roms' and rom.is_dir():result[rom.name]=set(ext.lower().split('|')) if ext else None
        except (OSError,ValueError,KeyError,TypeError):continue
    return result


def installed_ports(root):
    """Port PortMaster đã cài: {dir: {'title','inst','refs','gamedata'}}.
    refs = tên file dữ liệu mà script của port nhắc tới (bằng chứng để nhận diện gói)."""
    ports={}
    base=root/PORTS_DIR
    for pj in base.glob('*/port.json'):
        directory=pj.parent.name
        if directory in ('autoinstall','images','videos'):continue
        try:data=json.loads(pj.read_text(encoding='utf-8-sig'))
        except (OSError,ValueError):continue
        texts=[]
        for i in data.get('items') or []:
            if isinstance(i,str) and i.endswith('.sh'):
                try:texts.append((base/i).read_text(encoding='utf-8',errors='replace'))
                except OSError:pass
        ports[directory]=_port_info(directory,data,texts,(pj.parent/'gamedata').is_dir())
    return ports


def _port_info(directory,data,script_texts,has_gamedata=False):
    """Thông tin nhận diện của một port từ port.json + nội dung script .sh của nó."""
    attr=data.get('attr') or {}
    refs=set();uses_gamedata=has_gamedata
    for text in script_texts:
        if 'gamedata' in text:uses_gamedata=True
        for m in SCRIPT_REF.finditer(text):
            name=m.group(0).strip().casefold()
            if name not in GENERIC and '$' not in name:refs.add(name)
        for m in re.finditer(r'gameassembly="?([^"\s]+)',text):refs.add(m.group(1).casefold())
    return {'title':attr.get('title') or directory,'inst':(attr.get('inst') or '')[:1500],
            'refs':refs,'gamedata':uses_gamedata,'availability':attr.get('availability','')}


def pending_ports(root,exclude=None,sevenzip=None):
    """Gói port PortMaster đã chép vào thẻ nhưng CHƯA cài (trong thư mục chép game hoặc autoinstall).
    Dùng để báo người mới: gói dữ liệu này thuộc port nào và phải cài port trước."""
    root=Path(root);found={}
    candidates=list_packages(root)
    auto=root/AUTOINSTALL_DIR
    if auto.is_dir():candidates+=sorted(auto.glob('*.zip'))
    for p in candidates:
        if exclude and p.absolute()==Path(exclude).absolute():continue
        try:
            pkg=Package(p,sevenzip);pm=_portmaster_dir(pkg.entries)
            if not pm or (root/PORTS_DIR/pm/'port.json').exists():continue
            data=json.loads(pkg.read(pm+'/port.json').decode('utf-8-sig'))
            texts=[pkg.read(e.name,512*1024).decode('utf-8','replace') for e in pkg.entries if '/' not in e.name and e.name.endswith('.sh')]
            info=_port_info(pm,data,texts);info['package']=p.name;info['in_autoinstall']=p.parent==auto
            found[pm]=info
        except (OSError,ValueError,KeyError):continue
    return found


def _portmaster_dir(files):
    """Gói port PortMaster: có <dir>/port.json và script .sh ở gốc. Trả <dir> hoặc None."""
    for e in files:
        parts=e.name.split('/')
        if len(parts)==2 and parts[1]=='port.json' and any('/' not in f.name and f.name.endswith('.sh') for f in files):
            return parts[0]
    return None


def _match_port(files,ports,label='',name_only=False):
    """Chọn port có nhiều tên file trùng với script của nó nhất. Trả (dir, prefix, số file khớp, có trùng tên không) hoặc None.
    prefix = lớp thư mục bọc ngoài của gói cần bỏ (ví dụ 'Celeste Linux/').
    Tên gói/thư mục gốc trùng tên port được cộng điểm, để game dùng tên file chung (GameMaker data.win...)
    vẫn nhận ra được; chỉ trùng tên mà không có file nào khớp thì không tính."""
    names={}
    for e in files:names.setdefault(PurePosixPath(e.name).name.casefold(),[]).append(e.name)
    labels={_norm(PurePosixPath(label).stem)}|{_norm(e.name.split('/')[0]) for e in files if '/' in e.name}
    labels.discard('')
    scores=[]
    for directory,info in ports.items():
        hits=[n for n in info['refs'] if n in names]
        strong=[n for n in hits if not WEAK.match(n)]
        named=_name_match(directory,info['title'],labels)
        score=len(strong)+(2 if named and hits else 0)
        if score:scores.append((score,directory,hits))
    if not scores:
        if not name_only:return None
        # Không port nào có file khớp script (port cài tay/thiếu script): chỉ nhận khi đúng 1 port trùng tên gói
        named_only=[d for d,info in ports.items() if _name_match(d,info['title'],labels)]
        if len(named_only)!=1:return None
        tops={e.name.split('/')[0] for e in files}
        prefix=tops.pop()+'/' if len(tops)==1 and all('/' in e.name for e in files) else ''
        return named_only[0],prefix,0,True
    scores.sort(reverse=True)
    if len(scores)>1 and scores[1][0]==scores[0][0]:return None   # hai port ngang điểm: để người dùng chọn
    score,directory,hits=scores[0];named=score>len([n for n in hits if not WEAK.match(n)])
    # Thư mục chứa file trùng nông nhất là gốc dữ liệu game trong gói.
    paths=[PurePosixPath(p) for h in hits for p in names[h]]
    anchor=min(paths,key=lambda p:len(p.parts)).parent
    prefix='' if str(anchor)=='.' else anchor.as_posix()+'/'
    return directory,prefix,len(hits),named


def _port_data_items(files,directory,prefix,info):
    if prefix and not all(e.name.startswith(prefix) for e in files):
        # File nằm ngoài thư mục dữ liệu (readme, ảnh...) thì bỏ qua, không rải lung tung.
        files=[e for e in files if e.name.startswith(prefix)]
    base=PORTS_DIR+'/'+directory+('/gamedata/' if info['gamedata'] else '/')
    rel=lambda n:n[len(prefix):]
    # Gói đã có sẵn lớp gamedata/ thì không lồng thêm.
    if info['gamedata'] and all(rel(e.name).startswith('gamedata/') for e in files):
        base=PORTS_DIR+'/'+directory+'/'
    return [{'source':e.name,'target':base+rel(e.name),'size':e.size} for e in files]


def preview(path,root=Path('/mnt/SDCARD'),system=None,sevenzip=None):
    """Đọc gói, quyết định nơi cài. system: hệ máy người dùng chọn, hoặc 'port:<dir>' để ép vào một port."""
    root=Path(root).resolve();pkg=Package(path,sevenzip);available=systems(root);ports=installed_ports(root)
    manifest=json.loads(pkg.read(MANIFEST).decode('utf-8-sig')) if MANIFEST in pkg.by_name else None
    if manifest and manifest.get('format')!=1:raise ValueError('Phiên bản thông tin gói không hỗ trợ.')
    files=[e for e in pkg.entries if e.name!=MANIFEST]
    system=system or (manifest or {}).get('system')
    kind='rom';port_dir=None;title=None;certainty='Nhận diện nơi cài ROM; chưa xác nhận toàn bộ yêu cầu chơi game'
    items=[];notes=[]
    rooted=all(e.name.split('/')[0] in ROOTED_TOPS for e in files) and not system
    pm_dir=None if (rooted or system) else _portmaster_dir(files)
    if system and system.startswith('port:'):
        port_dir=system[5:]
        if port_dir not in ports:raise ValueError('Port đích chưa được cài.')
        prefix=os.path.commonprefix([e.name for e in files]);prefix=prefix[:prefix.rfind('/')+1] if '/' in prefix else ''
        kind='port_data';title=ports[port_dir]['title'];items=_port_data_items(files,port_dir,prefix,ports[port_dir])
        certainty='Người dùng chọn port; tên file chưa được đối chiếu với script'
    elif rooted:
        kind='rooted';items=[{'source':e.name,'target':e.name,'size':e.size} for e in files]
        certainty='Gói đã sắp sẵn theo thư mục thẻ'
    elif pm_dir:
        kind='portmaster';title=pm_dir
        if not (root/PORTMASTER_DIR).is_dir():
            raise ValueError('Đây là gói port PortMaster nhưng máy chưa cài app PortMaster. Cài PortMaster trước rồi quay lại.')
        try:title=(json.loads(pkg.read(pm_dir+'/port.json').decode('utf-8-sig')).get('attr') or {}).get('title') or pm_dir
        except (KeyError,ValueError):pass
        name=(pkg.path.stem if pkg.kind!='file' else pm_dir)+'.zip'
        items=[{'source':None,'target':AUTOINSTALL_DIR+'/'+name,'size':pkg.path.stat().st_size if pkg.kind=='zip' else None,
                'pack_zip':pkg.kind!='zip','copy_archive':pkg.kind=='zip'}]
        if items[0]['size'] is None:items[0]['size']=sum(e.size for e in files)   # zip STORED: xấp xỉ, kiểm lại khi cài
        certainty='Gói port PortMaster: mở app PortMaster để cài (kèm runtime nếu có Wi-Fi)'
        if pm_dir in ports:notes.append('Port này đã cài; PortMaster sẽ cài đè bản port (không đụng gamedata).')
    else:
        if not system:
            match=_match_port(files,ports,pkg.path.name)
            if match:
                port_dir,prefix,count,named=match;info=ports[port_dir]
                kind='port_data';title=info['title'];items=_port_data_items(files,port_dir,prefix,info)
                certainty='Khớp %d tên file với script của port %s'%(count,title)+(', tên gói trùng tên game' if named else '')
        if kind=='rom':
            if not system:
                candidates={INFER.get('.p8.png' if e.name.lower().endswith('.p8.png') else Path(e.name).suffix.lower()) for e in files}
                candidates.discard(None)
                if len(candidates)==1:system=candidates.pop()
            if not system:
                # Đuôi file chỉ một emulator trên thẻ nhận (theo extlist của Emus/*/config.json)
                exts={Path(e.name).suffix.lower().lstrip('.') for e in files}-{'zip','7z','txt','md','pdf','jpg','png','nfo','url','ini','cfg','json','xml'}
                if exts:
                    owners={k for k,v in available.items() if k!='PORTS' and v is not None and exts<=v}
                    if len(owners)==1:system=owners.pop()
            if not system:
                # Không phải ROM nhận ra được: thử khớp port theo tên gói (port không có script để đối chiếu)
                match=_match_port(files,ports,pkg.path.name,name_only=True)
                if match:
                    port_dir,prefix,count,named=match;info=ports[port_dir]
                    kind='port_data';title=info['title'];items=_port_data_items(files,port_dir,prefix,info)
                    certainty='Tên gói trùng tên game đã cài: '+title
            if kind=='rom' and system not in available:
                # Dữ liệu game của một port mà người dùng đã chép vào nhưng CHƯA cài: chỉ cách cho người mới
                waiting=pending_ports(root,exclude=pkg.path,sevenzip=pkg.sevenzip)
                match=_match_port(files,waiting,pkg.path.name)
                if match:
                    info=waiting[match[0]]
                    step=('Mở app PortMaster để nó cài port xong' if info['in_autoinstall'] else
                          'Cài gói "%s" trước (chọn gói đó, bấm A), rồi mở app PortMaster để nó cài port'%info['package'])
                    raise ValueError('Đây là dữ liệu game của %s, nhưng port %s chưa được cài. %s, sau đó quay lại cài gói này.'
                                     %(info['title'],info['title'],step))
                choices=sorted(k for k in available if k!='PORTS')+['port:'+d for d in sorted(ports)]
                return {'source':str(pkg.path),'needs_system':True,'systems':choices,
                        'labels':{**{k:system_label(k) for k in available},**{'port:'+d:'PORT: '+ports[d]['title'] for d in ports}},
                        'reason':'App chưa nhận ra gói này thuộc máy/game nào.'}
            if kind!='rom':pass
            elif system in ARCHIVE_ROM_SYSTEMS:
                if pkg.kind!='zip':raise ValueError('ROM Arcade cần ZIP gốc của ROM set; không tự chuyển 7z/thư mục thành ROM set.')
                items=[{'source':None,'target':'Roms/'+system+'/'+pkg.path.name,'size':pkg.path.stat().st_size,'copy_archive':True}]
            else:
                for e in files:
                    suffix=Path(e.name).suffix.lower().lstrip('.')
                    accepted=available[system]
                    if (suffix not in accepted) if accepted is not None else (suffix in JUNK_EXT or suffix in ('zip','7z')):continue
                    items.append({'source':e.name,'target':'Roms/'+system+'/'+PurePosixPath(e.name).name,'size':e.size})
    def allowed(target):
        parts=PurePosixPath(safe_name(target)).parts
        if PurePosixPath(target).parent.as_posix()==AUTOINSTALL_DIR and target.endswith('.zip') and kind=='portmaster':
            destination(root,target);return
        if len(parts)<3 or parts[0] not in ROOTED_TOPS:raise ValueError('Gói yêu cầu ghi ngoài thư mục game.')
        if parts[0] in ('Roms','Imgs') and parts[1] not in available:raise ValueError('Hệ máy/emulator đích chưa có trên thẻ: '+parts[1])
        if parts[0]=='Data' and (parts[1]!='ports' or len(parts)<4):raise ValueError('Chỉ ghi được vào Data/ports/<game>/.')
        destination(root,target)
    for item in items:allowed(item['target'])
    repairs=[];targets={i['target'] for i in items}
    declared_configs={c['path'] for c in (manifest or {}).get('config_files',[])}
    for requirement in (manifest or {}).get('required_files',[]):
        target=requirement['path'];allowed(target)
        if target in targets or destination(root,target).is_file():
            if requirement.get('size') is not None:
                size=next((i['size'] for i in items if i['target']==target),None)
                if size is None:size=destination(root,target).stat().st_size
                if size!=requirement['size']:raise ValueError('File sai kích thước: '+target)
            continue
        if target in declared_configs:continue
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
    if not items:raise ValueError('Không tìm thấy file game phù hợp.')
    allitems=items+repairs
    names=[x['target'].casefold() for x in allitems]
    if len(names)!=len(set(names)):raise ValueError('Đích bị trùng.')
    # File đã có trên thẻ: cùng kích thước thì bỏ qua (cài lại gói dữ liệu), khác thì dừng, không ghi đè.
    skipped=0;conflicts=[]
    for x in list(allitems):
        d=destination(root,x['target'])
        if not d.exists():continue
        if x.get('source') and d.is_file() and d.stat().st_size==x['size'] and kind in ('port_data','rooted'):
            items.remove(x);skipped+=1;continue
        conflicts.append(x['target'])
    if conflicts:
        raise ValueError('Đã có %d file khác nội dung, không ghi đè: %s'%(len(conflicts),', '.join(conflicts[:3])))
    if skipped:notes.append('Bỏ qua %d file đã có sẵn, cùng kích thước.'%skipped)
    if not items and not repairs:raise ValueError('Mọi file trong gói đã có sẵn trên thẻ. Không cần cài.')
    total=sum(x['size'] for x in items+repairs)
    if total>MAX_BYTES:raise ValueError('Gói quá lớn.')
    if shutil.disk_usage(root).free<2*total+32*1024**2:raise ValueError('Thẻ không đủ dung lượng để cài và giữ bản tạm.')
    if kind=='port_data' and port_dir and ports[port_dir]['refs']:
        have={PurePosixPath(i['target']).name.casefold() for i in items}
        gd=root/PORTS_DIR/port_dir/('gamedata' if ports[port_dir]['gamedata'] else '')
        onboard={p.name.casefold() for p in gd.glob('*')} if gd.is_dir() else set()
        expected=sorted(n for n in ports[port_dir]['refs'] if n not in have and n not in onboard)
        if expected:notes.append('Script port còn nhắc tới (có thể do port tự tạo): '+', '.join(expected[:6]))
    return {'source':str(pkg.path),'root':str(root),'system':system,'kind':kind,'port_dir':port_dir,'title':title,
            'items':items,'repairs':repairs,'bytes':total,'stamp':pkg.signature,'sevenzip':pkg.sevenzip,
            'certainty':certainty if not manifest else 'Đối chiếu danh sách bắt buộc của gói','notes':notes,
            'target_dir':_common_dir([x['target'] for x in items+repairs])}


def _common_dir(targets):
    parts=[PurePosixPath(t).parent.parts for t in targets]
    common=[]
    for level in zip(*parts):
        if len(set(level))!=1:break
        common.append(level[0])
    return '/'.join(common)


def _write_zip(pkg,out_path,cancel,extracted=None):
    """Đóng gói thư mục/7z thành ZIP (STORED) cho PortMaster autoinstall."""
    with zipfile.ZipFile(out_path,'w',zipfile.ZIP_STORED,allowZip64=True) as z:
        for e in pkg.entries:
            if cancel.is_set():raise InterruptedError('Đã hủy cài đặt.')
            with z.open(zipfile.ZipInfo(e.name,(1980,1,1,0,0,0)),'w',force_zip64=e.size>2**31) as f:
                if extracted is None:pkg.copy(e.name,f,cancel)
                else:
                    with (extracted/e.name).open('rb') as inp:shutil.copyfileobj(inp,f,1024*1024)


def install(plan,cancel=None,progress=None,allow_repairs=False):
    if plan.get('needs_system'):raise ValueError('Chưa chọn hệ máy.')
    if plan['repairs'] and not allow_repairs:raise ValueError('Cần xác nhận tải/tạo các file bổ sung trước.')
    root=Path(plan['root']);pkg=Package(plan['source'],plan['sevenzip'])
    if pkg.signature!=tuple(plan['stamp']):raise ValueError('Nguồn đã đổi sau khi xem trước. Hãy đọc lại gói.')
    cancel=cancel or threading.Event();progress=progress or (lambda text:None)
    entries=[dict(x) for x in plan['items']+plan['repairs']];total=sum(x['size'] for x in entries)
    if shutil.disk_usage(root).free<2*total+32*1024**2:raise ValueError('Thẻ không đủ dung lượng cho cài đặt an toàn.')
    stage=Path(tempfile.mkdtemp(prefix='.xiaozhi-install-',dir=root));committed=[];created_dirs=[]
    try:
        extracted=None
        if pkg.kind=='7z' and any(x.get('source') or x.get('pack_zip') for x in entries):
            progress('Đang giải nén 7z (%d file)...'%len(pkg.entries))
            extracted=stage/'x';pkg.extract_7z(extracted,cancel)
        for index,item in enumerate(entries):
            if cancel.is_set():raise InterruptedError('Đã hủy cài đặt.')
            if index%25==0 or index==len(entries)-1:
                progress('Chuẩn bị %d/%d: %s'%(index+1,len(entries),Path(item['target']).name))
            target=destination(root,item['target'])
            if target.exists():raise ValueError('Đích đã tồn tại. Không ghi đè.')
            temp=stage/str(index)
            if extracted is not None and item.get('source'):
                os.replace(extracted/item['source'],temp)
            elif item.get('pack_zip'):
                _write_zip(pkg,temp,cancel,extracted);item['size']=temp.stat().st_size
            else:
                with temp.open('wb') as f:
                    if 'data' in item:f.write(item['data'])
                    elif 'url' in item:_download(item,f,cancel)
                    elif item.get('copy_archive'):
                        with pkg.path.open('rb') as inp:
                            while True:
                                if cancel.is_set():raise InterruptedError('Đã hủy cài đặt.')
                                chunk=inp.read(1024*1024)
                                if not chunk:break
                                f.write(chunk)
                    else:pkg.copy(item['source'],f,cancel)
                    f.flush();os.fsync(f.fileno())
            if temp.stat().st_size!=item['size']:raise ValueError('Kích thước file không khớp: '+item['target'])
        # No destination is modified until all files/download hashes are validated.
        progress('Đang chuyển file vào thư mục game...')
        for index,item in enumerate(entries):
            if cancel.is_set():raise InterruptedError('Đã hủy cài đặt.')
            target=destination(root,item['target'])
            parents=[];p=target.parent
            while not p.exists():parents.append(p);p=p.parent
            for p in reversed(parents):p.mkdir();created_dirs.append(p)
            with target.open('xb'):pass
            committed.append(target)
            os.replace(stage/str(index),target)
            if target.suffix=='.sh':target.chmod(0o755)
        if hasattr(os,'sync'):os.sync()
        progress('Đã cài xong.')
        return [x.relative_to(root).as_posix() for x in committed]
    except BaseException:
        for p in reversed(committed):p.unlink(missing_ok=True)
        for p in reversed(created_dirs):
            try:p.rmdir()
            except OSError:pass
        raise
    finally:shutil.rmtree(stage,ignore_errors=True)


def _download(item,f,cancel):
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


def remove_source(path,root=Path('/mnt/SDCARD')):
    """Xoá gói gốc sau khi cài (người dùng bấm xác nhận). Chỉ xoá trong thư mục chép game."""
    path=Path(path).absolute();folders={(Path(root)/d).resolve() for d in PACKAGE_DIRS}
    if path.is_symlink() or path.resolve().parent not in folders or path.name==README_NAME:
        raise ValueError('Chỉ xoá gói nằm trong thư mục %s.'%PACKAGE_DIRS[0])
    if path.is_dir():shutil.rmtree(path)
    else:path.unlink()
