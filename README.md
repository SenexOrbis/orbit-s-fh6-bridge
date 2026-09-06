# Orbit S FH6 Bridge

Use a **HyperX Cloud Orbit S headset** for head-controlled free look in **Forza Horizon 6**, through OpenTrack. Windows only. No phone or webcam required.

**Version 0.8** is the current community baseline. It completed a 72-minute user test without a header mismatch, recovery event, or invalid game packet. This is evidence from one setup, not broad compatibility certification.

The headset bridge reads **yaw, pitch and roll (3DOF rotation)**. The bundled Forza connector uses **yaw only**. It does not provide position tracking or 4DOF/6DOF camera control.

## How it works

The C# bridge uses the separately installed HyperX Orbit DLL to obtain orientation and sends it to OpenTrack. A Python connector translates OpenTrack's output into relative mouse movement and right-button mouse-look while Forza is the foreground window.

| Connection | Destination | Content |
| --- | --- | --- |
| Headset bridge → OpenTrack input | `127.0.0.1:5252` | Yaw, pitch, roll; position fields zero |
| OpenTrack output → game connector | `127.0.0.1:4242` | OpenTrack output pose |
| Game connector → Forza | Windows mouse input | Yaw free look |

No game files are modified, and no game memory is read or written. This is an independent interoperability project, not an official HyperX, OpenTrack, or Forza product. No claim is made about game-policy or anti-cheat approval.

## Requirements

- Windows 10/11 with Python 3. Tested with an existing Python 3.11 setup; no pip packages are required.
- HyperX **Cloud Orbit S**, connected over USB. Other Cloud models have not been tested.
- Official HyperX Orbit software installed separately. Its **Orbit app must be closed** while the bridge runs.
- The exact supported `R2Clib.dll`, SHA-256:
  ```text
  70503bf228905ab6f2df3f8af2e9cfb0aa31e8aed594bb2d4e34147fa86abe8d
  ```
  The bridge expects it under `HyperX\Orbit` in the 32-bit Program Files folder. A different DLL causes a stop; do not remove the check to force compatibility.
