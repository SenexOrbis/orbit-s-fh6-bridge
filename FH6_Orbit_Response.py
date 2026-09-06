"""Orbit response v0.7: manual-center relative freelook and controller L3.

Game connection design based on the user-supplied FH6_OpenTrack_HeadTrack.py
v1.4.0 by StretchCGB (https://github.com/StretchCGB/FH6-HeadTracking).
This separate experimental implementation is not an upstream release.
Uses the same foreground-only relative mouse/RMB method, UDP port 4242.
No packages required. No headset access, game memory access or profile changes.
"""
import ctypes
import csv
import math
import os
from pathlib import Path
import socket
import struct
import time

# Angles are OpenTrack OUTPUT angles, after its mapping and inversion.
UDP_PORT = 4242
YAW_PIXELS_PER_DEG = 50.0 / (20.0 - 0.35)  # Retain v0.5/v0.6 local sensitivity.
PITCH_PIXELS_PER_DEG = 2.0
MAX_MOUSE_PIXELS = 50.0  # Same full-scale mouse travel as original speed 5.
SMOOTH_SECONDS = 0.040  # Time constant, independent of packet/update rate.
ENABLE_PITCH = False   # Yaw-only test. Roll is not mapped to mouse input.
INVERT_YAW = False
INVERT_PITCH = False
LOOP_SECONDS = 0.010
STALE_SECONDS = 0.5


class FreeLook:
    """Integrate changes in pose; no neutral-angle attraction or dead zone.

    Track the newest head angle even at the camera limit, so overtravel is
    discarded rather than requiring the head to traverse it on return.
    After hitting a limit the old physical neutral need not be camera center;
    manual recenter is the user's explicit alignment operation.
    """
    def __init__(self):
        self.reset()

    def reset(self, pose=None):
        self.previous = pose
        self.position = [0.0, 0.0]

    def target(self, pose):
        if self.previous is not None:
            yaw_delta = (pose[0] - self.previous[0] + 180.0) % 360.0 - 180.0
            pitch_delta = pose[1] - self.previous[1]
            changes = (yaw_delta * YAW_PIXELS_PER_DEG * (-1 if INVERT_YAW else 1),
                       pitch_delta * PITCH_PIXELS_PER_DEG * (-1 if INVERT_PITCH else 1)
                       if ENABLE_PITCH else 0.0)
            for i in range(2):
                self.position[i] = max(-MAX_MOUSE_PIXELS,
                                       min(MAX_MOUSE_PIXELS, self.position[i] + changes[i]))
        self.previous = pose
        return tuple(self.position)


def parse_pose(data):
    if len(data) != 48:
        return None
    values = struct.unpack('<6d', data)
    if not all(math.isfinite(v) for v in values):
        return None
    if any(abs(v) > 360.0 for v in values[3:]):
        return None
    return values[3], values[4]


def newest_pose(sock):
    """Drain even while paused/unfocused. Never replay a long packet queue.

    Bounded work protects hotkey responsiveness. If the budget is exhausted,
    suppress output this tick and continue draining on the next tick.
    """
    latest, count, invalid = None, 0, 0
    for _ in range(512):
        try:
            data, _ = sock.recvfrom(65535)
        except BlockingIOError:
            return latest, count, invalid, False
        pose = parse_pose(data)
        if pose is None:
            invalid += 1
        else:
            latest = pose
            count += 1
    return latest, count, invalid, True


