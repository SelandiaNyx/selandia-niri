#!/usr/bin/env python3
"""Compare the actual island with a private, real SwayNC daemon."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time

from gi.repository import Gio, GLib

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = Path(os.environ.get('XDG_STATE_HOME', ''))
if os.environ.get('SELANDIA_PRIVATE_PROBE') != '1' or not PRIVATE.name.startswith('selandia-smoke-'):
    raise SystemExit('Run through smoke.py --notification-probe-only')
BASE = Path(os.environ['XDG_CONFIG_HOME']) / 'niri'
ARTIFACTS = ROOT / '.validation/notification-policy-20261015'
BASELINE = os.environ.get('SELANDIA_NOTIFICATION_BASELINE')
RULES_PROBE = os.environ.get('SELANDIA_RULES_PROBE') == '1'
RULES_BASELINE = os.environ.get('SELANDIA_RULES_BASELINE')
if RULES_PROBE:
    ARTIFACTS = Path(os.environ.get('SELANDIA_RULES_ARTIFACTS', ROOT / '.validation/notification-rules-20261018'))
CC = 'org.erikreider.swaync.cc'
NOTIFY = 'org.freedesktop.Notifications'
connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)


def call(name, method, args=None):
    path = '/org/erikreider/swaync/cc' if name == CC else '/org/freedesktop/Notifications'
    return connection.call_sync(name, path, name, method, args, None,
                                Gio.DBusCallFlags.NO_AUTO_START, 3000, None).unpack()


def wait(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate(): return
        time.sleep(.02)
    assert predicate(), 'Notification condition timed out'


def main():
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    if BASELINE:
        shutil.copy2(Path(BASELINE)/'island.py', BASE/'shell/island.py')
    if RULES_BASELINE:
        for name in ('notification_events.py', 'notification_policy.py'):
            shutil.copy2(Path(RULES_BASELINE)/name, BASE/'shell'/name)
    config_path = BASE/'swaync/config.json'
    config = json.loads(config_path.read_text())
    if RULES_PROBE:
        config['notification-visibility'] = {
            'first-allow': {'app-name':'^Allowed$', 'state':'enabled'},
            'mute': {'app-name':'^(Muted|Allowed)$', 'state':'muted'},
            'ignore': {'app-name':'^Ignored$', 'state':'ignored'},
            'demote': {'app-name':'^Demoted$', 'override-urgency':'normal'},
            'promote': {'app-name':'^Promoted$', 'override-urgency':'critical'},
            'hint': {'desktop-entry':'^private.app$', 'category':'^private$', 'state':'muted'},
            'long-title': {'summary':'^x{180}hidden$', 'state':'muted'},
            'no-hint': {'app-name':'^NoHint$', 'urgency':'^Low$', 'state':'muted'},
            'typed-low': {'app-name':'^TypedLow$', 'urgency':'^Low$', 'state':'muted'},
            'typed-normal': {'app-name':'^TypedNormal$', 'urgency':'^Normal$', 'state':'muted'},
            'typed-critical': {'app-name':'^TypedCritical$', 'urgency':'^Critical$', 'state':'muted'},
            'transient': {'app-name':'^Transient$', 'state':'transient'}}
        config_path.write_text(json.dumps(config))
    key = hashlib.sha256(os.environ['NIRI_SOCKET'].encode()).hexdigest()[:20]
    endpoint = Path(os.environ['XDG_RUNTIME_DIR']) / ('selandia-island-' + key + '.sock')
    def state():
        try: return json.loads(endpoint.with_suffix('.json').read_text())
        except (OSError, ValueError): return {}
    def dismiss():
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as stream:
            stream.sendto(b'{"action":"dismiss"}', str(endpoint))
        wait(lambda:state().get('kind') != 'notification')
    def notify(title, *, replace=0, urgency=1, hints=None, timeout=-1, app='Selandia private probe'):
        values = {'urgency': GLib.Variant('y', urgency), **(hints or {})}
        return call(NOTIFY, 'Notify', GLib.Variant('(susssasa{sv}i)',
            (app, replace, 'dialog-information-symbolic', title,
             'Private notification body', [], values, timeout)))[0]
    def shown(title):
        return state().get('kind') == 'notification' and state().get('title') == title
    def quiet(seconds=.8):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            assert state().get('kind') != 'notification', state()
            time.sleep(.02)
    children, handles, results = [], [], {}
    def start(name, command, **kwargs):
        handle = (ARTIFACTS / (name + '.log')).open('w'); handles.append(handle)
        child = subprocess.Popen(command, stdout=handle, stderr=handle, **kwargs)
        children.append(child); return child
    try:
        daemon = start('swaync', ['swaync', '-c', str(config_path), '-s', str(BASE/'swaync/style.css')],
                       env=dict(os.environ, G_MESSAGES_DEBUG='all'))
        def ready():
            try: call(CC, 'GetSubscribeData'); return True
            except GLib.Error: return False
        wait(ready)
        owner_pid = connection.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus',
            'org.freedesktop.DBus', 'GetConnectionUnixProcessID', GLib.Variant('(s)', (NOTIFY,)),
            None, Gio.DBusCallFlags.NONE, 2000, None).unpack()[0]
        assert owner_pid == daemon.pid, (owner_pid, daemon.pid)
        call(CC, 'SetDnd', GLib.Variant('(b)', (False,)))
        bridge = start('island', [sys.executable, '-B', str(BASE/'shell/island.py'), 'listen'],
            env=dict(os.environ, PULSE_SERVER='unix:' + str(PRIVATE/'no-pulse')))
        wait(lambda: state().get('bridge_pid') == bridge.pid)
        time.sleep(.5)
        if RULES_PROBE:
            wait(lambda: state().get('notifications_available'))
            for app in ('Muted', 'Ignored'):
                title='private-'+app
                notify(title, app=app)
                if RULES_BASELINE:
                    time.sleep(.7);results[app.lower()+'_preview_leaks']=shown(title)
                    if shown(title):dismiss()
                else:
                    quiet();results[app.lower()+'_suppressed']=True
            if RULES_BASELINE:
                assert results['muted_preview_leaks'],results
                (ARTIFACTS/'baseline.json').write_text(json.dumps(results,indent=2)+'\n')
                print('PASS reproduced muted application preview despite SwayNC rule')
                return
            for app in ('Muted','Ignored'):
                notify('blocked-critical',app=app,urgency=2,hints={'SWAYNC_BYPASS_DND':GLib.Variant('b',True)})
                quiet()
            results['visibility_precedes_bypass']=True
            notify('first-rule-wins',app='Allowed');wait(lambda:shown('first-rule-wins'));dismiss()
            results['first_matching_rule']=True
            notify('transient-visible',app='Transient');wait(lambda:shown('transient-visible'));dismiss()
            notify('hint-blocked',hints={'desktop-entry':GLib.Variant('s','private.app'),'category':GLib.Variant('s','private')});quiet()
            notify('hint-one-mismatch',hints={'desktop-entry':GLib.Variant('s','private.app'),'category':GLib.Variant('s','public')})
            wait(lambda:shown('hint-one-mismatch'));dismiss()
            notify('x'*180+'hidden');quiet()
            results.update(transient_visible=True,hint_fields_and_semantics=True,matching_before_text_truncation=True)
            identifier=call(NOTIFY,'Notify',GLib.Variant('(susssasa{sv}i)',
                ('NoHint',0,'dialog-information-symbolic','no-urgency-hint','body',[],{},-1)))[0]
            time.sleep(.2)
            daemon_log=(ARTIFACTS/'swaync.log').read_text()
            assert f'Not displaying floating Notification: ID:{identifier},' in daemon_log,daemon_log[-1500:]
            quiet();results['missing_urgency_matches_daemon']=True
            cases = [
                ('boolean', GLib.Variant('b', True), 'TypedLow'),
                ('integer', GLib.Variant('i', 2), 'TypedLow'),
                ('string', GLib.Variant('s', 'critical'), 'TypedLow'),
                ('low', GLib.Variant('y', 0), 'TypedLow'),
                ('normal', GLib.Variant('y', 1), 'TypedNormal'),
                ('critical', GLib.Variant('y', 2), 'TypedCritical'),
                ('out-of-range-3', GLib.Variant('y', 3), 'TypedNormal'),
                ('out-of-range-255', GLib.Variant('y', 255), 'TypedNormal'),
            ]
            for label, value, app in cases:
                identifier = notify('urgency-' + label, app=app, hints={'urgency': value})
                wait(lambda: f'Not displaying floating Notification: ID:{identifier},' in
                     (ARTIFACTS/'swaync.log').read_text())
                quiet()
                results['urgency_' + label + '_matches_daemon'] = True
            call(CC,'SetDnd',GLib.Variant('(b)',(True,)))
            notify('demoted-critical',app='Demoted',urgency=2);quiet()
            notify('promoted-normal',app='Promoted');wait(lambda:shown('promoted-normal'));dismiss()
            call(CC,'SetDnd',GLib.Variant('(b)',(False,)))
            results['effective_urgency_controls_dnd']=True
            # Disk edits alone must not get ahead of the daemon's live config.
            config['notification-visibility']['mute']['state']='enabled'
            config_path.write_text(json.dumps(config))
            notify('not-loaded-yet',app='Muted');quiet()
            call(CC,'ReloadConfig')
            current=notify('reload-enabled',app='Muted',timeout=8000)
            wait(lambda:shown('reload-enabled'))
            config['notification-visibility']['mute']['state']='ignored'
            config_path.write_text(json.dumps(config));call(CC,'ReloadConfig')
            notify('replacement-now-hidden',app='Muted',replace=current)
            wait(lambda:state().get('kind')!='notification')
            results.update(reload_same_bridge=True,disk_edit_waits_for_reload=True,suppressed_replacement_closes=True)
            call(CC,'ChangeConfigValue',GLib.Variant('(svbs)',('timeout',GLib.Variant('i',1),False,'')))
            notify('memory-timeout');wait(lambda:shown('memory-timeout'))
            wait(lambda:not shown('memory-timeout'),timeout=1.8)
            assert json.loads(config_path.read_text())['timeout']==config['timeout']
            results['memory_timeout_change']=True
            assert state()['bridge_pid']==bridge.pid
            bridge.terminate();bridge.wait(timeout=3)
            assert bridge.returncode==0 and not endpoint.exists()
            results['clean_shutdown']=True
            (ARTIFACTS/'results.json').write_text(json.dumps(results,indent=2)+'\n')
            print('PASS real SwayNC application rules, ordering, urgency and config reload')
            return
        first = notify('initial-notification'); wait(lambda: shown('initial-notification'))
        call(NOTIFY, 'CloseNotification', GLib.Variant('(u)', (first,)))
        if BASELINE:
            time.sleep(.7); results['closed_preview_lingers'] = shown('initial-notification')
            assert results['closed_preview_lingers']; dismiss()
        else:
            wait(lambda: state().get('kind') != 'notification', timeout=1.5)
            results['close_clears_preview'] = True
        call(CC, 'SetDnd', GLib.Variant('(b)', (True,)))
        notify('dnd-notification')
        if BASELINE:
            wait(lambda: shown('dnd-notification'))
            results['dnd_bypassed'] = True
        else:
            quiet(); results['dnd_respected'] = True
            notify('critical-notification', urgency=2); wait(lambda: shown('critical-notification'))
            dismiss()
            notify('bypass-notification', hints={'SWAYNC_BYPASS_DND': GLib.Variant('b', True)})
            wait(lambda: shown('bypass-notification')); dismiss()
            call(CC, 'SetVisibility', GLib.Variant('(b)', (True,)))
            notify('center-open-critical', urgency=2); quiet()
            call(CC, 'SetVisibility', GLib.Variant('(b)', (False,)))
            call(CC, 'SetDnd', GLib.Variant('(b)', (False,)))
            call(CC, 'AddInhibitor', GLib.Variant('(s)', ('probe',)))
            notify('inhibited-notification'); quiet()
            call(CC, 'RemoveInhibitor', GLib.Variant('(s)', ('probe',)))
            current = notify('before-replacement'); wait(lambda: shown('before-replacement'))
            assert notify('after-replacement', replace=current) == current
            wait(lambda: shown('after-replacement'))
            call(NOTIFY, 'CloseNotification', GLib.Variant('(u)', (current,)))
            wait(lambda: state().get('kind') != 'notification', timeout=1.5)
            notify('turn-on-dnd'); wait(lambda: shown('turn-on-dnd'))
            call(CC, 'SetDnd', GLib.Variant('(b)', (True,)))
            wait(lambda: state().get('kind') != 'notification', timeout=1.5)
            call(CC, 'SetDnd', GLib.Variant('(b)', (False,)))
            quiet()
            results.update(critical_and_explicit_bypass=True, center_suppresses_critical=True,
                inhibitor_respected=True, replacement_and_close=True, dnd_clears_existing=True,
                no_replay=True)
            current = notify('legitimate-notification'); wait(lambda: shown('legitimate-notification'))
            connection.emit_signal(None, '/org/erikreider/swaync/cc', CC, 'SubscribeV2',
                                   GLib.Variant('(ubbb)', (1, True, True, True)))
            connection.emit_signal(None, '/org/freedesktop/Notifications', NOTIFY, 'NotificationClosed',
                                   GLib.Variant('(uu)', (current, 3)))
            connection.flush_sync(None)
            time.sleep(.4); assert shown('legitimate-notification')
            call(CC, 'CloseAllNotifications')
            wait(lambda: state().get('kind') != 'notification', timeout=1.5)
            notify('short-preview', timeout=450); wait(lambda: shown('short-preview'))
            wait(lambda: state().get('kind') != 'notification', timeout=1.5)
            notify('daemon-exit'); wait(lambda: shown('daemon-exit'))
            daemon.terminate(); daemon.wait(timeout=5)
            wait(lambda: not state().get('notifications_available') and state().get('kind') != 'notification')
            daemon = start('swaync-restarted', ['swaync', '-c', str(BASE/'swaync/config.json'), '-s', str(BASE/'swaync/style.css')])
            wait(ready)
            wait(lambda: state().get('notifications_available'))
            call(CC, 'SetDnd', GLib.Variant('(b)', (False,)))
            new_id = notify('daemon-restarted'); wait(lambda: shown('daemon-restarted'))
            assert new_id == 1, new_id
            assert state()['bridge_pid'] == bridge.pid
            bridge.terminate(); bridge.wait(timeout=3)
            assert bridge.returncode == 0 and not endpoint.exists()
            call(CC, 'GetSubscribeData')
            results.update(forged_signals_ignored=True, clear_all_clears_preview=True,
                explicit_timeout_respected=True, service_exit_clears_preview=True,
                service_restart_reuses_bridge=True, reused_ids_after_restart=True, clean_shutdown=True)
        (ARTIFACTS / ('baseline.json' if BASELINE else 'results.json')).write_text(json.dumps(results, indent=2)+'\n')
        print('PASS ' + ('reproduced real SwayNC DND bypass and lingering closed preview' if BASELINE else
                        'real SwayNC policy, close and replacement synchronized with island'))
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                try: child.wait(timeout=5)
                except subprocess.TimeoutExpired: child.kill(); child.wait(timeout=3)
        for handle in handles: handle.close()


if __name__ == '__main__': main()
