"""Large touch targets for airport entry; independent of actual aircraft position."""
import tkinter as tk
import time
from airport_selection import lookup,distance_bearing

BG='#07131f';FG='#e0f2ef'


class Selector:
    def __init__(self,display):
        self.display=display;self.frame=tk.Frame(display.root,bg=BG,highlightbackground='#62b6ff',highlightthickness=2)
        self.frame.place(relx=.5,rely=.5,anchor='center',relwidth=.70,relheight=.70)
        self.body=tk.Frame(self.frame,bg=BG);self.body.pack(fill='both',expand=True,padx=12,pady=8)
        self.code=tk.StringVar(value=display.config.get('manual_airport',''))
        saved=display.catalog.airports.get(self.code.get())
        if saved:self.code.set(saved['code'])
        self.message=tk.StringVar(value='Enter an airport ID, for example O22 or KGOO.')
        self.page=0;self.near=[];self.entry_page()

    def clear(self):
        for child in self.body.winfo_children():child.destroy()

    def button(self,parent,label,callback,**grid):
        # Minimum row/column sizes provide generous targets even for short keys.
        widget=tk.Button(parent,text=label,command=callback,font=('DejaVu Sans',15),pady=7)
        widget.grid(padx=3,pady=3,sticky='nsew',**grid)
        return widget

    def entry_page(self):
        self.clear()
        tk.Label(self.body,text='Select airport',bg=BG,fg=FG,font=('DejaVu Sans',17)).pack(pady=3)
        entry=tk.Entry(self.body,textvariable=self.code,font=('DejaVu Sans',24),justify='center',width=12)
        entry.pack(pady=4)
        # Physical keyboards work too; reject punctuation/overlength input while
        # keeping the Go error visible instead of losing what the user entered.
        entry.configure(validate='key',validatecommand=(entry.register(lambda text:len(text)<=7 and (not text or text.isascii() and text.isalnum())),'%P'))
        keyboard=tk.Frame(self.body,bg=BG);keyboard.pack()
        for row in range(6):keyboard.grid_rowconfigure(row,minsize=46)
        for column in range(6):keyboard.grid_columnconfigure(column,minsize=62,uniform='keys')
        for index,char in enumerate('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'):
            self.button(keyboard,char,lambda c=char:self.key(c),row=index//6,column=index%6)
        tk.Label(self.body,textvariable=self.message,bg=BG,fg='#ffd45c',font=('DejaVu Sans',10),wraplength=460).pack(pady=3)
        bar=tk.Frame(self.body,bg=BG);bar.pack(fill='x')
        for column in range(4):bar.grid_columnconfigure(column,weight=1,uniform='actions')
        for column,(label,action) in enumerate((('⌫',lambda:self.key('back')),('Clear',lambda:self.key('clear')),('Go',self.go),('Back',self.close))):
            self.button(bar,label,action,row=0,column=column)
        nearby=tk.Frame(self.body,bg=BG);nearby.pack(fill='x');nearby.grid_columnconfigure(0,weight=1)
        self.button(nearby,'Nearby airports',self.nearby,row=0,column=0)

    def key(self,key):
        current=self.code.get()
        self.code.set('' if key=='clear' else current[:-1] if key=='back' else (current+key)[:7])

    def go(self):
        try:
            airport=lookup(self.display.catalog,self.code.get())
            self.display.choose_airport(airport['ident'],remember=True)
        except (ValueError,OSError) as exc:self.message.set(str(exc));return
        self.close()

    def nearby(self):
        # Clearing the pinned airport is explicit. A missing GPS fix does not
        # invent a location from traffic or change the actual ownship reference.
        try:self.display.remember_airport('')
        except OSError as exc:self.message.set(str(exc));return
        self.display.airport_selected=None
        fix=getattr(self.display,'airport_fix',None)
        now=time.time()
        self.near=[];self.page=0
        if fix and 0<=now-fix.time<=15:
            self.near=self.display.catalog.nearby((fix.lat,fix.lon),200,__import__('traffic_display').xy)[:20]
            self.near_origin=(fix.lat,fix.lon)
        self.nearby_page()

    def nearby_page(self):
        self.clear()
        tk.Label(self.body,text='Nearby airports',bg=BG,fg=FG,font=('DejaVu Sans',17)).pack(pady=10)
        tk.Label(self.body,text='Nearest at selection time · within 200 NM',bg=BG,fg=FG,font=('DejaVu Sans',10)).pack(pady=4)
        if not self.near:
            tk.Label(self.body,text='Ownship position unavailable, or no airports\nin the nearby search area. Enter an airport ID instead.',bg=BG,fg='#ffd45c',wraplength=440,font=('DejaVu Sans',12)).pack(pady=24)
        for _,airport,_ in self.near[self.page*4:(self.page+1)*4]:
            distance,_=distance_bearing(self.near_origin,(airport['lat'],airport['lon']))
            bar=tk.Frame(self.body,bg=BG);bar.pack(fill='x');bar.grid_columnconfigure(0,weight=1)
            self.button(bar,f'{airport["code"]} · {distance:.1f} NM\n{airport["name"][:38]}',lambda a=airport:self.open_near(a),row=0,column=0)
        nav=tk.Frame(self.body,bg=BG);nav.pack(pady=8)
        prev=self.button(nav,'Prev',lambda:self.turn(-1),row=0,column=0)
        nxt=self.button(nav,'Next',lambda:self.turn(1),row=0,column=1)
        if self.page==0:prev.configure(state='disabled')
        if (self.page+1)*4>=len(self.near):nxt.configure(state='disabled')
        bar=tk.Frame(self.body,bg=BG);bar.pack()
        self.button(bar,'Enter ID',self.entry_page,row=0,column=0);self.button(bar,'Back',self.close,row=0,column=1)

    def turn(self,direction):
        self.page+=direction;self.nearby_page()

    def open_near(self,airport):
        self.display.choose_airport(airport['ident'],remember=False);self.close()

    def close(self):
        self.frame.destroy();self.display.airport_selector=None
        self.display.last_touch=time.monotonic();self.display.draw()