class Motion:
    """Pixel-space controller; quantization residue stays in the target error."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.smooth = [0.0, 0.0]
        self.sent = [0, 0]

    def step(self, target, dt):
        alpha = 1.0 if SMOOTH_SECONDS <= 0 else -math.expm1(-dt / SMOOTH_SECONDS)
        delta = []
        for i in range(2):
            self.smooth[i] += (target[i] - self.smooth[i]) * alpha
            delta.append(round(self.smooth[i] - self.sent[i]))
        return tuple(delta)

    def commit(self, delta):
        for i in range(2):
            self.sent[i] += delta[i]


# Fixed-width Windows types keep INPUT layout correct with 32/64-bit Python.
U32, I32, U16 = ctypes.c_uint32, ctypes.c_int32, ctypes.c_uint16


class MouseInput(ctypes.Structure):
    _fields_ = [('dx', I32), ('dy', I32), ('mouseData', U32),
                ('dwFlags', U32), ('time', U32), ('dwExtraInfo', ctypes.c_size_t)]


class KeyboardInput(ctypes.Structure):
    _fields_ = [('wVk', U16), ('wScan', U16), ('dwFlags', U32),
                ('time', U32), ('dwExtraInfo', ctypes.c_size_t)]


class HardwareInput(ctypes.Structure):
    _fields_ = [('uMsg', U32), ('wParamL', U16), ('wParamH', U16)]


class InputUnion(ctypes.Union):
    _fields_ = [('mi', MouseInput), ('ki', KeyboardInput), ('hi', HardwareInput)]


class Input(ctypes.Structure):
    _fields_ = [('type', U32), ('data', InputUnion)]


class WindowsInput:
    def __init__(self):
        self.api = ctypes.WinDLL('user32', use_last_error=True)
        self.api.SendInput.argtypes = (U32, ctypes.POINTER(Input), ctypes.c_int)
        self.api.SendInput.restype = U32
        self.api.GetForegroundWindow.restype = ctypes.c_void_p
        self.api.GetWindowTextW.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int)
        self.api.GetAsyncKeyState.argtypes = (ctypes.c_int,)
        self.api.GetAsyncKeyState.restype = ctypes.c_int16
        self.held = False

    def send(self, flags, dx=0, dy=0):
        event = Input()
        event.data.mi = MouseInput(dx, dy, 0, flags, 0, 0)
        if self.api.SendInput(1, ctypes.byref(event), ctypes.sizeof(event)) != 1:
            raise OSError('Windows rejected mouse input; error {}'.format(ctypes.get_last_error()))

    def release(self):
        if self.held:
            self.send(0x0010)
            self.held = False

    def move(self, delta):
        if not any(delta):
            return
        self.engage()
        self.send(0x0001, *delta)

    def engage(self):
        if not self.held:
            self.send(0x0008)
            self.held = True

    def focused(self):
        buffer = ctypes.create_unicode_buffer(512)
        self.api.GetWindowTextW(self.api.GetForegroundWindow(), buffer, len(buffer))
        # Same title-based gate as user's working script. Console title differs.
        return 'Forza Horizon 6' in buffer.value

    def key(self, code):
        return bool(self.api.GetAsyncKeyState(code) & 0x8000)


def run(sock, win, report, bridge_fresh=None):
    motion = Motion()
    freelook = FreeLook()
    latest = (0.0, 0.0)
    center = (0.0, 0.0)
    last_packet = None
    paused = False
    was_pause = was_center = False
    reset_until = 0.0
    start = last_tick = last_log = time.perf_counter()
    packets = invalid_total = 0
    recenter_count = 0
    last_recenter = ''
    writer = csv.writer(report)
    writer.writerow(['seconds', 'state', 'raw_yaw', 'raw_pitch', 'target_x',
                     'smoothed_x', 'sent_x', 'packet_age_ms', 'packets', 'invalid',
                     'relative_yaw', 'rmb_held',
                     'recenter_count', 'last_recenter'])
    while True:
        tick = time.perf_counter()
        dt = min(tick - last_tick, 0.1)
        last_tick = tick
        pose, count, invalid, backlog = newest_pose(sock)
        packets += count
        invalid_total += invalid
        if pose is not None:
            latest = pose
            last_packet = tick
        age = math.inf if last_packet is None else tick - last_packet
        focused = win.focused()
        source_alive = bridge_fresh is None or bridge_fresh()
        pause_key, center_key = win.key(0x77), win.key(0x78)
        if pause_key and not was_pause:
            paused = not paused
        keyboard_center = center_key and not was_center
        # Steam's per-game DualSense layout maps L3 to F9. No controller driver
        # assumptions and no duplicate native-controller/key event handling.
        if keyboard_center and focused and not paused and source_alive and age <= STALE_SECONDS and not backlog:
            center = latest
            recenter_count += 1
            last_recenter = 'F9 / Steam L3'
            print('\nRECENTERED via ' + last_recenter, flush=True)
            # This short button-release interval is ONLY after explicit recenter.
            reset_until = tick + 0.2
            win.release()
            motion.reset()
            freelook.reset(latest)
        was_pause, was_center = pause_key, center_key
        state = ('HEADSET STOPPED' if not source_alive else
                 'PAUSED' if paused else 'DRAINING' if backlog else
                 'WAITING FOR UDP' if age > STALE_SECONDS else
                 'STANDBY' if not focused else
                 'CENTERING' if tick < reset_until else 'IN GAME')
        target = (0.0, 0.0)
        yaw = 0.0
        if state != 'IN GAME':
            win.release()
            motion.reset()
            # Rebaseline while inactive; resuming does not replay head motion
            # accumulated in menus or while outside the game.
            freelook.reset(latest)
        else:
            yaw = (latest[0] - center[0] + 180.0) % 360.0 - 180.0
            target = freelook.target(latest)
            delta = motion.step(target, dt)
            win.engage()
            win.move(delta)
            motion.commit(delta)
            # Keep RMB engaged throughout active freelook, including at rest.
            # Pause, focus loss, recenter, stale UDP and exit still release it.
        if tick - last_log >= 0.1:
            age_ms = round(age * 1000, 1) if math.isfinite(age) else ''
            writer.writerow([round(tick-start, 3), state, *latest, target[0],
                             motion.smooth[0], motion.sent[0], age_ms, packets, invalid_total,
                             yaw, int(win.held), recenter_count, last_recenter])
            report.flush()
            print('\r{:16} yaw={:+6.1f}  mouse={:+4d}  UDP packets={}      '.format(
                state, latest[0], motion.sent[0], packets), end='', flush=True)
            last_log = tick
        time.sleep(max(0.0, LOOP_SECONDS - (time.perf_counter() - tick)))


def main():
    if os.name != 'nt':
        raise SystemExit('Run this game connector on your Windows gaming PC.')
    print('Orbit game response v0.7 - manual-center freelook, yaw only')
    print('OpenTrack input 5252 -> OpenTrack output 127.0.0.1:4242 -> game')
    print('F8 pause/resume; L3 or F9 center while looking forward; Ctrl+C quit.')
    print('Start the headset bridge separately. Keep its console open.')
    print('This improves the game connector; the headset still samples near 7 Hz.')
    path = Path(__file__).resolve().parent / ('Game_Response_Report_' + time.strftime('%Y%m%d_%H%M%S') + '.csv')
    win = WindowsInput()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind(('127.0.0.1', UDP_PORT))
            sock.setblocking(False)
            with path.open('x', newline='', encoding='utf-8') as report:
                print('Report:', path)
                run(sock, win, report)
    except KeyboardInterrupt:
        print('\nStopped.')
    finally:
        win.release()


if __name__ == '__main__':
    main()
