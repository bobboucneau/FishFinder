#!/usr/bin/env python3
"""Stable, unprivileged FishFinder launcher, progress screen and update approval.

The operating system starts this stable copy, not a path inside a version folder.
It launches both children with one shared settings/data environment. The release
pointer changes only while children are stopped. Heartbeats prove startup/liveness,
not correct navigation, receiver reception or full functional safety.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import tkinter as tk
from release_manager import Store, read

BG='#030909';FG='#e0f2ef';GREEN='#50ef97';YELLOW='#ffd45c';RED='#ff6262'


class Launcher:
    def __init__(self,args):
        self.args=args;self.store=Store(args.home);self.collector=None;self.display=None
        # Refuse a second supervisor, which would compete for the database/X UI.
        self.lock=(self.store.home/'runtime/launcher.lock').open('a')
        fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        self.root=tk.Tk();self.root.title('FishFinder startup');self.root.geometry(args.geometry)
        if args.fullscreen:self.root.attributes('-fullscreen',True)
        self.root.configure(bg=BG);self.root.protocol('WM_DELETE_WINDOW',self.root.withdraw)
        self.canvas=tk.Canvas(self.root,bg=BG,highlightthickness=0);self.canvas.pack(fill='both',expand=True)
        self.rows=[('Powered on',GREEN),('Checking installation…',YELLOW)]
        self.prompt=None;self.prompted=None;self.started=0;self.ready_since=None;self.failures=0;self.quitting=False
        self.child_logs=[]
        signal.signal(signal.SIGTERM,lambda *_:self.shutdown())
        signal.signal(signal.SIGINT,lambda *_:self.shutdown())
        # A visible short splash precedes the explanatory progress list.
        self.canvas.create_text(400,360,text='FISHFINDER',fill=FG,font=('DejaVu Sans',32))
        self.root.after(1500,self.startup);self.root.after(500,self.poll)

    def progress(self,*rows):
        self.root.deiconify();self.canvas.delete('all')
        self.canvas.create_text(400,230,text='FishFinder startup',fill=FG,font=('DejaVu Sans',23))
        for index,(label,color) in enumerate(rows):
            y=300+index*48
            self.canvas.create_oval(195,y-6,207,y+6,fill=color,outline='')
            self.canvas.create_text(222,y,text=label,fill=FG,anchor='w',font=('DejaVu Sans',12),width=400)

    def startup(self):
        try:
            request=self.store.home/'runtime/rollback-request.json'
            if request.exists():
                self.store.rollback();request.unlink()
            state=self.store.state()
            if state.get('trial'):
                if state.get('previous'):self.store.rollback()
            pending=read(self.store.pending_path,None)
            if pending and pending['policy']=='next-start':self.store.activate()
            elif pending and pending['policy']=='later':self.store.defer('ask')
            self.launch()
        except Exception as exc:self.problem('Startup stopped: '+str(exc))

    def environment(self):
        state=self.store.state();shared=self.store.home/'shared'
        env=dict(os.environ,FISHFINDER_HOME=str(self.store.home),
                 FISHFINDER_SETTINGS=str(shared/'settings.json'),
                 FISHFINDER_HEARTBEAT=str(self.store.home/'runtime/display-heartbeat.json'),
                 FISHFINDER_RELEASE_ID=state['current'],
                 FISHFINDER_OWNER_BUILD='1' if read(self.store.release(state['current'])/'.release.json',{}).get('owner_build') else '0',
                 FISHFINDER_PYTHON=self.args.python,
                 FISHFINDER_DATABASE=self.args.database,
                 FISHFINDER_LOCK_FILE=str(Path(self.args.database).parent/'collector.lock'))
        return env

    def launch(self):
        state=self.store.state()
        if not state.get('current'):raise ValueError('No installed release selected')
        app=self.store.release(state['current']);env=self.environment()
        label='OWNER BUILD' if read(app/'.release.json',{}).get('owner_build') else 'Verified release'
        self.progress(('Powered on',GREEN),(label+' '+state['current'],GREEN),('Starting collector…',YELLOW),('Opening display…',YELLOW))
        heartbeat=self.store.home/'runtime/display-heartbeat.json';heartbeat.unlink(missing_ok=True)
        collector_log=(self.store.home/'runtime/collector.log').open('a',buffering=1)
        display_log=(self.store.home/'runtime/display.log').open('a',buffering=1)
        self.child_logs=[collector_log,display_log]
        launcher=app/('DemoFinder.bash' if self.args.demo else 'Finder.bash')
        self.collector=subprocess.Popen(['/bin/bash',str(launcher)],cwd=app,env=env,
                                         stdout=collector_log,stderr=subprocess.STDOUT,start_new_session=True)
        command=[self.args.python,str(app/'traffic_display.py'),'--db',self.args.database,
                 '--airports',str(self.store.home/'shared/airports.json'),'--geometry',self.args.geometry]
        if self.args.demo:command.append('--demo')
        if self.args.fullscreen:command.append('--fullscreen')
        self.display=subprocess.Popen(command,cwd=app,env=env,stdout=display_log,stderr=subprocess.STDOUT,start_new_session=True)
        self.started=time.monotonic();self.ready_since=None

    def stop_children(self):
        # Process groups include map render workers. Stop gracefully, then bound
        # the wait so an unresponsive child cannot trap the updater indefinitely.
        for child in (self.display,self.collector):
            if child and child.poll() is None:
                try:os.killpg(child.pid,signal.SIGTERM)
                except ProcessLookupError:pass
        deadline=time.monotonic()+12
        for child in (self.display,self.collector):
            if not child:continue
            try:child.wait(timeout=max(.1,deadline-time.monotonic()))
            except subprocess.TimeoutExpired:
                try:os.killpg(child.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                child.wait()
        for stream in self.child_logs:stream.close()
        self.child_logs=[];self.display=self.collector=None

    def install(self):
        if self.prompt:self.prompt.destroy();self.prompt=None
        self.root.attributes('-topmost',False)
        self.progress(('Update approved',GREEN),('Stopping applications…',YELLOW))
        self.root.update_idletasks()
        self.stop_children()
        try:self.store.activate();self.launch()
        except Exception as exc:self.problem('Activation failed: '+str(exc))

    def update_prompt(self,pending):
        if self.prompt:return
        self.root.deiconify();self.root.lift();self.root.attributes('-topmost',True)
        self.prompt=tk.Frame(self.root,bg=BG,highlightbackground=YELLOW,highlightthickness=2)
        self.prompt.place(relx=.5,rely=.5,anchor='center',relwidth=.68,relheight=.55)
        label='Owner-modified build' if pending['owner_build'] else 'Signature-verified release'
        tk.Label(self.prompt,text=label+'\n'+pending['release'],bg=BG,fg=FG,font=('DejaVu Sans',15),wraplength=440).pack(pady=20)
        tk.Label(self.prompt,text='Install only when it is appropriate to interrupt the display.',bg=BG,fg=YELLOW,wraplength=420).pack(pady=8)
        def defer(policy):
            self.store.defer(policy);self.prompt.destroy();self.prompt=None;self.root.attributes('-topmost',False);self.root.withdraw()
        for text,callback in [('Install now',self.install),('Next startup',lambda:defer('next-start')),('Later',lambda:defer('later'))]:
            tk.Button(self.prompt,text=text,command=callback,font=('DejaVu Sans',13),padx=16,pady=8).pack(pady=6)

    def problem(self,message):
        self.progress(('Needs attention',RED),(message,RED),('Logs: FishFinder/runtime/',YELLOW))

    def poll(self):
        if self.quitting:return
        try:
            rollback=self.store.home/'runtime/rollback-request.json'
            if rollback.exists():
                self.stop_children();self.store.rollback();rollback.unlink();self.launch()
            pending=read(self.store.pending_path,None)
            if pending and pending['policy']=='ask' and self.prompted!=pending['release']:
                self.prompted=pending['release'];self.update_prompt(pending)
            if self.display is None and self.collector and self.collector.poll() is not None:
                state=self.store.state();app=self.store.release(state['current'])
                stream=(self.store.home/'runtime/collector.log').open('a',buffering=1);self.child_logs.append(stream)
                self.collector=subprocess.Popen(['/bin/bash',str(app/('DemoFinder.bash' if self.args.demo else 'Finder.bash'))],cwd=app,env=self.environment(),stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
            if self.display and self.collector:
                heartbeat=read(self.store.home/'runtime/display-heartbeat.json',{})
                now=time.monotonic();state=self.store.state()
                fresh=(heartbeat.get('release')==state['current'] and 0<=now-heartbeat.get('monotonic',0)<10)
                failed=self.collector.poll() is not None or (self.display.poll() not in (None,0))
                if self.display.poll()==0:
                    # The normal Exit button closes only the display. Keep the
                    # collector/supervisor alive and allow future update prompts.
                    self.display=None;self.root.withdraw()
                elif failed or (not fresh and now-self.started>60):
                    self.stop_children()
                    if state.get('trial') and state.get('previous'):
                        self.store.rollback();self.problem('New release failed startup; restoring previous version.');self.launch()
                    elif self.failures<2:
                        self.failures+=1;self.launch()
                    else:self.problem('Applications repeatedly failed. Inspect logs before retrying.')
                elif fresh and self.collector.poll() is None:
                    if self.ready_since is None:self.ready_since=now
                    if now-self.ready_since>=15:
                        if state.get('trial'):self.store.accept()
                        if not self.prompt:self.root.withdraw()
        except Exception as exc:self.problem(str(exc))
        self.root.after(500,self.poll)

    def shutdown(self):
        self.quitting=True;self.stop_children();self.root.destroy()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home',type=Path,default=Path.home()/'.local/share/FishFinder')
    parser.add_argument('--python',required=True);parser.add_argument('--database',required=True)
    parser.add_argument('--demo',action='store_true');parser.add_argument('--fullscreen',action='store_true')
    parser.add_argument('--geometry',default='800x800')
    args=parser.parse_args();app=Launcher(args);app.root.mainloop()


if __name__=='__main__':main()
