from datetime import datetime
from pathlib import Path

import h5py
import numpy as np
import pytest

from portalite2snirf import read_portalite_csv, write_snirf
from portalite2snirf.cli import main
from portalite2snirf.reader import PortaLiteFormatError

SAMPLE = Path(__file__).parent / "data" / "sample_recording.csv"  # a real recording, subject details removed
pytestmark = pytest.mark.skipif(not SAMPLE.exists(), reason="sample recording not available")


@pytest.fixture(scope="module")
def recording():
    return read_portalite_csv(SAMPLE)


@pytest.fixture(scope="module")
def snirf_file(recording, tmp_path_factory):
    return write_snirf(recording, tmp_path_factory.mktemp("out") / "sample.snirf")


def two_sensor_csv(tmp_path: Path) -> Path:
    """The sample file with its sensor duplicated as a second sensor block and column group.

    Two-sensor exports have not been seen yet; this is the layout the one-sensor file implies.
    """
    lines = SAMPLE.read_text(encoding="utf-8-sig").replace("\r", "\n").split("\n")
    lines = [line for line in lines if line.strip()]
    banner = next(i for i, line in enumerate(lines) if line.startswith(",,,Sensor"))
    sensor = next(i for i, line in enumerate(lines) if line == "Sensor 1")
    block = [line.replace("Right PFC", "Left PFC").replace("9417", "9418") for line in lines[sensor:banner]]
    block[0] = "Sensor 2"
    width = lines[banner + 1].count(",") - 2  # sensor columns excluding Sample,Timestamp,Seconds
    out = lines[:banner] + block
    out.append(lines[banner] + ",Sensor 'Left PFC' (9418)" + "," * (width - 1))
    out.append(lines[banner + 1] + "," + ",".join(lines[banner + 1].split(",")[3:]))
    out += [row + "," + ",".join(row.split(",")[3:]) for row in lines[banner + 2 :]]
    path = tmp_path / "two_sensors.csv"
    path.write_text("\r\r\n".join(out), encoding="utf-8-sig")
    return path


def test_header_and_events(recording):
    assert recording.sample_rate == 50
    assert recording.subject == "anonymous"
    assert recording.controller == "PortaLite MKII 8264"
    assert recording.start == datetime(2026, 9, 18, 15, 35, 29, 634400)
    assert [(e.seconds, e.label, e.description) for e in recording.events] == [
        (18.4758, "A", "relax"),
        (45.5886, "A", ""),
        (68.3981, "3", "stop"),
        (85.4195, "B", ""),
    ]


def test_samples_and_channels(recording):
    assert len(recording.time) == 6776
    assert np.allclose(np.diff(recording.time), 1 / 50)
    (sensor,) = recording.sensors
    assert sensor.label == "Right PFC" and sensor.sys_id == "9417"
    assert {(c.receiver, c.transmitter, c.wavelength) for c in sensor.channels} == {
        (r, t, w) for r in (1, 2) for t in (1, 2, 3) for w in (760, 850)
    }
    assert len(sensor.hb) == 12
    assert sensor.dpfs[:2] == pytest.approx([6.6597446, 5.6478174])
    assert "TSI" in sensor.aux


def test_snirf_stores_intensity_that_reproduces_optical_density(recording, snirf_file):
    sensor = recording.sensors[0]
    with h5py.File(snirf_file) as f:
        data = f["nirs/data1"]
        series = data["dataTimeSeries"][()]
        assert series.shape == (6776, 12)
        assert np.allclose(data["time"][()], recording.time)
        wavelengths = f["nirs/probe/wavelengths"][()]
        for i in range(12):
            ml = data[f"measurementList{i + 1}"]
            assert ml["dataType"][()] == 1
            channel = next(
                c
                for c in sensor.channels
                if c.transmitter == ml["sourceIndex"][()]
                and c.receiver == ml["detectorIndex"][()]
                and c.wavelength == wavelengths[ml["wavelengthIndex"][()] - 1]
            )
            delta_od = -np.log10(series[:, i] / series[0, i])
            assert np.allclose(delta_od, channel.optical_density - channel.optical_density[0])


def test_snirf_geometry_matches_portalite_distances(snirf_file):
    with h5py.File(snirf_file) as f:
        src = f["nirs/probe/sourcePos3D"][()]
        det = f["nirs/probe/detectorPos3D"][()]
    distances = np.linalg.norm(det[:, None, :] - src[None, :, :], axis=2)
    assert distances == pytest.approx(np.array([[29, 35, 41], [7.2, 8.0, 7.2]]), abs=1e-3)


