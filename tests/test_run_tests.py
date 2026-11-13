import os
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import run_tests

class TestIsolation(unittest.TestCase):
    def test_inherited_formal_services_and_state_are_not_reachable(self):
        original={'NIRI_SOCKET':'/formal/niri.sock','WAYLAND_DISPLAY':'wayland-1',
                  'XDG_RUNTIME_DIR':'/formal/runtime','XDG_STATE_HOME':'/formal/state',
                  'DBUS_SESSION_BUS_ADDRESS':'unix:path=/formal/bus',
                  'DBUS_SYSTEM_BUS_ADDRESS':'unix:path=/formal/system-bus','PULSE_SERVER':'unix:/formal/pulse'}
        before=dict(original)
        with tempfile.TemporaryDirectory() as root:
            values=run_tests.environment(root,original)
            self.assertNotIn('NIRI_SOCKET',values);self.assertNotIn('DBUS_SESSION_BUS_ADDRESS',values)
            self.assertEqual(values['WAYLAND_DISPLAY'],'/formal/runtime/wayland-1')
            for key in ('XDG_RUNTIME_DIR','XDG_STATE_HOME','XDG_CACHE_HOME','XDG_CONFIG_HOME'):
                self.assertTrue(Path(values[key]).is_relative_to(root))
                self.assertEqual(Path(values[key]).stat().st_mode&0o777,0o700)
            self.assertNotEqual(values['PULSE_SERVER'],original['PULSE_SERVER'])
            self.assertEqual(values['DBUS_SYSTEM_BUS_ADDRESS'],'unix:path='+str(Path(root)/'no-system-bus'))
            self.assertNotEqual(values['DBUS_SYSTEM_BUS_ADDRESS'],original['DBUS_SYSTEM_BUS_ADDRESS'])
        self.assertEqual(original,before)