- [OpenTrack](https://github.com/opentrack/opentrack). Tested with 2026.1.0.
- Forza Horizon 6 on PC. The tested setup launches through Steam with a PS5 controller.
- Windows' installed C# compiler at `%SystemRoot%\Microsoft.NET\Framework\v4.0.30319\csc.exe`. The launcher checks for it and compiles locally as x86.

Vendor DLLs, drivers, game files and OpenTrack are **not included**.

## Setup

1. Download this repository using **Code → Download ZIP**, then **Extract All** to a folder you can write to. Run from the extracted folder.
2. Install the requirements. Connect the headset over USB, then close HyperX Orbit, previous bridge windows, and phone-tracking software.
3. In OpenTrack select **Input: UDP over network**, port **5252**. Set incoming angle offsets to zero initially.
4. Select **Output: UDP over network**, address **127.0.0.1**, port **4242**. Never send output back to the input port 5252.
5. For the tested baseline use **Accela**, with **rotation smoothing and deadzone sliders at their minimum**. Leave Mirror off. Verify direction in the cockpit; existing mapping and inversion settings can affect sensitivity. No personal OpenTrack profile is bundled.
6. In Forza use **Mouse Free Look ON**, **Drift Camera ON**, and Driver/cockpit view, as in the tested setup. These game settings are not changed by the launcher.
7. Double-click **Start_Play.cmd**, read the prompts, and press Enter while facing forward. It compiles the bridge, runs hardware-free header recovery tests, starts both connectors, and opens OpenTrack if found. **Click Start in OpenTrack yourself.** It uses your existing profile.
8. Enter the parked cockpit, rest your head comfortably, and press **F9** to align the view. Try small left/right head movements before driving.

The bridge runs continuously; there is no one-minute cutoff. At the end, press **Ctrl+C in the launcher**, then stop tracking in OpenTrack. Normal shutdown lets the launcher release mouse-look and close its own bridge process.

## Controls

| Control | Action |
| --- | --- |
| F9 | Center the view using your current comfortable head posture |
| F8 | Pause/resume; use in menus or other camera views |
| Ctrl+C in launcher | End the session |
| PS5 L3 through Steam Input | Optional mapping to F9, described below |

### PS5 controller: L3 recenter

In Steam's **per-game Controller Layout → Edit Layout → Joysticks**, change **Left Stick Click (L3)** to **Keyboard → F9**, using a regular press. Replace its previous click command; leave directional stick movement unchanged. Enable Steam Input for this game if needed. Menu labels may vary with the Steam client.

This is a manual Steam setup, not a binding installed by the script. Do not change the Desktop Layout. L3 replaces its old click action. F9 remains a keyboard backup. See [Valve's keyboard-binding documentation](https://partner.steamgames.com/doc/features/steam_controller/legacy_mode).

## Camera behavior

- Relative free look with no center dead zone or idle return-to-center timer in this connector.
- Roughly 2.54 mouse pixels per degree of OpenTrack yaw, 40 ms smoothing time constant, and maximum commanded travel of ±50 pixels. This is **not** a calibrated game-camera angle.
- At the command limit, additional outward movement is discarded. Reversing responds immediately; returning to the old physical neutral after overtravel may not center the camera. Recenter manually with F9/L3.
- Mouse-look stays engaged through center and while holding a view. Explicit recenter briefly releases it for 0.2 seconds. Pause, focus loss, tracking loss and exit also release it.
- Active in **all Forza camera views**: the connector detects the foreground title, not the selected camera. It does not detect menus automatically. F8 is the manual pause.
- Pitch is disabled in this connector, and roll is not mapped. This is not a claim that every game or mod lacks those axes.

## Limitations and recovery

The measured headset rate is about **7.15–7.17 real poses per second**. OpenTrack may send around 250 packets/sec by repeating poses; that does not increase sensor sampling. Some stepping can remain.

Version 0.8 logs a header mismatch and performs at most four read-only rechecks. Refresh writes resume only after **the original header matches twice consecutively**, followed by the normal idle-flag check. New pointers are never adopted. Persistent mismatch, native read failure, unexpected refresh state or invalid orientation stops the bridge. The successful 72-minute v0.8 test did not exercise an actual recovery event.

The launcher independently monitors bridge sample completion so repeated OpenTrack packets cannot conceal a stopped source. A one-second sample gap suppresses mouse input; five seconds ends the session. A 30-second progress watchdog handles a stalled native bridge. See [technical notes](docs/TECHNICAL.md).

## Reports and feedback

Reports are written beside the scripts for the whole session. They include motion, timing, device metadata and local paths. **Review and redact Windows usernames, paths and other identifying details before attaching a report to a public issue.** Original user test reports are not distributed.

Use **Issues** for bugs and suggestions, or submit a pull request. Start with [CONTRIBUTING.md](CONTRIBUTING.md). Include the version, setup and steps to reproduce. The tested sensitivity and smoothing are intentionally stable; propose optional changes separately.

## Development

```bash
python -m unittest discover -s tests -v
```

These Python tests use synthetic poses and mocked mouse input; they do not open the headset or inject input. On Windows the launcher also runs the actual C# header-recovery self-tests before hardware access. To run them separately after building:

```bat
OrbitBridge.exe --self-test
```

Hardware validation must still be performed on a compatible headset. See [validation history](docs/VALIDATION.md).

## License and credits

[MIT License](LICENSE). The Forza connection approach and portions of the Python implementation derive from **StretchCGB's [FH6-HeadTracking](https://github.com/StretchCGB/FH6-HeadTracking)**. Its original MIT notice is preserved in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

The Orbit interoperability bridge and subsequent tuning were developed iteratively with AI coding assistance and user hardware/gameplay testing. OpenTrack, HyperX software and Forza remain separate projects/products with their own licenses.
