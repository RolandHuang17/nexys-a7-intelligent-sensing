"""Behavioral tests: game contracts, relative sensors, and independent saves."""
from dataclasses import replace
import json
import math
from pathlib import Path
import tempfile
import unittest

from tilt_game.engine import Game, Control
from tilt_game.input import TiltInput
from tilt_game.levels import LEVELS, Rect, Laser
from tilt_game.storage import SaveStore


def arena(**changes):
    base=replace(LEVELS[0],floor=(Rect(-20,-20,40,40),),start=(0,0),core=(15,15),
                 goal=(17,17),energy=((15,0),(0,15),(-15,0)),walls=(),holes=())
    return replace(base,**changes)


def advance(game,seconds,control=Control(),fps=60):
    for _ in range(round(seconds*fps)):
        game.advance(1/fps,control)


class Mechanics(unittest.TestCase):
    def test_neutral_does_not_drift_and_diagonal_is_normalized(self):
        game=Game(arena())
        advance(game,5)
        self.assertEqual((game.x,game.y),(0,0))
        a,b=Game(arena()),Game(arena())
        advance(a,1,Control(1,0))
        advance(b,1,Control(1,1))
        self.assertAlmostEqual(a.speed,b.speed,places=10)

    def test_brake_reduces_inertia_including_ice(self):
        ice=(Rect(-20,-20,40,40),)
        a,b=Game(arena(ice=ice)),Game(arena(ice=ice))
        advance(a,1,Control(1,0))
        advance(b,1,Control(1,0))
        start=a.x
        advance(a,.5,Control())
        advance(b,.5,Control(brake=True))
        self.assertGreater(a.x-start,3*(b.x-start))
        self.assertLess(b.speed,.05)

    def test_fixed_step_same_at_30_60_120_fps(self):
        games=[]
        for fps in (30,60,120):
            game=Game(arena())
            advance(game,3,Control(.35,-.2),fps)
            games.append(game)
        for other in games[1:]:
            self.assertAlmostEqual(games[0].x,other.x,places=10)
            self.assertAlmostEqual(games[0].y,other.y,places=10)

    def test_wall_does_not_tunnel_at_max_speed(self):
        wall=Rect(2,-5,.1,10)
        game=Game(arena(walls=(wall,)))
        advance(game,4,Control(1,0),fps=10)
        self.assertLessEqual(game.x,2-game.RADIUS+1e-4)
        self.assertEqual(game.deaths,0)

    def test_fall_restarts_from_checkpoint_keeps_collectibles(self):
        level=arena(floor=(Rect(-1,-1,4,2),),checkpoints=((1,0),),energy=((.5,0),(15,0),(0,15)))
        game=Game(level)
        advance(game,3,Control(1,0))
        self.assertGreater(game.deaths,0)
        self.assertEqual(game.checkpoint,(1,0))
        self.assertIn(0,game.collected)
        self.assertFalse(game.won)

    def test_portal_requires_core_and_star_rules(self):
        game=Game(arena(goal=(0,0),core=(3,0)))
        advance(game,.1)
        self.assertFalse(game.won)
        self.assertIn('locked',[e['kind'] for e in game.drain_events()])
        # Separate scoring fixtures; the campaign verifier uses only controls.
        for n,dead,seconds,expected in ((0,0,10,1),(3,1,10,2),(3,0,1000,2),(3,0,10,3)):
            g=Game(arena())
            g.won=True
            g.collected=set(range(n))
            g.deaths=dead
            g.elapsed=seconds
            self.assertEqual(g.stars,expected)

    def test_plate_requires_slow_dwell_and_stays_open(self):
        game=Game(arena(plate=(0,0),gate=Rect(3,-1,.3,2)))
        advance(game,.25,Control(brake=True))
        self.assertFalse(game.gate_open)
        advance(game,.3,Control(brake=True))
        self.assertTrue(game.gate_open)
        advance(game,1,Control(-1,0))
        self.assertTrue(game.gate_open)

    def test_laser_phase_and_warning_boundaries(self):
        laser=Laser(Rect(-1,-1,2,2),4,.5,0)
        self.assertTrue(laser.active(1.999))
        self.assertFalse(laser.active(2))
        self.assertTrue(laser.warning(3.6))
        game=Game(arena(lasers=(laser,)))
        advance(game,.02)
        self.assertEqual(game.deaths,1)

    def test_pause_freezes_time_and_hazards(self):
        game=Game(LEVELS[4])
        game.paused=True
        advance(game,5,Control(1,1))
        self.assertEqual(game.elapsed,0)
        self.assertEqual((game.x,game.y),game.level.start)

    def test_invalid_inputs_rejected_and_long_frames_bounded(self):
        game=Game(arena())
        for seconds in (-1,float('nan'),float('inf')):
            with self.assertRaises(ValueError):
                game.advance(seconds)
        with self.assertRaises(ValueError):
            game.advance(.1,Control(float('nan'),0))
        game.advance(10,Control(1,0))
        self.assertLess(game.elapsed,.13)


class SensorHarness:
    def __init__(self,tilt):
        self.tilt=tilt
        self.tick=100000000
        self.seq=0
        self.now=10.
        tilt.feed({'kind':'identity','device':{'usb_serial':'TEST_BOARD'}},self.now)
        tilt.feed({'kind':'status','connected':True},self.now)

    def batch(self,xyz,seconds,buttons=0):
        for _ in range(round(seconds/.04)):
            records=[]
            for _ in range(8):
                self.tick+=500000
                self.seq=(self.seq+1)&0xffffffff
                records.append(dict(zip(('seq','tick','x','y','z'),(self.seq,self.tick,*xyz))))
            self.now+=.04
            self.tilt.feed({'kind':'data','epoch':1,'row':{'tick':self.tick,'buttons':buttons,
                           'adxl_configured':True,'adxl_id_ok':True},'xyz':records},self.now)

    def calibrate(self,z_sign=1):
        self.tilt.begin()
        self.batch((0,0,750*z_sign),2.2)
        self.batch((150,0,735*z_sign),.8)
        self.batch((0,-150,735*z_sign),.9)
        self.batch((0,0,750*z_sign),1)


