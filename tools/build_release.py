"""Build a clean update on top of a previous release ZIP (ARM64 runtime + pylibs), overlay current source.
Usage: python tools/build_release.py --base-zip XiaozhiAI-TrimUI-BrickPro-v1.0.3.zip --output-dir dist
"""
import argparse, hashlib, json, re, zipfile
from pathlib import Path
parser=argparse.ArgumentParser();parser.add_argument('--base-zip',type=Path,required=True);parser.add_argument('--output-dir',type=Path,required=True);args=parser.parse_args()
root=Path(__file__).resolve().parents[1];args.output_dir.mkdir(parents=True,exist_ok=True)
version=re.search(r'VERSION = "([^"]+)"',(root/'trimui_auth.py').read_text(encoding='utf-8')).group(1)
name='XiaozhiAI-TrimUI-BrickPro-v'+version+'.zip';target=args.output_dir/name
changed=['trimui_auth.py','trimui_run.py','trimui_display.py','src/utils/tls.py','src/activation/ota.py','src/activation/client.py',
         'src/protocols/websocket_protocol.py','src/bootstrap/plugin_wiring.py',
         # 1.1.0: tab Cài gói game + AI tự cài
         'trimui_packages.py','game_packages.py','game_package_ai.py',
         'local_ai/HUONG_DAN_GEMINI.txt','local_ai/HUONG_DAN_CAI_GAME_CHO_AI.md',
         'bin/7zz.aarch64','third_party/7zip/LICENSE.txt','third_party/7zip/README-7zip.txt','third_party/7zip/SOURCE.txt',
         'third_party/7zip/7z2604-src.tar.xz']
overlays={'Apps/XiaozhiAI/'+n:(root/n).read_bytes() for n in changed}
overlays['Apps/XiaozhiAI/VERSION']=(version+'\n').encode()
overlays['Apps/XiaozhiAI/CHANGELOG.md']=(root/'CHANGELOG.md').read_bytes()
overlays['HUONG_DAN_CAI_DAT.txt']=(root/'HUONG_DAN_CAI_DAT.txt').read_bytes()
# Thư mục chép game cho người mới, có sẵn hướng dẫn khi giải nén gói vào thẻ
import importlib.util
spec=importlib.util.spec_from_file_location('gp',root/'game_packages.py');gp=importlib.util.module_from_spec(spec);spec.loader.exec_module(gp)
overlays[gp.PACKAGE_DIRS[0]+'/'+gp.README_NAME]=gp.README_TEXT.encode('utf-8')
def forbidden(name):
    parts=Path(name).parts
    return '__pycache__' in parts or name.endswith(('.pyc','.bak','.log')) or Path(name).name in {
        'efuse.json','gemini_key.txt','user_stats.json','kien_thuc_da_hoc.md','huong_dan_port_vi.json'} or '/config/config.json' in name
with zipfile.ZipFile(args.base_zip) as base,zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as out:
    for item in base.infolist():
        if item.is_dir() or forbidden(item.filename) or item.filename in overlays:continue
        out.writestr(item.filename,base.read(item))
    for name,data in overlays.items():out.writestr(name,data)
with zipfile.ZipFile(target) as check:
    assert check.testzip() is None
    assert not any(forbidden(n) for n in check.namelist())
    meta=json.loads(check.read('Apps/XiaozhiAI/config.json'))
    assert meta['launch']=='launch.sh'
    for n in changed:
        if n.endswith('.py'):compile(check.read('Apps/XiaozhiAI/'+n).decode('utf-8-sig'),n,'exec')
    assert check.read('Apps/XiaozhiAI/bin/7zz.aarch64')[:4]==b'\x7fELF'
sha=hashlib.file_digest(target.open('rb'),'sha256').hexdigest()
(target.with_suffix('.zip.sha256')).write_text(sha+'  '+target.name+'\n',encoding='ascii')
print(target);print('SHA256',sha)
