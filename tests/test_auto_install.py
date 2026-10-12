"""Luồng "AI tự cài" của tab Cài gói game. PortMaster (harbourmaster) và Gemini được giả lập; dữ liệu là byte giả."""
import asyncio, json, shutil, sys, tempfile, types, zipfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    import certifi  # noqa: F401
except ImportError:
    sys.modules['certifi'] = types.SimpleNamespace(where=lambda: None)
import game_packages as gp
import game_package_ai as gpa
import trimui_packages as tp

passed = 0


def check(name, cond):
    global passed
    assert cond, name
    passed += 1
    print('PASS ' + name, flush=True)


base = Path(tempfile.mkdtemp(prefix='auto_install_'))
root = base / 'card'
for system, ext in [('GBA', 'gba|zip'), ('SFC', 'sfc|smc|zip')]:
    (root / 'Roms' / system).mkdir(parents=True)
    (root / 'Emus' / system).mkdir(parents=True)
    (root / 'Emus' / system / 'config.json').write_text(json.dumps({'rompath': '../../Roms/' + system, 'extlist': ext}))
(root / 'Apps/PortMaster/PortMaster').mkdir(parents=True)
folder = gp.package_folders(root)[0]
# Port "paid": gói port + gói dữ liệu riêng; chép vào theo thứ tự tên (dữ liệu đứng TRƯỚC port trong danh sách)
with zipfile.ZipFile(folder / 'Zeta Game (PortMaster).zip', 'w') as z:
    z.writestr('Zeta Game.sh', 'cd $GAMEDIR/gamedata\n[ -f ZetaGame.pck ] && run ZetaGame.pck\n')
    z.writestr('zeta/port.json', json.dumps({'items': ['Zeta Game.sh', 'zeta/'], 'attr': {'title': 'Zeta Game', 'runtime': [], 'availability': 'paid',
                                                                                              'inst': 'Purchase the game on Steam and copy ZetaGame.pck into the gamedata folder.'}}))
(folder / 'Du lieu Steam' / 'Zeta').mkdir(parents=True)
(folder / 'Du lieu Steam' / 'Zeta' / 'ZetaGame.pck').write_bytes(b'pck')
with zipfile.ZipFile(folder / 'Mario.zip', 'w') as z:
    z.writestr('Mario.sfc', b's' * 64)
with zipfile.ZipFile(folder / 'Bi an.zip', 'w') as z:
    z.writestr('mystery.bin', b'm')


def fake_portmaster(zip_path, root_, say=None, cancel=None):
    """Giống harbourmaster install: giải port vào Data/ports, xoá zip autoinstall."""
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(root_ / 'Data/ports')
    Path(zip_path).unlink()
    return ['Đã cài port vào mục Ports.']


class Bus:
    def __init__(self):
        self.states = []

    async def emit(self, name, state=None):
        if state:
            self.states.append(dict(state))


async def main():
    bus = Bus()
    ui = tp.PackageUI(bus, root)
    await ui.open()
    names = [p.name for p in ui.entries]
    check('package list from CHEP_GAME_VAO_DAY', names == ['Bi an.zip', 'Du lieu Steam', 'Mario.zip', 'Zeta Game (PortMaster).zip'])
    with patch.object(tp, 'ensure_runtimes', lambda *a: []), \
         patch.object(gpa, 'suggest_target', lambda *a: (None, 'Tên file quá chung chung.')):
        # Một gói: dữ liệu game mà port còn nằm trong thư mục → tự cài port trước
        ui.index = names.index('Du lieu Steam')
        await ui.auto_one()
        check('data package installs its waiting port first', (root / 'Data/ports/zeta/port.json').is_file())
        check('then data goes to gamedata', (root / 'Data/ports/zeta/gamedata/ZetaGame.pck').read_bytes() == b'pck')
        check('result screen says done', bus.states[-1]['status'] == 'AI đã cài xong')
        check('headline is plain Vietnamese', bus.states[-1]['lines'][0] == 'Đã chép dữ liệu game cho Zeta Game, chơi được trong menu Ports.')
        check('port auto-installed first, not reported as missing game', bus.states[-1]['lines'][1] == 'Đã tự cài port Zeta Game trước.')
        check('no English PortMaster text on screen', not any('Purchase' in l for st in bus.states for l in st.get('lines', [])))
        check('both sources offered for removal', {p.name for p in ui.installed_sources} == {'Zeta Game (PortMaster).zip', 'Du lieu Steam'})
        # Mở lại app (đối tượng mới): gói đã cài rời danh sách chính, hiện ở Lịch sử, gói gốc KHÔNG bị xoá
        ui2 = tp.PackageUI(Bus(), root)
        await ui2.open()
        left = [p.name for p in ui2.entries]
        check('installed packages leave the main list after reopening', 'Du lieu Steam' not in left and 'Zeta Game (PortMaster).zip' not in left and 'Mario.zip' in left)
        check('source packages are NOT deleted', (folder / 'Du lieu Steam').exists() and (folder / 'Zeta Game (PortMaster).zip').exists())
        await ui2.handle(311)   # R1: lịch sử cài đặt (máy không có phím R2)
        hist = {r[1] for r in ui2.state['rows']}
        check('history lists installed packages', ui2.state['status'] == 'Lịch sử cài đặt' and hist == {'Du lieu Steam', 'Zeta Game (PortMaster).zip'})
        check('no delete option anywhere in history', all(k != 'X' for k, _ in ui2.state['controls']))
        check('history page offers R1 to go back', ('R1', 'Về danh sách gói') in ui2.state['controls'])
        await ui2.handle(311)   # R1 lần nữa: về danh sách
        check('R1 again returns to list', ui2.page == 'list')        # Tất cả: ROM tự nhận, gói lạ AI không chắc → bỏ qua và báo lý do
        await ui.open()
        await ui.auto_all()
        last = bus.states[-1]
        check('summary counts installed packages', last['status'] == 'AI đã cài 1/2 gói')
        check('ROM installed by auto all', (root / 'Roms/SFC/Mario.sfc').is_file())
        check('unsure package skipped with reason', any(l.startswith('✗ Bi an.zip') and 'chung chung' in l for l in last['lines']))
    with patch.object(gpa, 'suggest_target', lambda *a: ('GBA', 'Tên game là game Game Boy Advance.')):
        await ui.open()
        ui.index = [p.name for p in ui.entries].index('Bi an.zip')
        await ui.auto_one()
        check('AI choice used without asking, blocked if files do not fit', bus.states[-1]['status'] == 'AI chưa cài được gói này')
    check('no staging folders left', not list(root.glob('.xiaozhi-install-*')))

try:
    asyncio.run(main())
    print('SUMMARY pass=%d fail=0' % passed, flush=True)
finally:
    shutil.rmtree(base, ignore_errors=True)
