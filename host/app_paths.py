"""Immutable program resources and persistent per-user runtime data."""
import os,sys
from pathlib import Path

FROZEN=bool(getattr(sys,'frozen',False))
PORTABLE=FROZEN or os.environ.get('NEXYS_PORTABLE_RUNTIME')=='1'
SOURCE_ROOT=Path(__file__).resolve().parents[1]
RESOURCE_ROOT=Path(sys._MEIPASS)/'release_assets' if FROZEN else SOURCE_ROOT/'release_assets'
DATA_ROOT=(Path(os.environ.get('NEXYS_MONITOR_DATA',str(Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData/Local'))/'NexysMonitor')))
           if PORTABLE else SOURCE_ROOT)
APP_VERSION='1.6.0'

def app_command(*args):
    if FROZEN:return [sys.executable,*map(str,args)]
    return [sys.executable,str(SOURCE_ROOT/'host/portable_main.py'),*map(str,args)]

