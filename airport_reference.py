"""Round-screen airport quick reference; no claim to be an FAA airport diagram."""
from datetime import date,datetime,timezone
import math
import re
from airport_data import number,runway_segments

def current_reference(a,today=None):
    ref=a.get('reference',{});today=today or datetime.now(timezone.utc).date()
    try:return ref if date.fromisoformat(ref['effective'])<=today<date.fromisoformat(ref['expires']) else {}
    except (ValueError,KeyError,TypeError):return {}

def runways(a):
    return [r for r in a.get('runways',[]) if not (
        r.get('le_ident','').startswith('H') and r.get('he_ident','').startswith('H'))]

def radio_kind(f):
    kind=f.get('type','').upper()
    return 'CTAF' if kind=='UNIC' and 'CTAF' in f.get('description','').upper() else kind

def simple_airport(a):
    strips=runways(a)
    primary={}
    for f in a.get('frequencies',[]):
        kind=radio_kind(f)
        if kind in ('CTAF','TWR','GND'):primary.setdefault(kind,set()).add(f.get('frequency_mhz'))
    return (a.get('type')!='large_airport' and 0<len(strips)<=2 and
            all(len(values)<=1 for values in primary.values()) and
            all(r.get('closed')!='1' and all(re.fullmatch(r'(?:0?[1-9]|[12][0-9]|3[0-6])[LCR]?',r.get(key,'')) for key in ('le_ident','he_ident')) for r in strips) and
            not a.get('reference',{}).get('special_pattern'))

def active_runway(a,index):
    strips=runways(a)
    if not strips:return None,0
    if index is None:index=max(range(len(strips)),key=lambda i:number(strips[i].get('length_ft')) or 0)
    index=max(0,min(index,len(strips)-1));return strips[index],index

def pattern(a,end):
    ref=current_reference(a)
    if ref.get('tower')!='non-towered' or not simple_airport(a):return None
    return ref.get('patterns',{}).get(end)


def pattern_altitude(a,runway):
    ref=current_reference(a)
    if not ref or ref.get('tower')!='non-towered' or not simple_airport(a):return None,''
    altitude=ref.get('pattern_msl_ft')
    if altitude is not None:return altitude,'Published AGL converted to MSL'
    elev=number(a.get('elevation_ft'))
    if elev is None:return None,''
    scoped=[]
    for remark in ref.get('pattern_remarks',[]):
        match=re.fullmatch(r'TPA RWY ([0-9LRC]+/[0-9LRC]+) (\d+) FT AGL\.',remark)
        if not match:return None,''
        scoped.append((set(match[1].split('/')),int(match[2])))
    ends={runway.get('le_ident'),runway.get('he_ident')}
    values={value for scope,value in scoped if scope==ends}
    if len(values)==1:return round(elev+values.pop()),'Published runway AGL converted to MSL'
    if values:return None,''
    return round(elev+1000),'Standard-derived · verify local procedures'

