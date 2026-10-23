"""Touch settings panel. Network/data jobs never block Tk's event loop."""

# READING THIS FILE: the touch-friendly Setup pages and background actions.
#
# The Setup object owns temporary editable copies of settings. Restoring defaults
# changes those copies; Save / Back validates and writes them. Closing without
# saving leaves the existing application settings in place.
#
# Tk variables connect editable controls to Python values. Button callbacks are
# functions called later when the user presses a button, not during layout.
# Network/data operations run on worker threads and report through a queue.
# poll() checks that queue from the window thread so the UI remains responsive.
# Changing Wi-Fi is a user-triggered action; the program does not choose a new
# network merely because the current Stratux connection is unavailable.

import queue
import shutil
import subprocess
import threading
import tkinter as tk
from tkinter import ttk
import settings
from airport_data import AirportCatalog
import update_airports

BG='#071710'; FG='#e0f2ef'


class Setup:
    def __init__(self, display):
        self.display=display; self.jobs=queue.Queue(); self.closed=False; self.busy=False
        self.frame=tk.Frame(display.root,bg=BG,highlightbackground='#50ef97',highlightthickness=2)
        self.frame.place(relx=.5,rely=.5,anchor='center',relwidth=.68,relheight=.68)
        # Each editable field gets a Tk variable. These temporary UI values are distinct from
        # the saved configuration until Save / Back succeeds.
        self.vars={};self.focus=None;self.keyboard=None;self.refresh_button=None
        for key,value in display.config.items():
            self.vars[key]=tk.BooleanVar(value=value) if isinstance(value,bool) else tk.StringVar(value=str(value))
        tk.Label(self.frame,text='FishFinder setup',bg=BG,fg=FG,font=('DejaVu Sans',16)).pack(pady=5)
        nav=tk.Frame(self.frame,bg=BG);nav.pack()
        self.button(nav,'Display',lambda:self.show_page(0)).pack(side='left',padx=4)
        self.button(nav,'Receiver / Updates',lambda:self.show_page(1)).pack(side='left',padx=4)
        self.status=tk.StringVar(value='; '.join(getattr(display,'permission_issues',[])) or 'Changes apply when you tap Save.')
        bottom=tk.Frame(self.frame,bg=BG);bottom.pack(side='bottom',pady=5)
        self.button(bottom,'Cancel / Back',self.close).pack(side='left',padx=5)
        self.button(bottom,'Save / Back',self.save).pack(side='left',padx=5)
        tk.Label(self.frame,textvariable=self.status,bg=BG,fg='#ffd45c',wraplength=470,font=('DejaVu Sans',9)).pack(side='bottom',padx=8,pady=4)
        self.page=tk.Frame(self.frame,bg=BG);self.page.pack(fill='both',expand=True,padx=12)
        self.show_page(0);self.frame.after(250,self.poll)

    def show_page(self,index):
        if self.busy:self.status.set('Wait for the airport update before switching pages.');return
        self.hide_keyboard();self.refresh_button=None
        for child in self.page.winfo_children():child.destroy()
        fields=([('default_range','Range (NM)'),('label_size','Label size'),('orientation','Map orientation'),('ownship_symbol','Ownship airplane'),
                 ('horizon_minutes','Projection (minutes)'),('idle_seconds','Hide controls (seconds)'),('trail_seconds','Trail (seconds)')]
                if index==0 else [('stratux_ip','Stratux IP'),('own_tail','Your tail number'),
                                  ('ownship_source','Ownship preference'),('vertical_threshold_ft','Altitude limit (feet)')])
        form=tk.Frame(self.page,bg=BG);form.pack()
        choices={'label_size':('normal','large','extra-large'),'default_range':('2','5','10','20'),'orientation':('track-up','north-up'),
                 'ownship_symbol':('high-wing','low-wing','twin'),'ownship_source':('adsb-first','stratux-first')}
        for row,(key,label) in enumerate(fields):
            tk.Label(form,text=label,bg=BG,fg=FG,font=('DejaVu Sans',10)).grid(row=row,column=0,sticky='w',pady=2)
            if key in choices:widget=ttk.Combobox(form,textvariable=self.vars[key],values=choices[key],state='readonly',width=16)
            else:
                widget=tk.Entry(form,textvariable=self.vars[key],width=16,font=('DejaVu Sans',11))
                widget.bind('<Button-1>',lambda event,w=widget:self.show_keyboard(w))
            widget.grid(row=row,column=1,padx=7,pady=2)
        if index==0:
            for key,label in [('vertical_filter','Gray vertically distant aircraft'),('hide_vertical','Hide vertically distant aircraft'),('airports_visible','Show airports'),('ground_map','Show ground map (experiment)'),('runway_extensions','Runway extensions (all ranges)')]:
                tk.Checkbutton(self.page,text=label,variable=self.vars[key],bg=BG,fg=FG,selectcolor=BG,
                               activebackground=BG,borderwidth=0,highlightthickness=0,relief='flat').pack(anchor='w',padx=12)
        else:
            controls=tk.Frame(self.page,bg=BG);controls.pack(fill='x',padx=6,pady=5)
            for column in (0,1):controls.grid_columnconfigure(column,weight=1,uniform='actions')
            self.button(controls,'Wi-Fi / Internet',self.network).grid(row=0,column=0,padx=3,pady=3,sticky='ew')
            self.refresh_button=self.button(controls,'Update airports',self.refresh)
            self.refresh_button.grid(row=0,column=1,padx=3,pady=3,sticky='ew')
            self.button(controls,'Code updates',self.code_updates).grid(row=1,column=0,padx=3,pady=3,sticky='ew')
            self.button(controls,'Restore defaults',self.defaults).grid(row=1,column=1,padx=3,pady=3,sticky='ew')

    def button(self,parent,label,command):
        return tk.Button(parent,text=label,command=command,bg='#183b2d',fg=FG,font=('DejaVu Sans',11),padx=8,pady=6)

    def show_keyboard(self, entry):
        self.focus=entry
        if self.keyboard: return
        panel=tk.Frame(self.frame,bg=BG,highlightbackground=FG,highlightthickness=1)
        panel.place(relx=.5,rely=1,anchor='s',relwidth=1);self.keyboard=panel
        for row,chars in enumerate(('1234567890','QWERTYUIOP','ASDFGHJKL','ZXCVBNM.-')):
            strip=tk.Frame(panel,bg=BG);strip.pack()
            for char in chars:
                tk.Button(strip,text=char,command=lambda c=char:self.key(c),width=2,font=('DejaVu Sans',12),pady=4).pack(side='left',padx=1,pady=1)
        strip=tk.Frame(panel,bg=BG);strip.pack()
        self.button(strip,'Backspace',lambda:self.key('backspace')).pack(side='left',padx=6)
        self.button(strip,'Clear',lambda:self.key('clear')).pack(side='left',padx=6)
        self.button(strip,'Done',self.hide_keyboard).pack(side='left',padx=6)

    def key(self,key):
        if not self.focus:return
        if key=='clear':self.focus.delete(0,'end')
        elif key=='backspace':
            index=self.focus.index('insert')
            if index:self.focus.delete(index-1,index)
        else:self.focus.insert('insert',key)
        self.focus.focus_set()

    def hide_keyboard(self):
        if self.keyboard:self.keyboard.destroy();self.keyboard=None

    def defaults(self):
        for key,var in self.vars.items():var.set(settings.DEFAULTS[key])
        self.status.set('Defaults restored in this form. Tap Save to apply.')

    # Save is the boundary between editing and applying. Validation errors stay visible in
    # the panel instead of closing it with a bad configuration.
    def save(self):
        try:self.display.apply_settings({key:var.get() for key,var in self.vars.items()})
        except (ValueError,OSError,TypeError) as exc:self.status.set(str(exc));return
        self.close()

    def close(self):
        if self.busy:
            self.status.set('Airport update is running. Wait for completion before leaving.');return
        self.closed=True;self.frame.destroy();self.display.setup_panel=None
        import time
        self.display.last_touch=time.monotonic();self.display.draw()

    # This workflow delegates Wi-Fi activation to NetworkManager and requires the user's
    # explicit selection. A listed/highlighted network is not the same as an activated
    # connection.
    def network(self):
        command=shutil.which('nmcli')
        if not command:
            self.status.set('NetworkManager nmcli is required to activate a saved Wi-Fi network.');return
        panel=tk.Frame(self.frame,bg=BG,highlightbackground=FG,highlightthickness=1)
        panel.place(relx=.5,rely=.5,anchor='center',relwidth=.96,relheight=.90)
        tk.Label(panel,text='Saved Wi-Fi networks',bg=BG,fg=FG,font=('DejaVu Sans',16)).pack(pady=10)
        message=tk.StringVar(value='Loading saved networks…')
        choices=tk.Listbox(panel,font=('DejaVu Sans',13),height=7,exportselection=False)
        choices.pack(fill='both',expand=True,padx=14,pady=8)
        tk.Label(panel,textvariable=message,bg=BG,fg='#ffd45c',wraplength=430).pack(pady=8)
        results=queue.Queue();profiles=[]
        actions=tk.Frame(panel,bg=BG);actions.pack(pady=8)
        def task(args,kind):
            def work():
                try:
                    result=subprocess.run([command,*args],capture_output=True,text=True,timeout=45)
                    results.put((kind,result.returncode,result.stdout,result.stderr))
                except (OSError,subprocess.TimeoutExpired) as exc:results.put((kind,1,'',str(exc)))
            threading.Thread(target=work,daemon=True,name='wifi-connect').start()
        def load():
            connect.configure(state='disabled');message.set('Loading saved networks…')
            task(['-t','--escape','no','-f','UUID,TYPE,NAME','connection','show'],'list')
        def activate():
            selection=choices.curselection()
            if not selection:message.set('Tap a saved network first.');return
            uuid,name=profiles[selection[0]]
            connect.configure(state='disabled');message.set(f'Connecting to {name}…')
            task(['--wait','30','connection','up','uuid',uuid],'connect')
        def editor():
            app=shutil.which('nm-connection-editor')
            if not app:message.set('Use the desktop Wi-Fi menu to add a new network.');return
            try:subprocess.Popen([app],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            except OSError as exc:message.set(str(exc));return
            message.set('Save the profile in the editor, close it, then tap Refresh and Connect here.')
        connect=self.button(actions,'Connect',activate);connect.pack(side='left',padx=3)
        self.button(actions,'Refresh',load).pack(side='left',padx=3)
        self.button(panel,'Add / edit network',editor).pack(pady=3)
        self.button(panel,'Back',panel.destroy).pack(pady=8)
        def poll_network():
            if self.closed or not panel.winfo_exists():return
            try:
                kind,code,out,err=results.get_nowait()
                if kind=='list':
                    profiles.clear();choices.delete(0,'end')
                    for line in out.splitlines():
                        parts=line.split(':',2)
                        if len(parts)==3 and parts[1] in ('802-11-wireless','wifi'):
                            profiles.append((parts[0],parts[2]));choices.insert('end',parts[2])
                    message.set((err.strip() or 'Cannot list networks.') if code else 'Tap a network, then Connect.' if profiles else 'No saved Wi-Fi profiles. Add a network first.')
                else:
                    message.set(('Connection failed: '+(err.strip() or out.strip())) if code else 'Connected. Tap Back to return to setup.')
                connect.configure(state='normal' if profiles else 'disabled')
            except queue.Empty:pass
            panel.after(250,poll_network)
        load();poll_network()

    def code_updates(self):
        self.status.set('No code release server is configured yet. Recommended: versioned GitHub Releases with verified downloads and rollback. This button will not install unverified code.')

    def refresh(self):
        if self.busy:return
        self.busy=True;self.refresh_button.configure(state='disabled')
        self.status.set('Checking internet and downloading airport data…')
        def work():
            try:
                count=update_airports.refresh(self.display.args.airports)
                self.jobs.put((True,f'Installed {count:,} airports. Rejoin Stratux Wi-Fi when ready.'))
            except Exception as exc:self.jobs.put((False,f'Update failed; previous data retained: {exc}'))
        threading.Thread(target=work,daemon=True,name='airport-update').start()

    def poll(self):
        if self.closed:return
        try:
            success,message=self.jobs.get_nowait()
            self.busy=False
            if self.refresh_button:self.refresh_button.configure(state='normal')
            self.status.set(message)
            if success:
                self.display.catalog=AirportCatalog(self.display.args.airports)
                self.display.airport_query=None;self.display.airport_selected=None
        except queue.Empty:pass
        self.frame.after(250,self.poll)
