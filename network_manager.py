"""FishFinder's Wi-Fi policy, separate from the touch-screen presentation.

NetworkManager owns passwords and radio operations. This file stores only friendly
names, BSSIDs and NetworkManager UUIDs. All operations are bounded, run on worker
threads, and never require a shell or print credentials. Tests replace the command
runner and HTTP probes rather than changing the developer's network.
"""
from dataclasses import dataclass
import csv
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import urllib.request
import uuid
import settings

PROFILE_PATH = settings.SETTINGS_PATH.with_name('networks.json')
INTERNET_URL = 'https://www.gstatic.com/generate_204'
UPDATE_URL = 'https://davidmegginson.github.io/ourairports-data/airports.csv'


def fields(line):
    # nmcli terse output escapes colons and backslashes. Splitting on every ':'
    # would corrupt BSSIDs and legitimate SSIDs such as Bob:Home.
    result=[];value='';escaped=False
    for char in line:
        if escaped:value+=char;escaped=False
        elif char=='\\':escaped=True
        elif char==':':result.append(value);value=''
        else:value+=char
    result.append(value)
    return result


def friendly_key(name):
    return ' '.join(name.split()).casefold()


def friendly_name(name):
    name=' '.join(name.split())
    if not name or len(name)>40 or any(ord(c)<32 for c in name):
        raise ValueError('Use a friendly name of 1–40 characters.')
    return name


@dataclass(frozen=True)
class AccessPoint:
    bssid: str
    ssid: str
    signal: int
    security: str
    device: str
    active: bool = False


class Profiles:
    def __init__(self,path=PROFILE_PATH):
        self.path=Path(path)
        try:self.data=json.loads(self.path.read_text())
        except FileNotFoundError:self.data={'version':1,'preferred':None,'networks':[]}
        if not isinstance(self.data,dict) or not isinstance(self.data.get('networks'),list):
            raise ValueError('Saved network list is invalid; previous file retained.')

    def match(self,bssid):
        return next((p for p in self.data['networks'] if p['bssid'].upper()==bssid.upper()),None)

    def duplicate(self,name,bssid):
        return next((p for p in self.data['networks'] if friendly_key(p['name'])==friendly_key(name)
                     and p['bssid'].upper()!=bssid.upper()),None)

    def save(self,ap,connection_id,name,capabilities,preferred=False,replace=False):
        # Build a candidate first. Name conflicts never destroy the working entry.
        name=friendly_name(name);duplicate=self.duplicate(name,ap.bssid)
        if duplicate and not replace:raise ValueError('That friendly name is already in use.')
        data=json.loads(json.dumps(self.data))
        old=data.get('preferred')
        removed={ap.bssid.upper()}
        if duplicate:removed.add(duplicate['bssid'].upper())
        data['networks']=[p for p in data['networks'] if p['bssid'].upper() not in removed]
        entry=dict(name=name,bssid=ap.bssid.upper(),ssid=ap.ssid,uuid=connection_id,
                   stratux_ip=capabilities.get('stratux_ip'),internet=capabilities.get('internet',False),
                   updates=capabilities.get('updates',False))
        data['networks'].append(entry)
        if preferred or old in removed:data['preferred']=ap.bssid.upper() if entry['stratux_ip'] else None
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temporary=None
        try:
            with tempfile.NamedTemporaryFile(mode='w',dir=self.path.parent,delete=False) as stream:
                temporary=Path(stream.name);json.dump(data,stream,indent=2);stream.flush();os.fsync(stream.fileno())
            os.replace(temporary,self.path)
        finally:
            if temporary and temporary.exists():temporary.unlink()
        self.data=data
        return entry


def selection(profiles,aps):
    # Return an automatic choice only for the explicitly preferred receiver.
    # A sole alternative receiver still needs the user's confirmation.
    available={ap.bssid.upper():ap for ap in aps}
    preferred=profiles.data.get('preferred')
    if preferred in available:return 'preferred',available[preferred]
    known=[ap for ap in aps if profiles.match(ap.bssid)]
    return ('alternative',known[0]) if len(known)==1 else ('choose',None)


