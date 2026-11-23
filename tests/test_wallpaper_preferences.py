"""Migration, precision editing, rating safety, backend mapping and resident IPC."""
from copy import deepcopy
import json
import os
from pathlib import Path
import random
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'niri/shell'))
import i18n
import wallpaper as w
import wallpaper_options as options
import wallpaper_playlist as policy
import wallpaper_remote as remote
import wallpaper_fade as fade


def legacy():
    return {'enabled': True, 'items': [{'path': '/a', 'mode': 'live'}, {'path': '/b', 'mode': 'preview'}, {'path': '/c', 'mode': 'live'}],
            'order': 'random', 'trigger': 'timer', 'minutes': 17}


class PlaylistDataTests(unittest.TestCase):
    def test_lossless_legacy_migration_round_trip(self):
        old = legacy(); migrated = policy.registry(None, old, Path)
        settings = policy.current(migrated)['settings']
        self.assertEqual(settings['seconds'], 1020)
        self.assertEqual([{key: item[key] for key in ('path','mode')} for item in settings['items']], old['items'])
        for key in ('enabled','order','trigger','minutes'): self.assertEqual(settings[key], old[key])
        self.assertEqual(policy.registry(json.loads(json.dumps(migrated)), old, Path), migrated)

    def test_invalid_registry_never_clears_legacy_entries(self):
        for value in (None, [], {'version': 22}, {'version':1, 'lists':[]}, {'version':1, 'lists':[{}]},
                      {'version':1, 'active':[], 'lists':[{'id':'x','name':'valid','settings':legacy()}]},
                      {'version':1, 'active':'missing','lists':[{'id':'x','name':'valid','settings':legacy()}]}):
            self.assertEqual(len(policy.current(policy.registry(value, legacy(), Path))['settings']['items']),3)

    def test_bad_new_fields_preserve_old_preferences_and_entries(self):
        result = policy.validate({**legacy(), 'seconds':'bad', 'cycle':[{'path':[], 'mode':'live'}],
                                  'new_unknown':True}, Path)
        self.assertEqual(result['seconds'],1020); self.assertEqual(len(result['items']),3)
        result = policy.validate({'items':[{'path':'/a','mode':'live','enabled':'bad','weight':True}]},Path)
        self.assertTrue(result['items'][0]['enabled']); self.assertEqual(result['items'][0]['weight'],1)

    def test_names_unicode_bounds_and_unsafe_characters(self):
        for value in ('测试集 1','A' * 64,'A_1-(copy).'): self.assertEqual(policy.name(value),value)
        for value in ('',' ','a' * 65,'../path','x\\y','x\ny','a\x00b',None,[]):
            with self.subTest(value=value), self.assertRaises(ValueError): policy.name(value)

    def test_create_rename_copy_switch_delete_keep_independent_items(self):
        original = policy.registry(None,legacy(),Path)
        copied = policy.manage(original,'duplicate',title='Copy')
        self.assertEqual(len(copied['lists']),2)
        self.assertEqual(policy.current(copied)['settings']['items'],policy.current(original)['settings']['items'])
        policy.current(copied)['settings']['items'][0]['weight']=31
        self.assertEqual(policy.current(original)['settings']['items'][0]['weight'],1)
        copied=policy.manage(copied,'rename',title='Renamed')
        self.assertEqual(policy.current(copied)['name'],'Renamed')
        copied=policy.manage(copied,'select',identifier='default')
        copied=policy.manage(copied,'create',title='Empty')
        self.assertFalse(policy.current(copied)['settings']['items'])
        deleted=policy.manage(copied,'delete')
        self.assertEqual(deleted['active'],'default');self.assertEqual(len(deleted['lists']),2)
        self.assertEqual(len(original['lists']),1)
        with self.assertRaises(ValueError): policy.manage(original,'delete')
        with self.assertRaises(ValueError): policy.manage(original,'create',title='default')

    def test_editor_reorder_enable_weight_sort_remove_clear(self):
        items=policy.validate(legacy(),Path)['items']
        self.assertEqual([e['path'] for e in policy.edit(items,'down',0)],['/b','/a','/c'])
        self.assertEqual([e['path'] for e in policy.edit(items,'up',2)],['/a','/c','/b'])
        self.assertEqual([e['path'] for e in policy.edit(items,'top',2)],['/c','/a','/b'])
        disabled=policy.edit(items,'enabled',1,value=False)
        weighted=policy.edit(disabled,'weight',2,value=100)
        self.assertFalse(weighted[1]['enabled']);self.assertEqual(weighted[2]['weight'],100)
        self.assertEqual(policy.edit(weighted,'weight',2,value=0),weighted)
        self.assertEqual(policy.edit(items,'sort-name',title=lambda e: {'/a':'Z','/b':'B','/c':'A'}[e['path']])[0]['path'],'/c')
        self.assertEqual(policy.edit(list(reversed(items)),'sort-path'),items)
        self.assertEqual(len(policy.edit(items,'remove',1)),2);self.assertEqual(policy.edit(items,'clear'),[])
        self.assertTrue(items[1]['enabled']);self.assertEqual(items[2]['weight'],1)

    def test_weighted_random_uses_weights_and_never_picks_disabled_filtered_current(self):
        value=policy.validate(legacy(),Path);value['items'][1]['weight']=40
        with patch.object(policy.random,'choices',side_effect=lambda values, **kw:[values[-1]]) as choose:
            result=policy.candidates(value,{'path':'/a','mode':'live'}, allowed=lambda item:item['path']!='/c')
            self.assertEqual(result[0]['path'],'/b');self.assertEqual(choose.call_args.kwargs['weights'],[40])
        value['items'][1]['enabled']=False
        self.assertEqual(policy.candidates(value,None,allowed=lambda item:item['path']=='/b'),[])

    def test_shuffle_three_cycles_and_persistent_remainder_no_repeats(self):
        value=policy.validate({**legacy(),'order':'shuffle'},Path); selection=None
        random.seed(4711)
        for _ in range(3):
            cycle=[]
            for _ in range(3):
                ordered=policy.candidates(value,selection);next_item=ordered[0]
                cycle.append(next_item['path']);selection=next_item
                value=policy.validate(json.loads(json.dumps(policy.consume(value,ordered,0,1))),Path)
            self.assertEqual(len(set(cycle)),3);self.assertFalse(value['cycle'])
        self.assertNotEqual(policy.candidates(value,selection)[0]['path'],selection['path'])

    def test_seconds_min_max_and_precise_due(self):
        for seconds in (1,9,59,60,10800): self.assertEqual(policy.validate({'seconds':seconds},Path)['seconds'],seconds)
        for seconds in (0,10801,True,1.5,'1'): self.assertEqual(policy.validate({'seconds':seconds},Path)['seconds'],600)
        settings={'selection':None,'playlist':policy.validate({**legacy(),'seconds':3},Path)}
        schedule=policy.Schedule(0)
        self.assertFalse(schedule.due(settings,0));self.assertFalse(schedule.due(settings,2.99));self.assertTrue(schedule.due(settings,3))
        self.assertFalse(schedule.due(settings,5,allowed=lambda _:False))

    def test_shuffle_drops_filtered_and_disabled_remainder(self):
        value=policy.validate({**legacy(),'order':'shuffle','cycle':[{'path':'/a','mode':'live'},{'path':'/b','mode':'preview'}]},Path)
        value['items'][0]['enabled']=False
        self.assertEqual(policy.candidates(value,None,allowed=lambda e:e['path']!='/b')[0]['path'],'/c')


