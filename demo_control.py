"""Persistent operation mode and atomic requests to the stable supervisor.

Only the supervisor stops processes or chooses databases. The display requests
an explicit mode change; it never edits live aircraft records or Wi-Fi profiles.
"""
import json
import math
import os
from pathlib import Path


def write_json(path, value):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value)+'\n')
    temporary.replace(path)


def airport_spec(path, code):
    """Resolve an identifier and require usable runway endpoints and elevation."""
    code=str(code).strip().upper()
    if not code or len(code)>7 or not code.isascii() or not code.isalnum():
        raise ValueError('Enter a valid airport identifier, for example O22.')
    records=json.loads(Path(path).read_text())['airports']
    matches=[a for a in records if a.get('ident')==code]
    if not matches:matches=[a for a in records if a.get('code')==code]
    if len(matches)!=1:raise ValueError('Airport not found or ambiguous. Use its full identifier.')
    airport=matches[0]
    if not all(math.isfinite(float(airport[k])) and abs(float(airport[k]))<=limit for k,limit in (('lat',90),('lon',180))):
        raise ValueError('Airport coordinates are unavailable.')
    try:
        elevation=float(airport['elevation_ft'])
        if not math.isfinite(elevation):raise ValueError()
    except (TypeError,ValueError,KeyError):
        raise ValueError('This airport has no usable field elevation.')
    usable=[]
    for runway in airport.get('runways',[]):
        try:
            values=[float(runway[end+'_'+axis+'_deg']) for end in ('le','he') for axis in ('latitude','longitude')]
            if not all(math.isfinite(v) for v in values):continue
            if not all(abs(values[i])<=limit for i,limit in enumerate((90,180,90,180))):continue
            length=math.hypot(values[2]-values[0],values[3]-values[1])
            if length>0 and runway.get('le_ident') and not str(runway.get('closed','0')).lower() in ('1','true'):
                usable.append((length,runway))
        except (KeyError,ValueError,TypeError):continue
    if not usable:raise ValueError('Demo needs an airport with published runway endpoints.')
    runway=max(usable,key=lambda pair:pair[0])[1]
    return airport,(airport['code'],runway['le_ident'],elevation,2,350)


def request(home, mode, airport):
    if mode not in ('live','demo'):raise ValueError('Unknown operation mode')
    write_json(Path(home)/'runtime/mode-request.json',{'mode':mode,'airport':airport})
