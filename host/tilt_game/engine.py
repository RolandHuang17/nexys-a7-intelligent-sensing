"""Fixed-step, UI-independent game rules. No serial, file, or network I/O."""
from dataclasses import dataclass
import math
from .levels import Level


@dataclass(frozen=True)
class Control:
    x: float = 0
    y: float = 0
    brake: bool = False


class Game:
    STEP = 1 / 120
    RADIUS = .24

    def __init__(self, level: Level):
        self.level = level
        self.x, self.y = level.start
        self.vx = self.vy = 0.
        self.elapsed = self.accumulator = 0.
        self.collected = set()
        self.has_core = False
        self.gate_open = level.gate is None
        self.plate_charge = 0.
        self.checkpoint = level.start
        self.checkpoints = set()
        self.deaths = 0
        self.respawn_left = self.unsupported = 0.
        self.won = False
        self.paused = False
        self.events = []
        self.lock_notice = False

    @property
    def speed(self):
        return math.hypot(self.vx, self.vy)

    @property
    def on_ice(self):
        return any(r.contains(self.x, self.y) for r in self.level.ice)

    @property
    def stars(self):
        if not self.won:
            return 0
        full = len(self.collected) == len(self.level.energy)
        return 1 + int(full) + int(full and self.deaths == 0 and self.elapsed <= self.level.par)

    def emit(self, kind, **values):
        self.events.append({'kind': kind, 't': round(self.elapsed, 6), **values})

    def drain_events(self):
        events, self.events = self.events, []
        return events

    def advance(self, seconds, control=Control()):
        if self.paused or self.won:
            return
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError('invalid frame duration')
        if not all(math.isfinite(v) for v in (control.x, control.y)):
            raise ValueError('invalid control')
        # A stalled UI never advances a whole second of unseen collisions.
        self.accumulator += min(seconds, .12)
        while self.accumulator + 1e-12 >= self.STEP and not self.won:
            self.accumulator -= self.STEP
            self._step(control)

    def _step(self, control):
        dt = self.STEP
        self.elapsed += dt
        if self.respawn_left > 0:
            self.respawn_left = max(0, self.respawn_left-dt)
            return
        ux, uy = control.x, control.y
        mag = max(1., math.hypot(ux, uy))
        ux, uy = ux/mag, uy/mag
        drag = 11.5 if control.brake else (.38 if self.on_ice else 1.9)
        force = 4.2 if control.brake else 8.5
        damping = math.exp(-drag*dt)
        self.vx = (self.vx + ux*force*dt)*damping
        self.vy = (self.vy + uy*force*dt)*damping
        speed = self.speed
        if speed > self.level.max_speed:
            self.vx *= self.level.max_speed/speed
            self.vy *= self.level.max_speed/speed
        self.x += self.vx*dt
        self.y += self.vy*dt
        walls = self.level.walls + (() if self.gate_open else (self.level.gate,))
        for wall in walls:
            self._wall(wall)
        if not self.level.supported(self.x, self.y):
            self.unsupported += dt
            if self.unsupported >= .085:
                self.die('fall')
                return
        else:
            self.unsupported = 0
        if any(math.hypot(self.x-x, self.y-y) < r+self.RADIUS*.55 for x,y,r in self.level.holes):
            self.die('hole')
            return
        if any(l.active(self.elapsed) and l.rect.distance(self.x,self.y) < self.RADIUS for l in self.level.lasers):
            self.die('laser')
            return
        if any(m.at(self.elapsed).distance(self.x,self.y) < self.RADIUS for m in self.level.movers):
            self.die('mover')
            return
        if self.level.plate and not self.gate_open:
            if self._near(self.level.plate, .68) and self.speed < .9:
                self.plate_charge += dt
                if self.plate_charge >= .4:
                    self.gate_open = True
                    self.emit('gate_open')
            else:
                self.plate_charge = max(0, self.plate_charge-dt*2)
        for i, point in enumerate(self.level.checkpoints):
            if i not in self.checkpoints and self._near(point,.62):
                self.checkpoints.add(i)
                self.checkpoint = point
                self.emit('checkpoint', index=i)
        for i, point in enumerate(self.level.energy):
            if i not in self.collected and self._near(point,.61):
                self.collected.add(i)
                self.emit('energy', index=i)
        if not self.has_core and self._near(self.level.core,.68):
            self.has_core = True
            self.emit('core')
        if self._near(self.level.goal,.65):
            if self.has_core:
                self.won = True
                self.vx = self.vy = 0.
                self.emit('win', stars=self.stars, deaths=self.deaths, energy=len(self.collected))
            elif not self.lock_notice:
                self.lock_notice = True
                self.emit('locked')
        else:
            self.lock_notice = False

    def _near(self, point, radius):
        return math.hypot(self.x-point[0], self.y-point[1]) <= radius

    def _wall(self, r):
        px = max(r.x,min(self.x,r.x+r.w))
        py = max(r.y,min(self.y,r.y+r.h))
        dx, dy = self.x-px, self.y-py
        distance = math.hypot(dx,dy)
        if distance >= self.RADIUS:
            return
        if distance > 1e-9:
            nx, ny = dx/distance, dy/distance
            push = self.RADIUS-distance+1e-6
        else:
            options=((self.x-r.x, -1.,0.),(r.x+r.w-self.x,1.,0.),
                     (self.y-r.y,0.,-1.),(r.y+r.h-self.y,0.,1.))
            distance,nx,ny = min(options)
            push = distance+self.RADIUS+1e-6
        self.x += nx*push
        self.y += ny*push
        vn = self.vx*nx+self.vy*ny
        if vn < 0:
            self.vx -= 1.18*vn*nx
            self.vy -= 1.18*vn*ny

    def die(self, reason):
        if self.respawn_left or self.won:
            return
        self.deaths += 1
        self.emit('death', reason=reason, x=self.x, y=self.y)
        self.x, self.y = self.checkpoint
        self.vx = self.vy = self.unsupported = 0.
        self.respawn_left = .62

    def result(self):
        return {'level':self.level.number, 'won':self.won, 'stars':self.stars,
                'seconds':round(self.elapsed,3), 'deaths':self.deaths,
                'energy':len(self.collected), 'core':self.has_core}