class PreferencesTransactionsTests(unittest.TestCase):
    def setUp(self):
        i18n.set_language('en_US');self.addCleanup(i18n.set_language,None)
        temp=tempfile.TemporaryDirectory(prefix='selandia-precision-test-');self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        env=patch.dict(os.environ,XDG_STATE_HOME=str(self.root/'state'),XDG_CACHE_HOME=str(self.root/'cache'),
                       XDG_RUNTIME_DIR=str(self.root),PYTHONPATH=str(ROOT/'niri/shell'))
        env.start();self.addCleanup(env.stop)
        self.image=self.root/'image.svg';self.image.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="80" height="50"><rect width="80" height="50" fill="red"/></svg>')
        w.save_settings({'selection':{'path':str(self.image),'mode':'preview','fallback':''},'audio':{'muted':True,'volume':23},'playlist':legacy()})
        self.before=w.load_settings()
        self.rotation_events = []
        stack_log = patch.object(w, 'log_rotation', side_effect=lambda event, **values: self.rotation_events.append((event, values)))
        stack_log.start(); self.addCleanup(stack_log.stop)

    def test_invalid_new_sections_cannot_reset_selection_or_audio(self):
        raw=json.loads((w.state_dir()/'wallpaper.json').read_text())
        for value in ({'playlists':[]},{'playlists':{'version':1,'active':[],'lists':[{}]}},
                      {'ratings':[],'rating_filter':{'mature':'true'},'display':{'mode':[],'duration':None}}):
            w.save_settings({**raw,**value})
            result=w.load_settings();self.assertEqual(result['audio'],self.before['audio']);self.assertEqual(result['selection'],self.before['selection'])
            self.assertEqual(len(result['playlist']['items']),3)

    def test_management_keeps_audio_selection_and_inactive_playlists(self):
        result=w.manage_playlists('duplicate',title='Second',handoff=Mock())
        self.assertEqual(len(result['lists']),2)
        w.configure_playlist({'items':[],'seconds':2},handoff=Mock())
        result=w.manage_playlists('select',identifier='default',handoff=Mock())
        self.assertEqual(len(w.load_settings()['playlist']['items']),3)
        self.assertEqual(w.load_settings()['audio'],self.before['audio']);self.assertEqual(w.load_settings()['selection'],self.before['selection'])

    def test_configuration_failure_rolls_back_preferences_and_replays(self):
        handoff=Mock(side_effect=[RuntimeError('fixture failed'),None])
        with self.assertRaisesRegex(RuntimeError,'fixture failed'): w.configure_display({'mode':'tile'},handoff=handoff)
        self.assertEqual(w.load_settings(),self.before);self.assertEqual(handoff.call_count,2)

    def test_rating_confirmation_is_required_and_no_password_is_stored(self):
        with self.assertRaisesRegex(ValueError,'Confirm'): w.configure_rating_filter({'mature':True},handoff=Mock())
        self.assertFalse(w.load_settings()['rating_filter']['mature'])
        w.configure_rating_filter({'mature':True},confirm_mature=True,handoff=Mock())
        self.assertTrue(w.load_settings()['rating_filter']['mature'])
        raw=(w.state_dir()/'wallpaper.json').read_text().lower()
        self.assertNotIn('password',raw);self.assertNotIn('passphrase',raw)
        self.assertEqual(w.load_settings()['audio'],self.before['audio'])

    def test_bulk_ratings_filter_manual_and_automatic_switch(self):
        w.set_ratings(['/a','/b','/c'],'mature',handoff=Mock())
        with patch.object(w,'activate') as activate:
            self.assertIsNone(w.playlist_step(handoff=Mock()));activate.assert_not_called()
        w.configure_rating_filter({'mature':True},confirm_mature=True,handoff=Mock())
        with patch.object(w,'activate',return_value={'warnings':[]}) as activate:
            self.assertIsNotNone(w.playlist_step(handoff=Mock()));activate.assert_called()
        w.set_ratings([str(self.image)],'mature',handoff=Mock())
        w.configure_rating_filter({'mature':False},handoff=Mock())
        with self.assertRaisesRegex(ValueError,'hidden'): w.activate(self.image,handoff=Mock())

    def test_shuffle_remainder_and_selection_are_one_transaction(self):
        value=policy.validate({'items':[{'path':str(self.image),'mode':'preview'}],'order':'shuffle'},Path)
        w.configure_playlist(value,handoff=Mock());before=w.load_settings()
        with patch.object(w,'activate') as activate:
            activate.side_effect=RuntimeError('failed')
            with self.assertRaises(RuntimeError): w.playlist_step(handoff=Mock())
        self.assertEqual(w.load_settings(),before)
        result=w.playlist_step(handoff=Mock())
        self.assertEqual(result['item']['path'],str(self.image));self.assertEqual(w.load_settings()['playlist']['cycle'],[])

    def test_sigkill_during_preference_apply_recovers_audio_selection_and_registry(self):
        ready=self.root/'ready';worker=self.root/'worker.py'
        worker.write_text('import time\nfrom pathlib import Path\nimport wallpaper as w\n'+
                          f'def handoff(settings):\n Path({str(ready)!r}).touch()\n time.sleep(60)\n'+
                          'w.configure_display({"mode":"tile"},handoff=handoff)\n')
        child=subprocess.Popen([sys.executable,'-B',str(worker)],stderr=subprocess.PIPE)
        try:
            deadline=time.monotonic()+10
            while not ready.exists() and child.poll() is None and time.monotonic()<deadline:time.sleep(.02)
            self.assertTrue(ready.exists(),child.stderr.read().decode() if child.poll() is not None else 'not ready')
            child.kill();child.wait(timeout=3)
            self.assertEqual(w.load_settings()['display']['mode'],'tile')
            with w.settings_lock():w.recover_transition()
            self.assertEqual(w.load_settings(),self.before)
        finally:
            if child.poll() is None:child.kill();child.wait(timeout=3)
            child.stderr.close()

    def test_legacy_interruption_journal_migrates_before_recovery(self):
        old=json.loads((w.state_dir()/'wallpaper.json').read_text());after={**old,'audio':{'muted':False,'volume':71}}
        w.save_settings(after);w.atomic_write(w.state_dir()/'wallpaper-transition.json',json.dumps({'version':1,'phase':'prepared','before':old,'after':after}).encode())
        with w.settings_lock():w.recover_transition()
        self.assertEqual(w.load_settings(),self.before)

    def test_oversized_write_is_rejected_before_mutation(self):
        raw=(w.state_dir()/'wallpaper.json').read_bytes()
        with self.assertRaises(ValueError):w.save_settings({'extra':'x'*2_000_001})
        self.assertEqual((w.state_dir()/'wallpaper.json').read_bytes(),raw)

    def test_stale_ui_registry_cannot_overwrite_new_profile(self):
        expected=self.before['playlists'];w.manage_playlists('create',title='Elsewhere',handoff=Mock())
        with self.assertRaisesRegex(RuntimeError,'changed elsewhere'):
            w.configure_playlist(self.before['playlist'],registry=expected,expected_registry=expected,handoff=Mock())
        self.assertEqual(policy.current(w.load_settings()['playlists'])['name'],'Elsewhere')

    def test_running_shuffle_cycle_does_not_make_ui_draft_stale_or_rewind_it(self):
        value=policy.validate({**legacy(),'order':'shuffle'},Path)
        w.configure_playlist(value,handoff=Mock())
        expected=w.load_settings()['playlists']
        advanced=deepcopy(value);advanced['cycle']=[{'path':'/b','mode':'preview'}]
        w.save_settings(w.with_playlist(w.load_settings(),advanced))
        w.configure_playlist(value,registry=expected,expected_registry=expected,handoff=Mock())
        self.assertEqual(w.load_settings()['playlist']['cycle'],advanced['cycle'])


    def test_persisted_legacy_projection_is_readable_by_previous_revision(self):
        value=policy.validate({**legacy(),'order':'shuffle','seconds':3},Path)
        value['items'][0]['enabled']=False;value['items'][1]['weight']=70
        w.configure_playlist(value,handoff=Mock())
        raw=json.loads((w.state_dir()/'wallpaper.json').read_text())
        self.assertEqual(set(raw['playlist']),{'enabled','items','order','trigger','minutes'})
        self.assertEqual(set(raw['playlist']['items'][0]),{'path','mode'})
        self.assertNotIn('/a',[item['path'] for item in raw['playlist']['items']])
        self.assertEqual(raw['playlist']['order'],'random')
        self.assertEqual(w.load_settings()['playlist']['seconds'],3)
        self.assertFalse(w.load_settings()['playlist']['items'][0]['enabled'])
        self.assertEqual(w.load_settings()['playlist']['items'][1]['weight'],70)


    def test_large_valid_preferences_have_recoverable_double_sized_journal(self):
        before=w.load_settings()
        before['ratings']={('/'+'a'*1100+'/'+str(index)):'questionable' for index in range(950)}
        w.save_settings(before);before=w.load_settings()
        after={**before,'audio':{'muted':False,'volume':71}}
        w.save_settings(after)
        journal=json.dumps({'version':1,'phase':'prepared','before':before,'after':after}).encode()
        self.assertGreater(len(journal),2_000_000)
        w.atomic_write(w.state_dir()/'wallpaper-transition.json',journal)
        with w.settings_lock():w.recover_transition()
        self.assertEqual(w.load_settings(),before)


    def test_large_disabled_playlist_projection_still_recovers_full_registry(self):
        value=policy.validate({'items':[{'path':'/'+'b'*1100+'/'+str(index),'mode':'preview','enabled':False} for index in range(950)]},Path)
        before=w.with_playlist(w.load_settings(),value);w.save_settings(before);before=w.load_settings()
        after={**before,'audio':{'muted':False,'volume':71}}
        w.save_settings(after)
        journal=json.dumps({'version':1,'phase':'prepared','before':before,'after':after},ensure_ascii=False).encode()
        self.assertGreater(len(journal),4_100_000)
        w.atomic_write(w.state_dir()/'wallpaper-transition.json',journal)
        with w.settings_lock():w.recover_transition()
        self.assertEqual(w.load_settings(),before)


    def test_saved_mute_is_initialized_once_during_renderer_readiness(self):
        supervisor=w.PlaylistRenderer()
        settings={**self.before,'selection':{'path':str(self.image),'mode':'live','fallback':str(self.image)}}
        item={'path':str(self.image),'type':'video','file':'/video.mp4'}
        guard=Mock(pid=901,poll=Mock(return_value=None));renderer=Mock(pid=902,poll=Mock(return_value=None))
        ticks=iter(x/10 for x in range(1000))
        def sync(pid, audio, **kwargs):
            kwargs['applied'].add(('stream',1));return kwargs['applied']
        with patch.object(w,'describe',return_value=item), \
             patch.object(w,'playback_command',return_value=['mpvpaper','-o','loop-file=inf','ALL','/video.mp4']), \
             patch.object(w.wallpaper_audio,'available',return_value=True), \
             patch.object(w.wallpaper_audio,'process_identity',side_effect=lambda pid:{'pid':pid}), \
             patch.object(w.wallpaper_audio,'sync_streams',side_effect=sync) as initialize, \
             patch.object(w.subprocess,'Popen',side_effect=[guard,renderer]), \
             patch.object(w.time,'monotonic',side_effect=lambda:next(ticks)),patch.object(w.time,'sleep'), \
             patch.object(supervisor,'property',return_value='/video.mp4'),patch.object(supervisor,'stop'):
            supervisor.replace(settings)
            self.assertTrue(initialize.called)
            self.assertTrue(all(call.args[1]['muted'] for call in initialize.call_args_list))
            self.assertTrue(all('fields' not in call.kwargs for call in initialize.call_args_list))
            self.assertIn(('stream',1),supervisor.applied)
            supervisor.close()


    def test_small_static_fallback_preserves_intrinsic_center_tile_size(self):
        from gi.repository import GdkPixbuf
        w.activate(self.image,'preview',handoff=Mock())
        cached=GdkPixbuf.Pixbuf.new_from_file(w.load_settings()['selection']['fallback'])
        self.assertEqual((cached.get_width(),cached.get_height()),(80,50))



