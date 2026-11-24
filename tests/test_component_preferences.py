import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import Mock
import os

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'niri/shell'))
import component_preferences as c
import island
import bar_backend
import appearance
import eww_input


class ComponentTests(unittest.TestCase):
    def test_toggle_bar_uses_managed_stop_start_instead_of_waybar_signals(self):
        with patch('reload_components.active',return_value=True),patch('reload_components.service') as service:
            c.toggle_bar();service.assert_called_once_with('waybar','stop')
        with patch('reload_components.active',return_value=False),patch('reload_components.service') as service:
            c.toggle_bar();self.assertEqual([call.args for call in service.call_args_list],[('waybar','reset-failed'),('waybar','start')])

    def test_workspace_slice_is_ordered_and_keeps_the_active_workspace(self):
        items=[{'id':i,'idx':i,'output':'A','is_active':i==7} for i in range(8,0,-1)]
        for count in (3,5):
            visible=island.visible_workspaces(items,'A',count)
            self.assertEqual(len(visible),count)
            self.assertEqual([row['id'] for row in visible],sorted(row['id'] for row in visible))
            self.assertIn(7,[row['id'] for row in visible if row['active']])

    def test_malformed_drill_and_observation_records_do_not_break_components(self):
        with tempfile.TemporaryDirectory() as temporary,patch.object(c,'path',return_value=Path(temporary)/'components.json'):
            marker=c.path().parent/'component-drill.json'
            for value in ([],None,{'until':'invalid'}):
                marker.write_text(json.dumps(value));c.health('eww-ready')
            log=c.path().parent/'component-health.jsonl'
            log.write_text(json.dumps({'event':'eww-ready','session':[],'time':None}))
            self.assertFalse(c.stability()['ready'])


    def test_ipc_clients_cannot_fork_an_unmanaged_daemon(self):
        with patch.object(bar_backend.subprocess,'run',return_value=Mock(returncode=0)) as run:
            bar_backend.client(Path('/tmp/private'),'open-many','left')
            self.assertIn('--no-daemonize',run.call_args.args[0])

    def test_dead_or_stale_bridge_is_not_healthy(self):
        with tempfile.TemporaryDirectory() as temporary:
            sock=Path(temporary)/'island.sock';snapshot=sock.with_suffix('.json')
            with patch.object(island,'endpoint',return_value=sock):
                self.assertFalse(bar_backend.bridge_alive())
                snapshot.write_text(json.dumps({'bridge_pid':os.getpid(),'heartbeat':int(bar_backend.time.monotonic())}))
                self.assertTrue(bar_backend.bridge_alive())
                snapshot.write_text(json.dumps({'bridge_pid':os.getpid(),'heartbeat':0}))
                self.assertFalse(bar_backend.bridge_alive())
    def test_observation_deduplicates_restarts_and_never_invents_seven_days(self):
        from datetime import datetime,timezone
        with tempfile.TemporaryDirectory() as temporary,patch.object(c,'path',return_value=Path(temporary)/'components.json'):
            log=c.path().parent/'component-health.jsonl'
            records=[{'time':datetime.now(timezone.utc).isoformat(),'event':'eww-ready','session':'same-login'}]*12
            log.write_text('\n'.join(json.dumps(row) for row in records))
            state=c.stability();self.assertFalse(state['ready']);self.assertEqual(state['successful_logins'],1)
            log.write_text(log.read_text()+'\n'+json.dumps({'event':'fallback','time':datetime.now(timezone.utc).isoformat()}))
            self.assertEqual(c.stability()['successful_logins'],0)

    def test_compositor_identity_error_precedes_any_preference_write(self):
        with tempfile.TemporaryDirectory() as temporary,patch.object(c,'path',return_value=Path(temporary)/'components.json'):
            c.path().write_text('{"bar":"waybar"}');before=c.path().read_bytes()
            with patch.dict(os.environ,NIRI_SOCKET='/tmp/test-only.sock'),patch('session_identity.peer',side_effect=RuntimeError('peer gone')):
                with self.assertRaises(RuntimeError):c.choose('bar','eww')
            self.assertEqual(c.path().read_bytes(),before)

    def test_scoped_preload_removed_before_gtk4_children_preserves_other_library(self):
        source={'LD_PRELOAD':'/keep.so:/our.so','SELANDIA_EWW_INPUT_LIB':'/our.so','SELANDIA_EWW_GEOMETRY':'/tmp/runtime','OTHER':'yes'}
        self.assertEqual(eww_input.clean_environment(source),{'LD_PRELOAD':'/keep.so','OTHER':'yes'})
        self.assertIn('SELANDIA_EWW_INPUT_LIB',source)

    def test_model_volume_refresh_does_not_reset_the_mixer(self):
        with tempfile.TemporaryDirectory() as temporary:
            socket=Path(temporary)/'island.sock';socket.with_suffix('.json').write_text('{"volume":65,"has_audio":true}')
            with patch.object(island,'endpoint',return_value=socket),patch.object(sys,'argv',['island.py','volume','65']),patch.object(island,'call') as call,patch.object(island,'send') as send:
                island.main();call.assert_not_called();send.assert_not_called()
            with patch.object(island,'endpoint',return_value=socket),patch.object(sys,'argv',['island.py','volume','40']),patch.object(island,'call') as call,patch.object(island,'send'):
                island.main();call.assert_called_once_with(['pactl','set-sink-volume','@DEFAULT_SINK@','40.0%'])

    def test_eww_start_failure_reaps_child_cleans_runtime_and_reports_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            child=Mock();child.poll.return_value=1
            with patch.object(bar_backend.signal,'signal'),patch.dict(os.environ,XDG_RUNTIME_DIR=temporary),patch.object(bar_backend.component_preferences,'effective',return_value='eww'),patch.object(bar_backend.eww_input,'library',return_value=Path('/tmp/input.so')),patch.object(appearance,'apply_settings'),patch.object(bar_backend,'outputs',return_value=[('fake',1600)]),patch.object(bar_backend.subprocess,'Popen',return_value=child),patch.object(bar_backend,'unavailable',side_effect=RuntimeError('failure sentinel')) as unavailable:
                with self.assertRaisesRegex(RuntimeError,'failure sentinel'):bar_backend.run()
            child.wait.assert_called_once();self.assertEqual(list(Path(temporary).iterdir()),[])
            self.assertIn('daemon exited',unavailable.call_args.args[0])
    def test_invalid_independent_fields_keep_valid_preferences(self):
        with tempfile.TemporaryDirectory() as temporary,patch.object(c,'path',return_value=Path(temporary)/'components.json'):
            c.path().write_text(json.dumps({'bar':[],'launcher':'anyrun','terminal':'unknown'}))
            self.assertEqual(c.load(),c.DEFAULTS)


    def test_terminal_adapter_preserves_literal_command_arguments(self):
        args=['--config','discard.conf','--class','settings','--title','A "quote"','--hold','sudo','pacman','-Syu','literal $()']
        result=c.terminal_command(args,settings=c.DEFAULTS,which=lambda value:value)
        self.assertIn('--config-file',result)
        self.assertEqual(result[-5:],['--command','sudo','pacman','-Syu','literal $()'])
        self.assertIn('A "quote"',result)
        self.assertNotIn('discard.conf',result)

    def test_managed_failure_restores_preference(self):
        with tempfile.TemporaryDirectory() as temporary,patch.object(c,'path',return_value=Path(temporary)/'components.json'):
            c.path().write_text('{"bar":"waybar"}');before=c.path().read_bytes()
            with patch.dict(c.os.environ,{},clear=True),patch('reload_components.service',side_effect=[None,RuntimeError('failure'),None]):
                with self.assertRaises(RuntimeError):c.choose('bar','eww')
            self.assertEqual(c.path().read_bytes(),before)

    def test_geometry_keeps_an_island_gap_at_wide_and_narrow_sizes(self):
        for width in (568,800,1067,1600,3840):
            for size in (12,16,20):
                g=bar_backend.geometry(width,size)
                self.assertLessEqual(g['left']+12+g['island']/2,width/2)
                self.assertGreaterEqual(width-g['right']-12-g['island']/2,width/2)

    def test_only_center_island_contains_clock_and_three_bounded_layers(self):
        text,names=bar_backend.render([('monitor',1600)])
        self.assertEqual(len(names),3)
        definitions=text.split('(defwindow ')
        self.assertNotIn('state.clock',definitions[1])
        self.assertNotIn('state.clock',definitions[2])
        self.assertIn('bar-right',definitions[2])
        self.assertIn('state.clock',definitions[3])
        self.assertNotIn(':width "100%"',text)

    def test_events_expire_prioritize_and_dismiss_without_mutating_audio(self):
        p=island.Events();p.receive({'action':'notification','title':'X','summary':'<b>Hello</b>\nworld'},10)
        self.assertEqual(p.current(11,True),'notification')
        self.assertEqual(p.details['summary'],'Hello world')
        self.assertEqual(p.current(19,True),'media')
        p.receive({'action':'show','kind':'volume'},20)
        self.assertEqual(p.current(21,True),'volume')
        p.receive({'action':'dismiss'},22)
        self.assertEqual(p.current(23,False),'idle')
        p.receive([] ,23)

    def test_invalid_slider_values_never_reach_a_command(self):
        for value in ('nan','inf',-1,101):
            with self.assertRaises(ValueError):island.percent(value)

    def test_notification_close_targets_only_its_preview_and_preserves_other_osd(self):
        p=island.Events()
        p.receive({'action':'notification','notification_id':7,'title':'A'},10)
        p.receive({'action':'notification-close','notification_id':6},11)
        self.assertEqual(p.current(11,False),'notification')
        p.receive({'action':'notification','notification_id':8,'title':'B'},12)
        p.receive({'action':'notification-close','notification_id':7},13)
        self.assertEqual(p.current(13,False),'notification')
        p.receive({'action':'notification-close','notification_id':8},14)
        self.assertEqual(p.current(14,True),'media')
        self.assertEqual(p.details,{})
        p.receive({'action':'notification','notification_id':9,'title':'C'},15)
        p.receive({'action':'show','kind':'volume'},16)
        p.receive({'action':'notification-close','notification_id':9},17)
        self.assertEqual(p.current(17,False),'volume')

    def test_notification_timeout_is_bounded_and_bad_durations_are_safe(self):
        for duration,expected in ((.45,.45),(100,8),(float('nan'),8),(float('inf'),8),(-1,8),('1',8),(True,8)):
            with self.subTest(duration=duration):
                p=island.Events()
                p.receive({'action':'notification','duration':duration,'title':'A'},10)
                self.assertEqual(p.current(10+expected-.01,False),'notification')
                self.assertEqual(p.current(10+expected,False),'idle')

    def test_rust_theme_outputs_follow_every_opacity_and_font(self):
        import tomllib
        for opacity in (.20,.25,.30,1):
            settings={**appearance.DEFAULTS,'opacity':opacity,'font':'Noto Sans','mono_font':'monospace','font_size':16}
            files=appearance.render_files(settings)
            self.assertIn(f'{opacity:.3f}',files['eww.css'])
            self.assertIn('16px',files['eww.css'])
            self.assertIn('16px',files['anyrun.css'])
            parsed=tomllib.loads(files['alacritty.toml'])
            self.assertEqual(parsed['window']['opacity'],opacity)
            self.assertEqual(parsed['font']['normal']['family'],'monospace')
