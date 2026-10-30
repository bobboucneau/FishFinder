"""Local update inbox for managed installations; staging never activates code."""
from pathlib import Path
import os
import queue
import threading
import tkinter as tk
from release_manager import Store


def open_updates(display):
    home=os.environ.get('FISHFINDER_HOME')
    if not home:
        display.setup_panel.status.set('Install the stable bootstrap once first; see OWNER-BUILDS.md. No release server is configured yet.')
        return
    store=Store(home);panel=tk.Frame(display.root,bg='#071710',highlightbackground='#ffd45c',highlightthickness=2)
    panel.place(relx=.5,rely=.5,anchor='center',relwidth=.68,relheight=.68)
    tk.Label(panel,text='Local update inbox',font=('DejaVu Sans',16),bg='#071710',fg='#e0f2ef').pack(pady=12)
    tk.Label(panel,text='Copy ZIP, matching manifest and signature to:\n'+str(store.home/'inbox'),wraplength=460,bg='#071710',fg='#e0f2ef').pack(pady=4)
    files=sorted((store.home/'inbox').glob('*.zip'));choices=tk.Listbox(panel,height=5,font=('DejaVu Sans',11),exportselection=False);choices.pack(fill='x',padx=15,pady=8)
    for path in files:choices.insert('end',path.name)
    owner=tk.BooleanVar(value=False)
    tk.Checkbutton(panel,text='Owner-modified build (not signature verified)',variable=owner,bg='#071710',fg='#e0f2ef',selectcolor='#071710').pack(pady=5)
    message=tk.StringVar(value='No automatic downloads. Signature verification is the default.')
    tk.Label(panel,textvariable=message,wraplength=450,bg='#071710',fg='#ffd45c').pack(pady=8)
    jobs=queue.Queue();busy=False
    def stage():
        nonlocal busy
        if busy:return
        selected=choices.curselection()
        if not selected:message.set('Choose an update package first.');return
        archive=files[selected[0]];manifest=archive.with_suffix('.manifest.json');signature=archive.with_suffix('.sig')
        own=owner.get();busy=True;button.configure(state='disabled');message.set('Checking and staging…')
        def work():
            try:
                store.stage(archive,manifest,signature if signature.exists() else None,own)
                jobs.put('Staged. The launcher will ask when to install.')
            except Exception as exc:jobs.put(str(exc))
        threading.Thread(target=work,daemon=True,name='update-stage').start();panel.after(100,poll)
    def poll():
        nonlocal busy
        if not panel.winfo_exists():return
        try:message.set(jobs.get_nowait());busy=False;button.configure(state='normal')
        except queue.Empty:panel.after(100,poll)
    button=tk.Button(panel,text='Verify and stage',command=stage,font=('DejaVu Sans',12),pady=8);button.pack(pady=5)
    def close():
        if busy:message.set('Wait for verification to finish.');return
        panel.destroy()
    tk.Button(panel,text='Back',command=close,font=('DejaVu Sans',12),pady=8).pack(pady=5)
