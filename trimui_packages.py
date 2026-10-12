"""Tab "Cài gói game" trong Xiaozhi AI: xem trước gói trên thẻ rồi mới cài bằng nút máy.

L1/R1 chuyển giữa tab "Trợ lý AI" và tab này (SELECT là phím hệ thống thoát app/game, không dùng).
Gemini (Y) chỉ phân tích và đề xuất; mọi thao tác ghi thẻ vẫn do game_packages kiểm tra.
"""
import asyncio
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from game_packages import preview, install, remove_source, system_label, list_packages, PACKAGE_DIRS

KIND_LABEL = {'rom': 'ROM', 'rooted': 'Gói sắp sẵn theo thư mục thẻ', 'portmaster': 'Port PortMaster',
              'port_data': 'Dữ liệu game cho port đã cài'}
BG, CARD, CARD_SEL = (16, 22, 34), (26, 38, 54), (38, 62, 84)
ACCENT, WARN, MUTED, ERR = (70, 220, 185), (255, 185, 65), (175, 190, 210), (255, 110, 110)
_fonts = {}
logger = logging.getLogger('trimui_packages')


def _font(size):
    if size not in _fonts:
        _fonts[size] = ImageFont.truetype(str(Path(__file__).parent / 'fonts/DejaVuSans.ttf'), size)
    return _fonts[size]


def _fit(d, text, font, width):
    """Cắt chữ cho vừa 1 dòng (chia đôi, ít lần đo chữ — A53 đo chậm)."""
    text = str(text)
    if d.textlength(text, font=font) <= width:
        return text
    lo, hi = 1, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if d.textlength(text[:mid] + '…', font=font) <= width:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + '…'


def _wrap(d, text, font, width):
    out, line = [], ''
    for word in str(text).split():
        candidate = (line + ' ' + word).strip()
        if line and d.textlength(candidate, font=font) > width:
            out.append(line)
            line = word
        else:
            line = candidate
    out.append(line)
    return out


