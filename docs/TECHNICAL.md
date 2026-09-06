# Technical notes

## Files

| File | Responsibility |
| --- | --- |
| `Start_Play.cmd` | Find Python, invoke the supervisor, keep errors visible |
| `Play.py` | Compile/self-test C# bridge, start connectors, monitor real sample freshness and clean up its child |
| `OrbitBridge.cs` | Read the supported headset via installed vendor DLL and send poses to OpenTrack |
| `FH6_Orbit_Response.py` | Receive OpenTrack UDP and generate foreground-only yaw mouse-look |

## Supported device interface

The inspected interface uses VID `0951`, PID `1703`, x86 `R2Clib.dll` and its Cdecl initialization, open/close and DSP-register exports. The source checks the installed DLL's exact SHA-256 before loading it. It does not load DLLs from the repository folder.

The host pointer is obtained from `0x18009070`. The expected signature is `0x32444857` (`WHD2`). Meter count, ID-table pointer and value-table pointer are validated. Orientation records 13, 14, 16, 15 become quaternion w,x,y,z, interpreted as signed Q31 and normalized after a bounded norm check.

The only intended data write sets the verified host's meter-refresh flag (word 11) to `1`. The bridge waits for the device to clear it. It never clears the flag itself, retries a failed write, or writes firmware/settings. Register reads themselves use vendor USB commands; this is not passive capture.

Before each refresh, the original host pointer, signature, count and table pointers must match. On mismatch v0.8 logs the differing field and makes at most four read-only rechecks, with 50 ms delays plus USB time. It requires two consecutive complete matches to the original metadata, then still requires an idle refresh flag. New pointers are not adopted. Native read failures are not converted into retries.

## UDP and input

OpenTrack input packets are 48 bytes: six little-endian doubles in x,y,z,yaw,pitch,roll order. Position values are zero, angles are degrees. The game connector accepts finite 48-byte packets, drains queues to the newest valid pose, and computes a time-based smoothing step independently of packet arrival rate.

The supervisor receives bridge progress through stdout. A one-second fresh-sample gap suppresses mouse output; five seconds aborts. UDP packet arrival alone is insufficient because OpenTrack can repeat an old pose. Initialization has a separate allowance. C# has a 30-second progress watchdog, not a session-duration limit.

The game connector uses Windows `SendInput` and a foreground-title check for `Forza Horizon 6`. It has no game state or camera-angle feedback, and it cannot identify cockpit vs external view. Relative mouse limits are estimates; game sensitivity and behavior affect the result. Steam sends F9 for the optional per-game L3 mapping.

## Diagnostics and privacy

Generated reports contain device metadata, motion/timing and local paths, including the Windows user directory in some messages. They are ignored by Git and should be redacted before public sharing. Reports and compiled executables remain local.
