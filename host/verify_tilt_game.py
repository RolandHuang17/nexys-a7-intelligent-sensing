"""Independent navigation/pilot verifies every authored course with legal controls.

This is digital input, never physical-board acceptance. No ball teleporting,
collision bypass, gate bypass, time manipulation, or direct completion flags.
"""
import argparse
from collections import deque
import heapq
import json
import math
from pathlib import Path
import time

from tilt_game.engine import Game, Control
from tilt_game.levels import LEVELS, Rect, WORLD_W, WORLD_H

GRID=.25
CLEARANCE=.29


class Navigator:
    def __init__(self,level,gate_open=False,avoid_goal=False):
        self.level=level
        self.gate_open=gate_open
        self.avoid_goal=avoid_goal
        self.sweeps=[]
        for mover in level.movers:
            x,y=min(mover.a[0],mover.b[0]),min(mover.a[1],mover.b[1])
            self.sweeps.append(Rect(x-mover.size[0]/2,y-mover.size[1]/2,
                                   abs(mover.a[0]-mover.b[0])+mover.size[0],
                                   abs(mover.a[1]-mover.b[1])+mover.size[1]))
        self.allowed={(i,j) for i in range(int(WORLD_W/GRID)+1) for j in range(int(WORLD_H/GRID)+1)
                      if self.clear(i*GRID,j*GRID)}

    def clear(self,x,y):
        r=CLEARANCE
        if not all(self.level.supported(x+dx,y+dy) for dx,dy in ((0,0),(r,0),(-r,0),(0,r),(0,-r),
                                                                (r*.71,r*.71),(-r*.71,r*.71),(r*.71,-r*.71),(-r*.71,-r*.71))):
            return False
        if any(math.hypot(x-hx,y-hy)<hr+r for hx,hy,hr in self.level.holes):
            return False
        obstacles=self.level.walls+tuple(self.sweeps)
        if self.level.gate and not self.gate_open:
            obstacles+=(self.level.gate,)
        if any(rect.distance(x,y)<r for rect in obstacles):
            return False
        if self.avoid_goal and math.dist((x,y),self.level.goal)<.95:
            return False
        return True

    def nearest(self,point):
        candidate=(round(point[0]/GRID),round(point[1]/GRID))
        if candidate in self.allowed:
            return candidate
        return min(self.allowed,key=lambda p:math.dist((p[0]*GRID,p[1]*GRID),point))

    def line(self,a,b):
        n=max(1,math.ceil(math.dist(a,b)/.07))
        return all(self.clear(a[0]+(b[0]-a[0])*i/n,a[1]+(b[1]-a[1])*i/n) for i in range(n+1))

    def route(self,start,end):
        start_node,end_node=self.nearest(start),self.nearest(end)
        frontier=[(0,0,start_node)]
        came={start_node:None}
        costs={start_node:0}
        while frontier:
            _,cost,current=heapq.heappop(frontier)
            if current==end_node:
                break
            if cost>costs[current]+1e-9:
                continue
            for dx,dy in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)):
                target=(current[0]+dx,current[1]+dy)
                if target not in self.allowed:
                    continue
                if dx and dy and ((current[0]+dx,current[1]) not in self.allowed or (current[0],current[1]+dy) not in self.allowed):
                    continue
                new_cost=cost+math.hypot(dx,dy)
                if new_cost<costs.get(target,float('inf')):
                    costs[target]=new_cost
                    came[target]=current
                    heapq.heappush(frontier,(new_cost+math.dist(target,end_node),new_cost,target))
        if end_node not in came:
            raise AssertionError(f'Level {self.level.number}: no safe route {start} -> {end}')
        path=[]
        node=end_node
        while node is not None:
            path.append((node[0]*GRID,node[1]*GRID))
            node=came[node]
        path.reverse()
        # String-pull only through geometry checked independently of collisions.
        result=[]
        anchor=start
        i=0
        while i<len(path):
            best=i
            for j in range(i,min(len(path),i+80)):
                if self.line(anchor,path[j]):
                    best=j
            result.append(path[best])
            anchor=path[best]
            i=best+1
        if self.line(anchor,end):
            result.append(end)
        return deque(result)


