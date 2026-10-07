"""Touch settings panel. Network/data jobs never block Tk's event loop."""
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
        self.frame.place(relx=.5,rely=.5,anchor='center',relwidth=.75,relheight=.80)
        self.vars={}; self.focus=None; self.keyboard=None
        tk.Label(self.frame,text='FishFinder setup',bg=BG,fg=FG,font=('DejaVu Sans',17)).pack(pady=8)
        form=tk.Frame(self.frame,bg=BG); form.pack(fill='x',padx=18)
        fields=[('stratux_ip','Stratux IP address'),('own_tail','Your tail number'),
                ('default_range','Default range (NM)'),('vertical_threshold_ft','Gray beyond (ft)'),
                ('idle_seconds','Hide labels after (sec; 0 = never)'),('horizon_minutes','Projection (minutes)'),
                ('trail_seconds','Trail history (seconds)')]
        for row,(key,label) in enumerate(fields):
            tk.Label(form,text=label,bg=BG,fg=FG,font=('DejaVu Sans',10)).grid(row=row,column=0,sticky='w',pady=4)
            var=tk.StringVar(value=str(display.config[key]));self.vars[key]=var
            if key=='default_range':
                widget=ttk.Combobox(form,textvariable=var,values=('2','5','10','20'),state='readonly',width=15)
            else:
                widget=tk.Entry(form,textvariable=var,width=17,font=('DejaVu Sans',12))
                widget.bind('<Button-1>',lambda event,w=widget:self.show_keyboard(w))
            widget.grid(row=row,column=1,padx=8,pady=4)
        for key,label in [('vertical_filter','Use gray vertical-separation symbols'),('airports_visible','Show airports by default')]:
            var=tk.BooleanVar(value=display.config[key]); self.vars[key]=var
            tk.Checkbutton(self.frame,text=label,variable=var,bg=BG,fg=FG,selectcolor=BG,activebackground=BG,activeforeground=FG).pack(anchor='w',padx=18)
        controls=tk.Frame(self.frame,bg=BG);controls.pack(pady=9)
        self.button(controls,'Wi-Fi / Internet',self.network).grid(row=0,column=0,padx=3,pady=3)
        self.refresh_button=self.button(controls,'Update airport data',self.refresh)
        self.refresh_button.grid(row=0,column=1,padx=3,pady=3)
        self.button(controls,'Code updates',self.code_updates).grid(row=1,column=0,padx=3,pady=3)
        self.button(controls,'Restore defaults',self.defaults).grid(row=1,column=1,padx=3,pady=3)
        self.status=tk.StringVar(value='Connect to internet Wi-Fi before updating airports.\nReturn to Stratux Wi-Fi afterwards. Settings apply to both programs.')
        tk.Label(self.frame,textvariable=self.status,bg=BG,fg='#ffd45c',wraplength=480,font=('DejaVu Sans',10)).pack(padx=12,pady=5)
        bottom=tk.Frame(self.frame,bg=BG);bottom.pack(side='bottom',pady=12)
        self.button(bottom,'Cancel / Back',self.close).pack(side='left',padx=8)
        self.button(bottom,'Save / Back',self.save).pack(side='left',padx=8)
        self.frame.after(250,self.poll)

    def button(self,parent,label,command):
        return tk.Button(parent,text=label,command=command,bg='#183b2d',fg=FG,font=('DejaVu Sans',11),padx=10,pady=9)

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

    def network(self):
        command=shutil.which('nm-connection-editor')
        if not command:
            self.status.set('Use the desktop Wi-Fi menu to join and remember your internet network. For this button, install nm-connection-editor on the Pi.');return
        try:subprocess.Popen([command],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        except OSError as exc:self.status.set(f'Cannot open network settings: {exc}')
        else:self.status.set('Network settings opened. Save an internet Wi-Fi profile there; return here to update. Rejoin Stratux Wi-Fi afterwards.')

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
            self.busy=False;self.refresh_button.configure(state='normal');self.status.set(message)
            if success:
                self.display.catalog=AirportCatalog(self.display.args.airports)
                self.display.airport_query=None;self.display.airport_selected=None
        except queue.Empty:pass
        self.frame.after(250,self.poll)
