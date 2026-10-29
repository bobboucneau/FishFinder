"""Apply display-only X11 sleep preferences without blocking the touch thread."""
import os
import shutil
import subprocess
import threading


def commands(choice):
    # X manages inactivity and resets it on user input. Never disables both
    # screen-saver blanking and DPMS power-off, not just one of those mechanisms.
    if choice == 'never':return [('s','off'),('-dpms',)]
    seconds=str(int(choice)*60)
    return [('s',seconds),('+dpms',),('dpms','0','0',seconds)]


def apply(choice):
    def work():
        executable=shutil.which('xset')
        if not executable or not os.environ.get('DISPLAY'):
            print('Screen sleep: X11/xset unavailable; preference not applied.',flush=True)
            return
        for arguments in commands(choice):
            try:
                result=subprocess.run([executable,*arguments],capture_output=True,text=True,timeout=2)
                if result.returncode:print('Screen sleep: '+result.stderr.strip(),flush=True)
            except (OSError,subprocess.TimeoutExpired) as exc:print(f'Screen sleep: {exc}',flush=True)
    threading.Thread(target=work,daemon=True,name='screen-sleep').start()
