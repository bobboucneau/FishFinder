#!/usr/bin/env python3
"""One-time Pi installation. Preview first; --install is the only root operation.

This replaces version-specific systemd launch commands with one stable X session.
Applications, updates, signatures and owner builds subsequently run as the normal
user. Existing unit files are backed up and older application folders retained.
"""
import argparse
import json
import os
from pathlib import Path
import platform
import pwd
import shlex
import shutil
import subprocess
import tempfile

SERVICE='fishfinder-appliance.service'


def quote(value):
    if any(c in str(value) for c in '\n\r\x00'):raise ValueError('Invalid systemd argument')
    return '"'+str(value).replace('\\','\\\\').replace('"','\\"').replace('%','%%')+'"'


def files_for(user,home,python,database,demo=False):
    base=home/'.local/share/FishFinder';stable=base/'bootstrap'
    args=[str(python),str(stable/'bootstrap.py'),'--home',str(base),'--python',str(python),
          '--database',str(database),'--geometry','$GEOMETRY','--fullscreen']
    if demo:args.append('--demo')
    command=' '.join('"$GEOMETRY"' if value=='$GEOMETRY' else shlex.quote(value) for value in args)
    session=f'''#!/bin/bash
set -euo pipefail
GEOMETRY=$(xrandr --query | awk '$1=="DSI-1" && $2=="connected" {{for(i=3;i<=NF;i++) if($i ~ /^[0-9]+x[0-9]+[+-][0-9]+[+-][0-9]+$/) {{print $i;exit}}}}')
if [[ -z "$GEOMETRY" ]]; then echo 'DSI-1 unavailable' >&2; exit 1; fi
xrandr --output DSI-1 --primary
xinput map-to-output 'pointer:10-0014 Goodix Capacitive TouchScreen' DSI-1
xset s off || true
xset -dpms || true
exec {command}
'''
    unit=f'''[Unit]
Description=FishFinder stable appliance launcher
After=systemd-user-sessions.service network.target
Conflicts=getty@tty8.service
StartLimitIntervalSec=0

[Service]
Type=simple
User={user}
PAMName=login
TTYPath=/dev/tty8
StandardInput=tty
StandardOutput=journal
StandardError=journal
TTYReset=yes
TTYVHangup=yes
WorkingDirectory={str(base).replace('%','%%')}
# Fixed console selection is infrastructure; all application code runs as User.
ExecStartPre=+/usr/bin/chvt 8
ExecStart={quote('/usr/bin/startx')} {quote(stable/'xsession.bash')} -- :0 vt8 -keeptty
Restart=on-failure
RestartSec=5
TimeoutStopSec=30
KillMode=mixed

[Install]
WantedBy=multi-user.target
'''
    return unit,session


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user',default=os.environ.get('SUDO_USER') or pwd.getpwuid(os.getuid()).pw_name)
    parser.add_argument('--python',required=True,type=Path)
    parser.add_argument('--previous-app',required=True,type=Path)
    parser.add_argument('--archive',required=True,type=Path);parser.add_argument('--manifest',required=True,type=Path)
    parser.add_argument('--signature',type=Path);parser.add_argument('--public-key',type=Path)
    parser.add_argument('--owner-build',action='store_true');parser.add_argument('--demo',action='store_true')
    parser.add_argument('--install',action='store_true')
    args=parser.parse_args();account=pwd.getpwnam(args.user)
    if account.pw_uid==0:parser.error('Choose a normal user')
    home=Path(account.pw_dir);base=home/'.local/share/FishFinder'
    database=Path('/var/local/FishFinder')/('demo_objects.db' if args.demo else 'flying_objects.db')
    unit,session=files_for(args.user,home,args.python.resolve(),database,args.demo)
    if not args.install:
        print(unit);print(session);print('Preview only. One-time --install needs sudo on the Pi.');return
    if platform.system()!='Linux' or os.geteuid()!=0:parser.error('--install requires sudo on the Pi')
    if (base/'state.json').exists():parser.error('Bootstrap is already initialized. Use release_tools.py for ordinary updates; do not reinstall.')
    if subprocess.run(['systemctl','is-active','--quiet','display-manager']).returncode==0:parser.error('An active desktop display manager conflicts with the appliance X session')
    for command in ('systemd-analyze','startx','xrandr','xinput','xset','flock','runuser'):
        if not shutil.which(command):parser.error('Missing operating-system dependency: '+command)
    if not Path('/usr/bin/chvt').exists():parser.error('Missing /usr/bin/chvt')
    check=subprocess.run(['runuser','-u',args.user,'--',str(args.python),'-c',
                          'import tkinter; import cryptography; import websocket'],capture_output=True,text=True)
    if check.returncode:parser.error('The virtual environment needs tkinter, websocket-client and cryptography. See OWNER-BUILDS.md.')
    if subprocess.run(['runuser','-u',args.user,'--','test','-w',str(database.parent)]).returncode:
        parser.error('The normal user needs write access to the existing database directory')
    for path in (args.archive,args.manifest,args.previous_app/'settings.json'):
        if not path.is_file():parser.error('Missing required file: '+str(path))
    stable=base/'bootstrap';shared=base/'shared'
    for folder in (base,stable,shared,base/'runtime',base/'releases',base/'trusted-keys',base/'inbox'):
        folder.mkdir(parents=True,exist_ok=True);os.chown(folder,account.pw_uid,account.pw_gid);folder.chmod(0o750)
    source=Path(__file__).resolve().parent
    for name in ('bootstrap.py','release_manager.py','release_tools.py','build_release.py'):
        shutil.copyfile(source/name,stable/name);os.chown(stable/name,account.pw_uid,account.pw_gid)
    for name in ('settings.json','networks.json','airports.json'):
        old=args.previous_app/name
        if old.is_file() and not (shared/name).exists():
            shutil.copyfile(old,shared/name);os.chown(shared/name,account.pw_uid,account.pw_gid);(shared/name).chmod(0o640)
    wrapper=stable/'xsession.bash';wrapper.write_text(session);os.chown(wrapper,account.pw_uid,account.pw_gid);wrapper.chmod(0o750)
    with tempfile.TemporaryDirectory() as tmp:
        candidate=Path(tmp)/SERVICE;candidate.write_text(unit)
        subprocess.run(['systemd-analyze','verify',str(candidate)],check=True)
    # Run initial verification/extraction AS THE OWNER, not root. Thus even the
    # first release has the same permissions as every later unprivileged update.
    tool=['runuser','-u',args.user,'--',str(args.python),str(stable/'release_tools.py'),'--home',str(base)]
    if args.public_key:subprocess.run(tool+['trust-key',str(args.public_key),'--owner-authorized'],check=True)
    command=tool+['stage',str(args.archive.resolve()),'--manifest',str(args.manifest.resolve())]
    if args.owner_build:command+=['--owner-build']
    elif args.signature:command+=['--signature',str(args.signature.resolve())]
    else:parser.error('Supply a signature/trusted public key, or explicitly select --owner-build')
    subprocess.run(command,check=True)
    subprocess.run(['runuser','-u',args.user,'--',str(args.python),'-c',
                    'import sys;sys.path.insert(0,sys.argv[1]);from release_manager import Store;Store(sys.argv[2]).activate()',str(stable),str(base)],check=True)
    unit_path=Path('/etc/systemd/system')/SERVICE
    unit_path.write_text(unit);unit_path.chmod(0o644)
    old=Path('/etc/systemd/system/fishfinder-collector.service')
    backup=base/'runtime/previous-collector.service'
    if old.exists() and not backup.exists():shutil.copyfile(old,backup);os.chown(backup,account.pw_uid,account.pw_gid)
    # No running service is stopped until verification and the stable unit pass.
    for service in ('fishfinder-demo-display.service','fishfinder-collector.service'):
        if subprocess.run(['systemctl','show',service,'--property=LoadState','--value'],capture_output=True,text=True).stdout.strip()=='loaded':
            subprocess.run(['systemctl','stop',service],check=True)
    subprocess.run(['systemctl','disable','fishfinder-collector.service'],check=False)
    subprocess.run(['systemctl','daemon-reload'],check=True)
    subprocess.run(['systemctl','enable','--now',SERVICE],check=True)
    print('Stable appliance installed. Future app releases use release_tools.py as the normal user, without sudo.')
    print('Logs: '+str(base/'runtime'))


if __name__=='__main__':main()
