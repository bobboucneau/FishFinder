#!/usr/bin/env python3
"""Preview or install non-root FishFinder service and optional console X startup."""

# READING THIS FILE: generate Raspberry Pi startup configuration.
#
# Preview is the default; --install is the explicit request to write system
# configuration. The collector runs under the selected ordinary user, even
# though installing its service requires administrator privileges. This file
# also generates optional console/X startup text; those quoted strings are
# scripts or service files to be used later, not Python executed here.
#
# There are THREE quoting rules: Python strings, shell arguments, and systemd
# configuration. They are not interchangeable. Keep WorkingDirectory literal;
# its surrounding quote characters would become part of the directory name.
# Validate a candidate service before replacing a working installation.

import argparse
import os
from pathlib import Path
import platform
import pwd
import shlex
import shutil
import subprocess
import tempfile

SERVICE='fishfinder-collector.service'
MARKER='# FishFinder console startup'


# Use an explicit interpreter override first; otherwise search the known virtual-environment
# locations.
def find_python(app,override=None):
    if override is not None:return Path(os.path.abspath(override))
    candidates=[app/'.venv/bin/python3',app.parent/'.venv/bin/python3',
                Path('/usr/local/FishFinder/.venv/bin/python3'),Path('/usr/local/Fishfinder/.venv/bin/python3')]
    return next((p for p in candidates if p.is_file() and os.access(p,os.X_OK)),candidates[0])


# Return proposed service/startup files as text. Generating this dictionary does not install
# anything.
def files_for(user, home, app, database, demo=False, boot_ui=False, python=None):
    python=python or app/'.venv/bin/python3'
    launcher=app/('DemoFinder.bash' if demo else 'Finder.bash')
    command=['/bin/bash',str(launcher)]
    # WorkingDirectory is a single literal path, unlike ExecStart/Environment
    # words: surrounding quotes become part of the path and invalidate it.
    if any(c in str(app) for c in '\n\r\x00'):raise ValueError('Invalid application path')
    directory=str(app).replace('%','%%')
    # ExecStart and Environment use systemd word quoting.
    # Quote a single systemd argument correctly, including literal percent signs.
    def systemd(value):return '"'+str(value).replace('\\','\\\\').replace('"','\\"').replace('%','%%')+'"'
    unit=f'''[Unit]
Description=FishFinder traffic collector ({'demo' if demo else 'production'})
After=network.target
StartLimitIntervalSec=0

[Service]
Type=simple
User={user}
WorkingDirectory={directory}
Environment={systemd('FISHFINDER_SETTINGS='+str(app/'settings.json'))}
Environment={systemd('FISHFINDER_PYTHON='+str(python))}
Environment={systemd('FISHFINDER_DATABASE='+str(database))}
Environment={systemd('FISHFINDER_LOCK_FILE='+str(database.parent/'collector.lock'))}
ExecStart={' '.join(systemd(x) for x in command)}
Restart=always
RestartSec=5
RestartPreventExitStatus=75
KillSignal=SIGINT
TimeoutStopSec=20
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
'''
    result={Path('/etc/systemd/system')/SERVICE:unit}
    # Collector service setup and screen startup are separate choices. This early return
    # leaves the desktop/session configuration alone when only the collector was requested.
    if not boot_ui:return result
    session=home/'.local/bin/fishfinder-xsession'
    result[session]=f'''#!/bin/sh
# Called by startx on the logged-in console user's seat.
export FISHFINDER_SETTINGS={shlex.quote(str(app/'settings.json'))}
xset s off 2>/dev/null || true
xset -dpms 2>/dev/null || true
xset s noblank 2>/dev/null || true
# A window manager makes fullscreen positioning reliable when HDMI is attached.
wm_pid=
if command -v openbox >/dev/null 2>&1; then openbox & wm_pid=$!; fi
cleanup() {{ if [ -n "$wm_pid" ]; then kill "$wm_pid" 2>/dev/null || true; fi; }}
trap cleanup EXIT
geometry=800x800
if command -v xrandr >/dev/null 2>&1; then
    dsi_geometry=$(xrandr --query | awk '$1=="DSI-1" && $2=="connected" {{for(i=3;i<=NF;i++) if($i ~ /^[0-9]+x[0-9]+[+-][0-9]+[+-][0-9]+$/) {{print $i;exit}}}}')
    if [ -n "$dsi_geometry" ]; then
        geometry=$dsi_geometry
        xrandr --output DSI-1 --primary 2>/dev/null || true
        if command -v xinput >/dev/null 2>&1; then
            xinput map-to-output 'pointer:10-0014 Goodix Capacitive TouchScreen' DSI-1 || echo 'Touch mapping failed; check xinput device name.' >&2
        fi
    fi
fi
{shlex.quote(str(python))} {shlex.quote(str(app/'traffic_display.py'))} --db {shlex.quote(str(database))} --fullscreen --geometry "$geometry"
'''
    result[Path('/etc/systemd/system/getty@tty1.service.d/fishfinder.conf')]=f'''[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin {user} --noclear %I $TERM
'''
    # Source via the user's existing login file; avoid taking over .xinitrc.
    result[home/'.config/fishfinder/console-start.sh']=f'''{MARKER}
if [ -z "${{DISPLAY:-}}" ] && [ -z "${{SSH_CONNECTION:-}}" ] && [ "$(tty)" = /dev/tty1 ] && [ ! -e "$HOME/.fishfinder-no-autostart" ]; then
    mkdir -p "$HOME/.local/state/fishfinder"
    startx {shlex.quote(str(session))} -- :0 vt1 >> "$HOME/.local/state/fishfinder/display.log" 2>&1
fi
'''
    return result