def _size(n):
    return '%.1f MB' % (n / 1024**2) if n >= 1024**2 else '%d KB' % max(1, n // 1024)


def draw_tabs(d, active):
    """Thanh tab dùng chung cho 2 không gian của app (vẽ ở đầu màn hình)."""
    tabs = [('L1', 'Trợ lý AI'), ('R1', 'Cài gói game')]
    x = 32
    for i, (key, label) in enumerate(tabs):
        text = label + '  ' + key if key == 'R1' else key + '  ' + label
        tw = int(d.textlength(text, font=_font(24))) + 36
        on = i == active
        d.rounded_rectangle((x, 16, x + tw, 60), radius=12, fill=ACCENT if on else CARD)
        d.text((x + 18, 25), text, font=_font(24), fill=BG if on else MUTED)
        x += tw + 12


def render_packages(width, height, state):
    im = Image.new('RGB', (width, height), BG)
    d = ImageDraw.Draw(im)
    w, h = width, height
    draw_tabs(d, 1)
    title_color = {'error': ERR, 'warn': WARN}.get(state.get('tone'), ACCENT)
    d.text((32, 78), _fit(d, state.get('status', ''), _font(34), w - 64), font=_font(34), fill=title_color)
    top, bottom = 132, h - 150
    rows = state.get('rows')
    if rows is not None:
        # Danh sách có ô chọn (gói / hệ máy)
        sel = state.get('selected', 0)
        row_h = 62
        visible = max(1, (bottom - top - 34) // (row_h + 8))
        start = max(0, min(sel - visible // 2, len(rows) - visible))
        if not rows:
            for i, line in enumerate(_wrap(d, state.get('empty', ''), _font(26), w - 64)):
                d.text((32, top + 10 + i * 36), line, font=_font(26), fill=MUTED)
        for i, row in enumerate(rows[start:start + visible]):
            idx = start + i
            y = top + i * (row_h + 8)
            d.rounded_rectangle((32, y, w - 32, y + row_h), radius=10, fill=CARD_SEL if idx == sel else CARD)
            if idx == sel:
                d.rounded_rectangle((32, y, 40, y + row_h), radius=4, fill=ACCENT)
            tag, name, info = row
            x = 56
            if tag:
                tw = int(d.textlength(tag, font=_font(20))) + 20
                d.rounded_rectangle((x, y + 16, x + tw, y + 46), radius=6, fill=WARN if tag in ('THƯ MỤC', 'PORT') else ACCENT)
                d.text((x + 10, y + 19), tag, font=_font(20), fill=BG)
                x += tw + 16
            info_w = int(d.textlength(info, font=_font(22))) if info else 0
            d.text((x, y + 15), _fit(d, name, _font(27), w - 80 - x - info_w), font=_font(27), fill='white')
            if info:
                d.text((w - 56 - info_w, y + 19), info, font=_font(22), fill=MUTED)
        if len(rows) > visible:
            label = '%d/%d' % (sel + 1, len(rows))
            d.text((w - 32 - d.textlength(label, font=_font(24)), 86), label, font=_font(24), fill=MUTED)
        if state.get('hint'):
            d.text((32, bottom - 26), _fit(d, state['hint'], _font(21), w - 64), font=_font(21), fill=MUTED)
    else:
        # Bảng thông tin (xem trước / kết quả) + đoạn chữ cuộn được
        y = top
        for key, value in state.get('table', []):
            d.text((32, y), key, font=_font(24), fill=MUTED)
            for line in _wrap(d, value, _font(26), w - 300)[:2]:
                d.text((240, y - 1), line, font=_font(26), fill='white')
                y += 36
            y += 6
        if state.get('table'):
            y += 10
        lines = []
        for text in state.get('lines', []):
            lines.extend(_wrap(d, text, _font(25), w - 64))
        scroll = max(0, min(state.get('scroll', 0), max(0, len(lines) - 1)))
        progress = state.get('progress')
        limit = bottom - (60 if progress is not None else 10)
        for line in lines[scroll:]:
            if y > limit - 34:
                d.text((w - 220, limit - 26), '▼ Xuống: cuộn', font=_font(20), fill=MUTED)
                break
            d.text((32, y), line, font=_font(25), fill='white')
            y += 34
        if progress is not None:
            d.rounded_rectangle((32, bottom - 46, w - 32, bottom - 16), radius=12, fill=CARD)
            fill = int((w - 68) * max(0.0, min(1.0, progress)))
            if fill > 12:
                d.rounded_rectangle((34, bottom - 44, 34 + fill, bottom - 18), radius=11, fill=ACCENT)
    # Phím bấm dạng huy hiệu (giống màn Trợ lý AI)
    x, y = 32, h - 128
    for key, label in state.get('controls', []):
        bw = int(d.textlength(key, font=_font(22))) + 24
        lw = int(d.textlength(label, font=_font(22)))
        if x + bw + lw + 40 > w - 32:
            x, y = 32, y + 50
        d.rounded_rectangle((x, y, x + bw + lw + 26, y + 42), radius=8, fill=CARD)
        d.rounded_rectangle((x + 4, y + 4, x + 4 + bw, y + 38), radius=6, fill=WARN if key == 'Y' else ACCENT)
        d.text((x + 16, y + 9), key, font=_font(22), fill=BG)
        d.text((x + bw + 14, y + 9), label, font=_font(22), fill='white')
        x += bw + lw + 40
    d.text((32, h - 30), 'L1: về Trợ lý AI  |  MENU: thoát app', font=_font(20), fill=(150, 170, 195))
    return im


class PackageUI:
    def __init__(self, bus, root=Path('/mnt/SDCARD')):
        self.bus = bus
        self.root = Path(root)
        self.active = False
        self.busy = False
        self.entries = []
        self.index = 0
        self.plan = None
        self.page = 'list'
        self.state = {}
        self.cancel = threading.Event()
        self.installed_source = None
        self.system_index = 0
        self.advice_back = 'list'
        self.manual_plan = None   # danh sách chọn tay khi app/AI chưa nhận ra gói
        self.ai_choice = None
        # Luồng riêng: executor mặc định của asyncio hay bị các tác vụ âm thanh của app chiếm
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='packages')

    async def run(self, fn, *args):
        return await asyncio.get_running_loop().run_in_executor(self.pool, fn, *args)

    async def show(self, state):
        logger.info('[packages] %s (page=%s)', state.get('status'), self.page)
        self.state = state
        await self.bus.emit('trimui_packages', self.state)

    async def leave(self):
        if self.busy:
            return
        self.active = False
        await self.bus.emit('trimui_packages', None)

    # ---------- danh sách gói ----------
    async def open(self):
        self.active = True
        self.page = 'list'
        self.plan = None
        self.entries = await self.run(list_packages, self.root)
        self.index = min(self.index, max(0, len(self.entries) - 1))
        await self.list_page()

    def _row(self, p):
        if p.is_dir():
            try:
                n = sum(1 for x in p.rglob('*') if x.is_file())
            except OSError:
                n = 0
            return ('THƯ MỤC', p.name, '%d file' % n)
        suffix = p.suffix.lower().lstrip('.')
        tag = suffix.upper() if suffix in ('zip', '7z') else 'ROM'
        try:
            info = _size(p.stat().st_size)
        except OSError:
            info = ''
        return (tag, p.name, info)

    async def list_page(self):
        await self.show({'status': 'Chọn gói để xem trước', 'rows': [self._row(p) for p in self.entries],
                         'selected': self.index,
                         'empty': 'Chưa có game nào để cài. Cách chép: cắm thẻ nhớ vào máy tính → mở thư mục '
                                  + PACKAGE_DIRS[0] + ' (ngoài cùng thẻ) → chép game vào (zip, 7z, thư mục hoặc file ROM) '
                                  '→ cắm thẻ lại máy → vào đây bấm X để làm mới.',
                         'hint': 'Chép game vào thư mục ' + PACKAGE_DIRS[0] + ' ở ngoài cùng thẻ nhớ (có file HUONG_DAN.txt)',
                         'controls': [('A', 'Xem trước'), ('Y', 'Hỏi AI về gói'), ('X', 'Làm mới'), ('B', 'Về Trợ lý AI')]})

    # ---------- xem trước ----------
    async def read_plan(self, system=None):
        if not self.entries:
            return
        self.busy = True
        try:
            await self.show({'status': 'Đang đọc gói...', 'lines': [self.entries[self.index].name], 'controls': []})
            entry = self.entries[self.index]
            self.plan = await self.run(preview, entry, self.root, system)
            self.ai_choice = None
            if self.plan.get('needs_system'):
                # App chưa tự nhận ra: nhờ AI chọn trong các nơi cài hợp lệ, người mới không phải tự chọn
                self.manual_plan = self.plan
                await self.show({'status': 'AI đang nhận diện gói...', 'lines': [entry.name,
                                 'App chưa tự nhận ra gói này, đang nhờ AI xem tên và loại file để chọn đúng chỗ cài.'], 'controls': []})
                why = ''
                try:
                    from game_package_ai import suggest_target
                    choice, why = await self.run(suggest_target, entry, self.plan['systems'], self.plan.get('labels', {}), self.root)
                except Exception as exc:
                    choice, why = None, str(exc)
                if not choice:
                    self.page = 'systems'
                    self.system_index = 0
                    self.plan['reason'] = 'AI cũng chưa chắc: ' + why if why else self.plan['reason']
                    await self.system_page()
                    return
                self.plan = await self.run(preview, entry, self.root, choice)
                self.ai_choice = (self.manual_plan.get('labels', {}).get(choice, choice), why)
            self.page = 'preview'
            plan = self.plan
            kind_text = KIND_LABEL.get(plan['kind'], plan['kind'])
            if plan['kind'] == 'rom' and plan.get('system'):
                kind_text = 'ROM ' + system_label(plan['system'])
            table = [('Gói', Path(plan['source']).name),
                     ('Loại', kind_text + (' — ' + plan['title'] if plan.get('title') else '')),
                     ('Nhận diện', plan['certainty']),
                     ('Cài vào', '/' + (plan.get('target_dir') or '')),
                     ('Dung lượng', '%s  (%d file)' % (_size(plan['bytes']), len(plan['items']) + len(plan['repairs'])))]
            lines = list(plan.get('notes', []))
            if self.ai_choice:
                table[2] = ('Nhận diện', 'AI chọn: ' + self.ai_choice[0])
                lines.insert(0, 'Lý do: ' + self.ai_choice[1])
            if plan['repairs']:
                lines.append('Cần bổ sung theo khai báo của gói:')
                lines.extend(('Tải HTTPS: ' if 'url' in x else 'Tạo file: ') + x['target'] for x in plan['repairs'])
            if plan['kind'] == 'portmaster':
                lines.append('Sau khi chép: mở app PortMaster, port sẽ tự cài (cần Wi-Fi nếu thiếu runtime).')
            lines.append('Không ghi đè file có sẵn. Chỉ chép file, không tự chạy game.')
            controls = [('A', 'Tải/tạo bổ sung và cài' if plan['repairs'] else 'Cài'), ('Y', 'Hỏi AI thêm'), ('B', 'Quay lại')]
            if self.ai_choice:
                controls.insert(2, ('X', 'Chọn nơi khác'))
            await self.show({'status': 'Xem trước — chưa cài', 'table': table, 'lines': lines, 'controls': controls})
        except Exception as exc:
            self.plan = None
            self.page = 'blocked'
            await self.show({'status': 'Chưa thể cài gói này', 'tone': 'error',
                             'table': [('Gói', self.entries[self.index].name)], 'lines': [str(exc)],
                             'controls': [('Y', 'Nhờ AI phân tích'), ('B', 'Quay lại')]})
        finally:
            self.busy = False

    async def system_page(self):
        labels = self.plan.get('labels', {})
        choices = self.plan['systems']
        await self.show({'status': 'Gói này là game của máy nào?', 'tone': 'warn',
                         'rows': [('PORT' if c.startswith('port:') else 'HỆ', labels.get(c, c).removeprefix('PORT: '), '')
                                  for c in choices],
                         'selected': self.system_index, 'hint': self.plan['reason'],
                         'controls': [('A', 'Chọn và xem trước'), ('Y', 'Hỏi AI nên chọn gì'), ('B', 'Quay lại')]})

    # ---------- cài ----------
    async def do_install(self):
        if not self.plan or self.plan.get('needs_system'):
            return
        self.busy = True
        self.page = 'install'
        self.cancel.clear()
        loop = asyncio.get_running_loop()
        name = Path(self.plan['source']).name
        cancel_keys = [('B', 'Hủy và dọn bản tạm'), ('MENU', 'Hủy')]
        try:
            await self.show({'status': 'Đang cài gói...', 'lines': [name], 'progress': 0.0, 'controls': cancel_keys})

            def progress(text):
                m = re.search(r'(\d+)/(\d+)', text)
                frac = int(m.group(1)) / max(1, int(m.group(2))) if m else (1.0 if 'xong' in text else None)
                state = {'status': 'Đang cài gói...', 'lines': [name, text], 'progress': frac, 'controls': cancel_keys}
                asyncio.run_coroutine_threadsafe(self.show(state), loop)

            kind, source = self.plan['kind'], self.plan['source']
            result = await self.run(install, self.plan, self.cancel, progress, True)
            self.installed_source = source
            tail = {'portmaster': 'Bước tiếp: thoát app (MENU), mở app PortMaster — nó tự cài port. Nếu game cần dữ liệu riêng '
                                  '(bản mua trên Steam/itch.io), quay lại đây cài gói dữ liệu sau khi port đã cài xong.',
                    'port_data': 'Mở game trong mục Ports. Lần đầu port có thể mất vài phút xử lý dữ liệu.'}.get(
                kind, 'Về menu game, làm mới danh sách để thấy game mới.')
            import posixpath
            where = posixpath.commonpath(result) if len(result) > 1 else posixpath.dirname(result[0])
            sample = [posixpath.relpath(r, where) for r in result[:3]] + (['… và %d file khác' % (len(result) - 3)] if len(result) > 3 else [])
            await self.show({'status': 'Đã cài xong', 'table': [('Gói', name), ('Đã chép', '%d file' % len(result)), ('Vị trí', '/' + where)],
                             'lines': sample + [tail],
                             'controls': [('X', 'Xoá gói gốc'), ('B', 'Danh sách gói')]})
        except Exception as exc:
            self.installed_source = None
            await self.show({'status': 'Không cài được gói', 'tone': 'error', 'table': [('Gói', name)],
                             'lines': [str(exc), 'Không có file nào trên thẻ bị thay đổi.'],
                             'controls': [('B', 'Danh sách gói')]})
        finally:
            self.busy = False
            self.page = 'result'
            self.plan = None

    async def remove_installed(self):
        if not self.installed_source:
            return
        source = self.installed_source
        self.installed_source = None
        try:
            await self.run(remove_source, source, self.root)
            await self.show({'status': 'Đã xoá gói gốc', 'lines': [Path(source).name], 'controls': [('B', 'Danh sách gói')]})
        except Exception as exc:
            await self.show({'status': 'Không xoá được gói gốc', 'tone': 'error', 'lines': [str(exc)],
                             'controls': [('B', 'Danh sách gói')]})

    # ---------- AI ----------
    async def ask_ai(self):
        if not self.entries:
            return
        self.busy = True
        self.advice_back = self.page
        try:
            from game_package_ai import analyze
            await self.show({'status': 'AI đang phân tích gói...', 'lines': [
                self.entries[self.index].name,
                'Chỉ gửi tên file, kích thước và vài file cấu hình nhỏ — không gửi ROM, dữ liệu game hay key.'],
                'controls': []})
            result = await self.run(analyze, self.entries[self.index], self.root)
            lines = ['Đã đối chiếu trên máy: ' + (', '.join(result['verified_missing']) or 'chưa xác định chắc chắn file nào thiếu.'),
                     'AI đề xuất (chưa xác minh):', result['summary']]
            lines += ['• ' + s for s in result['suggestions']]
            if result['uncertainties']:
                lines.append('Chưa chắc chắn:')
                lines += ['• ' + s for s in result['uncertainties']]
            lines.append('AI không tự sửa, tải hay cài gì. Bạn quyết định ở màn xem trước.')
            await self.show({'status': 'AI phân tích gói', 'lines': lines, 'scroll': 0,
                             'controls': [('Lên/Xuống', 'Cuộn'), ('B', 'Quay lại')]})
        except Exception as exc:
            await self.show({'status': 'AI chưa phân tích được', 'tone': 'warn', 'lines': [str(exc)],
                             'controls': [('B', 'Quay lại')]})
        finally:
            self.busy = False
            self.page = 'advice'

    # ---------- phím ----------
    async def handle(self, code, repeat=False):
        if not repeat:
            logger.info('[packages] phim %s (page=%s busy=%s)', code, self.page, self.busy)
        if self.busy:
            if code in (304, 316) and self.page == 'install':   # B / MENU: hủy, cài đặt tự hoàn tác
                self.cancel.set()
            return
        if code in (103, 108, 544, 545):
            step = -1 if code in (103, 544) else 1
            if self.page == 'list' and self.entries:
                n = len(self.entries)
                self.index = max(0, min(n - 1, self.index + step)) if repeat else (self.index + step) % n
                await self.list_page()
            elif self.page == 'systems':
                n = len(self.plan['systems'])
                self.system_index = max(0, min(n - 1, self.system_index + step)) if repeat else (self.system_index + step) % n
                await self.system_page()
            elif 'lines' in self.state:
                self.state['scroll'] = max(0, self.state.get('scroll', 0) + step)
                await self.bus.emit('trimui_packages', self.state)
            return
        if repeat:
            return
        if code == 304:   # B
            if self.page == 'list':
                await self.leave()
            elif self.page == 'advice' and self.advice_back == 'systems' and self.plan:
                self.page = 'systems'
                await self.system_page()
            else:
                await self.open()
        elif code == 305:   # A
            if self.page == 'list':
                await self.read_plan()
            elif self.page == 'systems':
                await self.read_plan(self.plan['systems'][self.system_index])
            elif self.page == 'preview':
                await self.do_install()
        elif code == 308:   # X
            if self.page == 'list':
                await self.open()
            elif self.page == 'preview' and self.ai_choice and self.manual_plan:
                self.plan = self.manual_plan
                self.page = 'systems'
                self.system_index = 0
                await self.system_page()
            elif self.page == 'result':
                await self.remove_installed()
        elif code == 307:   # Y
            if self.page in ('list', 'preview', 'blocked', 'systems'):
                await self.ask_ai()