class Manager:
    def __init__(self,profiles=None,runner=None):
        self.profiles=profiles or Profiles();self.runner=runner or subprocess.run
        self.lock=threading.Lock();self.selected=None;self.last_result=None

    def nm(self,*arguments,password=None):
        # Secrets are sent through stdin for nmcli --ask, never command arguments,
        # logs or FishFinder JSON. Error messages intentionally omit command output.
        try:
            result=self.runner(['nmcli',*arguments],input=(password+'\n') if password is not None else None,
                capture_output=True,text=True,timeout=45,env={**os.environ,'LC_ALL':'C'})
        except (OSError,subprocess.TimeoutExpired) as exc:
            raise RuntimeError('NetworkManager unavailable or timed out. Retry or check local permissions.') from exc
        if result.returncode:raise RuntimeError('Network operation failed. Check password and NetworkManager permissions, then retry.')
        return result.stdout

    def scan(self):
        with self.lock:
            # Rescan uses NetworkManager's bounded wait; it does not activate anything.
            output=self.nm('--wait','15','-t','--escape','yes','-f',
                           'BSSID,SSID,SIGNAL,SECURITY,DEVICE,IN-USE','device','wifi','list','--rescan','yes')
            aps={}
            for line in output.splitlines():
                row=fields(line)
                if len(row)!=6 or not re.fullmatch(r'(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}',row[0]):continue
                if not row[1]:continue
                try:ap=AccessPoint(row[0].upper(),row[1],int(row[2]),row[3],row[4],row[5]=='*')
                except ValueError:continue
                if ap.bssid not in aps or ap.signal>aps[ap.bssid].signal:aps[ap.bssid]=ap
            return sorted(aps.values(),key=lambda ap:(self.profiles.match(ap.bssid) is None,-ap.signal,ap.ssid))

    def current_uuid(self,device):
        value=self.nm('-g','GENERAL.CON-UUID','device','show',device).strip()
        try:return str(uuid.UUID(value))
        except ValueError:raise RuntimeError('Connected network has no usable saved profile.')

    def connect(self,ap,password=None):
        with self.lock:
            saved=self.profiles.match(ap.bssid)
            # Disable automatic selection of arbitrary networks by NM on THIS
            # Wi-Fi interface. Explicit connection/up and our selected-only retry
            # still work; other interfaces/profiles are not modified or deleted.
            self.nm('device','set',ap.device,'autoconnect','no')
            if saved:
                self.nm('--wait','30','connection','up','uuid',saved['uuid'],'ifname',ap.device,'ap',ap.bssid)
                connection_id=saved['uuid']
            elif ap.active:
                connection_id=self.current_uuid(ap.device)
            else:
                identifier='FishFinder-'+uuid.uuid4().hex[:12]
                self.nm('--ask','--wait','30','device','wifi','connect',ap.bssid,'ifname',ap.device,
                        'name',identifier,'private','yes',password=password or '')
                connection_id=self.current_uuid(ap.device)
            self.nm('connection','modify','uuid',connection_id,'802-11-wireless.bssid',ap.bssid,
                    'connection.autoconnect','no')
            active=self.nm('-t','--escape','yes','-f','BSSID,IN-USE','device','wifi','list','ifname',ap.device,'--rescan','no')
            if not any(fields(line)==[ap.bssid,'*'] for line in active.splitlines()):
                raise RuntimeError('Connected access point did not match the selected BSSID.')
            self.selected=(ap,connection_id)
            result=self.probe(ap.device,saved.get('stratux_ip') if saved else None)
            authorize(ap,result['stratux_ip'])
            return connection_id,result

    def probe(self,device,configured=None):
        gateway=self.nm('-g','IP4.GATEWAY','device','show',device).strip().splitlines()
        addresses=[configured,settings.load()['stratux_ip'],*(gateway[:1])]
        receiver=None
        for address in dict.fromkeys(a for a in addresses if a):
            try:
                address=str(ipaddress.IPv4Address(address))
                # Disable HTTP proxy use for local receiver probes. Limit response
                # size and require Stratux-specific fields, not just HTTP 200.
                opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open('http://'+address+'/getSituation',timeout=3) as response:
                    data=json.loads(response.read(65537))
                if isinstance(data,dict) and {'GPSLatitude','GPSLongitude','GPSFixQuality'} <= data.keys():
                    receiver=address;break
            except (OSError,ValueError):pass
        result=dict(stratux_ip=receiver,internet=False,updates=False)
        try:
            with urllib.request.urlopen(INTERNET_URL,timeout=4) as response:
                result['internet']=response.status==204 and response.geturl()==INTERNET_URL
        except OSError:pass
        try:
            request=urllib.request.Request(UPDATE_URL,headers={'Range':'bytes=0-255','User-Agent':'FishFinder-network-check'})
            with urllib.request.urlopen(request,timeout=4) as response:
                header=response.read(256)
                columns=next(csv.reader(header.decode('utf-8-sig').splitlines()),[])
                result['updates']=response.status in (200,206) and columns[:2]==['id','ident']
        except (OSError,ValueError,csv.Error):pass
        self.last_result=result
        return result

    def retry_selected(self,stop):
        # Once a user chooses a receiver, retry only that exact saved AP. Never
        # scan and silently substitute another airplane while the display runs.
        while not stop.wait(10):
            if not self.selected or not self.lock.acquire(blocking=False):continue
            try:
                ap,connection_id=self.selected
                active=self.nm('-t','--escape','yes','-f','BSSID,IN-USE','device','wifi','list','ifname',ap.device,'--rescan','no')
                if not any(fields(line)==[ap.bssid,'*'] for line in active.splitlines()):
                    self.nm('--wait','8','connection','up','uuid',connection_id,'ifname',ap.device,'ap',ap.bssid)
            except RuntimeError:pass
            finally:self.lock.release()


