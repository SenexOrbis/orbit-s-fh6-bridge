# Validation history

The baseline was developed through iterative tests on one Windows PC with a HyperX Cloud Orbit S, OpenTrack 2026.1.0, and Forza Horizon 6 launched through Steam with a PS5 controller. Results are observations, not a guarantee for other hardware, firmware or game updates.

| Build | Evidence |
| --- | --- |
| Early bridge previews | About 7.15–7.17 fresh orientation samples/sec; yaw/pitch/roll received by OpenTrack |
| v0.5 | Sensitivity and endpoint behavior accepted in gameplay testing |
| v0.6 | Continuous bridge completed approximately 43 minutes with no invalid game packets |
| v0.7 | Manual-center freelook and Steam L3→F9 accepted; a later ~27-minute session stopped on a header mismatch |
| v0.8 | Added bounded read-only header recovery and more precise diagnostics; a subsequent ~72-minute run completed cleanly: 30,915 headset samples, no recovery events and no invalid game packets |

The real recovery path was not exercised in the clean v0.8 run. Startup self-tests cover its decision logic without hardware. The original mismatch's exact cause remains unknown because the older report did not identify the changed field.

Public packaging preserves executable behavior from v0.8. Changes are documentation, attribution, tests, ignored generated files and a corrected source comment about validation status. No personal session logs are included.

Automated Python tests use synthetic data and mocked input. They cannot prove Windows input delivery, Steam binding behavior, headset safety across versions, or game-camera accuracy.
