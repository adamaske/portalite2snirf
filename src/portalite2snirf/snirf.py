"""Write a PortaLite recording as a SNIRF 1.1 file.

The raw optical densities A (log10 attenuation) are stored as CW amplitude, I = 10**-A, so
any SNIRF tool that computes optical density as -log(I / I0) gets the same attenuation
changes the Artinis app used.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import h5py
import numpy as np

from .placement import CENTRES, RX1_MEDIAL, SENSOR_LAYOUT, landmarks, place_sensor, sensor_sides, to_2d
from .reader import Recording

CW_AMPLITUDE = 1


def _string(group: h5py.Group, name: str, value: str) -> None:
    group.create_dataset(name, data=value, dtype=h5py.string_dtype("utf-8"))


def _int(group: h5py.Group, name: str, value: int) -> None:
    group.create_dataset(name, data=np.int32(value))


def _strings(group: h5py.Group, name: str, values: list[str]) -> None:
    group.create_dataset(name, data=values, dtype=h5py.string_dtype("utf-8"))


def write_snirf(recording: Recording, path: str | Path) -> Path:
    path = Path(path)

    wavelengths = sorted({ch.wavelength for s in recording.sensors for ch in s.channels})
    sources = sorted({(k, ch.transmitter) for k, s in enumerate(recording.sensors) for ch in s.channels})
    detectors = sorted({(k, ch.receiver) for k, s in enumerate(recording.sensors) for ch in s.channels})
    unknown = [f"{kind}{n}" for kind, optodes in (("Tx", sources), ("Rx", detectors)) for _, n in optodes if (kind, n) not in SENSOR_LAYOUT]
    if unknown:
        raise ValueError(f"No PortaLite optode position for {sorted(set(unknown))}")

    sides = sensor_sides([s.label for s in recording.sensors])
    placed = [place_sensor(side) for side in sides]
    src3d = np.array([placed[k][("Tx", n)] for k, n in sources])
    det3d = np.array([placed[k][("Rx", n)] for k, n in detectors])

    def label(sensor: int, prefix: str, number: int) -> str:
        return f"{recording.sensors[sensor].label} {prefix}{number}" if len(recording.sensors) > 1 else f"{prefix}{number}"

    time = recording.time.astype(float)
    start = recording.start

    with h5py.File(path, "w") as f:
        _string(f, "formatVersion", "1.1")
        nirs = f.create_group("nirs")

        meta = nirs.create_group("metaDataTags")
        _string(meta, "SubjectID", recording.subject or "unknown")
        _string(meta, "MeasurementDate", start.strftime("%Y-%m-%d"))
        _string(meta, "MeasurementTime", start.strftime("%H:%M:%S.%f")[:-3])
        _string(meta, "LengthUnit", "mm")
        _string(meta, "TimeUnit", "s")
        _string(meta, "FrequencyUnit", "Hz")
        _string(meta, "ManufacturerName", "Artinis Medical Systems")
        _string(meta, "Model", recording.controller or "PortaLite MKII")
        _string(meta, "SourceFile", recording.source_file.name)
        _string(meta, "SamplingRate", str(recording.sample_rate))
        for key in ("App Version", "Comments"):
            if recording.header.get(key):
                _string(meta, key.replace(" ", ""), recording.header[key])
        _string(
            meta,
            "PortaLiteSensors",
            json.dumps(
                [
                    {"label": s.label, "sys_id": s.sys_id, "dpfs": s.dpfs, **{k: s.header[k] for k in ("H", "K", "Tissue Type") if k in s.header}}
                    for s in recording.sensors
                ]
            ),
        )
        _string(
            meta,
            "PortaLiteEvents",
            json.dumps([{"seconds": e.seconds, "label": e.label, "description": e.description} for e in recording.events]),
        )

        data = nirs.create_group("data1")
        series = []
        for k, sensor in enumerate(recording.sensors):
            for ch in sorted(sensor.channels, key=lambda c: (c.receiver, c.transmitter, c.wavelength)):
                index = len(series) + 1
                series.append(np.power(10.0, -ch.optical_density))
                ml = data.create_group(f"measurementList{index}")
                _int(ml, "sourceIndex", sources.index((k, ch.transmitter)) + 1)
                _int(ml, "detectorIndex", detectors.index((k, ch.receiver)) + 1)
                _int(ml, "wavelengthIndex", wavelengths.index(ch.wavelength) + 1)
                _int(ml, "dataType", CW_AMPLITUDE)
                _int(ml, "dataTypeIndex", 1)
        data.create_dataset("dataTimeSeries", data=np.column_stack(series))
        data.create_dataset("time", data=time)

        probe = nirs.create_group("probe")
        probe.create_dataset("wavelengths", data=np.array(wavelengths, dtype=float))
        probe.create_dataset("sourcePos2D", data=to_2d(src3d))
        probe.create_dataset("detectorPos2D", data=to_2d(det3d))
        probe.create_dataset("sourcePos3D", data=src3d)
        probe.create_dataset("detectorPos3D", data=det3d)
        _strings(probe, "sourceLabels", [label(k, "Tx", n) for k, n in sources])
        _strings(probe, "detectorLabels", [label(k, "Rx", n) for k, n in detectors])
        landmark_labels, landmark_positions = landmarks()
        probe.create_dataset("landmarkPos3D", data=landmark_positions)
        _strings(probe, "landmarkLabels", landmark_labels)
        medial, lateral = ("Rx1", "Tx1-3") if RX1_MEDIAL else ("Tx1-3", "Rx1")
        _string(meta, "ProbePlacement", "; ".join(
            f"{s.label or f'sensor {k + 1}'}: {side} forehead, centred on {CENTRES[side]} and level at its height, "
            f"{medial} medial and {lateral} lateral (template positions, not digitised)"
            for k, (s, side) in enumerate(zip(recording.sensors, sides))
        ))

        onsets: dict[str, list[float]] = defaultdict(list)
        for event in recording.events:
            onsets[event.label or "event"].append(event.seconds)
        for j, (name, times) in enumerate(onsets.items(), start=1):
            stim = nirs.create_group(f"stim{j}")
            _string(stim, "name", name)
            stim.create_dataset("data", data=np.array([[t, 0.0, 1.0] for t in times], dtype=float))
            _strings(stim, "dataLabels", ["Onset", "Duration", "Amplitude"])

        aux_index = 0
        for sensor in recording.sensors:
            for name, values in sensor.aux.items():
                if not np.any(values):  # sensor without the optional IMU exports zeros
                    continue
                aux_index += 1
                aux = nirs.create_group(f"aux{aux_index}")
                prefix = f"{sensor.label} " if len(recording.sensors) > 1 else ""
                _string(aux, "name", prefix + name)
                aux.create_dataset("dataTimeSeries", data=values.astype(float)[:, None])
                aux.create_dataset("time", data=time)
                if name == "TSI":
                    _string(aux, "dataUnit", "%")

    return path