class Sensors(unittest.TestCase):
    def test_face_up_board_negative_z_is_supported(self):
        tilt=TiltInput()
        h=SensorHarness(tilt)
        h.calibrate(z_sign=-1)
        self.assertTrue(tilt.ready,tilt.reason)
        h.batch((150,0,-735),.5)
        self.assertGreater(tilt.control(h.now).x,.4)
        h.batch((0,-150,-735),.5)
        self.assertLess(tilt.control(h.now).y,-.4)

    def test_calibration_relative_to_unscaled_gravity(self):
        tilt=TiltInput()
        h=SensorHarness(tilt)
        h.calibrate()
        self.assertTrue(tilt.ready,tilt.reason)
        self.assertAlmostEqual(tilt.gravity,750)
        h.batch((150,0,735),.5,buttons=16)
        control=tilt.control(h.now)
        self.assertGreater(control.x,.4)
        self.assertAlmostEqual(control.y,0,delta=.02)
        self.assertTrue(control.brake)
        h.batch((0,-150,735),.5)
        self.assertLess(tilt.control(h.now).y,-.4)
        self.assertFalse(tilt.control(h.now).brake)

    def test_deadzone_stale_and_disconnect_release_brake(self):
        tilt=TiltInput()
        h=SensorHarness(tilt)
        h.calibrate()
        h.batch((4,-4,750),.5,buttons=16)
        self.assertEqual(tilt.control(h.now),Control(brake=True))
        self.assertFalse(tilt.fresh(h.now+.251))
        self.assertEqual(tilt.control(h.now+.251),Control())
        tilt.feed({'kind':'status','connected':False},h.now)
        self.assertFalse(tilt.ready)
        self.assertFalse(tilt.brake)

    def test_sequence_wrap_dedup_gaps_and_reset(self):
        tilt=TiltInput()
        h=SensorHarness(tilt)
        h.seq=0xfffffffa
        h.batch((0,0,750),.04)
        self.assertEqual(tilt.received,8)
        count=tilt.received
        row={'tick':h.tick,'buttons':0,'adxl_configured':True,'adxl_id_ok':True}
        tilt.feed({'kind':'data','epoch':1,'row':row,
                   'xyz':[{'seq':h.seq,'tick':h.tick,'x':0,'y':0,'z':750}]},h.now)
        self.assertEqual(tilt.received,count)
        h.seq+=3
        h.batch((0,0,750),.04)
        self.assertEqual(tilt.missing,3)
        tilt.feed({'kind':'reset','epoch':2},h.now)
        self.assertIsNone(tilt.last_fresh)
        self.assertFalse(tilt.ready)

    def test_unchanged_sensor_time_cannot_fake_freshness(self):
        tilt=TiltInput()
        h=SensorHarness(tilt)
        h.batch((0,0,750),.04)
        old=tilt.last_fresh
        h.now+=1
        tilt.feed({'kind':'data','epoch':1,'row':{'tick':h.tick+100000000,'buttons':16,
                   'adxl_configured':True,'adxl_id_ok':True},'xyz':[]},h.now)
        self.assertEqual(tilt.last_fresh,old)
        self.assertFalse(tilt.fresh(h.now))
        self.assertFalse(tilt.brake)


class Saves(unittest.TestCase):
    def test_board_unlocks_sequentially_practice_separate_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            save=SaveStore(directory)
            self.assertEqual(save.unlocked('board'),1)
            self.assertEqual(save.unlocked('keyboard'),8)
            result={'level':1,'won':True,'stars':3,'seconds':45.3,'deaths':0,'energy':3,'core':True}
            save.record('keyboard',result)
            self.assertEqual(save.unlocked('board'),1)
            save.record('board',{**result,'stars':1,'seconds':60})
            save.record('board',{**result,'stars':2,'seconds':65})
            reopened=SaveStore(directory)
            self.assertEqual(reopened.unlocked('board'),2)
            self.assertEqual(reopened.data['board']['1']['stars'],2)
            self.assertEqual(reopened.data['board']['1']['best_seconds'],60)

    def test_corrupt_primary_uses_backup_without_overwriting_it(self):
        with tempfile.TemporaryDirectory() as directory:
            save=SaveStore(directory)
            save.commit()
            save.commit()
            primary=Path(directory)/'progress.json'
            backup=primary.with_suffix('.bak')
            original=backup.read_bytes()
            primary.write_text('{broken',encoding='utf8')
            restored=SaveStore(directory)
            self.assertTrue(restored.warning)
            restored.commit()
            self.assertEqual(backup.read_bytes(),original)
            self.assertEqual(SaveStore(directory).data['version'],1)

    def test_invalid_save_is_not_accepted_and_failed_game_not_written(self):
        with tempfile.TemporaryDirectory() as directory:
            save=SaveStore(directory)
            with self.assertRaises(ValueError):
                save.record('board',{'won':False})
            save.data['settings']['sensitivity']=0
            with self.assertRaises(ValueError):
                save.commit()


if __name__=='__main__':
    unittest.main(verbosity=2)