def draw(d,a):
    # The airport owns the whole scope while open: no map/control hitboxes behind it.
    d.canvas.delete('all');d.buttons=[];d.hits=[];d.airport_hits=[];d.airport_buttons=[]
    d.rect(0,0,800,800,fill='#07131f',outline='')
    d.text(400,53,a['code'],size=26,fill='#62b6ff')
    d.text(400,94,a['name'],size=15,width=490*d.unit)
    elevation=number(a.get('elevation_ft'))
    d.text(400,130,f'{elevation:,.0f} ft MSL · field elevation' if elevation is not None else 'Field elevation unavailable',size=12)
    ref=current_reference(a);tower=ref.get('tower','unknown')
    freqs=a.get('frequencies',[])
    primary='TWR' if tower=='towered' or any(radio_kind(f)=='TWR' for f in freqs) else 'CTAF' if tower=='non-towered' or any(radio_kind(f)=='CTAF' for f in freqs) else None
    radio=[f for f in freqs if radio_kind(f)==primary] if primary else []
    weather=[f for f in freqs if f.get('type','').upper() in ('AWOS','ASOS','ATIS')]
    for y,label,values in [(177,primary or 'RADIO',radio),(218,'WX',weather)]:
        d.text(220,y,values[0].get('type',label) if label=='WX' and len(values)==1 else label,size=13,anchor='w',fill='#9fb8c6')
        text=(f"{float(values[0]['frequency_mhz']):.3f}" if number(values[0].get('frequency_mhz')) is not None else '?') if len(values)==1 else 'See radio list' if values or primary is None else 'Unavailable'
        d.text(440,y,text,size=25 if len(values)==1 else 15)
    runway,index=active_runway(a,getattr(d,'airport_runway_index',None));d.airport_runway_index=index
    if d.airport_runways:
        detail_page(d,a);buttons(d,a);return
    d.airport_page=0
    if not simple_airport(a):
        d.text(400,340,'See FAA Airport Diagram' if a.get('country')=='US' else 'See official airport diagram',size=20,width=530*d.unit)
        d.text(400,385,'and Chart Supplement' if a.get('country')=='US' else 'and aeronautical publication',size=17)
        d.text(400,445,'Layout or procedures exceed this quick-reference view.',size=13,width=500*d.unit)
    else:
        if tower=='towered':label='Towered · follow tower instructions'
        elif tower=='non-towered':
            label=' · '.join(f"{runway.get(k,'?')} {pattern(a,runway.get(k)) or 'pattern unavailable'}" for k in ('le_ident','he_ident'))
        else:label='Pattern direction unavailable'
        d.text(400,264,label,size=16,width=600*d.unit)
        altitude,provenance=pattern_altitude(a,runway)
        standard=provenance.startswith('Standard')
        d.text(400,298,(f'Pattern {altitude:,.0f} ft MSL'+(' *' if standard else '')) if altitude is not None else 'Pattern altitude unavailable',size=18,fill='#ffd45c' if standard else '#e0f2ef')
        if provenance:d.text(400,323,'* Field + 1,000 ft; verify local procedures' if standard else provenance,size=10,fill='#ffd45c' if standard else '#9fb8c6')
        diagram(d,a,runway)
        if len(runways(a))>1:
            for i,r in enumerate(runways(a)):
                x=215+i*190
                d.airport_button(x,600,x+180,640,f"RWY {r.get('le_ident','?')}/{r.get('he_ident','?')}",f'runway:{i}')
    buttons(d,a)

def buttons(d,a):
    d.airport_button(225,654,395,699,'Reference' if d.airport_runways else 'Radios / data','view')
    d.airport_button(405,654,575,699,'Back to traffic','close')
    ref=a.get('reference',{})
    source=f"FAA effective {ref.get('effective')} · expires {ref.get('expires')}" if ref else 'Pattern source unavailable'
    if ref and not current_reference(a):source='FAA data expired · update airports'
    d.text(400,722,source,size=10,fill='#ffd45c' if ref and not current_reference(a) else '#9fb8c6',width=490*d.unit)
    d.text(400,748,'Quick reference · verify current publications',size=10,fill='#ffd45c')

def detail_page(d,a):
    rows=[]
    for f in a.get('frequencies',[]):rows.append(f"{f.get('type','Radio')} {f.get('frequency_mhz','?')} · {f.get('description','')}")
    rows+=a.get('reference',{}).get('pattern_remarks',[])
    if a.get('reference',{}).get('tower')=='towered':rows.append('Tower hours are not evaluated. Pattern arrows are omitted at all times.')
    rows.append('Standard-derived altitude uses field elevation + 1,000 ft for light piston GA; it is not a verified local altitude.')
    rows.append('Turn arrows indicate pattern side, not a flight path or permission to depart.')
    rows.append('Runway sketch only: no taxiways, obstacles or operational restrictions depicted.')
    rows.append('Sources: OurAirports + FAA NASR where available.')
    pages=max(1,math.ceil(len(rows)/6));d.airport_page=min(d.airport_page,pages-1)
    for i,text in enumerate(rows[d.airport_page*6:(d.airport_page+1)*6]):d.text(400,272+i*49,text,size=12,width=550*d.unit)
    d.airport_button(245,580,375,625,'Prev','prev',enabled=d.airport_page>0)
    d.airport_button(425,580,555,625,'Next','next',enabled=d.airport_page<pages-1)


