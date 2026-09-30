# portalite2snirf

Converts CSV exports from the Artinis mobile app (PortaLite MKII) into `.snirf` files that
open in NIRWizard, MNE-NIRS, Cedalion, Homer3 and other SNIRF tools.

## Use without Python

Download the zip for your computer from the [latest release](https://github.com/adamaske/portalite2snirf/releases/latest)
and unzip it:

- Windows: `PortaLite-to-SNIRF-windows.zip` holds `PortaLite to SNIRF.exe`.
- Mac: `PortaLite-to-SNIRF-macos-apple-silicon.zip` (M1 and newer) or
  `PortaLite-to-SNIRF-macos-intel.zip` holds `PortaLite to SNIRF.app`.

Double-click it and choose one or more PortaLite CSV files, or drop CSV files onto it. Each
`.snirf` file is written next to its CSV, and a window lists what was converted.

The programs are not code-signed, so the first launch needs one extra step:

- Windows: "Windows protected your PC" → More info → Run anyway.
- Mac: the first double-click is refused. Open System Settings → Privacy & Security, click
  Open Anyway next to "PortaLite to SNIRF", and confirm.

## Use from the command line

```
portalite2snirf Measurement_20260918_153745_0.csv            # writes Measurement_..._0.snirf next to it
portalite2snirf *.csv -o converted/                          # several files into one folder
```

Started without files it opens a file picker. Dropping CSV files onto the program converts them.

From source: `uv run portalite2snirf <file.csv>`; tests: `uv run pytest`.

## Building the standalone programs

`.github/workflows/release.yml` builds them on GitHub's Windows and macOS machines. Run it from
the Actions tab to download the programs from the run, or push a version tag to publish them as
a release:

```
git tag v0.1.0 && git push origin v0.1.0
```

Locally, `uv sync --group build && uv run pyinstaller packaging/portalite2snirf.spec` builds for
the system you are on into `dist/`; PyInstaller cannot build for another system. Use a python.org
(or system) Python: uv's own Python builds leave Tcl/Tk out of the bundle, so the program cannot
open its windows.

## What ends up in the SNIRF file

| CSV | SNIRF |
|---|---|
| `Rx*-Tx* (760/850 nm)` columns | `data1`, CW amplitude (dataType 1), stored as I = 10^-A |
| Events (label, seconds) | one `stim` group per label, duration 0 |
| TSI, IMU (IMU only if the sensor has one) | `aux` channels |
| Subject name, first-sample time, app version, DPFs, event descriptions | `metaDataTags` |

The raw columns in the export are log10 attenuation (optical density), not light intensity.
Storing I = 10^-A means a tool that computes ΔOD = -log(I/I0) gets back exactly the attenuation
changes the Artinis app used. Date of birth and gender are not copied.

Probe geometry (mm), per sensor: Rx1-Tx1/Tx2/Tx3 = 29/35/41 (long channels), Rx2-Tx1/Tx2/Tx3 =
7.2/8.0/7.2 (short channels). These distances match the Artinis spec sheet and were confirmed by
back-calculating the pathlengths in the app's own ΔO2Hb/ΔHHb columns.

Optodes are placed on a standard head: the file carries the 300 10-5 landmarks (Nz, LPA, RPA,
Cz, ... in RAS mm) from the NIRWizard example recordings, and each sensor sits just above the
eyebrows, centred on AFp4 ("Right" in the sensor label) or AFp3 ("Left"). It is worn level: the
long axis follows the scalp at the centre landmark's height instead of the AFp row, which drops
towards the temples. The optodes are solved onto the scalp so the straight-line 3D distances are
exactly the ones above. The transmitter cluster sits towards the midline and Rx1 laterally, as
the sensor is worn (`RX1_MEDIAL` in `placement.py`). These are template
positions, not digitised ones. 2D positions are an azimuthal projection around Cz (nose up).

The app's ΔO2Hb/ΔHHb columns are not copied: re-deriving them from the raw data in your
analysis tool gives the same time courses (r > 0.999 for O2Hb in MNE), scaled by ~10% because
Artinis uses a different extinction-coefficient table.

## Limitations

- Only single-sensor exports have been seen. Two-sensor files are parsed on the assumption that
  the second sensor's columns follow the first under their own `,,,Sensor '...'` banner.
- Times are local wall-clock time; the export carries no timezone.

## Licence

MIT, see `LICENSE`.
