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

import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import tkinter as tk
from tkinter import ttk
import settings
from airport_data import AirportCatalog
import update_airports

from ff_controls import BG, RoundedButton
FG='#e0f2ef'


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
        tk.Label(self.frame,text='FishFinder Config',bg=BG,fg=FG,font=('DejaVu Sans',16)).pack(pady=5)
        nav=tk.Frame(self.frame,bg=BG);nav.pack()
        self.button(nav,'Display',lambda:self.show_page(0)).pack(side='left',padx=2)
        self.button(nav,'Receiver',lambda:self.show_page(1)).pack(side='left',padx=2)
        self.button(nav,'Demo',lambda:self.show_page(2)).pack(side='left',padx=2)
        self.button(nav,'Support',lambda:self.show_page(3)).pack(side='left',padx=2)
        self.status=tk.StringVar(value='; '.join(getattr(display,'permission_issues',[])) or 'Changes apply when you tap Save.')
        bottom=tk.Frame(self.frame,bg=BG);bottom.pack(side='bottom',pady=5)
        self.button(bottom,'Cancel / Back',self.close).pack(side='left',padx=5)
        self.button(bottom,'Save / Back',self.save).pack(side='left',padx=5)
        tk.Label(self.frame,textvariable=self.status,bg=BG,fg='#ffd45c',wraplength=470,font=('DejaVu Sans',9)).pack(side='bottom',padx=8,pady=4)
        self.page=tk.Frame(self.frame,bg=BG);self.page.pack(fill='both',expand=True,padx=12)
        self.show_page(0);self.frame.after(250,self.poll)

    def show_page(self,index):
        if self.busy:self.status.set('Wait for the current operation before switching pages.');return
        self.hide_keyboard();self.refresh_button=None
        for child in self.page.winfo_children():child.destroy()
        if index==2:self.demo_page();return
        if index==3:self.support_page();return
        fields=([('default_range','Range (NM)'),('label_size','Label size'),('orientation','Map orientation'),('ownship_symbol','Ownship airplane'),
                 ('horizon_minutes','Projection (minutes)'),('idle_seconds','Hide controls (seconds)'),('trail_seconds','Trail (seconds)')]
                if index==0 else [('stratux_ip','Stratux IP'),('own_tail','Your tail number'),
                                  ('ownship_source','Ownship preference'),('vertical_threshold_ft','Altitude limit (feet)'),('screen_sleep','Screen sleep (minutes)'),('pattern_height_agl','Fallback pattern height (ft AGL)')])
        form=tk.Frame(self.page,bg=BG);form.pack()
        choices={'screen_sleep':('never','5','10','20','30','60'),'label_size':('normal','large','extra-large'),'default_range':('2','5','10','20'),'orientation':('track-up','north-up'),
                 'ownship_symbol':('high-wing','low-wing','twin'),'ownship_source':('adsb-first','stratux-first')}
        for row,(key,label) in enumerate(fields):
            tk.Label(form,text=label,bg=BG,fg=FG,font=('DejaVu Sans',10)).grid(row=row,column=0,sticky='w',pady=2)
            if key in choices:widget=ttk.Combobox(form,textvariable=self.vars[key],values=choices[key],state='readonly',width=16)
            else:
                widget=tk.Entry(form,textvariable=self.vars[key],width=16,font=('DejaVu Sans',11))
                widget.bind('<Button-1>',lambda event,w=widget:self.show_keyboard(w))
            widget.grid(row=row,column=1,padx=7,pady=2)
        if index==0:
            for offset,(key,label) in enumerate([('vertical_filter','Gray vertically distant aircraft'),('hide_vertical','Hide vertically distant aircraft'),('airports_visible','Show airports'),('ground_map','Show ground map (experiment)'),('runway_extensions','Runway extensions (all ranges)')]):
                tk.Checkbutton(form,text=label,variable=self.vars[key],bg=BG,fg=FG,selectcolor=BG,
                               activebackground=BG,borderwidth=0,highlightthickness=0,relief='flat',
                               font=('DejaVu Sans',10)).grid(row=len(fields)+offset,column=0,
                               columnspan=2,sticky='w',padx=8,pady=2)
        else:
            controls=tk.Frame(self.page,bg=BG);controls.pack(fill='x',padx=6,pady=5)
            for column in (0,1):controls.grid_columnconfigure(column,weight=1,uniform='actions')
            self.button(controls,'Wi-Fi / Internet',self.network).grid(row=0,column=0,padx=3,pady=3,sticky='ew')
            self.refresh_button=self.button(controls,'Update airports',self.refresh)
            self.refresh_button.grid(row=0,column=1,padx=3,pady=3,sticky='ew')
            self.button(controls,'Code updates',self.code_updates).grid(row=1,column=0,padx=3,pady=3,sticky='ew')
            self.button(controls,'Restore defaults',self.defaults).grid(row=1,column=1,padx=3,pady=3,sticky='ew')

    def demo_page(self):
        self.status.set('Mode buttons apply after confirmation; Save is for other settings.')
        if not hasattr(self,'demo_code'):
            self.demo_code=tk.StringVar(value=os.environ.get('FISHFINDER_DEMO_AIRPORT','O22'))
        active=getattr(self.display.args,'moving_demo',False)
        tk.Label(self.page,text='DEMO MODE' if active else 'LIVE MODE',bg=BG,fg='#ffd45c' if active else FG,font=('DejaVu Sans',19,'bold')).pack(pady=12)
        tk.Label(self.page,text='Demo airport identifier',bg=BG,fg=FG,font=('DejaVu Sans',15)).pack(pady=6)
        airport_button = self.button(self.page,self.demo_code.get(),self.select_demo_airport)
        airport_button.pack(pady=8)
        self.button(self.page,'Start / restart demo',lambda:self.change_mode('demo')).pack(pady=8)
        self.button(self.page,'Return to live traffic',lambda:self.change_mode('live')).pack(pady=8)
        tk.Label(self.page,text='Synthetic traffic only. Switching restarts the display.\nLive records and Wi-Fi are preserved.',bg=BG,fg='#a8cce5',font=('DejaVu Sans',11),wraplength=450).pack(pady=6)

    def select_demo_airport(self):
        from airport_selector import Selector
        if self.busy or self.display.airport_selector is not None:
            return

        def selected(identifier):
            self.demo_code.set(identifier)
            self.show_page(2)

        self.display.airport_selector = Selector(
            self.display, initial_code=self.demo_code.get(), on_select=selected)

    def change_mode(self,mode):
        import os
        from demo_control import airport_spec,request
        if os.environ.get('FISHFINDER_MODE_CONTROL')!='1':
            self.status.set('Restart the updated appliance launcher to enable mode switching.');return
        try:
            code=self.demo_code.get().strip().upper()
            if mode=='demo':
                airport,_=airport_spec(self.display.args.airports,code);code=airport['ident']
        except (ValueError,OSError) as exc:self.status.set(str(exc));return
        # The extra deliberate confirmation helps avoid accidentally substituting
        # simulated traffic for real receiver data during a flight.
        for child in self.page.winfo_children():child.destroy()
        self.hide_keyboard()
        text=('Start synthetic traffic at '+code+'?' if mode=='demo' else 'Stop simulation and return to live traffic?')
        tk.Label(self.page,text=text,bg=BG,fg='#ffd45c',font=('DejaVu Sans',18),wraplength=430).pack(pady=25)
        def confirm():
            try:request(os.environ['FISHFINDER_HOME'],mode,code)
            except (OSError,KeyError) as exc:self.status.set(str(exc));return
            self.status.set('Changing mode… Please wait.')
        self.button(self.page,'Confirm change',confirm).pack(pady=10)
        self.button(self.page,'Cancel',lambda:self.show_page(2)).pack(pady=10)

    def support_page(self):
        from release_manager import Store, atomic, read
        import support_tools

        base = os.environ.get('FISHFINDER_HOME')
        if not base:
            self.status.set('Support requires the FishFinder appliance launcher.')
            return
        home = Path(base)
        support = home / 'support'
        config = support / 'destination.json'
        db = getattr(self.display.args, 'db', None)
        launcher = os.environ.get('FISHFINDER_SUPPORT_CONTROL') == '1'
        previous = Store(home).rollback_target() if launcher else None
        address = tk.StringVar(value=read(config, {}).get('sftp', ''))
        self.status.set('Support exports stay on this device until you approve sending.')
        tk.Label(self.page,text='SFTP destination',bg=BG,fg=FG).pack(pady=(8,2))
        entry = tk.Entry(self.page,textvariable=address,width=38)
        entry.pack()
        entry.bind('<Button-1>',lambda event:self.show_keyboard(entry))

        def save_destination():
            value = address.get().strip()
            support.mkdir(mode=0o700,parents=True,exist_ok=True)
            atomic(config, {'sftp': support_tools.destination(value) if value else ''})
            return value

        def save_address():
            try:
                save_destination()
                self.status.set('Support destination saved.')
            except (OSError, ValueError) as exc:
                self.status.set(str(exc))

        self.button(self.page,'Save destination',save_address).pack(pady=4)
        include = tk.BooleanVar(value=False)
        if (support/'latest-damaged.zip').is_file():
            tk.Checkbutton(self.page,text='Include latest damaged database',variable=include,
                           bg=BG,fg=FG,selectcolor=BG).pack()
        tk.Label(self.page,text='Bundle includes release state and recent logs. Logs and\n'
                                'a damaged database may contain aircraft or location data.',
                 bg=BG,fg=FG).pack(pady=5)

        def export(send=False):
            if self.busy:
                return
            try:
                target = support_tools.destination(address.get()) if send else ''
            except ValueError as exc:
                self.status.set(str(exc))
                return
            include_db = include.get()
            def work():
                path = support_tools.bundle(home, include_db)
                if send:
                    support_tools.upload(path, target)
                return 'Support bundle sent.' if send else 'Support bundle saved locally.'
            if send:
                self.support_confirm('Send the selected support data to '+target+'?',
                                     lambda:self.support_job(work))
            else:
                self.support_job(work)

        actions = tk.Frame(self.page,bg=BG)
        actions.pack(pady=4)
        self.button(actions,'Create bundle',export).pack(side='left',padx=3)
        self.button(actions,'Send bundle',lambda:export(True)).pack(side='left',padx=3)

        def request(filename, payload):
            try:
                atomic(home/'runtime'/filename, payload)
                self.status.set('Request sent. FishFinder will restart.')
            except OSError as exc:
                self.status.set(str(exc))

        if launcher and db and support_tools.recovery_offered(db):
            self.button(self.page,'Fresh Start',lambda:self.support_confirm(
                'Save the damaged database for support and start with an empty database?',
                lambda:request('fresh-start-request.json',{'database':str(db)}))).pack(pady=4)
        if previous:
            self.button(self.page,'Roll back to '+previous,lambda:self.support_confirm(
                'Restart FishFinder on '+previous+'?',
                lambda:request('rollback-request.json',{'target':previous}))).pack(pady=4)
        else:
            tk.Label(self.page,text='No compatible previous release available' if launcher else
                     'Reboot to enable the updated recovery launcher.',bg=BG,fg=FG).pack(pady=4)

    def support_confirm(self, message, action):
        self.hide_keyboard()
        for child in self.page.winfo_children():
            child.destroy()
        tk.Label(self.page,text=message,wraplength=420,bg=BG,fg=FG,
                 font=('DejaVu Sans',16)).pack(pady=22)
        self.button(self.page,'Confirm',action).pack(pady=5)
        self.button(self.page,'Cancel',lambda:self.show_page(3)).pack(pady=5)

    def support_job(self, work):
        if self.busy:
            return
        self.busy = True
        self.status.set('Working on support bundle…')
        def run():
            try:
                message = work()
            except Exception as exc:
                message = str(exc)
            self.jobs.put((False, message))
        threading.Thread(target=run,daemon=True,name='support-bundle').start()

    def button(self,parent,label,command):
        return RoundedButton(parent,label,command,role='confirm' if label=='Save / Back' else 'cancel' if label=='Cancel / Back' else 'nav')

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
            self.status.set('Wait for the current operation before leaving.');return
        self.closed=True;self.frame.destroy();self.display.setup_panel=None
        import time
        self.display.last_touch=time.monotonic();self.display.draw()

    # This workflow delegates Wi-Fi activation to NetworkManager and requires the user's
    # explicit selection. A listed/highlighted network is not the same as an activated
    # connection.
    def network(self):
        import network_screen
        if getattr(self.display,'network_panel',None):return
        self.display.network_panel=network_screen.NetworkScreen(self.display)

    def code_updates(self):
        import update_screen
        update_screen.open_updates(self.display)

    def refresh(self):
        if self.busy:return
        self.busy=True;self.refresh_button.configure(state='disabled')
        self.status.set('Checking internet and downloading airport data…')
        def work():
            try:
                count=update_airports.refresh(self.display.args.airports,progress=lambda message:self.jobs.put((None,message)))
                self.jobs.put((True,f'Installed {count:,} airports. Rejoin Stratux Wi-Fi when ready.'))
            except Exception as exc:self.jobs.put((False,f'Update failed; previous data retained: {exc}'))
        threading.Thread(target=work,daemon=True,name='airport-update').start()

    def poll(self):
        if self.closed:return
        try:
            success,message=self.jobs.get_nowait()
            if success is None:
                self.status.set(message)
                self.frame.after(50,self.poll)
                return
            self.busy=False
            if self.refresh_button:self.refresh_button.configure(state='normal')
            self.status.set(message)
            if success:
                self.display.catalog=AirportCatalog(self.display.args.airports)
                self.display.airport_query=None;self.display.airport_selected=None
        except queue.Empty:pass
        self.frame.after(250,self.poll)
