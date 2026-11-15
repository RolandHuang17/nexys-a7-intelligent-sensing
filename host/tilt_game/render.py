"""Cached antialiased scenery and retained Canvas items for the game HUD."""
import math
import random
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageTk
from .levels import WORLD_W, WORLD_H, LEVELS

BG='#080f23'
PANEL='#101e37'
TEXT='#ecf4ff'
MUTED='#a1b2ce'
CYAN='#56e3e8'
GOLD='#ffd17a'
RED='#ff8395'
PURPLE='#ac9bff'


def icon_image(size=128):
    im=Image.new('RGBA',(size,size))
    d=ImageDraw.Draw(im)
    u=size/128
    d.rounded_rectangle((2*u,2*u,126*u,126*u),radius=28*u,fill='#101f38',outline='#3d8b9d',width=max(1,round(3*u)))
    d.line([(22*u,90*u),(43*u,90*u),(43*u,44*u),(92*u,44*u)],fill=CYAN,width=max(2,round(9*u)),joint='curve')
    d.ellipse((75*u,27*u,108*u,60*u),fill='#88f1ed',outline='#d5ffff',width=max(1,round(2*u)))
    d.ellipse((80*u,31*u,89*u,40*u),fill='#ffffff')
    d.polygon([(90*u,77*u),(97*u,89*u),(110*u,93*u),(97*u,98*u),(91*u,110*u),(85*u,98*u),(73*u,93*u),(85*u,88*u)],fill=GOLD)
    return im


def star_points(x,y,r):
    return [v for i in range(10) for v in
            (x+math.sin(i*math.pi/5)*(r if i%2==0 else r*.44),
             y-math.cos(i*math.pi/5)*(r if i%2==0 else r*.44))]


