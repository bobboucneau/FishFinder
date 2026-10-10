"""Validated settings shared by the display and collector."""
import ipaddress
import json
import os
from pathlib import Path
import tempfile

DEFAULTS = dict(stratux_ip='192.168.10.1', own_tail='', default_range=10,
                idle_seconds=10, vertical_threshold_ft=5000, vertical_filter=True,
                horizon_minutes=2, orientation='track-up', airports_visible=True, trail_seconds=300)
SETTINGS_PATH = Path(os.environ.get('FISHFINDER_SETTINGS', str(Path(__file__).resolve().parent/'settings.json')))


def validate(values):
    result = dict(DEFAULTS)
    result.update({k:v for k,v in values.items() if k in DEFAULTS})
    result['stratux_ip'] = str(ipaddress.IPv4Address(result['stratux_ip'].strip()))
    result['own_tail'] = str(result['own_tail']).strip().upper()
    if len(result['own_tail']) > 16 or any(not (c.isalnum() or c=='-') for c in result['own_tail']):
        raise ValueError('Tail number: use up to 16 letters, numbers or hyphens')
    for key, low, high in [('idle_seconds',0,300),('vertical_threshold_ft',1000,20000),
                           ('horizon_minutes',1,10),('trail_seconds',30,300)]:
        raw=result[key]
        if isinstance(raw,bool) or float(raw)!=int(raw): raise ValueError(f'{key}: use a whole number')
        result[key]=int(raw)
        if not low<=result[key]<=high: raise ValueError(f'{key}: choose {low} to {high}')
    if result['orientation'] not in ('track-up','north-up'):raise ValueError('Orientation: choose track-up or north-up')
    result['default_range']=int(result['default_range'])
    if result['default_range'] not in (2,5,10,20): raise ValueError('Range must be 2, 5, 10 or 20 NM')
    for key in ('vertical_filter','airports_visible'):
        if not isinstance(result[key],bool): raise ValueError(f'{key}: expected on/off')
    return result


def load(path=SETTINGS_PATH):
    try:
        return validate(json.loads(Path(path).read_text()))
    except FileNotFoundError:
        return dict(DEFAULTS)


def save(values,path=SETTINGS_PATH):
    values=validate(values); path=Path(path)
    temp=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,delete=False) as f:
            temp=Path(f.name); json.dump(values,f,indent=2); f.flush(); os.fsync(f.fileno())
        os.replace(temp,path)
    finally:
        if temp is not None and temp.exists(): temp.unlink()
    return values