class DisplayMappingTests(unittest.TestCase):
    def setUp(self):
        i18n.set_language("en_US");self.addCleanup(i18n.set_language,None)

    def test_all_sway_modes_are_supported_cover_maps_to_fill(self):
        for mode in options.MODES:
            command=w.static_command('/local.png',{'mode':mode})
            self.assertIn(command[command.index('-m')+1],('fill','stretch','fit','center','tile'))
        self.assertEqual(options.sway_mode('cover'),'fill')

    def test_video_mapping_preserves_sound_and_reports_unsupported_tile(self):
        with patch.object(w.shutil,'which',return_value='/bin/fixture'):
            for mode in options.MODES:
                command=w.playback_command({'type':'video','file':'/v.mp4'},'live',audio_available=True,display={'mode':mode})
                self.assertIn(options.mpv_options(mode),command[2]);self.assertIn('audio=yes',command[2]);self.assertNotIn('no-audio',command[2])
                silent=w.playback_command({'type':'video','file':'/v.mp4'},'live',audio_available=False,display={'mode':mode})
                self.assertIn('no-audio',silent[2])
        self.assertIn('does not support tiling',' '.join(options.notices({'type':'video'},'live',{'mode':'tile','transition':'instant'})))

    def test_engine_flags_are_scoped_to_each_output_with_truthful_limitations(self):
        with tempfile.TemporaryDirectory() as assets, patch.object(w.shutil,'which',return_value='/bin/fixture'):
            for mode in options.MODES:
                command=w.playback_command({'type':'scene','path':'/scene'},'live',assets=assets,outputs=['DP-1','DP-2'],audio_available=False,display={'mode':mode})
                self.assertEqual(command.count('--scaling'),2);self.assertEqual(command.count('--clamp'),2)
                self.assertIn('--silent',command);self.assertIn('--no-audio-processing',command)
        self.assertIn('no equivalent center/tile',' '.join(options.notices({'type':'scene'},'live',{'mode':'center','transition':'instant'})))

    def test_transition_discloses_live_limits_static_modes_supported(self):
        for kind in ('video','scene','web'):
            self.assertIn('does not support crossfade',' '.join(options.notices({'type':kind},'live',{'mode':'fill','transition':'fade'})))
            self.assertNotIn('does not support crossfade',' '.join(options.notices({'type':kind},'preview',{'mode':'fill','transition':'fade'})))

    def test_invalid_display_rating_fields_are_independent_safe_defaults(self):
        for value in (None,[],{'mode':'bad','transition':'bad','duration':float('nan')},{'duration':True},{'duration':float('inf')}):
            self.assertEqual(options.display(value),options.DISPLAY)
        self.assertEqual(options.rating_filter({'mature':'true'}),options.FILTER)
        self.assertEqual(options.ratings({'/a':'bad','/b':'mature'},Path),{'/b':'mature'})

    def test_fade_geometry_matches_fill_fit_stretch_center(self):
        self.assertEqual(fade.geometry(100,50,200,200,'fit'),(0.,50.,2.,2.))
        self.assertEqual(fade.geometry(100,50,200,200,'fill'),(-100.,0.,4.,4.))
        self.assertEqual(fade.geometry(100,50,200,200,'stretch'),(0.,0.,2.,4.))
        self.assertEqual(fade.geometry(100,50,200,200,'center'),(50.,75.,1.,1.))