def pattern_arrow(point,heading,direction):
    """A downwind/base/final U symbol; the final tangent aims at the threshold."""
    x,y=point;hx,hy=heading
    sign=1 if direction=='Right' else -1
    side=(-hy*sign,hx*sign);radius=16
    center=(x-hx*26+side[0]*radius,y-hy*26+side[1]*radius)
    points=[(x+side[0]*32+hx*8,y+side[1]*32+hy*8)]
    points.extend((center[0]+radius*(side[0]*math.cos(t)-hx*math.sin(t)),
                   center[1]+radius*(side[1]*math.cos(t)-hy*math.sin(t)))
                  for t in (i*math.pi/24 for i in range(25)))
    points.append((x-hx*7,y-hy*7))
    return points

def diagram(d,a,selected):
    from traffic_display import xy
    segments=runway_segments(dict(a,runways=runways(a)),xy)
    if not segments:
        d.text(400,440,'Runway geometry unavailable',size=16);return
    points=[v for _,p,q,_ in segments for v in (p,q)]
    mid=((min(v[0] for v in points)+max(v[0] for v in points))/2,(min(v[1] for v in points)+max(v[1] for v in points))/2)
    scale=min(390/max(.01,max(v[0] for v in points)-min(v[0] for v in points)),140/max(.01,max(v[1] for v in points)-min(v[1] for v in points)))
    def screen(v):return (400+(v[0]-mid[0])*scale,450-(v[1]-mid[1])*scale)
    def line(points,**kw):
        coords=[n for x,y in points for n in (d.cx+(x-400)*d.unit,d.cy+(y-400)*d.unit)]
        d.canvas.create_line(*coords,**kw)
    d.text(586,350,'NORTH UP',size=10,fill='#9fb8c6')
    label_positions=[]
    screen_segments=[(screen(p),screen(q)) for _,p,q,_ in segments]
    def distance(point,a,b):
        dx,dy=b[0]-a[0],b[1]-a[1];den=dx*dx+dy*dy
        t=max(0,min(1,((point[0]-a[0])*dx+(point[1]-a[1])*dy)/den)) if den else 0
        return math.dist(point,(a[0]+t*dx,a[1]+t*dy))
    for r,p,q,schematic in segments:
        chosen=(r.get('le_ident'),r.get('he_ident'))==(selected.get('le_ident'),selected.get('he_ident'))
        p,q=screen(p),screen(q);length=math.dist(p,q)
        if length<1:continue
        v=((q[0]-p[0])/length,(q[1]-p[1])/length)
        color='#e0f2ef' if chosen else '#526b7b'
        line([p,q],fill=color,width=(7 if chosen else 4)*d.unit,**({'dash':(5,4)} if schematic else {}))
        for point,heading,key in [(p,v,'le_ident'),(q,(-v[0],-v[1]),'he_ident')]:
            end=r.get(key,'?');x,y=point
            direction=pattern(a,end)
            right=(-heading[1],heading[0]);sign=1 if direction=='Left' else -1
            for offset in (25,45,65,-25,-45):
                pos=(x+right[0]*offset*sign,y+right[1]*offset*sign)
                if all(distance(pos,a,b)>18 for a,b in screen_segments) and all(math.dist(pos,other[:2])>28 for other in label_positions):break
            label_positions.append((*pos,end,color))
            if chosen and direction and not schematic and r.get('closed')!='1':
                line(pattern_arrow(point,heading,direction),fill='#ff3030',width=4*d.unit,
                     arrow='last',arrowshape=(12*d.unit,15*d.unit,6*d.unit),capstyle='round',joinstyle='round')
    for x,y,end,color in label_positions:d.text(x,y,end,size=13,fill=color)
    d.text(400,579,f"RWY {selected.get('le_ident','?')}/{selected.get('he_ident','?')} · {selected.get('length_ft') or '?'} × {selected.get('width_ft') or '?'} ft",size=12)

