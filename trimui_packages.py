"""Gamepad UI: review a local package, then explicitly confirm installation."""
import asyncio
import threading
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
from game_packages import preview,install,remove_source

KIND_LABEL={'rom':'ROM','rooted':'Gói sắp sẵn theo thư mục thẻ','portmaster':'Port PortMaster (cài qua app PortMaster)','port_data':'Dữ liệu game cho port đã cài'}


def render_packages(width,height,state):
    im=Image.new('RGB',(width,height),(16,22,34));d=ImageDraw.Draw(im)
    path=str(Path(__file__).parent/'fonts/DejaVuSans.ttf');scale=min(width/1024,height/768)
    def font(n):return ImageFont.truetype(path,max(14,int(n*scale)))
    x=32*scale;y=30*scale
    d.text((x,y),'CÀI GÓI GAME',font=font(40),fill=(70,220,185));y+=70*scale
    lines=[state.get('status',''),*state.get('lines',[])]
    visible=[]
    for text in lines:
        line=''
        for word in str(text).split():
            candidate=(line+' '+word).strip()
            if line and d.textlength(candidate,font=font(25))>width-2*x:visible.append(line);line=word
            else:line=candidate
        visible.append(line)
    offset=state.get('scroll',0)
    for line in visible[offset:offset+13]:
        d.text((x,y),line,font=font(25),fill='white');y+=36*scale
    d.text((x,height-100*scale),state.get('controls',''),font=font(23),fill=(70,220,185))
    d.text((x,height-55*scale),'SELECT: về AI | MENU: thoát | Lên/Xuống: chọn/cuộn',font=font(21),fill=(175,190,210))
    return im


