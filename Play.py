"""Owns the bridge it starts; manual-center freelook with L3 or F9."""
import csv
import os
from pathlib import Path
import signal
import socket
import subprocess
import threading
import time

import FH6_Orbit_Response as game

ROOT = Path(__file__).resolve().parent


def open_opentrack():
    result = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq opentrack.exe',
                             '/FO', 'CSV', '/NH'], capture_output=True, text=True)
    if result.returncode != 0:
        print('Could not check OpenTrack. Open it manually if needed.')
        return
    if any(row and row[0].lower() == 'opentrack.exe'
           for row in csv.reader(result.stdout.splitlines())):
        return
    for variable in ('ProgramFiles(x86)', 'ProgramFiles', 'LOCALAPPDATA', 'APPDATA'):
        base = os.environ.get(variable)
        if base:
            path = Path(base) / 'opentrack' / 'opentrack.exe'
            if path.is_file():
                subprocess.Popen([str(path)], cwd=str(path.parent))
                return
    print('OpenTrack was not found in common folders. Please open it manually.')


class Bridge:
    def __init__(self, process):
        self.process = process
        self.started = time.monotonic()
        self.last_pose = None
        self.error = None
        self.thread = threading.Thread(target=self.read, daemon=True)
        self.thread.start()

    def read(self):
        try:
            for line in self.process.stdout:
                line = line.strip()
                fields = line.split(',')
                try:
                    values = list(map(float, fields))
                except ValueError:
                    values = []
                if len(values) == 6:
                    self.last_pose = time.monotonic()
                elif line.startswith(('STOPPED:', 'TIMEOUT', 'Close error:', 'Cleanup error:')):
                    self.error = line
                    print('\n' + line, flush=True)
                elif line.startswith(('Orbit to', 'Report:', 'Host signature:', 'Sending', 'Continuous', 'RECOVERY:')):
                    print('\n' + line, flush=True)
        except Exception as exc:
            self.error = 'Bridge status reader failed: ' + str(exc)

    def fresh(self):
        now = time.monotonic()
        if self.process.poll() is not None:
            raise RuntimeError(self.error or 'Headset bridge ended; see its report.')
        if self.error:
            raise RuntimeError(self.error)
        # Permit initialization, but suppress mouse movement until a real pose.
        if self.last_pose is None:
            if now - self.started > 35:
                raise RuntimeError('Headset initialization timed out.')
            return False
        age = now - self.last_pose
        if age > 5:
            raise RuntimeError('No fresh headset sample for five seconds; stopping.')
        return age < 1.0

    def stop(self):
        if self.process.poll() is None:
            try:
                self.process.send_signal(signal.CTRL_BREAK_EVENT)
                self.process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                if self.process.poll() is None:
                    print('\nBridge did not exit promptly; terminating this session process.')
                    self.process.kill()
                    self.process.wait(timeout=5)
        self.thread.join(timeout=1)


def main():
    if os.name != 'nt':
        raise SystemExit('Run Start_Play.cmd on your Windows gaming PC.')
    print('ORBIT PLAY v0.8 - continuous bridge, header recovery, same v0.7 freelook')
    print('Close old game connectors and bridges, HyperX Orbit, and the phone tracker.')
    print('Keep the headset connected by USB. Look forward when starting.')
    print('OpenTrack: input UDP 5252; output UDP 127.0.0.1:4242.')
    print('Keep your tested mapping/filter settings. Click Start in OpenTrack.')
    print('F8 pause for menus; L3 or F9 center in game; Ctrl+C HERE ends the session.')
    print('PS5 controller: set Steam per-game Left Stick Click to keyboard F9 first.')
    print('First longer test: 10-15 minutes, including pauses and a return to center.')
    input('Press Enter when ready to start... ')

    compiler = Path(os.environ['SystemRoot']) / 'Microsoft.NET/Framework/v4.0.30319/csc.exe'
    if not compiler.is_file():
        raise RuntimeError('Windows C# compiler not found; no software was installed.')
    subprocess.run([str(compiler), '/nologo', '/target:exe', '/platform:x86',
                    '/out:' + str(ROOT / 'OrbitBridge.exe'), str(ROOT / 'OrbitBridge.cs')],
                   cwd=ROOT, check=True)
    subprocess.run([str(ROOT / 'OrbitBridge.exe'), '--self-test'], cwd=ROOT, check=True)
    win = game.WindowsInput()
    bridge = None
    report = ROOT / ('Game_Response_Report_' + time.strftime('%Y%m%d_%H%M%S') + '.csv')
    try:
        # Bind before touching hardware: a running old game connector blocks startup.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind(('127.0.0.1', 4242))
            sock.setblocking(False)
            open_opentrack()
            with report.open('x', newline='', encoding='utf-8') as log:
                process = subprocess.Popen([str(ROOT / 'OrbitBridge.exe')], cwd=ROOT,
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
                bridge = Bridge(process)
                print('Game report:', report)
                game.run(sock, win, log, bridge_fresh=bridge.fresh)
    finally:
        try:
            win.release()
        finally:
            if bridge is not None:
                bridge.stop()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nSession stopped.')
    except Exception as exc:
        print('\nERROR:', exc)
    finally:
        print('Stop tracking in OpenTrack when finished.')
