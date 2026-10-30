"""Touch-first network chooser. All scans/connections/probes run off the Tk thread.

The chooser is used both at live startup and from Setup, including in demo mode.
A friendly name is committed only after a verified Wi-Fi association; Stratux and
Internet results are separate and neither is required to save a home/FBO network.
"""
import queue
import sys
import threading
import tkinter as tk
from tkinter import ttk
import settings
import network_manager as nm

BG='#071710';FG='#e0f2ef';NOTICE='#ffd45c'


class NetworkScreen:
    def __init__(self,display,startup=False):
        self.display=display;self.startup=startup;self.closed=False;self.busy=False
        self.jobs=queue.Queue();self.aps=[];self.selected=None;self.capabilities=None;self.connection_id=None
        self.frame=tk.Frame(display.root,bg=BG,highlightbackground=FG,highlightthickness=1)
        self.frame.place(relx=.5,rely=.5,anchor='center',relwidth=.70,relheight=.70)
        self.message=tk.StringVar(value='Looking for networks…')
        self.body=tk.Frame(self.frame,bg=BG);self.body.pack(fill='both',expand=True,padx=10,pady=8)
        try:
            if not getattr(display,'network_manager',None):
                display.network_manager=nm.Manager()
                threading.Thread(target=display.network_manager.retry_selected,args=(display.stop,),daemon=True,name='network-retry').start()
            self.manager=display.network_manager
        except (OSError,ValueError) as exc:
            self.label('Saved network settings need attention.')
            self.label(str(exc));self.button('Back / Skip',self.close);return
        self.list_page();self.scan(automatic=startup)

    def label(self,text):
        tk.Label(self.body,text=text,bg=BG,fg=FG,font=('DejaVu Sans',11),wraplength=450).pack(pady=3)

    def button(self,text,callback,parent=None):
        widget=tk.Button(parent or self.body,text=text,command=callback,bg='#183b2d',fg='#10251f' if sys.platform=='darwin' else FG,
                         font=('DejaVu Sans',11),padx=8,pady=6)
        widget.pack(side='left' if parent else 'top',padx=3,pady=3)
        return widget

    def clear(self):
        for child in self.body.winfo_children():child.destroy()

    def status(self):
        tk.Label(self.body,textvariable=self.message,bg=BG,fg=NOTICE,wraplength=440,font=('DejaVu Sans',10)).pack(pady=5)

    def job(self,callback,done):
        if self.busy:return
        self.busy=True
        def work():
            try:self.jobs.put((done,callback(),None))
            except Exception as exc:self.jobs.put((done,None,str(exc)))
        threading.Thread(target=work,daemon=True,name='network-operation').start()
        self.frame.after(100,self.poll)

    def poll(self):
        if self.closed:return
        try:
            done,value,error=self.jobs.get_nowait();self.busy=False
            if error:self.message.set(error+' Use Wait / Retry or Other networks.');return
            done(value)
        except queue.Empty:self.frame.after(100,self.poll)

    def list_page(self):
        if self.busy:return
        self.clear();self.label('Choose a network')
        holder=tk.Frame(self.body,bg=BG);holder.pack(fill='x',pady=5)
        self.list=tk.Listbox(holder,font=('DejaVu Sans',11),height=5,exportselection=False)
        self.list.pack(side='left',fill='both',expand=True)
        vertical=tk.Scrollbar(holder,command=self.list.yview);vertical.pack(side='right',fill='y')
        self.list.configure(yscrollcommand=vertical.set)
        # A scrollbar is useful when an FBO advertises many nearby access points.
        scroll=tk.Scrollbar(self.body,orient='horizontal',command=self.list.xview)
        scroll.pack(fill='x');self.list.configure(xscrollcommand=scroll.set)
        self.status()
        bar=tk.Frame(self.body,bg=BG);bar.pack()
        self.button('Connect',self.choose,bar)
        self.button('Wait / Retry',lambda:self.scan(automatic=self.startup),bar)
        self.button('Other networks',lambda:self.scan(automatic=False))
        self.button('Skip' if self.startup else 'Back',self.close)

    def scan(self,automatic=False):
        if self.busy:return
        self.message.set('Scanning… Wi-Fi changes only after your selection or a saved preferred match.')
        def complete(aps):
            self.aps=aps;self.list.delete(0,'end')
            for ap in aps:
                saved=self.manager.profiles.match(ap.bssid)
                title=saved['name'] if saved else ap.ssid
                self.list.insert('end',f'{title} · {ap.signal}% · {ap.bssid[-8:]}'+(' ✓' if ap.active else ''))
            kind,ap=nm.selection(self.manager.profiles,aps)
            preferred=self.manager.profiles.data.get('preferred')
            if automatic and kind=='preferred':
                self.selected=ap;self.message.set('Connecting to preferred receiver…');self.connect();return
            if kind=='alternative':
                self.list.selection_set(aps.index(ap))
                self.message.set('Preferred receiver unavailable. Connect to the listed alternative, wait, or choose another network.')
            else:self.message.set('Select a network; full SSID/BSSID appears before connecting.' if aps else 'No networks found. Wait / Retry, or Skip.')
            if automatic and preferred and kind!='preferred':
                self.message.set('Preferred Stratux unavailable. Wait / Retry, or select another network.')
        self.job(self.manager.scan,complete)

    def choose(self):
        if self.busy:return
        selected=self.list.curselection()
        if not selected:self.message.set('Select a network first.');return
        self.selected=self.aps[selected[0]];ap=self.selected;saved=self.manager.profiles.match(ap.bssid)
        self.clear();self.label(saved['name'] if saved else ap.ssid)
        self.label(f'SSID: {ap.ssid}\nBSSID: {ap.bssid}\nSecurity: {ap.security or "Open"}')
        self.password=tk.StringVar()
        if ap.security not in ('','--') and not saved and not ap.active:
            self.label('Wi-Fi password')
            entry=tk.Entry(self.body,textvariable=self.password,show='*',width=28,font=('DejaVu Sans',12));entry.pack()
            entry.bind('<Button-1>',lambda event:self.keyboard(entry))
            if '802.1X' in ap.security or 'WEP' in ap.security:
                self.message.set('Enterprise/WEP networks need an administrator-created NetworkManager profile.');self.status()
                self.button('Back',self.list_page);return
        self.status();self.button('Connect / Retry',self.connect);self.button('Other networks',self.list_page)

    def connect(self):
        if self.busy:return
        password=self.password.get() if hasattr(self,'password') else ''
        # Remove password from the visible Tk variable immediately after capture.
        if hasattr(self,'password'):self.password.set('')
        self.message.set('Connecting, checking BSSID, probing Stratux and Internet…')
        self.job(lambda:self.manager.connect(self.selected,password),self.connected)

    def connected(self,result):
        self.connection_id,self.capabilities=result
        self.name_page()

    def name_page(self):
        self.clear();ap=self.selected;saved=self.manager.profiles.match(ap.bssid)
        self.label('Connected · '+ap.ssid)
        c=self.capabilities
        self.label(('Stratux: '+c['stratux_ip'] if c['stratux_ip'] else 'Stratux: not found')+
                   '\nInternet: '+('reachable' if c['internet'] else 'not confirmed / login may be required')+
                   '\nAirport updates: '+('reachable' if c['updates'] else 'not confirmed'))
        self.label('Friendly name')
        self.name=tk.StringVar(value=saved['name'] if saved else ap.ssid)
        entry=tk.Entry(self.body,textvariable=self.name,width=28,font=('DejaVu Sans',12));entry.pack()
        entry.bind('<Button-1>',lambda event:self.keyboard(entry))
        self.preferred=tk.BooleanVar(value=self.manager.profiles.data.get('preferred')==ap.bssid)
        if c['stratux_ip']:
            tk.Checkbutton(self.body,text='Make preferred Stratux',variable=self.preferred,bg=BG,fg=FG,selectcolor=BG).pack()
        self.message.set('Name this connection. Passwords stay in NetworkManager.');self.status()
        bar=tk.Frame(self.body,bg=BG);bar.pack()
        self.button('Save / Done',self.save,bar);self.button('Receiver IP',self.address_page,bar)
        self.button('Wait / Recheck',self.recheck)
        self.button('Other networks',lambda:(self.list_page(),self.scan()))

    def recheck(self):
        if self.busy:return
        self.message.set('Checking receiver and Internet again…')
        def complete(result):
            self.capabilities=result
            nm.authorize(self.selected,result['stratux_ip'])
            self.name_page()
        self.job(lambda:self.manager.probe(self.selected.device,self.capabilities.get('stratux_ip')),complete)

    def address_page(self):
        if self.busy:return
        self.clear();self.label('Stratux address override')
        self.address=tk.StringVar(value=self.capabilities.get('stratux_ip') or settings.load()['stratux_ip'])
        entry=tk.Entry(self.body,textvariable=self.address,font=('DejaVu Sans',12));entry.pack(pady=8)
        entry.bind('<Button-1>',lambda event:self.keyboard(entry))
        self.message.set('Try configured IP and this network’s gateway; this field handles custom receiver addresses.')
        self.status()
        def probe():
            import ipaddress
            try:value=str(ipaddress.IPv4Address(self.address.get().strip()))
            except ValueError:self.message.set('Enter a valid IPv4 address.');return
            self.message.set('Checking receiver and Internet…')
            def complete(result):
                self.capabilities=result
                nm.authorize(self.selected,result['stratux_ip'])
                self.name_page()
            self.job(lambda:self.manager.probe(self.selected.device,value),complete)
        self.button('Test address',probe);self.button('Back',self.name_page)

    def save(self,replace=False):
        if self.busy:return
        try:
            name=nm.friendly_name(self.name.get())
            duplicate=self.manager.profiles.duplicate(name,self.selected.bssid)
            if duplicate and not replace:
                # This is the sole destructive-association boundary. Keep old data
                # until the user explicitly chooses Replace existing.
                self.message.set('That friendly name is already in use. Replace its saved device, choose another name, or cancel.')
                if hasattr(self,'conflict') and self.conflict.winfo_exists():return
                self.conflict=tk.Frame(self.body,bg=BG);self.conflict.pack()
                self.button('Replace existing',lambda:self.save(True),self.conflict)
                self.button('Change name',self.conflict.destroy,self.conflict)
                self.button('Cancel',self.close)
                return
            # Persist the receiver address through the same validated settings file
            # already watched by the collector. Do not alter actual position data.
            if self.capabilities['stratux_ip']:
                values=settings.load();values['stratux_ip']=self.capabilities['stratux_ip']
                self.display.apply_settings(values)
            self.display.network_status=name+' · Stratux '+('available' if self.capabilities['stratux_ip'] else 'unavailable')+' · Internet '+('reachable' if self.capabilities['internet'] else 'not confirmed')
            self.manager.profiles.save(self.selected,self.connection_id,name,self.capabilities,
                                       self.preferred.get(),replace)
        except (ValueError,OSError) as exc:self.message.set(str(exc));return
        self.close()

    def keyboard(self,entry):
        # Local keyboard supports lowercase, digits, spaces and punctuation. The
        # password is masked by its Entry and never copied to another widget.
        if self.busy:return
        panel=tk.Frame(self.frame,bg=BG,highlightbackground=FG,highlightthickness=1)
        panel.place(relx=.5,rely=1,anchor='s',relwidth=1)
        letters=['1234567890','qwertyuiop','asdfghjkl','zxcvbnm.-']
        symbols=['!@#$%^&*()','_+=[]{}<>','\\|;:\"\',?/','`~']
        upper=False;symbol=False
        rows=tk.Frame(panel,bg=BG);rows.pack()
        def insert(text):entry.insert('insert',text)
        def rebuild():
            for child in rows.winfo_children():child.destroy()
            for chars in (symbols if symbol else letters):
                bar=tk.Frame(rows,bg=BG);bar.pack()
                for char in chars:
                    char=char.upper() if upper else char
                    tk.Button(bar,text=char,command=lambda c=char:insert(c),width=2,font=('DejaVu Sans',11),pady=4).pack(side='left',padx=1,pady=1)
        def shift():
            nonlocal upper
            upper=not upper;rebuild()
        def sym():
            nonlocal symbol
            symbol=not symbol;rebuild()
        bar=tk.Frame(panel,bg=BG);bar.pack()
        self.button('Shift',shift,bar);self.button('Symbols',sym,bar);self.button('Space',lambda:insert(' '),bar)
        bar=tk.Frame(panel,bg=BG);bar.pack()
        self.button('⌫',lambda:entry.delete(max(0,entry.index('insert')-1)),bar)
        self.button('Clear',lambda:entry.delete(0,'end'),bar);self.button('Done',panel.destroy,bar)
        rebuild()

    def close(self):
        if self.busy:self.message.set('Connection check is running; wait for it to finish.');return
        self.closed=True;self.frame.destroy();self.display.network_panel=None
        # No startup popup repeats after Skip. A user can reopen it in Setup.
        self.display.last_touch=__import__('time').monotonic()
        if self.display.setup_panel and getattr(self.display,'network_status',None):
            self.display.setup_panel.status.set(self.display.network_status)