SESSION_PATH=PROFILE_PATH.with_name('network-session.json')
_guard_cache=(0,None,False)


def boot_id():
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def authorize(ap,address):
    # This is an association gate, not authentication of the radio. A boot ID
    # stops a previous flight's selection being trusted automatically after boot.
    data=dict(boot=boot_id(),bssid=ap.bssid,device=ap.device,address=address)
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',dir=SESSION_PATH.parent,delete=False) as stream:
            temporary=Path(stream.name);json.dump(data,stream);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,SESSION_PATH)
    finally:
        if temporary and temporary.exists():temporary.unlink()


def receiver_allowed(address):
    # Legacy installations with no enrolled FishFinder networks keep working.
    # After enrollment, collector HTTP and WebSocket access require the current
    # boot's selected BSSID. Home/FBO connections with no receiver fail closed.
    import time
    global _guard_cache
    if not PROFILE_PATH.exists():return True
    now=time.monotonic()
    if _guard_cache[1]==address and now-_guard_cache[0]<2:return _guard_cache[2]
    allowed=False
    try:
        session=json.loads(SESSION_PATH.read_text())
        if session['boot']==boot_id() and session['address']==address:
            result=subprocess.run(['nmcli','-t','--escape','yes','-f','BSSID,IN-USE',
                'device','wifi','list','ifname',session['device'],'--rescan','no'],
                capture_output=True,text=True,timeout=2,env={**os.environ,'LC_ALL':'C'})
            allowed=result.returncode==0 and any(fields(line)==[session['bssid'],'*'] for line in result.stdout.splitlines())
    except (OSError,ValueError,KeyError,subprocess.SubprocessError):pass
    _guard_cache=(now,address,allowed)
    return allowed