def test_right_pfc_sensor_sits_on_right_forehead(snirf_file):
    with h5py.File(snirf_file) as f:
        probe = f["nirs/probe"]
        labels = [s.decode() for s in probe["landmarkLabels"][()]]
        landmarks = probe["landmarkPos3D"][()]
        optodes = np.r_[probe["sourcePos3D"][()], probe["detectorPos3D"][()]]
        optodes_2d = np.r_[probe["sourcePos2D"][()], probe["detectorPos2D"][()]]
    assert len(labels) == 300 and landmarks.shape == (300, 4)
    assert np.all(optodes[:, 0] > 0)  # right of the midline
    for optode in optodes:  # on the scalp of the forehead, just above the eyebrows
        distances = np.linalg.norm(landmarks[:, :3] - optode, axis=1)
        nearest = labels[np.argmin(distances)]
        assert nearest.startswith(("AF", "Fp")) and distances.min() < 12, nearest
    assert optodes_2d.shape == (5, 2) and np.all(optodes_2d[:, 0] > 0) and np.all(optodes_2d[:, 1] > 0)


def test_sensor_is_worn_level(snirf_file):
    with h5py.File(snirf_file) as f:
        src = f["nirs/probe/sourcePos3D"][()]
        det = f["nirs/probe/detectorPos3D"][()]
        placement = f["nirs/metaDataTags/ProbePlacement"][()].decode()
    # the long axis (Rx1, Tx1, Tx3) is horizontal, with Rx1 lateral to the transmitter cluster
    assert src[[0, 2], 2] == pytest.approx([det[0, 2]] * 2, abs=0.5)
    assert det[0, 0] > src[:, 0].max()
    assert "centred on AFp4 and level" in placement and "Tx1-3 medial and Rx1 lateral" in placement


def test_snirf_is_valid(snirf_file):
    snirf = pytest.importorskip("snirf")
    result = snirf.validateSnirf(str(snirf_file))
    assert result.is_valid()


def test_mne_hemoglobin_tracks_app_output(recording, snirf_file):
    mne = pytest.importorskip("mne")
    raw = mne.io.read_raw_snirf(snirf_file, preload=True, verbose="error")
    assert sorted(raw.annotations.description) == ["3", "A", "A", "B"]
    hb = mne.preprocessing.nirs.beer_lambert_law(mne.preprocessing.nirs.optical_density(raw), ppf=(6.66, 5.65))
    sensor = recording.sensors[0]
    for name in hb.ch_names:
        pair, kind = name.split()
        src, det = pair.split("_")
        app = sensor.hb[("O2Hb" if kind == "hbo" else "HHb", int(det[1:]), int(src[1:]))]
        ours = hb.get_data(picks=name)[0]
        # MNE and Artinis use different extinction tables, so compare shape rather than scale.
        assert np.corrcoef(ours, app)[0, 1] > (0.999 if kind == "hbo" else 0.98)


def test_two_sensors(tmp_path):
    recording = read_portalite_csv(two_sensor_csv(tmp_path))
    assert [s.label for s in recording.sensors] == ["Right PFC", "Left PFC"]
    right, left = recording.sensors
    assert left.dpfs == right.dpfs
    for a, b in zip(right.channels, left.channels):
        assert np.array_equal(a.optical_density, b.optical_density)
    path = write_snirf(recording, tmp_path / "two.snirf")
    with h5py.File(path) as f:
        assert f["nirs/data1/dataTimeSeries"].shape == (6776, 24)
        assert [s.decode() for s in f["nirs/probe/sourceLabels"][()]] == [
            f"{label} Tx{n}" for label in ("Right PFC", "Left PFC") for n in (1, 2, 3)
        ]
        sources = f["nirs/probe/sourcePos3D"][()]
    right, left = sources[:3], sources[3:]
    assert np.all(right[:, 0] > 0) and np.all(left[:, 0] < 0)
    assert left * [-1, 1, 1] == pytest.approx(right, abs=1.0)  # mirror images


def test_rejects_non_portalite_file(tmp_path):
    bad = tmp_path / "not_portalite.csv"
    bad.write_text("a,b,c\n1,2,3\n")
    with pytest.raises(PortaLiteFormatError):
        read_portalite_csv(bad)


def test_cli_converts_and_reports_failures(tmp_path, capsys):
    bad = tmp_path / "bad.csv"
    bad.write_text("%PDF-1.7\n")
    assert main([str(SAMPLE), str(bad), "-o", str(tmp_path / "out")]) == 1
    assert (tmp_path / "out" / f"{SAMPLE.stem}.snirf").exists()
    output = capsys.readouterr().out
    assert "OK" in output and "ERROR bad.csv" in output


def test_standalone_program_shows_results_in_a_window(tmp_path, monkeypatch, capsys):
    # files dropped onto the packaged program: there is no console, so report in a dialog
    from portalite2snirf import cli

    shown = []
    monkeypatch.setattr(cli.sys, "frozen", True, raising=False)
    monkeypatch.setattr(cli, "_show_results", lambda messages, ok: shown.append((messages, ok)))
    assert main([str(SAMPLE), "-o", str(tmp_path)]) == 0
    assert len(shown) == 1 and shown[0][1] and "OK" in shown[0][0][0]
    # scripts and CI can ask for plain output instead
    assert main([str(SAMPLE), "-o", str(tmp_path), "--no-window"]) == 0
    assert len(shown) == 1 and "OK" in capsys.readouterr().out
