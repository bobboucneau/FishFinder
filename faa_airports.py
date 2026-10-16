"""FAA NASR airport enrichment. Only effective cycles and explicit fields are used."""
import csv
from datetime import date,datetime,timedelta,timezone
import io
import re
import urllib.request
from urllib.parse import urljoin
import zipfile
from airport_data import number

INDEX='https://www.faa.gov/air_traffic/flight_info/aeronav/aero_data/NASR_Subscription/'

def download(url,limit):
    request=urllib.request.Request(url,headers={'User-Agent':'FishFinder-airport-reference/0.4'})
    with urllib.request.urlopen(request,timeout=90) as response:raw=response.read(limit+1)
    if len(raw)>limit:raise ValueError('FAA download exceeds size limit')
    return raw

def cycle_links(html,today=None):
    today=today or datetime.now(timezone.utc).date()
    matches=re.findall(r'href=["\']([^"\']*NASR_Subscription/(\d{4}-\d{2}-\d{2})/?)["\']',html,re.I)
    valid=[(date.fromisoformat(day),urljoin(INDEX,url)) for url,day in matches if date.fromisoformat(day)<=today]
    if not valid:raise ValueError('No effective FAA cycle found')
    return max(valid)

def rows(archive,name,required):
    info=archive.getinfo(name)
    if info.file_size>100_000_000:raise ValueError('FAA table too large')
    with archive.open(info) as stream:
        reader=csv.DictReader(io.TextIOWrapper(stream,encoding='utf-8-sig'))
        if not set(required)<=set(reader.fieldnames or []):raise ValueError(f'FAA {name}: missing fields')
        yield from reader

def enrich(data,raw,effective,source):
    """Mutate a candidate cache, never the installed file. A present FAA runway-end record defaults left unless right is specified."""
    start=date.fromisoformat(effective);end=start+timedelta(days=28)
    today=datetime.now(timezone.utc).date()
    if not start<=today<end:raise ValueError('FAA cycle is not currently effective')
    by_code={}
    for a in data['airports']:
        if a.get('country')=='US':
            for code in (a['ident'],a.get('code')):
                if code:by_code.setdefault(code,[]).append(a)
    base={};count=0
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        for r in rows(z,'APT_BASE.csv',('EFF_DATE','SITE_NO','ARPT_ID','ICAO_ID','LAT_DECIMAL','LONG_DECIMAL','TPA','ELEV','TWR_TYPE_CODE')):
            if r['EFF_DATE'].replace('/','-')!=effective:raise ValueError('Mixed FAA cycle dates')
            choices=by_code.get(r['ICAO_ID'],[]) + by_code.get(r['ARPT_ID'],[])
            for a in {a['ident']:a for a in choices}.values():
                lat,lon=number(r['LAT_DECIMAL']),number(r['LONG_DECIMAL'])
                if lat is None or lon is None or abs(a['lat']-lat)>.02 or abs(a['lon']-lon)>.02:continue
                agl,elev=number(r['TPA']),number(r['ELEV'])
                ref=dict(source='FAA NASR',effective=effective,expires=end.isoformat(),url=source,
                         tower='non-towered' if r['TWR_TYPE_CODE']=='NON-ATCT' else 'towered' if r['TWR_TYPE_CODE'].startswith('ATCT') else 'unknown',
                         patterns={},pattern_msl_ft=round(agl+elev) if agl is not None and elev is not None and 0<agl<10000 else None,
                         pattern_remarks=[],special_pattern=False)
                a['reference']=ref
                if elev is not None:a['elevation_ft']=str(elev)
                base.setdefault(r['SITE_NO'],[]).append(a);count+=1
        for r in rows(z,'APT_RWY_END.csv',('EFF_DATE','SITE_NO','RWY_END_ID','RIGHT_HAND_TRAFFIC_PAT_FLAG')):
            if r['EFF_DATE'].replace('/','-')!=effective:raise ValueError('Mixed FAA cycle dates')
            for a in base.get(r['SITE_NO'],[]):
                flag=r['RIGHT_HAND_TRAFFIC_PAT_FLAG'].strip()
                if flag in ('Y','N',''):a['reference']['patterns'][r['RWY_END_ID']]='Right' if flag=='Y' else 'Left'
        for r in rows(z,'APT_RMK.csv',('SITE_NO','REF_COL_NAME','REMARK')):
            remark=r['REMARK'].strip()
            for a in base.get(r['SITE_NO'],[]):
                ref=a['reference']
                if r['REF_COL_NAME']=='TPA':
                    ref['pattern_remarks'].append(remark[:500]);ref['pattern_msl_ft']=None
                if re.search(r'(?:TRAFFIC|PATTERN|TFC).*(?:EXCEPT|PROHIBIT|RESTRICT|WHEN|ONLY)',remark,re.I):ref['special_pattern']=True
    if len(by_code)>=200 and count<100:raise ValueError('Unexpectedly few matched FAA airports; old cache retained')
    data['source']='OurAirports + FAA NASR'
    data['faa']=dict(effective=effective,expires=end.isoformat(),source=source,matched=count)
    return data

def fetch_enrichment(data):
    day,page=cycle_links(download(INDEX,2_000_000).decode('utf-8'))
    html=download(page,2_000_000).decode('utf-8')
    links=re.findall(r'href=["\']([^"\']+_APT_CSV\.zip)["\']',html,re.I)
    if len(links)!=1:raise ValueError('Cannot identify FAA airport CSV download')
    url=urljoin(page,links[0])
    if not url.startswith(('https://nfdc.faa.gov/','https://aeronav.faa.gov/')):raise ValueError('Unexpected FAA data host')
    return enrich(data,download(url,30_000_000),day.isoformat(),page)
