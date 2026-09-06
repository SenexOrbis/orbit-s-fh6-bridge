"""Hardware-free regression tests; never instantiate WindowsInput or a bridge."""
import contextlib
import csv
import io
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import FH6_Orbit_Response as game
import Play


def packet(yaw=0, pitch=0):
    return struct.pack('<6d', 0, 0, 0, yaw, pitch, 0)


class QueueSocket:
    def __init__(self, packets):
        self.packets = iter(packets)

    def recvfrom(self, size):
        try:
            return next(self.packets), ('127.0.0.1', 4242)
        except StopIteration:
            raise BlockingIOError


class TrackingTests(unittest.TestCase):
    def test_packet_validation(self):
        self.assertEqual(game.parse_pose(packet(10, -5)), (10, -5))
        for value in (b'', packet()+b'x', packet(float('nan')), packet(361)):
            self.assertIsNone(game.parse_pose(value))

    def test_queue_uses_newest_valid_pose(self):
        sock = QueueSocket([packet(i) for i in range(40)] + [packet(float('inf'))])
        self.assertEqual(game.newest_pose(sock), ((39, 0), 40, 1, False))

    def test_queue_budget_preserves_responsiveness(self):
        sock = QueueSocket([packet()] * 513)
        self.assertTrue(game.newest_pose(sock)[3])
        self.assertFalse(game.newest_pose(sock)[3])

    def test_still_head_has_no_target_decay(self):
        view = game.FreeLook()
        view.reset((0, 0))
        goal = view.target((8, 0))
        self.assertGreater(goal[0], 0)
        for _ in range(10000):
            self.assertEqual(view.target((8, 0)), goal)

    def test_no_center_dead_zone(self):
        for sign in (-1, 1):
            view = game.FreeLook()
            view.reset((0, 0))
            self.assertGreater(sign*view.target((sign*.1, 0))[0], 0)

    def test_endpoint_reversal_and_manual_center(self):
        for sign in (-1, 1):
            view = game.FreeLook()
            view.reset((0, 0))
            self.assertEqual(view.target((sign*25, 0))[0], sign*50)
            self.assertEqual(view.target((sign*40, 0))[0], sign*50)
            self.assertLess(sign*view.target((sign*39, 0))[0], 50)
            view.reset((sign*39, 0))
            self.assertEqual(view.target((sign*39, 0)), (0, 0))

    def test_yaw_wrap(self):
        view = game.FreeLook()
        view.reset((179, 0))
        self.assertAlmostEqual(view.target((-179, 0))[0], 2*game.YAW_PIXELS_PER_DEG)

    def test_smoothing_is_time_based(self):
        outcomes = []
        for dt in (.01, .02, .04):
            motion = game.Motion()
            for _ in range(round(.12/dt)):
                motion.commit(motion.step((50, 0), dt))
            outcomes.append(motion.smooth[0])
        for value in outcomes:
            self.assertAlmostEqual(value, outcomes[0])

    def test_subpixel_accumulation_and_return(self):
        motion = game.Motion()
        for i in range(1000):
            motion.commit(motion.step((i/100, 0), .01))
        self.assertEqual(motion.sent[0], 10)
        for _ in range(100):
            motion.commit(motion.step((0, 0), .01))
        self.assertEqual(motion.sent, [0, 0])

    def test_production_loop_controls_and_source_loss(self):
        clock = Clock()
        win = MouseStub(clock)
        report = io.StringIO()
        with patch.object(game, 'time', clock), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(KeyboardInterrupt):
                game.run(Stream(clock), win, report, bridge_fresh=lambda: clock.now < 5.2)
        rows = list(csv.DictReader(io.StringIO(report.getvalue())))
        self.assertEqual(max(int(x['recenter_count']) for x in rows), 1)
        self.assertTrue(all(x['rmb_held']=='1' for x in rows if x['state']=='IN GAME'))
        self.assertTrue(all(float(x['target_x'])>20 for x in rows if .5<float(x['seconds'])<1.9))
        self.assertFalse(any(kind=='move' and (3.5<=t<4 or 4.2<=t<4.6 or t>=5.2)
                             for t,kind in win.events))
        self.assertFalse(win.held)
        self.assertEqual(rows[-1]['state'], 'HEADSET STOPPED')

    def test_supervisor_freshness_and_exit(self):
        # Bypass constructor so no thread or process is created.
        bridge = Play.Bridge.__new__(Play.Bridge)
        bridge.process = ProcessStub()
        bridge.started = 0
        bridge.last_pose = None
        bridge.error = None
        with patch.object(Play.time, 'monotonic', return_value=.2):
            self.assertFalse(bridge.fresh())
            bridge.last_pose = 0
            self.assertTrue(bridge.fresh())
        with patch.object(Play.time, 'monotonic', return_value=1.1):
            self.assertFalse(bridge.fresh())
        with patch.object(Play.time, 'monotonic', return_value=5.1):
            with self.assertRaises(RuntimeError):
                bridge.fresh()
        bridge.process.code = 0
        with self.assertRaises(RuntimeError):
            bridge.fresh()


class ProcessStub:
    code = None

    def poll(self):
        return self.code


class Clock:
    now = 0.0

    def perf_counter(self):
        return self.now

    def sleep(self, delay):
        self.now += max(.001, delay)
        if self.now >= 6:
            raise KeyboardInterrupt


class Stream:
    def __init__(self, clock):
        self.clock = clock
        self.last = -1

    def recvfrom(self, size):
        t = self.clock.now
        tick = round(t*10000)
        if tick == self.last:
            raise BlockingIOError
        self.last = tick
        return packet(0 if t<.1 else 8 if t<2.8 else 10), ('127.0.0.1', 4242)


class MouseStub:
    def __init__(self, clock):
        self.clock = clock
        self.held = False
        self.events = []

    def engage(self):
        self.held = True

    def release(self):
        self.held = False

    def move(self, delta):
        if any(delta):
            self.events.append((self.clock.now, 'move'))

    def focused(self):
        return not 3.5 <= self.clock.now < 4

    def key(self, code):
        t = self.clock.now
        if code == 0x78:
            return 2 <= t < 2.5  # Holding F9 must center just once.
        return 4.2 <= t < 4.23 or 4.6 <= t < 4.63


if __name__ == '__main__':
    unittest.main()
