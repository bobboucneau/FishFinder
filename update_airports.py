#!/usr/local/Fishfinder/.venv/bin/python3
"""Download OurAirports reference data and atomically create an offline cache."""
import argparse
import csv
import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import urllib.request
from airport_data import coordinates

BASE = 'https://davidmegginson.github.io/ourairports-data/'
RUNWAY_FIELDS = ('length_ft','width_ft','surface','lighted','closed','le_ident','he_ident',
 'le_latitude_deg','le_longitude_deg','he_latitude_deg','he_longitude_deg','le_heading_degT','he_heading_degT')


def fetch(name):
    request = urllib.request.Request(BASE+name, headers={'User-Agent':'FishFinder-reference-cache/0.2'})
    with urllib.request.urlopen(request, timeout=90) as response:
        data = response.read(40_000_001)
    if len(data) > 40_000_000:
        raise ValueError('Dataset exceeds download size limit')
    rows = csv.DictReader(io.StringIO(data.decode('utf-8-sig')))
    required = {'ident','type','name','latitude_deg','longitude_deg'} if name == 'airports.csv' else {'airport_ident','length_ft','le_ident','he_ident','le_heading_degT','he_heading_degT'} if name == 'runways.csv' else {'airport_ident','type','frequency_mhz'}
    if not required <= set(rows.fieldnames or []):
        raise ValueError(f'{name}: missing required columns')
    return list(rows)


def build(airports, runways, frequencies, countries=()):
    result = {}
    for row in airports:
        if row['type'] not in ('small_airport','medium_airport','large_airport'):
            continue
        if countries and row.get('iso_country') not in countries:
            continue
        pos = coordinates(row['latitude_deg'], row['longitude_deg'])
        if pos is None or not row['ident']:
            continue
        result[row['ident']] = dict(ident=row['ident'], code=row.get('icao_code') or row.get('gps_code') or row.get('local_code') or row['ident'],
            name=row['name'], lat=pos[0], lon=pos[1], elevation_ft=row.get('elevation_ft',''),
            type=row['type'], country=row.get('iso_country',''), municipality=row.get('municipality',''), runways=[], frequencies=[])
    for row in runways:
        if row['airport_ident'] in result:
            result[row['airport_ident']]['runways'].append({k:row.get(k,'') for k in RUNWAY_FIELDS})
    for row in frequencies:
        if row['airport_ident'] in result:
            result[row['airport_ident']]['frequencies'].append({k:row.get(k,'') for k in ('type','description','frequency_mhz')})
    if not result:
        raise ValueError('No usable airports; old cache retained')
    return dict(schema=1, downloaded_utc=datetime.now(timezone.utc).isoformat(), source='OurAirports', countries=list(countries), airports=list(result.values()))


def refresh(output, countries=None):
    output=Path(output)
    if countries is None:
        try: countries=json.loads(output.read_text()).get('countries',[])
        except (OSError,ValueError): countries=[]
    data=build(fetch('airports.csv'),fetch('runways.csv'),fetch('airport-frequencies.csv'),countries)
    # Reject a suspiciously truncated update under the same regional scope.
    if output.exists():
        try: old=json.loads(output.read_text())
        except (OSError,ValueError): old={}
        if old.get('countries',[])==list(countries) and len(data['airports']) < .8*len(old.get('airports',[])):
            raise ValueError('Unexpected airport count reduction; old cache retained')
    if not any(a['runways'] for a in data['airports']):
        raise ValueError('No runway records; old cache retained')
    if not any(a['frequencies'] for a in data['airports']):
        raise ValueError('No frequency records; old cache retained')
    output.parent.mkdir(parents=True,exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=output.parent,delete=False) as stream:
            temp = Path(stream.name)
            json.dump(data,stream,ensure_ascii=False,separators=(',',':'))
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temp,output)
    finally:
        if temp is not None and temp.exists(): temp.unlink()
    return len(data['airports'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path(__file__).resolve().parent/'airports.json')
    parser.add_argument('--country',action='append',default=[])
    args=parser.parse_args()
    print('Downloading airports, runways and frequencies...',flush=True)
    count=refresh(args.output,[c.upper() for c in args.country])
    print(f'Saved {count} airports to {args.output}')


if __name__=='__main__': main()