class ResidentIPCTests(unittest.TestCase):
    def test_other_state_cannot_contact_the_same_display_service(self):
        with tempfile.TemporaryDirectory() as root:
            with patch.dict(os.environ,XDG_STATE_HOME=root+'/formal'):
                server=remote.Server();self.addCleanup(server.close);formal=server.path
            with patch.dict(os.environ,XDG_STATE_HOME=root+'/test'):
                self.assertNotEqual(remote.path(),formal)
                self.assertIs(remote.request('activate',path='/fixture'),remote.NO_SERVICE)
            dispatch=Mock()
            self.assertFalse(server.poll(dispatch));dispatch.assert_not_called()
            self.assertTrue(formal.exists())

    def setUp(self):
        i18n.set_language('en_US');self.addCleanup(i18n.set_language,None)
        temp=tempfile.TemporaryDirectory(prefix='selandia-ipc-');self.addCleanup(temp.cleanup)
        env=patch.dict(os.environ,XDG_RUNTIME_DIR=temp.name,NIRI_SOCKET='/private/niri.sock')
        env.start();self.addCleanup(env.stop)

    def test_no_service_and_empty_result_are_distinct(self):
        self.assertIs(remote.request('playlist_step'),remote.NO_SERVICE)
        server=remote.Server();self.addCleanup(server.close)
        worker=threading.Thread(target=lambda:self.poll_once(server,lambda c,v:None));worker.start()
        self.assertIsNone(remote.request('playlist_step'));worker.join(timeout=3);self.assertFalse(worker.is_alive())

    @staticmethod
    def poll_once(server,dispatch):
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            if server.poll(dispatch):return
            time.sleep(.01)
        raise AssertionError('IPC request did not arrive')

    def test_errors_propagate_without_restart_fallback(self):
        server=remote.Server();self.addCleanup(server.close)
        def fail(c,v):raise ValueError('fixture rejection')
        worker=threading.Thread(target=lambda:self.poll_once(server,fail));worker.start()
        with self.assertRaisesRegex(RuntimeError,'fixture rejection'):remote.request('activate',path='/a')
        worker.join(timeout=3);self.assertFalse(worker.is_alive())

    def test_regular_file_and_symlink_are_rejected(self):
        target=remote.path();target.write_text('not a socket')
        with self.assertRaisesRegex(RuntimeError,'Untrusted'):remote.request('activate')
        target.unlink();target.symlink_to('/tmp/nonexistent')
        with self.assertRaisesRegex(RuntimeError,'Untrusted'):remote.request('activate')

    def test_server_preserves_foreign_regular_file_and_replacement(self):
        target=remote.path();target.write_text('keep this')
        with self.assertRaisesRegex(RuntimeError,'Untrusted'):remote.Server()
        self.assertEqual(target.read_text(),'keep this')
        target.unlink();server=remote.Server();target.unlink();target.write_text('later user edit')
        server.close();self.assertEqual(target.read_text(),'later user edit')

    def test_large_unicode_registry_response_is_not_truncated(self):
        server=remote.Server();self.addCleanup(server.close)
        result={'name':'壁纸' * 400_000}
        worker=threading.Thread(target=lambda:self.poll_once(server,lambda c,v:result));worker.start()
        self.assertEqual(remote.request('manage_playlists'),result)
        worker.join(timeout=3);self.assertFalse(worker.is_alive())

    def test_live_server_cannot_be_unlinked_by_second_supervisor(self):
        server=remote.Server();self.addCleanup(server.close)
        with self.assertRaisesRegex(RuntimeError,'already running'):remote.Server()
        self.assertTrue(remote.path().exists())
