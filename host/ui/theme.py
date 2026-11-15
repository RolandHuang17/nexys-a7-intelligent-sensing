"""Semantic desktop palette shared by ttk and legacy Tk surfaces."""
import json
import tkinter as tk
from tkinter import ttk

LIGHT = dict(bg='#f3f5f8', surface='#ffffff', ink='#172b44', muted='#52657d', border='#dce4ee',
             blue='#1769c2', teal='#087e78', orange='#a65d08', red='#bc3c4a', soft='#e7edf4')
DARK = dict(bg='#111827', surface='#1c2737', ink='#edf3fa', muted='#afbdd0', border='#34445b',
            blue='#79b7ff', teal='#5bd8c9', orange='#ffc576', red='#ff99a4', soft='#344155')
OLD = {'#edf2f7':'bg','#183047':'ink','#60758a':'muted','#2868aa':'blue','#168c82':'teal',
       '#cc852d':'orange','#bc5356':'red','#e6edf3':'border','#f0f4f8':'border','#e7edf3':'soft',
       '#dce5ee':'border','#d8e2ec':'border','white':'surface','#ffffff':'surface',
       '#e1b56e':'orange','#77dfc6':'teal','#173b5c':'surface'}

def manager(widget):
    return getattr(widget.winfo_toplevel(), 'theme_manager', None)

class ThemedCanvas(tk.Canvas):
    """Resolve display colors only; leave coordinates and plotted data untouched."""
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self._theme_manager=manager(self)

    def _create(self, itemType, args, kw):
        theme = self._theme_manager
        if theme:
            kw = dict(kw)
            for name in ('fill','outline','activefill','activeoutline'):
                if name in kw: kw[name] = theme.resolve(kw[name])
        return super()._create(itemType, args, kw)

class ThemeManager:
    def __init__(self, root, preference_path):
        self.root=root; self.path=preference_path; self.palette=LIGHT; self.choice='跟随系统'
        self.roles={}; self.listeners=[]
        try:self.choice=json.loads(self.path.read_text(encoding='utf8')).get('theme','跟随系统')
        except (OSError,ValueError):pass
        if self.choice not in ('跟随系统','浅色','深色'):self.choice='跟随系统'
        root.theme_manager=self
        self.set(self.choice, persist=False)
        root.bind_all('<Map>', self._mapped, add='+')
        self._watch_id=root.after(2000,self._watch_system)

    def _system_dark(self):
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize') as key:
                return not winreg.QueryValueEx(key,'AppsUseLightTheme')[0]
        except (OSError,ImportError):return False

    def _watch_system(self):
        if self.choice=='跟随系统' and self._system_dark()!=self.dark:self.set(self.choice,persist=False)
        self._watch_id=self.root.after(2000,self._watch_system)

    def resolve(self,color):
        return self.palette.get(OLD.get(str(color).lower(),''),color)

    def set(self,choice,persist=True):
        if choice not in ('跟随系统','浅色','深色'):raise ValueError('未知主题')
        self.previous_palette=self.palette
        self.choice=choice;self.dark=choice=='深色' or (choice=='跟随系统' and self._system_dark())
        self.root.theme_use('bootstrap-dark' if self.dark else 'bootstrap-light')
        self.palette=DARK if self.dark else LIGHT;p=self.palette;s=self.root.style
        s.configure('.',font=('Microsoft YaHei UI',10))
        s.configure('TFrame',background=p['bg']);s.configure('TLabel',background=p['bg'],foreground=p['ink'])
        s.configure('TButton',padding=(12,7));s.configure('TCheckbutton',background=p['bg'])
        s.configure('TLabelframe',background=p['surface'],bordercolor=p['border'])
        s.configure('TLabelframe.Label',background=p['surface'],foreground=p['ink'],font=('Microsoft YaHei UI',10,'bold'))
        s.configure('Card.TFrame',background=p['surface']);s.configure('Card.TLabel',background=p['surface'],foreground=p['ink'])
        s.configure('Muted.TLabel',foreground=p['muted']);s.configure('CardMuted.TLabel',background=p['surface'],foreground=p['muted'])
        s.configure('Title.TLabel',font=('Microsoft YaHei UI',19,'bold'),foreground=p['ink'])
        s.configure('CardValue.TLabel',background=p['surface'],foreground=p['ink'],font=('Segoe UI',22,'bold'))
        s.configure('Accent.TButton',foreground=p['blue'])
        s.configure('Nav.TButton',padding=(16,13),anchor='w')
        s.configure('Active.Nav.TButton',foreground=p['blue'],font=('Microsoft YaHei UI',10,'bold'))
        s.configure('Treeview',rowheight=32,font=('Microsoft YaHei UI',10))
        s.configure('Treeview.Heading',font=('Microsoft YaHei UI',10,'bold'),padding=(8,8))
        self.root.configure(bg=p['bg']);self.apply_tree(self.root)
        for callback in self.listeners:callback()
        if persist:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            self.path.write_text(json.dumps({'theme':choice},ensure_ascii=False),encoding='utf8')

    def register(self,widget):self.apply_tree(widget)

    def preserve(self,widget):widget._ui_preserve=True

    def _mapped(self,event):
        if isinstance(event.widget,tk.Toplevel):self.root.after_idle(lambda w=event.widget:self.apply_tree(w) if w.winfo_exists() else None)

    def apply_tree(self,widget):
        if not widget.winfo_exists() or getattr(widget,'_ui_preserve',False):return
        if isinstance(widget,ttk.Label):
            # Legacy dialogs can explicitly override a ttk style's foreground.
            key=(str(widget),'foreground')
            original=str(widget.cget('foreground')).lower()
            if key not in self.roles and original in OLD:
                self.roles[key]='ink' if original=='#173b5c' else OLD[original]
            if key in self.roles:widget.configure(foreground=self.palette[self.roles[key]])
        elif not isinstance(widget,ttk.Widget):
            options=widget.keys()
            for option in ('background','foreground','highlightbackground','insertbackground'):
                if option not in options:continue
                key=(str(widget),option)
                if key not in self.roles:
                    original=str(widget.cget(option)).lower()
                    role=OLD.get(original)
                    if role is None:role='surface' if option=='background' else ('border' if option=='highlightbackground' else 'ink')
                    self.roles[key]=role
                widget.configure(**{option:self.palette[self.roles[key]]})
        if isinstance(widget,ThemedCanvas):
            # A paused plot must keep its exact points while changing colors.
            colors={value:self.palette[role] for role,value in self.previous_palette.items()}
            for item in widget.find_all():
                for option in ('fill','outline'):
                    try:
                        current=widget.itemcget(item,option)
                        if current in colors:widget.itemconfigure(item,**{option:colors[current]})
                    except tk.TclError:pass
        for child in widget.winfo_children():self.apply_tree(child)
