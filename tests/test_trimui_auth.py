"""Run on ARM64/Python 3.11 with packaged pylibs; no cloud account used."""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aiohttp import web
from src.utils import config_manager as configs
from src.utils.resource_finder import clear_path_caches
from trimui_auth import authorize_cloud, render_auth_screen, run_startup_gate

passed = 0

def check(name, condition):
    global passed
    assert condition, name
    passed += 1
    print('PASS ' + name, flush=True)


def new_config(device):
    os.environ['XIAOZHI_DATA_DIR'] = tempfile.mkdtemp(prefix='auth_test_')
    configs.reset_config(); clear_path_caches()
    config = configs.initialize_config()
    config.update_configs({'SYSTEM_OPTIONS.DEVICE_ID': device,
        'SYSTEM_OPTIONS.NETWORK.OTA_VERSION_URL': 'http://127.0.0.1:18765/ota/'})
    return config


async def tests():
    bindings = {}; mode = {'value': 'normal'}; requests = []
    async def ota(request):
        device = request.headers['Device-Id']; requests.append((device, request.headers.get('Activation-Version')))
        await request.json()
        if mode['value'] == 'ota_error': return web.Response(status=503)
        token = 'token-' + device
        data = {'websocket': {'url': 'ws://127.0.0.1:18765/ws', 'token': token}}
        if mode['value'] == 'missing_ws': return web.json_response({})
        if mode['value'] == 'bad_token': data['websocket']['token'] = 'bad-token'
        if device not in bindings:
            data['activation'] = {'code': '123456', 'challenge': 'challenge-' + device}
        return web.json_response(data)
    async def activate(request):
        device = request.headers['Device-Id']; data = await request.json()
        check('activation payload signed for its device',bool(data['Payload']['hmac']) and data['Payload']['challenge'] == 'challenge-' + device)
        if mode['value'] == 'pending': return web.Response(status=202)
        bindings[device] = 'account-' + device
        return web.Response(status=200)
    async def websocket(request):
        token = request.headers.get('Authorization', '')
        if token not in ['Bearer token-' + d for d in bindings]: return web.Response(status=401)
        socket = web.WebSocketResponse(); await socket.prepare(request)
        async for message in socket:
            if message.type == web.WSMsgType.TEXT:
                if json.loads(message.data).get('type') == 'hello':
                    await socket.send_json({'type': 'hello', 'transport': 'websocket'})
        return socket
    app = web.Application(); app.router.add_post('/ota/', ota); app.router.add_post('/ota/activate', activate); app.router.add_get('/ws', websocket)
    runner = web.AppRunner(app); await runner.setup(); await web.TCPSite(runner,'127.0.0.1',18765).start()
    try:
        states = []
        async def show(state): states.append(state)
        cfg = new_config('02:00:00:00:00:01')
        check('new device has no packaged URL/token', not cfg.get_config('SYSTEM_OPTIONS.NETWORK.WEBSOCKET_URL') and not cfg.get_config('SYSTEM_OPTIONS.NETWORK.WEBSOCKET_ACCESS_TOKEN'))
        check('first account enters after activation and hello', await authorize_cloud(show))
        check('first account shows six-digit code before ready',any(s.get('code') == '123456' for s in states) and states[-1].get('ready'))
        token_a = cfg.get_config('SYSTEM_OPTIONS.NETWORK.WEBSOCKET_ACCESS_TOKEN')
        states.clear(); check('already bound account rechecks server',await authorize_cloud(show))
        check('already bound device shows no new activation code',not any(s.get('code') for s in states))
        cfg = new_config('02:00:00:00:00:02'); states.clear()
        check('second account independently activates',await authorize_cloud(show))
        check('second account cannot reuse first token',cfg.get_config('SYSTEM_OPTIONS.NETWORK.WEBSOCKET_ACCESS_TOKEN') != token_a)
        check('two distinct account bindings',len(bindings) == 2 and len(set(bindings.values())) == 2)
        check('OTA always requests activation v2',all(v == '2' for _,v in requests))
        mode['value'] = 'bad_token'; states.clear()
        check('rejected websocket token cannot enter',not await authorize_cloud(show))
        check('rejected token never reports ready',not any(s.get('ready') for s in states))
        mode['value'] = 'ota_error'; states.clear()
        check('offline OTA cannot enter',not await authorize_cloud(show))
        mode['value'] = 'missing_ws'; new_config('02:00:00:00:00:03'); states.clear()
        check('malformed OTA without websocket cannot enter',not await authorize_cloud(show))
        mode['value'] = 'pending'; new_config('02:00:00:00:00:04'); states.clear()
        arrived = asyncio.Event()
        async def pending_show(state):
            states.append(state)
            if state.get('code'): arrived.set()
        task = asyncio.create_task(authorize_cloud(pending_show)); await asyncio.wait_for(arrived.wait(),10)
        check('unbound device waits with activation screen',not task.done() and not any(s.get('ready') for s in states))
        task.cancel(); await asyncio.gather(task,return_exceptions=True)
        check('cancelled activation never reports ready',not any(s.get('ready') for s in states))
        # Full entry must not construct UI/audio container when authorization fails.
        import trimui_run
        with patch('trimui_auth.authorize_cloud', return_value=False), patch.object(trimui_run,'ServiceContainer',side_effect=AssertionError('unauthorized container')):
            os.environ['XIAOZHI_HEADLESS'] = '1'
            check('entry refuses UI/audio before authorization',await trimui_run.main() == 1)
        from src.core.event_bus import EventBus, Events
        bus=EventBus();controller=SimpleNamespace(authorized=True,player=None,mode='server')
        await trimui_run.setup_supplement_listeners(SimpleNamespace(event_bus=bus),controller)
        await bus.emit(Events.NETWORK_ERROR,'HTTP 401')
        check('runtime network error locks controls',controller.authorized is False)
        check('runtime error never silently switches local',controller.mode == 'server')
        from src.utils.tls import client_ssl_context
        import ssl
        ctx=client_ssl_context()
        check('TLS verifies peer and hostname',ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname)
        # Test actual gate input handling using pipe evdev records and in-memory framebuffer.
        class Framebuffer:
            width=1024; height=768
            def present(self,image): pass
            def close(self): pass
        readfd,writefd=os.pipe()
        async def stalled(show):
            await show({'status':'Waiting','busy':True});await asyncio.sleep(60)
        try:
            import struct
            os.write(writefd,struct.pack('<qqHHi',0,0,1,307,1))  # Y is not a bypass
            with patch('trimui_display.Framebuffer',Framebuffer),patch('trimui_auth.authorize_cloud',stalled):
                gate=asyncio.create_task(run_startup_gate(lambda:'/proc/self/fd/'+str(readfd)))
                await asyncio.sleep(.2);check('Y cannot bypass startup authorization',not gate.done())
                os.write(writefd,struct.pack('<qqHHi',0,0,1,316,1))
                check('MENU cancels waiting gate',await asyncio.wait_for(gate,2) is False)
        finally:os.close(readfd);os.close(writefd)
        for name,state in [('activation',{'status':'Liên kết tài khoản của bạn','detail':'Trên điện thoại vào xiaozhi.me, đăng nhập tài khoản của bạn, chọn Thêm thiết bị và nhập mã dưới đây.','code':'123456','busy':True}),('offline',{'status':'Chưa kết nối được tài khoản','detail':'Không kết nối được. Kiểm tra Wi-Fi, ngày giờ và chứng chỉ HTTPS rồi thử lại.'})]:
            render_auth_screen(1024,768,state).save('/tmp/auth-'+name+'.png')
        print('SUMMARY pass=%d fail=0'%passed,flush=True)
    finally:await runner.cleanup()

if __name__ == '__main__': asyncio.run(tests())
