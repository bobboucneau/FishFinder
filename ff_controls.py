"""Shared Canvas controls on an 800-unit circular design surface."""
import tkinter as tk

BG = '#041018'
PALETTE = {'nav': ('#0756a7', '#71dbff'), 'edit': ('#24425a', '#8bb6d5'),
           'confirm': ('#08752e', '#75f593'), 'cancel': ('#c61932', '#ff8b99'),
           'panel': ('#092535', '#78d9ff'), 'off': ('#162834', '#506475')}


class RoundScreen(tk.Canvas):
    """Scale drawing and touch coordinates together as the window resizes."""

    def __init__(self, parent, redraw):
        super().__init__(parent, bg=BG, highlightthickness=0, takefocus=True)
        self.redraw = redraw
        self.hits = []
        self.bind('<Configure>', lambda event: redraw())
        self.bind('<ButtonRelease-1>', self.tap)

    def start(self):
        self.delete('all')
        self.hits.clear()
        w, h = self.winfo_width(), self.winfo_height()
        self.scale = min(w, h) / 800
        self.offset = ((w-800*self.scale)/2, (h-800*self.scale)/2)
        self.create_oval(*self.points(5, 5, 795, 795), outline='#168df0',
                         width=max(1, round(5*self.scale)))

    def points(self, *coords):
        return tuple(value*self.scale+self.offset[i%2] for i,value in enumerate(coords))

    def label(self, x, y, value, size, color='white', bold=False, **options):
        self.create_text(*self.points(x,y), text=value, fill=color,
                         font=('DejaVu Sans', -max(1,round(size*self.scale)),
                               'bold' if bold else 'normal'), **options)

    def box(self, bounds, role='panel', radius=36):
        rounded_box(self,bounds,self.points,self.scale,role,radius)

    def button(self, bounds, label, action, role='nav', size=28):
        x,y,u,v = bounds
        if role == 'cancel':
            fill,edge = PALETTE[role]
            self.create_oval(*self.points(*bounds), fill=fill, outline=edge,
                             width=max(1,round(3*self.scale)))
        else:
            self.box(bounds, role if action else 'off')
        self.label((x+u)/2,(y+v)/2,label,size,bold=True)
        if action:
            self.hits.append((bounds,action))

    def tap(self, event):
        if not getattr(self,'scale',0):
            return
        x = (event.x-self.offset[0])/self.scale
        y = (event.y-self.offset[1])/self.scale
        for (left,top,right,bottom),action in reversed(self.hits):
            if left<=x<=right and top<=y<=bottom:
                action()
                return


def rounded_box(canvas,bounds,points,scale,role='panel',radius=36):
    """One corner definition and palette for map, dialogs, and standalone screens.

    points() translates the 800-unit design into actual window coordinates.
    This is drawing only: each screen keeps responsibility for its own actions.
    """
    x,y,u,v=bounds
    r=min(radius,(u-x)/2,(v-y)/2)
    fill,edge=PALETTE[role]
    canvas.create_polygon(*points(x+r,y,u-r,y,u,y,u,y+r,u,v-r,u,v,
                          u-r,v,x+r,v,x,v,x,v-r,x,y+r,x,y),
                          smooth=True,splinesteps=16,fill=fill,outline=edge,
                          width=max(1,round(2*scale)))


class RoundedButton(tk.Canvas):
    """A small reusable Tk widget with the same rounded style as airport entry.

    Existing Setup pages can keep their pack/grid layout. The button understands
    state='disabled' so a running update cannot be started twice.
    """
    def __init__(self,parent,label,command,role='nav'):
        self.label=label;self.command=command;self.role=role;self.enabled=True
        super().__init__(parent,width=max(130,len(label)*8+24),height=38,
                         bg=BG,highlightthickness=0,takefocus=True)
        self.bind('<Configure>',lambda event:self.paint())
        self.bind('<ButtonRelease-1>',self.activate)
        self.bind('<Return>',self.activate)
        self.bind('<space>',self.activate)
        self.bind('<FocusIn>',lambda event:self.paint())
        self.bind('<FocusOut>',lambda event:self.paint())

    def configure(self,cnf=None,**kwargs):
        # Match the small part of Tk Button's public interface used by Setup.
        if 'state' in kwargs:
            self.enabled=kwargs.pop('state')!='disabled'
        result=super().configure(cnf,**kwargs)
        if hasattr(self,'enabled'):self.paint()
        return result

    def paint(self):
        self.delete('all')
        w,h=self.winfo_width(),self.winfo_height()
        rounded_box(self,(2,2,w-2,h-2),lambda *coords:coords,1,
                    self.role if self.enabled else 'off',18)
        self.create_text(w/2,h/2,text=self.label,fill='white' if self.enabled else '#8294a0',
                         font=('DejaVu Sans',11,'bold'))
        if self.focus_get()==self:
            self.create_rectangle(8,8,w-8,h-8,outline='white',dash=(2,2))

    def activate(self,event=None):
        if self.enabled:self.command()
