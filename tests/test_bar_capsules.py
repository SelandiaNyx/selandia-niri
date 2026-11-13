"""Focused software metadata and compact side capsules."""
from pathlib import Path
import os
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'niri/shell'))
import appearance,bar_backend,island,i18n


class BarCapsuleTests(unittest.TestCase):
    def tearDown(self):i18n.set_language(None);island.application_name.cache_clear()

    def test_focused_application_prefers_desktop_name_and_preserves_plain_title(self):
        with patch.object(island,'application_name',return_value='Example Browser'):
            data=island.focused_application({'id':42,'app_id':'org.example.Browser','title':'<b>Literal</b> "quote"\nsecond line'})
        self.assertEqual(data['app_name'],'Example Browser')
        self.assertEqual(data['window_title'],'<b>Literal</b> "quote" second line')
        self.assertEqual(data['window_id'],42)

    def test_missing_and_malformed_metadata_are_readable_in_both_languages(self):
        for language,desktop,unknown in [('en_US','Desktop','Unknown application'),('zh_CN','桌面','未知应用')]:
            i18n.set_language(language)
            for invalid in (None,[],True):self.assertEqual(island.focused_application(invalid)['app_name'],desktop)
            self.assertEqual(island.focused_application({'app_id':[],'title':123})['app_name'],unknown)
            self.assertEqual(island.focused_application({'title':'XWayland title'})['app_name'],'XWayland title')

    def test_metadata_controls_and_length_cannot_inject_commands_or_markup(self):
        with patch.object(island,'application_name',side_effect=lambda value:value):
            value=island.focused_application({'app_id':'<literal> $()\x00','title':'x'*1000+'\x1b'})
        self.assertEqual(value['app_name'],'<literal> $()')
        self.assertEqual(len(value['window_title']),512)
        rendered,_=bar_backend.render([('probe',800)])
        self.assertIn(':text {state.app_name}',rendered)
        self.assertNotIn(':markup {state.app_name}',rendered)
        self.assertIn(':tooltip {state.window_title}',rendered)

    def test_desktop_values_uses_the_cached_snapshot_without_running_the_shell(self):
        outputs={'DP-1':{'logical':{'width':1600}},'HDMI-A-1':{'logical':{'width':800}}}
        workspaces=[{'id':index,'idx':index,'output':'DP-1','is_active':index==1,'name':'W'+str(index)} for index in range(1,7)]
        workspaces.append({'id':20,'idx':1,'output':'HDMI-A-1','is_active':True,'name':None})
        snapshot={'available':True,'window':{'id':9,'app_id':'org.example.App','title':'T'},'workspaces':workspaces}
        with patch.object(island,'application_name',return_value='Example App'),patch.object(island,'call',side_effect=AssertionError('the shell must not run')):
            data=island.desktop_values(snapshot,outputs)
        self.assertEqual(data['app_name'],'Example App')
        self.assertEqual(data['window_id'],9)
        self.assertEqual([item['id'] for item in data['workspaces']['DP-1']],[1,2,3,4,5])
        self.assertEqual([item['id'] for item in data['workspaces']['HDMI-A-1']],[20])
        self.assertEqual(data['workspaces']['DP-1'][0]['active'],True)
        self.assertEqual(data['workspaces']['HDMI-A-1'][0]['name'],'1')

    def test_desktop_values_reports_unavailable_and_empty_focus_in_both_languages(self):
        for language,unavailable,title in [('en_US','Unavailable','Focused application unavailable'),('zh_CN','不可用','当前应用不可用')]:
            i18n.set_language(language)
            data=island.desktop_values({'available':False,'window':None,'workspaces':[]},{'DP-1':{},'HDMI-A-1':{}})
            self.assertEqual(data['app_name'],unavailable)
            self.assertEqual(data['window_title'],title)
            self.assertEqual(data['app_id'],'')
            self.assertIsNone(data['window_id'])
            self.assertEqual(data['workspaces'],{'DP-1':[],'HDMI-A-1':[]})
        i18n.set_language('en_US')
        with patch.object(island,'application_name',return_value=''):
            data=island.desktop_values({'available':True,'window':None,'workspaces':[]},{'DP-1':{'logical':{'width':1600}}})
        self.assertEqual(data['app_name'],'Desktop')
        self.assertEqual(data['window_title'],'No focused window')
        self.assertEqual(data['workspaces'],{'DP-1':[]})

    def test_desktop_values_limits_visible_workspaces_by_output_width(self):
        snapshot={'available':True,'window':{'id':1,'app_id':'org.example.App','title':'T'},
                  'workspaces':[{'id':index,'idx':index,'output':'DP-1','is_active':index==1} for index in range(1,8)]}
        with patch.object(island,'application_name',return_value='App'):
            wide=island.desktop_values(snapshot,{'DP-1':{'logical':{'width':1300}}})
            narrow=island.desktop_values(snapshot,{'DP-1':{'logical':{'width':1299}}})
        self.assertEqual(len(wide['workspaces']['DP-1']),5)
        self.assertEqual(len(narrow['workspaces']['DP-1']),3)
        self.assertEqual([item['id'] for item in narrow['workspaces']['DP-1']],[1,2,3])

    def test_software_capsule_only_on_left_clock_action_remains_calendar(self):
        rendered,names=bar_backend.render([('probe',1600)],size=16)
        left,right,center=rendered.split('(defwindow ')[1:]
        self.assertIn('current-app',left)
        self.assertNotIn('current-app',right+center)
        self.assertIn(' calendar',right)
        self.assertIn(':truncate true',left)
        self.assertEqual(len(names),3)

    def test_height_changes_do_not_alter_horizontal_geometry_or_island_limit(self):
        for size in (12,16,20):
            for width in (800,1600,3840):
                shape=bar_backend.geometry(width,size)
                self.assertGreaterEqual(shape['left'],min(round(250*max(1,size/12)),round(width*.27)))
                self.assertEqual(shape['right'],min(round(760*max(1,size/12)),round(width*(.40 if (width<1500 or size>=15) else .45))))
                self.assertGreaterEqual(shape['height'],44)
        self.assertLess(bar_backend.geometry(3840,16)['height'],max(44,round(16*2.8+10)))

    def test_metrics_values_are_compact_and_handle_missing_readings(self):
        values=island.metrics_values({
            'cpu_percent':12.4,
            'memory':{'percent':37.6,'used':6*1024**3,'total':16*1024**3},
            'network':{'interface':'wlan0','down_bps':1024**2,'up_bps':2048},
            'temperatures':[{'name':'CPU · package','celsius':51.2}],
            'gpus':[{'name':'iGPU','percent':None,'temperature':48}],
        })
        self.assertEqual(values['cpu_text'],'12%')
        self.assertEqual(values['memory_text'],'38%')
        self.assertIn('MiB/s',values['network_text'])
        self.assertEqual(values['temperature_text'],'51°C')
        self.assertEqual(values['gpu_text'],'48°C')
        self.assertTrue(values['metrics_available'])
        self.assertIn('wlan0',values['metrics_detail'])
        self.assertIn('CPU · package',values['metrics_detail'])
        empty=island.metrics_values({})
        self.assertEqual((empty['cpu_text'],empty['memory_text'],empty['network_text'],
                          empty['temperature_text'],empty['gpu_text']),('—','—','—','—','—'))
        self.assertFalse(empty['metrics_available'])

    def test_side_capsule_ellipses_leave_expanded_island_style_separate(self):
        files=appearance.render_files(appearance.DEFAULTS)
        self.assertIn('.segment .pill:checked',files['eww.css'])
        self.assertIn('border-radius: 999px',files['eww.css'])
        self.assertIn('border-radius: 22px; padding: 8px 12px',files['eww.css'])

    def test_reservation_covers_idle_capsules_without_double_struts(self):
        for size in (12,16,20):
            with self.subTest(size=size):
                reserved=bar_backend.reserved_height(size)
                self.assertGreaterEqual(reserved,bar_backend.capsule_height(size)+12)
                self.assertGreaterEqual(reserved,round(size*2.8+22))
                generated=appearance.render_files({**appearance.DEFAULTS,'font_size':size})
                self.assertIn('struts { top 0; }',generated['theme.kdl'])

    def test_bar_reservation_environment_does_not_leak_to_launched_apps(self):
        import eww_input
        cleaned=eww_input.clean_environment({'SELANDIA_EWW_EXCLUSIVE_ZONE':'55',
            'SELANDIA_EWW_INPUT_LIB':'/private/input.so','LD_PRELOAD':'/private/input.so:/other/lib.so','KEPT':'yes'})
        self.assertNotIn('SELANDIA_EWW_EXCLUSIVE_ZONE',cleaned)
        self.assertEqual(cleaned['LD_PRELOAD'],'/other/lib.so')
        self.assertEqual(cleaned['KEPT'],'yes')

    def test_eww_workers_default_is_scoped_to_child_environment(self):
        host={'KEPT':'yes','LD_PRELOAD':'/other/lib.so','GSK_RENDERER':'cairo'}
        with patch.dict(os.environ,host,clear=True),patch.object(bar_backend,'load_settings',return_value=appearance.DEFAULTS):
            environment=bar_backend.eww_environment(Path('/private/input.so'),Path('/private/config'))
            self.assertEqual(dict(os.environ),host)
        self.assertEqual(environment['TOKIO_WORKER_THREADS'],'2')
        self.assertEqual(environment['LD_PRELOAD'],'/private/input.so:/other/lib.so')
        self.assertEqual(environment['GSK_RENDERER'],'cairo')
        self.assertEqual(environment['KEPT'],'yes')

    def test_eww_workers_respect_explicit_user_value(self):
        with patch.dict(os.environ,{'TOKIO_WORKER_THREADS':'5'},clear=True),patch.object(bar_backend,'load_settings',return_value=appearance.DEFAULTS):
            environment=bar_backend.eww_environment(Path('/private/input.so'),Path('/private/config'))
            self.assertEqual(os.environ['TOKIO_WORKER_THREADS'],'5')
        self.assertEqual(environment['TOKIO_WORKER_THREADS'],'5')

    def test_telemetry_markup_and_actions_in_wide_layout(self):
        rendered, names = bar_backend.render([('probe', 1600)], size=12)
        left, right, center = rendered.split('(defwindow ')[1:]
        self.assertIn(':class "separator"', left)
        self.assertIn(':class "separator"', right)
        self.assertIn('CPU', right)
        self.assertIn('{state.cpu_text}', right)
        self.assertIn('RAM', right)
        self.assertIn('{state.memory_text}', right)
        self.assertIn('TEMP', right)
        self.assertIn('{state.temperature_text}', right)
        self.assertIn(' system', right)
        self.assertIn('{state.clock_time}', right)
        self.assertIn('{state.clock_date}', right)
        self.assertIn(' notification-toggle', right)
        self.assertIn(' control', right)

    def test_responsive_hiding_at_narrow_width(self):
        rendered, names = bar_backend.render([('probe', 960)], size=12)
        left, right, center = rendered.split('(defwindow ')[1:]
        self.assertIn('{state.cpu_text}', right)
        self.assertIn('{state.memory_text}', right)
        self.assertNotIn('{state.temperature_text}', right)
        self.assertIn('{state.clock_time}', right)
        self.assertNotIn('{state.clock_date}', right)
        self.assertIn('⋯', right)
        self.assertNotIn('(systray', right)

if __name__=='__main__':unittest.main()
