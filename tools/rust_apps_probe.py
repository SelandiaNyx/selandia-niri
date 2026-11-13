#!/usr/bin/env python3
"""Private real MPRIS, PulseAudio, Anyrun and Alacritty integration."""
import json,os,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];PRIVATE=Path(os.environ.get('XDG_STATE_HOME',''))
if os.environ.get('SELANDIA_PRIVATE_PROBE')!='1' or not PRIVATE.name.startswith('selandia-smoke-'):raise SystemExit('Use smoke.py --rust-apps-probe-only')
BASE=Path(os.environ['XDG_CONFIG_HOME'])/'niri';sys.path[:0]=[str(BASE/'shell'),str(ROOT/'tools')]
import appearance,island,session_probe,media_probe
from gi.repository import GLib
EVID=ROOT/'.validation/resume-rust-20261011/rust-apps';EVID.mkdir(parents=True,exist_ok=True)
def wait(test,seconds=15):
 end=time.monotonic()+seconds
 while time.monotonic()<end:
  try:
   if test():return
  except (OSError,ValueError,subprocess.SubprocessError):pass
  time.sleep(.08)
 raise AssertionError('Rust apps native condition timed out')
def main():
 children=[];logs=[];result={}
 def start(name,args,environment=None):
  log=(EVID/(name+'.log')).open('w');logs.append(log);p=subprocess.Popen(args,env=environment,stdout=log,stderr=subprocess.STDOUT);children.append(p);return p
 def stop(p):
  p.terminate()
  try:p.wait(timeout=8)
  except subprocess.TimeoutExpired:p.kill();p.wait(timeout=3)
 def state():return json.loads(island.endpoint().with_suffix('.json').read_text())
 def command(*args):return subprocess.check_output(args,text=True,stderr=subprocess.PIPE,timeout=6)
 pointer=PRIVATE/'pointer';protocol=ROOT/'tools/protocols/wlr-virtual-pointer.xml'
 for kind,name in [('client-header','wlr-virtual-pointer-client.h'),('private-code','pointer.c')]:
  subprocess.run(['wayland-scanner',kind,str(protocol),str(PRIVATE/name)],check=True, timeout=5)
 flags=command('pkg-config','--cflags','--libs','wayland-client').split()
 subprocess.run(['cc','-O2','-I',str(PRIVATE),str(ROOT/'tools/pointer_probe.c'),str(PRIVATE/'pointer.c'),'-o',str(pointer),*flags],check=True, timeout=30)
 def geometry():
  info=json.loads((Path(os.environ['XDG_RUNTIME_DIR'])/'selandia-eww-runtime.json').read_text())
  if not info.get('ready'):return {}
  return json.loads((Path(info['geometry'])/'island.json').read_text())
 preview=BASE/'preview.kdl';preview.write_text(preview.read_text().replace('scale 1.5','scale 1.0'))
 appearance.apply_settings({**appearance.load_settings(),'opacity':.2,'reduced_motion':False})
 cover=PRIVATE/'cover.png';command('ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i','color=c=teal:s=64x64','-frames:v','1',str(cover))
 media_probe.XML=media_probe.XML.replace('</interface>\n</node>', '<property name="Position" type="x" access="read"/></interface>\n</node>')
 class Players(media_probe.FakePlayers):
  @staticmethod
  def property(entry,prop):
   if prop=='Metadata':return GLib.Variant('a{sv}',{'xesam:title':GLib.Variant('s','Native island fixture'),'mpris:artUrl':GLib.Variant('s',cover.as_uri()),'mpris:length':GLib.Variant('x',100000000)})
   if prop=='Position':return GLib.Variant('x',25000000)
   if prop=='CanGoPrevious':return GLib.Variant('b',True)
   return media_probe.FakePlayers.property(entry,prop)
  def method(self,entry,method,invocation):
   if method in ('Next','Previous'):
    self.calls.append((entry['name'],method));invocation.return_value(GLib.Variant('()',()));return
   return super().method(entry,method,invocation)
 players=Players(single=True);players.entries[0]['can_next']=True;players.start()
 audio=PRIVATE/'rust-audio';audio.mkdir(mode=0o700)
 env=dict(os.environ,XDG_RUNTIME_DIR=str(audio),PIPEWIRE_RUNTIME_DIR=str(audio),PULSE_SERVER='unix:'+str(audio/'pulse/native'),PULSE_RUNTIME_PATH=str(audio/'pulse'),PIPEWIRE_CONFIG_DIR='/usr/share/pipewire',DBUS_SYSTEM_BUS_ADDRESS='unix:path='+str(audio/'no-system-bus'))
 try:
  for name,args in [('pipewire',['pipewire']),('pulse',['pipewire-pulse']),('policy',['wireplumber','--profile','policy'])]:start(name,args,env)
  os.environ['PULSE_SERVER']=env['PULSE_SERVER']
  wait(lambda:command('pactl','info'))
  command('pactl','load-module','module-null-sink','sink_name=rust-island','sink_properties=node.driver=true node.always-process=true')
  wait(lambda:command('pactl','set-default-sink','rust-island') is not None);command('pactl','set-sink-volume','rust-island','37%')
  bar=start('bar',[sys.executable,'-B',str(BASE/'shell/bar_backend.py')])
  wait(lambda:state().get('has_progress') and state().get('has_audio'))
  data=state();assert data['progress']==25 and data['cover']==str(cover) and data['volume']==37,data
  session_probe.screenshot(EVID/'media.png')
  for index,expected in [(3,'Next'),(1,'Previous'),(2,'Pause'),(2,'Play')]:
   island.send('show',kind='media')
   wait(lambda:state()['kind']=='media' and len(geometry().get('controls',[]))==4)
   time.sleep(.65)
   g=geometry();r=g['controls'][index]
   output=next(value for value in json.loads(command('niri','msg','--json','outputs')).values() if value.get('logical'))['logical']
   x=(output['width']-g['width'])//2+r['x']+r['width']//2;y=12+r['y']+r['height']//2
   command(str(pointer),str(x),str(y),str(output['width']),str(output['height']),'click')
   wait(lambda:any(method==expected for _,method in players.calls))
   if expected in ('Play','Pause'):wait(lambda:state()['playing']==(expected=='Play'))
  command('pactl','set-sink-volume','rust-island','61%');wait(lambda:state()['kind']=='volume' and state()['volume']==61)
  session_probe.screenshot(EVID/'volume.png')
  command(sys.executable,'-B',str(BASE/'shell/island.py'),'volume','44');wait(lambda:'44%' in command('pactl','get-sink-volume','rust-island'))
  result['mpris']={'progress':25,'cover':str(cover),'calls':players.calls,'controls':'actual GTK virtual-pointer clicks'};result['audio']={'external_event':61,'control':44,'refresh_kept_initial':37}
  # Click the real right-hand clock, verifying its action and independent layer.
  info=json.loads((Path(os.environ['XDG_RUNTIME_DIR'])/'selandia-eww-runtime.json').read_text())
  right=json.loads((Path(info['geometry'])/'right.json').read_text())
  rect=right['capsules'][0]
  output=next(value for value in json.loads(command('niri','msg','--json','outputs')).values() if value.get('logical'))['logical']
  x=output['width']-12-right['width']+rect['x']+rect['width']//2
  y=12+rect['y']+rect['height']//2
  command(str(pointer),str(x),str(y),str(output['width']),str(output['height']),'click')
  wait(lambda:'selandia-calendar' in command('niri','msg','layers'))
  assert 'selandia-control' not in command('niri','msg','layers')
  session_probe.screenshot(EVID/'calendar.png')
  command(str(BASE/'scripts/desktop'),'calendar');wait(lambda:'selandia-calendar' not in command('niri','msg','layers'))
  result['clock']='actual pointer click opens calendar, no control centre; second invocation closes'
  stop(bar);wait(lambda:not island.endpoint().exists())
  launcher=start('anyrun',[str(BASE/'scripts/desktop'),'launcher'])
  wait(lambda:'anyrun' in command('niri','msg','layers'))
  session_probe.screenshot(EVID/'anyrun.png');assert launcher.poll() is None;stop(launcher)
  terminal=start('alacritty',[str(BASE/'scripts/desktop'),'launch','terminal'])
  wait(lambda:any('Alacritty' in str(w.get('app_id','')) for w in json.loads(command('niri','msg','--json','windows'))))
  session_probe.screenshot(EVID/'alacritty.png');assert terminal.poll() is None;stop(terminal)
  result.update(status='PASS',anyrun='native layer visible',alacritty='native window visible')
  (EVID/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
 finally:
  players.close()
  for p in reversed(children):
   if p.poll() is None:stop(p)
  for log in logs:log.close()
if __name__=='__main__':main()
