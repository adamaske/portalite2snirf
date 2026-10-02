# portalite2snirf

Converts CSV exports from the Artinis PortaLite MKII app to `.snirf`, for NIRWizard, MNE-NIRS,
Homer3 and other SNIRF tools.

## Download

Get the zip for your computer from the [latest release](https://github.com/adamaske/portalite2snirf/releases/latest):

- Windows: `PortaLite-to-SNIRF-windows.zip`
- Mac: `PortaLite-to-SNIRF-macos-apple-silicon.zip` (M1 or newer) or `PortaLite-to-SNIRF-macos-intel.zip`

Unzip it, double-click **PortaLite to SNIRF** and pick your CSV files, or drop them onto it. Each
`.snirf` file is written next to its CSV.

The programs aren't code-signed, so the first launch needs an extra step:

- Windows: More info → Run anyway.
- Mac: try to open it once, then System Settings → Privacy & Security → Open Anyway.

## Command line

```
uv run portalite2snirf recording.csv          # writes recording.snirf next to it
uv run portalite2snirf *.csv -o converted/
```

Tests: `uv run pytest`.

## What's in the file

- The raw 760/850 nm channels as intensity, I = 10^-A. The export stores optical density, so the
  ΔOD your tool computes matches the Artinis app.
- Events as `stim` groups, TSI and IMU as `aux`, subject name and app details in `metaDataTags`.
  Date of birth and gender are left out.
- The app's ΔO2Hb/ΔHHb columns are left out. Recomputing them from the raw data gives the same
  time courses (r > 0.999 in MNE), differing in scale by about 10% because Artinis uses other
  extinction coefficients.

Optode positions come from a template head, not a digitiser. Each sensor sits level just above the
eyebrow, centred on AFp4 (right) or AFp3 (left), with the transmitters towards the midline. The
3D distances are 29/35/41 mm for the long channels and 7.2/8.0/7.2 mm for the short ones.

## Limitations

- Only single-sensor exports have been tested. Two-sensor files are parsed by assumption.
- Times are local; the export has no timezone.

## Building

Push a version tag and GitHub Actions builds the Windows and macOS programs and publishes a
release:

```
git tag v0.2.0 && git push origin v0.2.0
```

To build locally, run `uv sync --group build && uv run pyinstaller packaging/portalite2snirf.spec`
with a python.org Python. uv's own Python leaves Tcl/Tk out, so the program can't open windows.

## Licence

MIT
