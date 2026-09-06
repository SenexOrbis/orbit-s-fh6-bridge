# Contributing

Bug reports, documentation fixes and pull requests are welcome. This is a small community project tested on one Orbit S setup, so clear evidence is useful.

1. Open an issue describing the problem or proposed change.
2. Keep changes focused. Preserve the accepted v0.8 sensitivity and smoothing defaults unless a change is explicitly discussed; optional settings are preferable for different tastes.
3. Run `python -m unittest discover -s tests -v`. For C# changes, build on Windows and run `OrbitBridge.exe --self-test` without hardware first.
4. Describe what you tested locally, on Windows and on an actual headset. Keep simulations distinct from hardware results.
5. Submit a pull request describing the problem, changed behavior and limitations.

Do not submit proprietary DLLs, firmware, credentials, unredacted session reports or private user paths. Retain upstream attribution and licensing. Contributions are submitted under this repository's MIT license.

Hardware compatibility proposals must document the device/DLL version and observed protocol. Do not remove the DLL hash, pointer validation, write restrictions, timeouts or source-freshness checks just to make another device run. The only intended data write is the already identified meter-refresh request; firmware and settings writes are outside this project's scope.