def sky_image(w,h):
    image=Image.new('RGB',(w,h))
    draw=ImageDraw.Draw(image)
    for y in range(h):
        f=y/max(1,h-1)
        draw.line((0,y,w,y),fill=(8+int(4*f),15+int(7*f),35+int(11*f)))
    rng=random.Random(2048)
    for _ in range(max(50,w*h//7000)):
        x,y=rng.randrange(w),rng.randrange(h)
        b=rng.randrange(65,135)
        draw.ellipse((x,y,x+1,y+1),fill=(b,b+10,min(200,b+35)))
    return image


class Renderer:
    def __init__(self,canvas):
        self.c=canvas
        self.images=[]
        self.items={}
        self.card_hits=[]
        self.s=1
        self.ox=self.oy=0
        self.mode=''
        self.width=self.height=0
        self.effects=True
        self.font_scale=min(1.22,max(1,float(canvas.tk.call('tk','scaling'))/(96/72)))

    def text(self,x,y,text,size=12,color=TEXT,anchor='w',bold=False,**kw):
        return self.c.create_text(x,y,text=text,fill=color,anchor=anchor,
                                  font=('Microsoft YaHei UI',-round(size*self.font_scale),'bold' if bold else 'normal'),**kw)

    def rounded(self,x,y,w,h,fill=PANEL,outline='#253b58',r=15,**kw):
        points=[x+r,y,x+w-r,y,x+w,y,x+w,y+r,x+w,y+h-r,x+w,y+h,
                x+w-r,y+h,x+r,y+h,x,y+h,x,y+h-r,x,y+r,x,y]
        return self.c.create_polygon(points,smooth=True,splinesteps=16,fill=fill,outline=outline,**kw)

    def reset(self):
        self.c.delete('all')
        self.images=[]
        self.items={}
        self.card_hits=[]
        self.width=max(640,self.c.winfo_width())
        self.height=max(400,self.c.winfo_height())

    def photo(self,image,x=0,y=0,anchor='nw',**kw):
        photo=ImageTk.PhotoImage(image,master=self.c)
        self.images.append(photo)
        return self.c.create_image(x,y,image=photo,anchor=anchor,**kw)

    def thumbnail(self,level,w,h):
        ratio=min((w-20)/WORLD_W,(h-12)/WORLD_H)
        x0=(w-WORLD_W*ratio)/2
        y0=(h-WORLD_H*ratio)/2
        im=Image.new('RGB',(w,h),'#0b162a')
        d=ImageDraw.Draw(im)
        for r in level.floor:
            d.rectangle((x0+r.x*ratio,y0+r.y*ratio,x0+(r.x+r.w)*ratio,y0+(r.y+r.h)*ratio),
                        fill='#1b3549',outline='#377786')
        for x,y,r in level.holes:
            d.ellipse((x0+(x-r)*ratio,y0+(y-r)*ratio,x0+(x+r)*ratio,y0+(y+r)*ratio),fill='#040a17')
        for x,y,color in ((*level.start,CYAN),(*level.core,GOLD),(*level.goal,'#9c99ff')):
            px,py=x0+x*ratio,y0+y*ratio
            d.ellipse((px-2,py-2,px+2,py+2),fill=color)
        return im

    def map(self,store,mode,selected):
        self.reset()
        self.mode='map'
        w,h=self.width,self.height
        self.photo(sky_image(w,h))
        self.text(34,28,'GRAVITY  /  VOYAGER',12,CYAN,bold=True)
        self.text(32,71,'重力迷航',36,bold=True)
        self.text(34,111,'让重力指引方向，点亮航道尽头的星核。',14,MUTED)
        self.text(w-34,48,f'{store.total_stars(mode):02d}  /  24',30,GOLD,anchor='e',bold=True)
        self.text(w-34,82,'实板航行记录' if mode=='board' else '键盘练习记录 · 独立保存',12,MUTED,anchor='e')
        self.text(w-34,112,'8 个星区  /  逐关探索',12,CYAN,anchor='e')
        margin,gap=32,15
        cw=(w-margin*2-gap*3)/4
        ch=min(217,(h-167-24)/2)
        for i,level in enumerate(LEVELS):
            col,row=i%4,i//4
            x=margin+col*(cw+gap)
            y=147+row*(ch+15)
            unlocked=level.number<=store.unlocked(mode)
            record=store.data[mode].get(str(level.number),{})
            active=i==selected
            self.rounded(x,y,cw,ch,fill='#142a42' if active else '#0e1d32',
                         outline=CYAN if active else '#263b54',width=2 if active else 1)
            self.text(x+16,y+23,f'{level.number:02d}',15,CYAN if unlocked else MUTED,bold=True)
            self.text(x+cw-15,y+23,'待探索' if unlocked and not record else ('已通关' if record else '未解锁'),11,
                      GOLD if record else MUTED,anchor='e')
            self.photo(self.thumbnail(level,max(50,int(cw-24)),max(40,int(ch-103))),x+12,y+43)
            self.text(x+16,y+ch-43,level.name,17,TEXT if unlocked else MUTED,bold=True)
            self.text(x+16,y+ch-20,level.subtitle,9,MUTED)
            for j in range(3):
                self.c.create_polygon(star_points(x+cw-57+j*16,y+ch-23,6.5),
                                      fill=GOLD if j<record.get('stars',0) else '#34445c',outline='')
            self.card_hits.append((x,y,x+cw,y+ch,i,unlocked))

    def point(self,x,y):
        return self.ox+x*self.s,self.oy+y*self.s

    def rect(self,r):
        x,y=self.point(r.x,r.y)
        return x,y,x+r.w*self.s,y+r.h*self.s

    def circle(self,point,r,**kw):
        x,y=self.point(*point)
        r *= self.s
        return self.c.create_oval(x-r,y-r,x+r,y+r,**kw)

    def scene_image(self,level):
        w,h=self.width,self.height
        k=2
        image=sky_image(w,h).resize((w*k,h*k))
        mask=Image.new('L',image.size)
        md=ImageDraw.Draw(mask)
        for r in level.floor:
            md.rectangle(tuple(round(v*k) for v in self.rect(r)),fill=255)
        glow=mask.filter(ImageFilter.MaxFilter(7)).filter(ImageFilter.GaussianBlur(6))
        image.paste('#153c52',(0,0),glow)
        shadow=ImageChops.offset(mask,0,7*k)
        image.paste('#030b19',(0,0),shadow)
        image.paste('#1a3447',(0,0),mask)
        inner=mask.filter(ImageFilter.MinFilter(5))
        edge=ImageChops.subtract(mask,inner)
        image.paste('#57b9c2',(0,0),edge)
        d=ImageDraw.Draw(image)
        grid=Image.new('RGB',image.size,'#1a3447')
        gd=ImageDraw.Draw(grid)
        for i in range(WORLD_W+1):
            px=(self.ox+i*self.s)*k
            gd.line((px,self.oy*k,px,(self.oy+WORLD_H*self.s)*k),fill='#213d50',width=1)
        for i in range(WORLD_H+1):
            py=(self.oy+i*self.s)*k
            gd.line((self.ox*k,py,(self.ox+WORLD_W*self.s)*k,py),fill='#213d50',width=1)
        image.paste(grid,(0,0),inner)
        d=ImageDraw.Draw(image)
        for r in level.ice:
            box=tuple(round(v*k) for v in self.rect(r))
            d.rectangle(box,fill='#34365e',outline='#9181c2',width=2)
            for xx in range(int(box[0]+10),int(box[2]-5),24):
                yy=box[1]+(xx-box[0])%(max(1,int(box[3]-box[1]-12)))
                d.line((xx,yy,xx+7,yy+7),fill='#74739e',width=2)
        for r in level.walls:
            box=tuple(round(v*k) for v in self.rect(r))
            d.rounded_rectangle(box,radius=5,fill='#3a536c',outline='#9cb3c6',width=2)
        for x,y,r in level.holes:
            px,py=self.point(x,y)
            box=((px-r*self.s)*k,(py-r*self.s)*k,(px+r*self.s)*k,(py+r*self.s)*k)
            d.ellipse(box,fill='#030916',outline='#51617e',width=3)
        return image.resize((w,h),Image.Resampling.LANCZOS)

    def game(self,game,mode):
        self.reset()
        self.mode='game'
        w,h=self.width,self.height
        self.s=min((w-292)/WORLD_W,(h-108)/WORLD_H)
        self.ox=24
        self.oy=74+(h-108-WORLD_H*self.s)/2
        self.photo(self.scene_image(game.level))
        self.text(30,27,f'{game.level.number:02d}  /  {game.level.name}',23,bold=True)
        self.text(31,52,game.level.subtitle,10,CYAN)
        self.items['timer']=self.text(w-263,29,'00:00.0',21,GOLD,anchor='e',bold=True)
        self.text(30,h-16,game.level.hint,12,MUTED)
        side=w-240
        self.side=side
        self.hud_scale=min(1,(h-56)/510)
        sy=lambda y: 16+(y-16)*self.hud_scale
        self.rounded(side,16,221,h-54,fill='#0c1a30',outline='#213653')
        self.text(side+18,sy(43),'航行目标',15,bold=True)
        self.text(side+18,sy(73),'通行核心',12,MUTED)
        self.items['core_status']=self.text(side+202,sy(73),'待收集',12,GOLD,anchor='e')
        self.text(side+18,sy(104),'额外能量',12,MUTED)
        self.items['energy_status']=self.text(side+202,sy(104),'0 / 3',14,CYAN,anchor='e',bold=True)
        self.c.create_line(side+18,sy(125),side+202,sy(125),fill='#263a53')
        self.text(side+18,sy(152),'姿态指引',12,MUTED)
        self.items['tilt_ring']=self.c.create_oval(side+59,sy(176),side+163,sy(280),outline='#34526a',width=2)
        self.c.create_line(side+111,sy(176),side+111,sy(280),fill='#263d56')
        self.c.create_line(side+59,sy(228),side+163,sy(228),fill='#263d56')
        self.items['tilt_dot']=self.c.create_oval(side+105,sy(222),side+117,sy(234),fill=CYAN,outline='')
        self.items['brake']=self.text(side+111,sy(302),'中键 / 空格  ·  刹车',12,MUTED,anchor='center')
        self.items['deaths']=self.text(side+18,sy(345),'失误  0 次',12,MUTED)
        self.text(side+18,sy(374),f'三星目标  {int(game.level.par)} 秒',12,GOLD)
        self.text(side+18,sy(404),'收齐能量 · 无失误 · 达到时间',10,MUTED)
        self.c.create_line(side+18,sy(428),side+202,sy(428),fill='#263a53')
        self.text(side+18,sy(450),'实板倾斜控制' if mode=='board' else '键盘练习 · 成绩独立',11,CYAN)
        self.text(side+18,sy(477),'P / Esc  暂停\nR  重新开始本关',11,MUTED,anchor='nw',width=180)
        self.items['checkpoints']=[]
        for p in game.level.checkpoints:
            a=self.circle(p,.63,outline='#417b85',width=2,dash=(3,3))
            b=self.circle(p,.18,fill='#417b85',outline='')
            self.items['checkpoints'].append((a,b))
        self.items['gate']=[]
        if game.level.gate:
            self.items['gate'].append(self.c.create_rectangle(*self.rect(game.level.gate),fill='#e4b369',outline=GOLD,width=2))
            self.items['plate']=self.circle(game.level.plate,.66,fill='#5c4b32',outline=GOLD,width=2)
            self.items['plate_text']=self.text(*self.point(*game.level.plate),'停',11,GOLD,anchor='center',bold=True)
        self.items['lasers']=[]
        for l in game.level.lasers:
            self.items['lasers'].append(self.c.create_rectangle(*self.rect(l.rect),fill=RED,outline=RED,width=2))
        self.items['movers']=[]
        for m in game.level.movers:
            self.c.create_line(*self.point(*m.a),*self.point(*m.b),fill='#4c406c',dash=(3,5))
            self.items['movers'].append(self.c.create_rectangle(*self.rect(m.at(0)),fill='#d496d7',outline='#ffe0f6',width=2))
        self.items['energy']=[]
        for x,y in game.level.energy:
            px,py=self.point(x,y)
            rr=max(6,self.s*.23)
            aura=self.circle((x,y),.43,outline='#526b60',width=1)
            gem=self.c.create_polygon(px,py-rr,px+rr,py,px,py+rr,px-rr,py,fill=GOLD,outline='#fff1c9',width=1)
            self.items['energy'].append((aura,gem))
        px,py=self.point(*game.level.core)
        rr=self.s*.40
        self.items['core']=[self.circle(game.level.core,.63,outline='#8e7849',dash=(3,4)),
                            self.c.create_polygon(px,py-rr,px+rr*.8,py,px,py+rr,px-rr*.8,py,fill=GOLD,outline='#fff2c8',width=2)]
        self.items['portal']=[self.circle(game.level.goal,r,outline='#7f88b6',width=width) for r,width in ((.8,2),(.62,3),(.38,1))]
        self.items['portal_label']=self.text(*self.point(game.level.goal[0],game.level.goal[1]+1.15),'终点 · 需核心',10,MUTED,anchor='center')
        self.items['trail']=[self.c.create_oval(0,0,0,0,fill=color,outline='') for color in ('#203d53','#285368','#337989','#48a5b5')]
        self.history=[]
        self.items['ball_shadow']=self.circle(game.level.start,.27,fill='#07101d',outline='')
        self.ball_photo=self._ball_sprite(max(24,int(self.s*.72)))
        self.items['ball']=self.c.create_image(*self.point(game.x,game.y),image=self.ball_photo)
        self.items['notice']=self.text((w-260)/2,61,'',12,CYAN,anchor='center')

    def _ball_sprite(self,size):
        big=size*3
        im=Image.new('RGBA',(big,big))
        pixels=im.load()
        radius=big*.34
        cx,cy=big/2,big/2
        for yy in range(big):
            for xx in range(big):
                nx,ny=(xx-cx)/radius,(yy-cy)/radius
                d=nx*nx+ny*ny
                if d<=1:
                    nz=math.sqrt(1-d)
                    light=max(0,-nx*.4-ny*.55+nz*.7)
                    spec=light**16
                    pixels[xx,yy]=(min(255,int(40+120*light+100*spec)),
                                   min(255,int(116+108*light+55*spec)),
                                   min(255,int(160+85*light+30*spec)),255)
        return ImageTk.PhotoImage(im.resize((size,size),Image.Resampling.LANCZOS),master=self.c)

    def update(self,game,control,notice=''):
        if self.mode!='game':
            return
        c=self.c
        s=self.s
        x,y=self.point(game.x,game.y)
        c.coords(self.items['ball'],x,y)
        r=s*.25
        c.coords(self.items['ball_shadow'],x-r,y-r+3,x+r,y+r+3)
        visible='hidden' if game.respawn_left>.32 else 'normal'
        c.itemconfigure(self.items['ball'],state=visible)
        self.history.append((x,y))
        self.history=self.history[-16:]
        for i,item in enumerate(self.items['trail']):
            p=self.history[max(0,len(self.history)-1-(4-i)*3)]
            rr=s*(.045+i*.025)
            c.coords(item,p[0]-rr,p[1]-rr,p[0]+rr,p[1]+rr)
            c.itemconfigure(item,state='normal' if self.effects and game.speed>.35 and not game.respawn_left else 'hidden')
        minutes,seconds=divmod(game.elapsed,60)
        c.itemconfigure(self.items['timer'],text=f'{int(minutes):02d}:{seconds:04.1f}')
        c.itemconfigure(self.items['core_status'],text='已获得' if game.has_core else '待收集',fill=CYAN if game.has_core else GOLD)
        c.itemconfigure(self.items['energy_status'],text=f'{len(game.collected)} / 3')
        c.itemconfigure(self.items['deaths'],text=f'失误  {game.deaths} 次')
        side=self.width-240
        tx,ty=side+111+control.x*39,16+(228-16+control.y*39)*self.hud_scale
        c.coords(self.items['tilt_dot'],tx-6,ty-6,tx+6,ty+6)
        c.itemconfigure(self.items['brake'],text='刹车已按住' if control.brake else '中键 / 空格  ·  刹车',fill=GOLD if control.brake else MUTED)
        c.itemconfigure(self.items['notice'],text=notice)
        for i,items in enumerate(self.items['energy']):
            for item in items:
                c.itemconfigure(item,state='hidden' if i in game.collected else 'normal')
        for item in self.items['core']:
            c.itemconfigure(item,state='hidden' if game.has_core else 'normal')
        for item in self.items['portal']:
            c.itemconfigure(item,outline=CYAN if game.has_core else '#7f88b6')
        c.itemconfigure(self.items['portal_label'],text='终点 · 已开启' if game.has_core else '终点 · 需核心',fill=CYAN if game.has_core else MUTED)
        for i,items in enumerate(self.items['checkpoints']):
            c.itemconfigure(items[0],outline=CYAN if i in game.checkpoints else '#417b85')
            c.itemconfigure(items[1],fill=CYAN if i in game.checkpoints else '#417b85')
        for item in self.items['gate']:
            c.itemconfigure(item,state='hidden' if game.gate_open else 'normal')
        if 'plate' in self.items:
            c.itemconfigure(self.items['plate'],fill='#225b5b' if game.gate_open else '#5c4b32')
            c.itemconfigure(self.items['plate_text'],text='开' if game.gate_open else '停',fill=CYAN if game.gate_open else GOLD)
        for laser,item in zip(game.level.lasers,self.items['lasers']):
            active,warning=laser.active(game.elapsed),laser.warning(game.elapsed)
            c.itemconfigure(item,fill=RED if active else '',outline=RED if active else GOLD if warning else '#4b526a',
                            width=3 if active else 1,dash=() if active else (3,4))
        for mover,item in zip(game.level.movers,self.items['movers']):
            c.coords(item,*self.rect(mover.at(game.elapsed)))

    def overlay(self,title,body,tag='overlay',stars=None,kicker='FLIGHT PAUSED'):
        self.c.delete(tag)
        w,h=self.width,self.height
        shade=Image.new('RGBA',(w,h),(3,9,23,184))
        self.photo(shade,tags=tag)
        pw=min(580,w-80)
        ph=272 if stars is not None else 238
        x,y=(w-pw)/2,(h-ph)/2
        self.rounded(x,y,pw,ph,fill='#11243d',outline='#477184',tags=tag,width=1)
        self.text(w/2,y+34,kicker,11,CYAN,anchor='center',bold=True,tags=tag)
        self.text(w/2,y+81,title,29,TEXT,anchor='center',bold=True,tags=tag)
        if stars is not None:
            for i in range(3):
                self.c.create_polygon(star_points(w/2+(i-1)*53,y+137,18),fill=GOLD if i<stars else '#3c4b62',outline='',tags=tag)
        self.text(w/2,y+ph-70,body,13,MUTED,anchor='center',justify='center',width=pw-55,tags=tag)
        self.text(w/2,y+ph-26,'使用下方按钮继续',11,CYAN,anchor='center',tags=tag)

    def calibration(self,tilt):
        self.reset()
        self.mode='calibration'
        w,h=self.width,self.height
        self.photo(sky_image(w,h))
        self.text(36,38,'握持校准',27,bold=True)
        self.text(36,76,'只需几个动作，让板子的方向和你的习惯一致。',14,MUTED)
        steps=(('neutral','01  握稳板子'),('right','02  向右轻倾'),('forward','03  向前轻倾'),('return','04  回到自然姿势'))
        current=next((i for i,(p,_) in enumerate(steps) if p==tilt.phase),0)
        for i,(phase,label) in enumerate(steps):
            x=36+i*(w-72)/4
            self.text(x,122,label,13,CYAN if i==current else MUTED,bold=i==current)
        cx,cy=w/2,h/2+7
        self.c.create_oval(cx-141,cy-141,cx+141,cy+141,outline='#24445d',width=2)
        self.c.create_oval(cx-109,cy-109,cx+109,cy+109,outline='#24445d',dash=(2,8))
        self.rounded(cx-86,cy-57,172,114,fill='#194651',outline=CYAN,r=15,width=2)
        self.c.create_rectangle(cx-40,cy-24,cx+11,cy+25,fill='#16263d',outline='#88a4ac',width=1)
        for dx,dy in ((50,-22),(50,0),(50,22)):
            self.c.create_oval(cx+dx-5,cy+dy-5,cx+dx+5,cy+dy+5,fill=GOLD,outline='')
        arrow={'right':'→','forward':'↑','neutral':'—','return':'—'}.get(tilt.phase,'—')
        self.text(cx,cy-94,arrow,38,CYAN,anchor='center')
        self.items['cal_reason']=self.text(cx,cy+183,tilt.reason,16,TEXT,anchor='center',width=w-100,justify='center')
        self.items['cal_progress_bg']=self.rounded(cx-140,cy+215,280,6,fill='#20384e',outline='',r=3)
        self.items['cal_progress']=self.c.create_rectangle(cx-140,cy+215,cx-140+280*tilt.progress,cy+221,fill=CYAN,outline='')
        self.cal_center=(cx,cy)

    def update_calibration(self,tilt):
        if self.mode!='calibration':
            return
        cx,cy=self.cal_center
        self.c.itemconfigure(self.items['cal_reason'],text=tilt.reason)
        self.c.coords(self.items['cal_progress'],cx-140,cy+215,cx-140+280*tilt.progress,cy+221)
