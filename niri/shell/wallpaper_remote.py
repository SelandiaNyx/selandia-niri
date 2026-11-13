"""Bounded same-user IPC for atomic renderer handoff in the resident service."""
import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import struct

from i18n import tr

LIMIT = 8_100_000
NO_SERVICE = object()


def path():
    runtime = Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}'))
    display = os.environ.get('NIRI_SOCKET') or os.environ.get('WAYLAND_DISPLAY', 'default')
    state = Path(os.environ.get('XDG_STATE_HOME', str(Path.home()/'.local/state'))).resolve()
    # A copied/test state tree must not control the formal service just because
    # it inherited the same compositor/runtime. Both peers name their state.
    identity = display + '\0' + str(state)
    return runtime / ('selandia-wallpaper-' + hashlib.sha256(identity.encode()).hexdigest()[:20] + '.sock')


def receive(client):
    data = bytearray()
    while len(data) <= LIMIT:
        part = client.recv(min(65536, LIMIT + 1 - len(data)))
        if not part:
            break
        data.extend(part)
        if b'\n' in data:
            return json.loads(data.split(b'\n', 1)[0])
    raise ValueError(tr('Invalid wallpaper service message', '壁纸服务消息无效'))


def request(command, **values):
    target = path()
    try:
        info = target.lstat()
    except FileNotFoundError:
        return NO_SERVICE
    if info.st_uid != os.getuid() or not stat.S_ISSOCK(info.st_mode):
        raise RuntimeError(tr('Untrusted wallpaper service socket', '壁纸服务套接字不可信'))
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(50)
        try:
            client.connect(str(target))
        except (FileNotFoundError, ConnectionRefusedError):
            return NO_SERVICE
        _, uid, _ = struct.unpack('3i', client.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        if uid != os.getuid():
            raise RuntimeError(tr('Wallpaper service owner mismatch', '壁纸服务所有者不匹配'))
        client.sendall((json.dumps({'command': command, 'values': values}, ensure_ascii=False) + '\n').encode())
        response = receive(client)
        if not isinstance(response, dict) or type(response.get('ok')) is not bool:
            raise RuntimeError(tr('Invalid wallpaper service response', '壁纸服务响应无效'))
        if not response['ok']:
            raise RuntimeError(response.get('error') or tr('Wallpaper service failed', '壁纸服务失败'))
        return response.get('result')


class Server:
    def __init__(self):
        self.path = path()
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            self.socket.bind(str(self.path))
        except OSError:
            info = self.path.lstat()
            if info.st_uid != os.getuid() or not stat.S_ISSOCK(info.st_mode):
                self.socket.close()
                raise RuntimeError(tr("Untrusted wallpaper service socket", "壁纸服务套接字不可信"))
            # Never unlink another live supervisor's socket.
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                try:
                    probe.connect(str(self.path))
                except ConnectionRefusedError:
                    self.path.unlink()
                    self.socket.bind(str(self.path))
                else:
                    self.socket.close()
                    raise RuntimeError(tr('Wallpaper service already running', '壁纸服务已在运行'))
        self.inode = self.path.stat().st_ino
        os.chmod(self.path, 0o600)
        self.socket.listen(8)
        self.socket.setblocking(False)

    def poll(self, dispatch):
        try:
            client, _ = self.socket.accept()
        except BlockingIOError:
            return False
        with client:
            client.settimeout(2)
            try:
                _, uid, _ = struct.unpack('3i', client.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                if uid != os.getuid():
                    raise ValueError('peer')
                request = receive(client)
                if not isinstance(request, dict) or not isinstance(request.get('values'), dict):
                    raise ValueError('request')
                result = dispatch(request.get('command'), request['values'])
                response = {'ok': True, 'result': result}
            except Exception as error:
                response = {'ok': False, 'error': str(error)}
            try:
                client.sendall((json.dumps(response, ensure_ascii=False) + '\n').encode())
            except (BrokenPipeError, OSError):
                pass  # Committed state survives a closed control center.
        return True

    def close(self):
        self.socket.close()
        try:
            info = self.path.lstat()
            if info.st_ino == self.inode and stat.S_ISSOCK(info.st_mode): self.path.unlink()
        except FileNotFoundError:
            pass
