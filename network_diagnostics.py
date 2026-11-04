"""Read-only connection information and a bounded, user-requested ping.

These checks neither change networks nor enroll devices. Host text is validated
before passing it as a separate process argument; no shell ever interprets it.
A failed ICMP test is not proof that a host or its Stratux service is offline.
"""
import ipaddress
import re
import subprocess


def target(value):
    value=value.strip()
    if not value or len(value)>253:
        raise ValueError('Enter an IP address or host name.')
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        labels=value.rstrip('.').split('.')
        if all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?',label) for label in labels):
            return value
    raise ValueError('Use an IP address or host name, without a port or URL.')


def ping(value,runner=subprocess.run):
    host=target(value)
    try:
        result=runner(['ping','-n','-c','2','-W','2','--',host],
                      capture_output=True,text=True,timeout=7)
    except subprocess.TimeoutExpired:
        return f'{host}: no ping reply before timeout. ICMP may be blocked.'
    except OSError:
        return 'Ping is unavailable on this system.'
    times=re.findall(r'time[=<]([0-9.]+)\s*ms',result.stdout)
    if result.returncode==0:
        return f'{host}: responded'+(f' · {float(times[-1]):g} ms' if times else '')
    return f'{host}: no ping reply or name lookup failed. This does not prove it is offline.'


def connection(manager):
    # nmcli escapes colons in terse output. Reuse the parser that already
    # protects SSIDs and BSSIDs rather than splitting IPv6 or names incorrectly.
    from network_manager import fields
    with manager.lock:
        rows=[fields(line) for line in manager.nm('-t','--escape','yes','-f',
              'DEVICE,TYPE,STATE','device','status').splitlines()]
        devices=[r[0] for r in rows if len(r)==3 and r[1]=='wifi' and r[2].startswith('connected')]
        if not devices:return {'connected':False}
        device=devices[0]
        info={}
        for line in manager.nm('-t','--escape','yes','-f',
                'GENERAL.CONNECTION,IP4.ADDRESS,IP4.GATEWAY,IP6.ADDRESS',
                'device','show',device).splitlines():
            row=fields(line)
            if len(row)>=2:info[row[0]]=row[1]
        addresses4=[v for k,v in info.items() if k.startswith('IP4.ADDRESS')]
        addresses6=[v for k,v in info.items() if k.startswith('IP6.ADDRESS') and not v.lower().startswith('fe80:')]
        gateway=next((v for k,v in info.items() if k.startswith('IP4.GATEWAY') and v),'')
        name=info.get('GENERAL.CONNECTION','Wi-Fi')
        # Recover the friendly FishFinder name only for the actually active AP.
        active=manager.nm('-t','--escape','yes','-f','BSSID,IN-USE',
                          'device','wifi','list','ifname',device,'--rescan','no')
        for line in active.splitlines():
            row=fields(line)
            if len(row)==2 and row[1]=='*':
                saved=manager.profiles.match(row[0])
                if saved:name=saved['name']
                break
        return dict(connected=True,name=name,device=device,ipv4=addresses4,ipv6=addresses6,gateway=gateway)