def verify_unit(content,validator):
    """Verify a candidate with the Pi's actual systemd parser before replacing it."""
    with tempfile.TemporaryDirectory(prefix='fishfinder-unit-') as tmp:
        candidate=Path(tmp)/SERVICE
        candidate.write_text(content)
        result=subprocess.run([validator,'verify',str(candidate)],capture_output=True,text=True)
        if result.returncode:
            raise ValueError('systemd rejected the candidate unit:\n'+(result.stderr.strip() or result.stdout.strip()))


# Show a preview unless --install was requested; validate candidates, preserve existing user
# files where needed, then install/start services.
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install',action='store_true',help='Apply changes; without this flag only preview files')
    parser.add_argument('--boot-ui',action='store_true',help='Also enable tty1 autologin and startx at console login')
    parser.add_argument('--demo',action='store_true',help='Install collector/display in simulation mode for bench testing')
    parser.add_argument('--user',default=os.environ.get('SUDO_USER') or pwd.getpwuid(os.getuid()).pw_name)
    parser.add_argument('--python',type=Path,help='Virtual-environment interpreter; otherwise detect inside/beside app directory')
    parser.add_argument('--app-dir',type=Path,default=Path('/usr/local/Fishfinder'))
    args=parser.parse_args();account=pwd.getpwnam(args.user)
    if account.pw_uid==0:parser.error('Choose the normal Pi user with --user; applications must not run as root')
    if account.pw_shell.endswith(('nologin','false')):parser.error('Choose an interactive login user')
    home=Path(account.pw_dir);app=args.app_dir.resolve()
    database=Path('/var/local/FishFinder')/('demo_objects.db' if args.demo else 'flying_objects.db')
    python=find_python(app,args.python)
    files=files_for(args.user,home,app,database,args.demo,args.boot_ui,python)
    login=next((home/n for n in ('.bash_profile','.bash_login','.profile') if (home/n).exists()),home/'.profile')
    source='\n'+MARKER+'\n. "$HOME/.config/fishfinder/console-start.sh"\n'
    if args.boot_ui:
        content=login.read_text() if login.exists() else ''
        if MARKER not in content:files[login]=content+source
    if not args.install:
        for path,content in files.items():print(f'\n--- {path} ---\n{content}')
        print('Preview only. Add --install to apply.');return
    if platform.system()!='Linux' or os.geteuid()!=0:parser.error('Installation requires sudo on the Pi running Linux')
    for path in (app/'FishFinder.py',app/'traffic_display.py',app/'fs_checks.py',app/('DemoFinder.bash' if args.demo else 'Finder.bash'),python):
        if not path.exists():parser.error(f'Missing installed file: {path}')
    if not os.access(python,os.X_OK):parser.error(f'Interpreter is not executable: {python}')
    if not shutil.which('flock'):parser.error('Install util-linux (flock) before enabling the collector')
    if args.boot_ui:
        if not shutil.which('startx'):parser.error('Install xinit/Xorg before enabling boot UI')
        if not account.pw_shell.endswith('/bash'):parser.error('Console autostart currently requires a bash login shell')
        if subprocess.run(['systemctl','is-active','--quiet','display-manager']).returncode==0:
            parser.error('Select console boot and reboot first; an active desktop display manager conflicts with startx')
        if Path('/etc/systemd/system/getty@tty1.service.d/override.conf').exists():
            parser.error('Existing tty1 override.conf: review it before adding FishFinder autologin')
    new_directory=not database.parent.exists()
    database.parent.mkdir(parents=True,exist_ok=True)
    if new_directory:
        os.chown(database.parent,account.pw_uid,account.pw_gid)
        database.parent.chmod(0o750)
    # Assign only a newly created data directory; existing data ownership is respected.
    check=subprocess.run(['runuser','-u',args.user,'--','test','-w',str(database.parent)])
    if check.returncode:
        parser.error(f'{args.user} needs write access to {database.parent}; fix ownership before installing')
    probe_code="import sys;sys.path.insert(0,sys.argv[1]);from fs_checks import database_problem,write_problem;issue=database_problem(sys.argv[2]) or write_problem(sys.argv[3]);print(issue) if issue else None;sys.exit(1 if issue else 0)"
    probe=subprocess.run(['runuser','-u',args.user,'--',str(python),'-c',probe_code,str(app),str(database),str(database.parent/'collector.lock')],capture_output=True,text=True)
    if probe.returncode:parser.error(probe.stdout.strip() or probe.stderr.strip() or 'Data/lock permission check failed')
    validator=shutil.which('systemd-analyze')
    if not validator:parser.error('systemd-analyze is required to validate the unit before installation')
    try:verify_unit(files[Path('/etc/systemd/system')/SERVICE],validator)
    except ValueError as exc:parser.error(str(exc))
    for path,content in files.items():
        missing=[];parent=path.parent
        while not parent.exists():missing.append(parent);parent=parent.parent
        path.parent.mkdir(parents=True,exist_ok=True)
        backup=path.with_name(path.name+'.fishfinder-backup')
        if path.exists() and not backup.exists():shutil.copy2(path,backup)
        path.write_text(content)
        if path.is_relative_to(home):
            os.chown(path,account.pw_uid,account.pw_gid)
            # Ensure directories created as root remain usable by the normal user.
            for parent in missing:os.chown(parent,account.pw_uid,account.pw_gid)
        path.chmod(0o755 if path.name=='fishfinder-xsession' else 0o644)
    try:
        subprocess.run(['systemctl','daemon-reload'],check=True)
        subprocess.run(['systemctl','enable','--now',SERVICE],check=True)
        subprocess.run(['systemctl','restart',SERVICE],check=True)
    except subprocess.CalledProcessError:
        parser.exit(1,'Service setup/start failed. Inspect: systemctl status fishfinder-collector --no-pager\nThen: journalctl -u fishfinder-collector -n 40 --no-pager\n')
    print('Collector installed. Read logs: journalctl -u fishfinder-collector -f')
    if args.boot_ui:print('Console autologin/startx installed for next boot. Exit returns to the console; no restart loop.')


if __name__=='__main__':main()
