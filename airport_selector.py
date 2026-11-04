"""Large touch targets for airport entry; independent of actual aircraft position."""
import tkinter as tk
import time
from airport_selection import lookup,distance_bearing
from ff_controls import RoundScreen

CHARACTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

BG='#07131f';FG='#e0f2ef'


class Selector:
    def __init__(self,display):
        self.display=display;self.frame=tk.Frame(display.root,bg=BG,highlightbackground='#62b6ff',highlightthickness=2)
        self.frame.place(relx=.5,rely=.5,anchor='center',relwidth=.70,relheight=.70)
        self.body=tk.Frame(self.frame,bg=BG);self.body.pack(fill='both',expand=True,padx=12,pady=8)
        self.code=tk.StringVar(value=display.config.get('manual_airport',''))
        saved=display.catalog.airports.get(self.code.get())
        if saved:self.code.set(saved['code'])
        self.message=tk.StringVar(value='')
        self.page=0;self.near=[];self.wheel=0;self.entry_page()

    def clear(self):
        for child in self.body.winfo_children():child.destroy()

    def button(self,parent,label,callback,**grid):
        # Minimum row/column sizes provide generous targets even for short keys.
        widget=tk.Button(parent,text=label,command=callback,font=('DejaVu Sans',15),pady=7)
        widget.grid(padx=3,pady=3,sticky='nsew',**grid)
        return widget

    def entry_page(self):
        self.clear()
        self.frame.configure(highlightthickness=0)
        self.frame.place_configure(relwidth=1,relheight=1)
        self.body.pack_configure(padx=0,pady=0)
        self.screen=RoundScreen(self.body,self.draw_entry)
        self.screen.pack(fill='both',expand=True)
        self.screen.bind('<KeyPress>',self.keyboard)
        self.screen.bind('<ButtonPress-1>',self.wheel_press)
        self.screen.bind('<ButtonRelease-1>',self.wheel_release)
        self.screen.bind('<Destroy>',lambda event:self.stop_repeat())
        self.repeat_job=None
        self.press=None
        self.screen.focus_set()

    def match(self):
        """Preview a valid match without changing the saved airport."""
        try:
            return lookup(self.display.catalog,self.code.get())
        except ValueError:
            return None

    def draw_entry(self):
        c=self.screen
        c.start()
        airport=self.match()
        c.button((360,19,440,99),'×',self.close,'cancel',59)
        c.box((174,109,626,193))
        c.label(400,151,self.code.get().upper() or 'Enter airport ID',42,bold=True)
        c.box((83,209,717,281))
        if airport:
            fix=getattr(self.display,'airport_fix',None)
            detail='Position unavailable'
            if fix and 0<=time.time()-fix.time<=15:
                distance,_=distance_bearing((fix.lat,fix.lon),(airport['lat'],airport['lon']))
                detail=f'{distance:.1f} NM'
            c.label(400,232,airport['name'][:49],22,bold=True)
            c.label(400,258,f"{airport['code']}  ·  {detail}",17,'#a8cce5')
        else:
            c.label(400,245,'Select letters or numbers with the wheel',20,'#a8cce5')
        c.button((298,294,502,356),'▲',lambda:self.spin(-1))
        c.box((307,361,493,525))
        c.label(400,383,CHARACTERS[(self.wheel-1)%len(CHARACTERS)],28,'#a8cce5')
        c.box((316,402,484,477),'nav')
        c.label(400,439,CHARACTERS[self.wheel],57,bold=True)
        c.label(400,501,CHARACTERS[(self.wheel+1)%len(CHARACTERS)],28,'#a8cce5')
        c.button((298,530,502,592),'▼',lambda:self.spin(1))
        c.button((42,344,264,425),'⌫ Back',lambda:self.key('back'),'edit')
        c.button((47,442,264,523),'Clear',lambda:self.key('clear'),'edit')
        c.button((535,367,753,495),'→ Next',
                 self.append_selected if len(self.code.get())<7 else None)
        c.label(400,610,self.message.get(),16,'#ffd45c',width=max(1,round(480*c.scale)))
        c.button((226,638,574,709),'✓ Done',self.go if airport else None,'confirm',37)
        c.button((302,720,498,768),'Nearby airports',self.nearby,size=20)

    def wheel_press(self,event):
        # Save the starting point in design units, so gestures scale with the UI.
        c=self.screen
        if not getattr(c,'scale',0):
            return
        x=(event.x-c.offset[0])/c.scale
        y=(event.y-c.offset[1])/c.scale
        self.press=(x,y)
        self.repeated=False
        if 298<=x<=502 and (294<=y<=356 or 530<=y<=592):
            step=-1 if y<=356 else 1
            self.repeat_job=c.after(380,lambda:self.repeat_spin(step,145))

    def repeat_spin(self,step,delay):
        self.repeated=True
        self.spin(step)
        self.repeat_job=self.screen.after(delay,lambda:self.repeat_spin(step,max(55,delay-12)))

    def stop_repeat(self):
        if getattr(self,'repeat_job',None) is not None:
            self.screen.after_cancel(self.repeat_job)
            self.repeat_job=None

    def wheel_release(self,event):
        self.stop_repeat()
        c=self.screen
        if self.press is None:
            return
        x,y=self.press
        self.press=None
        if self.repeated:
            return
        dy=(event.y-c.offset[1])/c.scale-y
        dx=(event.x-c.offset[0])/c.scale-x
        if 307<=x<=493 and 361<=y<=525 and abs(dy)>=24 and abs(dy)>abs(dx):
            steps=max(1,round(abs(dy)/42))
            self.spin(steps if dy<0 else -steps)
        elif abs(dy)<24 and abs(dx)<24:
            c.tap(event)

    def spin(self, step):
        self.wheel=(self.wheel+step)%len(CHARACTERS)
        self.draw_entry()

    def append_selected(self):
        self.key(CHARACTERS[self.wheel])

    def keyboard(self,event):
        if event.keysym=='Escape': self.close()
        elif event.keysym=='Return': self.go()
        elif event.keysym=='BackSpace': self.key('back')
        elif event.keysym in ('Up','Down'): self.spin(-1 if event.keysym=='Up' else 1)
        elif event.char and event.char.upper() in tuple(CHARACTERS):
            self.key(event.char.upper())
        return 'break'

    def key(self,key):
        current=self.code.get()
        self.code.set('' if key=='clear' else current[:-1] if key=='back' else (current+key)[:7])
        self.message.set('')
        self.draw_entry()

    def go(self):
        try:
            airport=lookup(self.display.catalog,self.code.get())
            self.display.choose_airport(airport['ident'],remember=True)
        except (ValueError,OSError) as exc:
            self.message.set(str(exc))
            self.draw_entry()
            return
        self.close()

    def nearby(self):
        # Clearing the pinned airport is explicit. A missing GPS fix does not
        # invent a location from traffic or change the actual ownship reference.
        try:self.display.remember_airport('')
        except OSError as exc:
            self.message.set(str(exc));self.draw_entry();return
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
        self.frame.configure(highlightthickness=2)
        self.frame.place_configure(relwidth=.70,relheight=.70)
        self.body.pack_configure(padx=12,pady=8)
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