class PackageUI:
    def __init__(self,bus,root=Path('/mnt/SDCARD')):
        self.bus=bus;self.root=Path(root);self.active=False;self.busy=False
        self.entries=[];self.index=0;self.plan=None;self.page='list';self.state={};self.cancel=threading.Event()
        self.installed_source=None
    async def show(self,status,lines=None,controls='',scroll=0):
        self.state={'status':status,'lines':lines or [],'controls':controls,'scroll':scroll}
        await self.bus.emit('trimui_packages',self.state)
    async def open(self):
        self.active=True;self.page='list';self.plan=None
        folder=self.root/'GamePackages';folder.mkdir(exist_ok=True)
        self.entries=sorted([p for p in folder.iterdir() if not p.is_symlink() and not p.name.startswith('.')],key=lambda p:p.name.casefold())
        self.index=min(self.index,max(0,len(self.entries)-1));await self.list_page()
    async def list_page(self):
        lines=['Chép ZIP, 7z, thư mục game hoặc file ROM vào GamePackages trên thẻ.']
        start=max(0,self.index-3)
        lines.extend(('> ' if i==self.index else '  ')+p.name for i,p in enumerate(self.entries) if start<=i<start+9)
        if not self.entries:lines.append('Chưa có gói game.')
        await self.show('Chọn gói để đọc thông tin',lines,'A: xem gói | X: làm mới danh sách')
    async def read_plan(self,system=None):
        if not self.entries:return
        self.busy=True
        try:
            await self.show('Đang đọc gói...',controls='B: chờ phân tích kết thúc')
            self.plan=await asyncio.to_thread(preview,self.entries[self.index],self.root,system)
            if self.plan.get('needs_system'):
                self.page='systems';self.system_index=0;await self.system_page();return
            self.page='preview'
            plan=self.plan;lines=[Path(plan['source']).name,'Loại: '+KIND_LABEL.get(plan['kind'],plan['kind'])+(' — '+plan['title'] if plan.get('title') else ''),plan['certainty'],
                'Dung lượng: %.1f MiB'%(plan['bytes']/1024**2),
                'Đích: '+(plan.get('target_dir') or 'gốc thẻ')+'/  (%d file)'%(len(plan['items'])+len(plan['repairs']))]
            if plan['repairs']:
                lines.append('Cần bổ sung theo khai báo:')
                lines.extend(('Tải HTTPS: ' if 'url' in x else 'Tạo file: ')+x['target'] for x in plan['repairs'])
            lines.extend(plan.get('notes',[]))
            lines.append('Không ghi đè game có sẵn. Chỉ cài file, không tự chạy game.')
            await self.show('XEM TRƯỚC — CHƯA CÀI',lines,('A: xác nhận tải/tạo và cài' if plan['repairs'] else 'A: cài')+' | X: hỏi Gemini | B: quay lại')
        except Exception as exc:
            self.plan=None;self.page='blocked'
            await self.show('Chưa thể cài gói',[str(exc)],'X: Gemini phân tích tên file/config | B: quay lại')
        finally:self.busy=False
    async def system_page(self):
        choices=self.plan['systems'];start=max(0,self.system_index-3)
        labels=self.plan.get('labels',{})
        await self.show('Chọn hệ máy / port của gói',[self.plan['reason']]+[('> ' if i==self.system_index else '  ')+labels.get(n,n) for i,n in enumerate(choices) if start<=i<start+10],'A: chọn và đọc lại | B: quay lại')
    async def do_install(self):
        if not self.plan or self.plan.get('needs_system'):return
        self.busy=True;self.page='install';self.cancel.clear();loop=asyncio.get_running_loop()
        try:
            await self.show('Đang cài gói...',controls='B/SELECT/MENU: hủy và dọn bản tạm')
            def progress(text):
                asyncio.run_coroutine_threadsafe(self.show(text,controls='B/SELECT/MENU: hủy'),loop)
            kind=self.plan['kind'];source=self.plan['source']
            result=await asyncio.to_thread(install,self.plan,self.cancel,progress,True)
            self.installed_source=source
            tail={'portmaster':'Mở app PortMaster để hoàn tất cài port (cần Wi-Fi nếu thiếu runtime).',
                  'port_data':'Mở game trong mục Ports. Lần đầu port có thể mất vài phút xử lý dữ liệu.'}.get(kind,'Về menu game, làm mới danh sách để mở.')
            await self.show('ĐÃ CÀI FILE GAME',['Đã chép %d file.'%len(result)]+result[:8]+[tail,'Chép đúng thư mục không đảm bảo mọi Port chạy được.'],'X: xoá gói gốc trong GamePackages | B: danh sách gói')
        except Exception as exc:self.installed_source=None;await self.show('Không cài được gói',[str(exc)],'B: danh sách gói')
        finally:self.busy=False;self.page='result';self.plan=None
    async def ask_gemini(self):
        if not self.entries:return
        self.busy=True
        try:
            from game_package_ai import analyze
            await self.show('Gemini đang đọc tên file và cấu hình...',controls='Không gửi ROM, file game hoặc API key trong nội dung gói.')
            result=await asyncio.to_thread(analyze,self.entries[self.index],self.root)
            self.page='advice'
            lines=['ĐÃ ĐỐI CHIẾU: '+(', '.join(result['verified_missing']) or 'Chưa xác định file thiếu chắc chắn.'),
                   'GEMINI ĐỀ XUẤT — CHƯA XÁC MINH:',result['summary'],*result['suggestions'],*result['uncertainties'],
                   'Đề xuất này không tự sửa file, tải file hay mở khóa cài đặt.']
            await self.show('PHÂN TÍCH GEMINI',lines,'Lên/Xuống: cuộn | B: quay lại')
        except Exception as exc:
            self.page='advice';await self.show('Gemini chưa phân tích được',[str(exc)],'B: quay lại')
        finally:self.busy=False
    async def handle(self,code):
        if self.busy:
            if code in (304,314,316):self.cancel.set()
            return
        if code==314:
            self.active=False;await self.bus.emit('trimui_packages',None);return
        if code==304:await self.open();return
        if code in (103,108,544,545):
            step=-1 if code in (103,544) else 1
            if self.page=='list' and self.entries:
                self.index=(self.index+step)%len(self.entries);await self.list_page()
            elif self.page=='systems':
                self.system_index=(self.system_index+step)%len(self.plan['systems']);await self.system_page()
            else:
                self.state['scroll']=max(0,self.state.get('scroll',0)+step);await self.bus.emit('trimui_packages',self.state)
            return
        if code==305:
            if self.page=='list':await self.read_plan()
            elif self.page=='systems':await self.read_plan(self.plan['systems'][self.system_index])
            elif self.page=='preview':await self.do_install()
        elif code==308:
            if self.page=='list':await self.open()
            elif self.page=='result':await self.remove_installed()
            else:await self.ask_gemini()
    async def remove_installed(self):
        if not self.installed_source:return
        source=self.installed_source;self.installed_source=None
        try:
            await asyncio.to_thread(remove_source,source,self.root)
            await self.show('Đã xoá gói gốc',[Path(source).name],'B: danh sách gói')
        except Exception as exc:await self.show('Không xoá được gói gốc',[str(exc)],'B: danh sách gói')
