"""Eight authored, deterministic courses. Distances are logical track units."""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float

    def contains(self, x, y):
        return self.x <= x <= self.x + self.w and self.y <= y <= self.y + self.h

    def distance(self, x, y):
        return math.hypot(max(self.x-x, 0, x-self.x-self.w),
                          max(self.y-y, 0, y-self.y-self.h))


@dataclass(frozen=True)
class Laser:
    rect: Rect
    period: float = 4.4
    duty: float = .46
    phase: float = 0

    def active(self, t):
        return (t + self.phase) % self.period < self.period * self.duty

    def warning(self, t):
        return not self.active(t) and self.period - (t+self.phase) % self.period < .55


@dataclass(frozen=True)
class Mover:
    a: tuple
    b: tuple
    size: tuple
    period: float
    phase: float = 0

    def at(self, t):
        f = (1 - math.cos((t+self.phase) * math.tau / self.period)) / 2
        x, y = (self.a[i] + (self.b[i]-self.a[i])*f for i in (0, 1))
        return Rect(x-self.size[0]/2, y-self.size[1]/2, *self.size)


@dataclass(frozen=True)
class Level:
    number: int
    name: str
    subtitle: str
    hint: str
    floor: tuple
    start: tuple
    core: tuple
    goal: tuple
    energy: tuple
    par: float
    walls: tuple = ()
    holes: tuple = ()
    checkpoints: tuple = ()
    ice: tuple = ()
    lasers: tuple = ()
    movers: tuple = ()
    gate: Rect | None = None
    plate: tuple | None = None
    max_speed: float = 4.6

    def supported(self, x, y):
        return any(r.contains(x, y) for r in self.floor)


R = Rect
LEVELS = (
    Level(1, '初航训练', 'FIRST LIGHT', '轻轻倾斜开始滚动；转弯前按住中键减速。',
          (R(1,9,9,4), R(7,6,5,7), R(7,6,11,4), R(15,2,9,8)),
          (3,11), (17,8), (22,4), ((6,11),(10,8),(20,6)), 50, max_speed=3.4),
    Level(2, '折线航道', 'SWITCHBACK', '看向下一个弯道，提前刹车，出弯后再加速。',
          (R(1,10,9,3), R(7,6,3,7), R(7,6,10,3), R(14,2,3,7), R(14,2,10,3)),
          (3,11.5), (15.5,3.5), (22.5,3.5), ((7.5,11.5),(9,7.5),(15.5,7)), 60,
          walls=(R(3.8,10,.5,1.05), R(11.8,7.9,.6,1.1))),
    Level(3, '悬桥穿越', 'THIN AIR', '窄桥上小幅倾斜；点亮检查点后，失误就从这里继续。',
          (R(1,10,6,4), R(6,11,7,1.5), R(12,7,5,6), R(14,3,1.4,5), R(13,1,11,4)),
          (3,12), (15,9.5), (22,2.5), ((9.5,11.75),(14.7,6),(19,2.5)), 75,
          holes=((15.8,11.3,.55),), checkpoints=((14.5,9.5),)),
    Level(4, '能量门阵', 'OPEN CIRCUIT', '在金色压板上慢下来，停留片刻即可永久打开能量门。',
          (R(1,9,8,4), R(7,5,4,8), R(7,5,12,4), R(16,2,8,7)),
          (3,11), (19,4), (22,6.5), ((4,10.5),(9,6.5),(21,3.5)), 80,
          holes=((17.5,7.6,.5),), checkpoints=((10,7),),
          gate=R(13.2,5,.48,4), plate=(9,11)),
    Level(5, '脉冲走廊', 'PULSE WINDOW', '红色激光亮起时先等一等；虚线熄灭后再通过。',
          (R(1,9,7,4), R(6,9,15,3), R(19,3,4,9), R(16,1,8,4)),
          (3,11), (20.5,8), (21,2.5), ((7.5,10.5),(15.5,10.5),(18,2.5)), 90,
          checkpoints=((16.5,10.5),(20.5,4.5)),
          lasers=(Laser(R(11,9,.18,3),4.2,.48,.8), Laser(R(19,6,4,.18),4.8,.5,2.1))),
    Level(6, '流光回廊', 'ORBITAL TRAFFIC', '巡航障碍不会追你。观察轨迹，从空出来的一侧绕过去。',
          (R(1,9,7,4), R(6,7,14,6), R(18,2,6,11)),
          (3,11), (16.5,10), (21,3.5), ((8,8.5),(13,11.5),(22,9.5)), 95,
          holes=((16,8,.7),), checkpoints=((18.8,11),),
          movers=(Mover((11,7.8),(11,11.6),(.42,1.2),4.4),
                  Mover((20,6),(22,6),(1,.45),3.2))),
    Level(7, '冰面工厂', 'ZERO FRICTION', '蓝紫色冰面会滑得更远，按住刹车能重新控制速度。',
          (R(1,10,8,3), R(6,7,5,6), R(9,7,10,3), R(16,3,4,7), R(16,1,8,4)),
          (3,11.5), (18,4.5), (22,2.5), ((8.5,11),(10,8),(18,8.6)), 100,
          walls=(R(10,7,.35,.75),), holes=((12.8,8.3,.5),(17.8,6.2,.5)),
          checkpoints=((9,8.5),(18,3.5)), ice=(R(6,7,5,6),R(10,7,9,3),R(16,3,4,6))),
    Level(8, '星核终局', 'THE LAST BEACON', '窄桥、压板、激光和冰面都在这里。点亮最后的星核。',
          (R(1,10,6,4),R(6,11,6,1.4),R(11,8,5,5),R(14,5,3,7),R(14,5,7,3),R(19,1,5,7)),
          (3,12), (21.5,2.5), (22,5.5), ((9,11.7),(12.5,9),(18,6.5)), 125,
          holes=((15.8,10.5,.5),), checkpoints=((13,10),(19.8,6.5)), ice=(R(14,5,3,2.5),),
          lasers=(Laser(R(17,5,.18,3),4.4,.45,1.4),),
          movers=(Mover((20,4),(22.5,4),(1,.5),4.4),), gate=R(14,7.8,3,.35), plate=(13,11.5)),
)

WORLD_W, WORLD_H = 26, 15