def pilot(level):
    game=Game(level)
    objectives=[]
    if level.plate:
        objectives.append(('plate',level.plate))
    objectives += [('energy',p) for p in level.energy]
    objectives += [('core',level.core),('goal',level.goal)]
    controls=[]
    snapshots=[]
    nav_cache={}
    for name,target in objectives:
        if game.won:
            break
        key=(game.gate_open,name!='goal' and game.has_core)
        if key not in nav_cache:
            nav_cache[key]=Navigator(level,*key)
        nav=nav_cache[key]
        path=nav.route((game.x,game.y),target)
        deadline=game.elapsed+180
        for _ in range(10800):
            if not path:
                path.append(target)
            tx,ty=path[0]
            distance=math.hypot(tx-game.x,ty-game.y)
            if distance<.14 and len(path)>1:
                path.popleft()
                tx,ty=path[0]
                distance=math.hypot(tx-game.x,ty-game.y)
            final_distance=math.dist((game.x,game.y),target)
            done=(name=='plate' and game.gate_open or name=='energy' and
                  any(i in game.collected and p==target for i,p in enumerate(level.energy)) or
                  name=='core' and game.has_core or name=='goal' and game.won)
            if done:
                break
            wait=False
            for laser in level.lasers:
                if laser.rect.distance(game.x,game.y)<1.25 and (laser.active(game.elapsed) or laser.active(game.elapsed+.75)):
                    wait=True
            dwell=name=='plate' and final_distance<.36
            desired_speed=min(1.5,distance*3)
            if wait or dwell:
                desired_speed=0
            dx,dy=tx-game.x,ty-game.y
            desired_vx=dx/max(distance,1e-9)*desired_speed
            desired_vy=dy/max(distance,1e-9)*desired_speed
            drag=.38 if game.on_ice else 1.9
            ux=((desired_vx-game.vx)*7+drag*game.vx)/8.5
            uy=((desired_vy-game.vy)*7+drag*game.vy)/8.5
            control=Control(ux,uy,dwell)
            game.advance(1/60,control)
            controls.append([round(ux,10),round(uy,10),bool(dwell)])
            game.drain_events()
            if len(controls)%60==0:
                snapshots.append([round(game.elapsed,3),round(game.x,4),round(game.y,4),game.deaths])
            if game.deaths:
                raise AssertionError(f'Level {level.number}: pilot died ({name}) at t={game.elapsed:.3f}; last={snapshots[-4:]}')
            if game.elapsed>deadline:
                raise AssertionError(f'Level {level.number}: pilot timeout {name} pos={(game.x,game.y)} target={target}')
        else:
            raise AssertionError(f'Level {level.number}: pilot step limit {name}')
    if not game.won or len(game.collected)!=3 or game.deaths:
        raise AssertionError(f'Level {level.number}: incomplete {game.result()}')
    replay=Game(level)
    for x,y,brake in controls:
        replay.advance(1/60,Control(x,y,brake))
        replay.drain_events()
    if replay.result()!=game.result():
        raise AssertionError(f'Level {level.number}: deterministic replay mismatch')
    return {'result':game.result(),'controls':controls,'snapshots':snapshots}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--level',type=int)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    results=[]
    began=time.monotonic()
    for level in LEVELS:
        if args.level and level.number!=args.level:
            continue
        record=pilot(level)
        (args.output/f'level_{level.number:02}.json').write_text(json.dumps({'source':'digital_control_replay','dt':1/60,**record},ensure_ascii=False),encoding='utf8')
        results.append(record['result'])
        print(json.dumps(record['result'],ensure_ascii=False),flush=True)
    summary={'source':'digital_control_replay','physical_board_trials':0,'passed':True,
             'course_count':len(results),'results':results,'elapsed_wall_seconds':time.monotonic()-began,
             'verification':'A* clearance planner + feedback controller + exact legal-input replay; no teleport or rule bypass'}
    (args.output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in summary.items() if k!='results'},ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
