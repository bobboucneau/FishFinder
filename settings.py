"""Validated settings shared by the display and collector."""

# READING THIS FILE: one agreed list of settings for the whole application.
#
# DEFAULTS supplies a value for every setting, including settings absent from an
# older saved file. validate() checks type and range before anyone uses a value.
# load() reads JSON text from disk; save() writes a complete replacement safely.
# The collector can notice an IP-address change on a later polling/retry cycle.
# The display applies its visual settings when the user saves Setup.
#
# A dictionary is a collection of named values: config['label_size'] means
# 'look up the value stored under the name label_size'. None means missing or
# unavailable; it is different from zero. True and False are on/off values.

import ipaddress
import json
import os
from pathlib import Path
import tempfile

# These defaults are also used by Restore defaults. Adding a preference here gives older
# settings files a compatible value; validate() and Setup must understand the same key.
DEFAULTS = dict(screen_sleep='never', label_size='normal', runway_extensions=True, stratux_ip='192.168.10.1', own_tail='', default_range=10,
                idle_seconds=10, vertical_threshold_ft=5000, vertical_filter=True, hide_vertical=False,
                horizon_minutes=2, orientation='track-up', ownship_symbol='high-wing', ownship_source='adsb-first', airports_visible=True, ground_map=False, trail_seconds=300)
SETTINGS_PATH = Path(os.environ.get('FISHFINDER_SETTINGS', str(Path(__file__).resolve().parent/'settings.json')))


# Merge defaults with known saved keys, convert allowed values, and reject unsupported
# choices before they affect the application.
def validate(values):
    result = dict(DEFAULTS)
    # Ignore unrecognized keys rather than forwarding arbitrary JSON fields into the
    # application. Copy the defaults first so validating one file does not mutate the shared
    # default dictionary.
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
    if result['screen_sleep'] not in ('never','5','10','20','30','60'):raise ValueError('Screen sleep: choose never or 5/10/20/30/60 minutes')
    if result['label_size'] not in ('normal','large','extra-large'):raise ValueError('Label size: choose normal, large or extra-large')
    if result['orientation'] not in ('track-up','north-up'):raise ValueError('Orientation: choose track-up or north-up')
    if result['ownship_symbol'] not in ('high-wing','low-wing','twin'):raise ValueError('Ownship airplane: choose high-wing, low-wing or twin')
    if result['ownship_source'] not in ('adsb-first','stratux-first'):raise ValueError('Ownship source: choose adsb-first or stratux-first')
    result['default_range']=int(result['default_range'])
    if result['default_range'] not in (2,5,10,20): raise ValueError('Range must be 2, 5, 10 or 20 NM')
    for key in ('vertical_filter','hide_vertical','airports_visible','ground_map','runway_extensions'):
        if not isinstance(result[key],bool): raise ValueError(f'{key}: expected on/off')
    return result


# Read and validate settings. A missing file means use defaults; a malformed existing file
# should produce an error rather than hide the problem.
def load(path=SETTINGS_PATH):
    try:
        return validate(json.loads(Path(path).read_text()))
    except FileNotFoundError:
        return dict(DEFAULTS)


# Validate first, write a temporary file beside the destination, flush it, then replace the
# destination in one step.
def save(values,path=SETTINGS_PATH):
    values=validate(values); path=Path(path)
    from fs_checks import write_problem
    problem=write_problem(path,atomic=True)
    if problem:raise PermissionError(problem)
    temp=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,delete=False) as f:
            temp=Path(f.name); json.dump(values,f,indent=2); f.flush(); os.fsync(f.fileno())
        # The temporary file lives in the same directory/filesystem, allowing a whole-file
        # replacement. This avoids a crash leaving half of settings.json written.
        os.replace(temp,path)
    finally:
        if temp is not None and temp.exists(): temp.unlink()
    return values


def explicit(key,path=SETTINGS_PATH):
    """Whether a preference has been saved, before defaults were merged."""
    try:return key in json.loads(Path(path).read_text())
    except FileNotFoundError:return False

# Combine the chosen base label size with a modest zoom multiplier. This affects map labels,
# not buttons or range-ring text.
def label_scale(config,range_nm):
    return {'normal':1,'large':1.25,'extra-large':1.5}[config['label_size']]*{20:1,10:1.12,5:1.25,2:1.4}[range_nm]
