#!/usr/bin/env python3
"""Run checks in private bus/state/runtime; keep host display read-only for icons."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

def environment(root, original=None):
    values=dict(os.environ if original is None else original)
    display=values.get('WAYLAND_DISPLAY')
    if display and not Path(display).is_absolute():
        values['WAYLAND_DISPLAY']=str(Path(values.get('XDG_RUNTIME_DIR',f'/run/user/{os.getuid()}'))/display)
    for key in ('NIRI_SOCKET','DBUS_SESSION_BUS_ADDRESS','DBUS_STARTER_ADDRESS','DBUS_STARTER_BUS_TYPE'):
        values.pop(key,None)
    for key,directory in (('XDG_RUNTIME_DIR','runtime'),('XDG_STATE_HOME','state'),
                          ('XDG_CACHE_HOME','cache'),('XDG_CONFIG_HOME','config')):
        path=Path(root)/directory;path.mkdir(mode=0o700,exist_ok=True);values[key]=str(path)
    values['PULSE_SERVER']='unix:'+str(Path(root)/'no-formal-audio')
    values['DBUS_SYSTEM_BUS_ADDRESS']='unix:path='+str(Path(root)/'no-system-bus')
    values['PYTHONDONTWRITEBYTECODE']='1'
    return values

def main(arguments=None):
    with tempfile.TemporaryDirectory(prefix='selandia-unit-') as temporary:
        root=Path(temporary);values=environment(root)
        config=root/'bus.conf'
        config.write_text('<busconfig><type>session</type><listen>unix:tmpdir=/tmp</listen>'
                          '<auth>EXTERNAL</auth><policy context="default">'
                          '<allow send_destination="*"/><allow receive_sender="*"/>'
                          '<allow own="*"/></policy></busconfig>')
        args=arguments if arguments is not None else sys.argv[1:] or ['discover','-s','tests']
        # The full suite needs ~50s. GNU timeout bounds the whole private group,
        # including a test's descendants; kill-after handles ignored SIGTERM.
        return subprocess.run(['timeout','--kill-after=2s','180s','dbus-run-session',
                               '--config-file',str(config),'--',sys.executable,'-B',
                               '-m','unittest',*args],env=values,timeout=185).returncode

if __name__=='__main__':raise SystemExit(main())
