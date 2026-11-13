"""Build the scoped Rust GTK3 input-region helper; never preload into GTK4."""
import hashlib
import os
from pathlib import Path
import stat
import subprocess
import tempfile
from appearance import BASE


def clean_environment(environment=None):
    values=dict(os.environ if environment is None else environment)
    helper=values.pop('SELANDIA_EWW_INPUT_LIB',None)
    if helper:
        preload=[item for item in values.get('LD_PRELOAD','').split(':') if item and item!=helper]
        if preload:values['LD_PRELOAD']=':'.join(preload)
        else:values.pop('LD_PRELOAD',None)
    values.pop('SELANDIA_EWW_GEOMETRY',None)
    values.pop('SELANDIA_EWW_EXCLUSIVE_ZONE',None)
    return values


def library():
    source=BASE/'eww/input_region.rs'
    version=subprocess.check_output(['rustc','--version'],text=True,timeout=8)
    identity=hashlib.sha256(source.read_bytes()+version.encode()+os.uname().machine.encode()).hexdigest()[:24]
    cache=Path(os.environ.get('XDG_CACHE_HOME',str(Path.home()/'.cache')))/'selandia-niri/eww-input'
    cache.mkdir(mode=0o700,parents=True,exist_ok=True)
    info=cache.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o022:
        raise OSError('untrusted Eww input cache')
    target=cache/(identity+'.so')
    if any(character.isspace() or character==':' for character in str(target)):
        raise OSError('Eww input cache path cannot contain whitespace or colon')
    if target.exists() or target.is_symlink():
        info=target.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o022:
            raise OSError('untrusted Eww input library')
        return target
    with tempfile.TemporaryDirectory(prefix='build-',dir=cache) as temporary:
        built=Path(temporary)/'input.so'
        result=subprocess.run(['rustc','--edition=2024','--crate-type','cdylib','-O',str(source),'-o',str(built),
                               '-l','dl','-l','gtk-3','-l','gdk-3','-l','gtk-layer-shell','-l','cairo','-l','gobject-2.0','-l','glib-2.0'],
                              capture_output=True,text=True,timeout=90,env=clean_environment())
        if result.returncode:raise RuntimeError(result.stderr[-3000:])
        os.chmod(built,0o600);os.replace(built,target)
    return target
