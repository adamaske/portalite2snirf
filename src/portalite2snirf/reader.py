"""Parser for CSV exports from the Artinis mobile app (PortaLite MKII).

File layout (one controller, one or more sensors):

    Export for,'<name>'
    <key>,<value>              measurement header (date, sample rate, subject...)
    Events
    No.,Timestamp,Seconds,Label,Description,From Device
    <event rows>
    Controller 1,PortaLite MKII <serial>
    Sensor 1
    <key>,<value>              sensor header (label, DPFs, ...)
    ,,,Sensor '<label>' (<sys-id>),,,...   banner row marking where each sensor's columns start
    Sample,Timestamp,Seconds,<sensor columns>...
    <data rows>

The raw "Rx1-Tx1 (760 nm)" columns are log10 attenuation (optical density), not light
intensity: the app's concentration columns are exactly linear in them.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

RAW_COLUMN = re.compile(r"^Rx(\d+)-Tx(\d+) \((\d+) nm\)$")
HB_COLUMN = re.compile(r"^Δ(O2Hb|HHb) (Long|Short)-(\d)(\d)$")
BANNER = re.compile(r"^Sensor '(.*)' \((\d+)\)$")


@dataclass
class Event:
    number: int
    timestamp: str
    seconds: float
    label: str
    description: str
    from_device: str


@dataclass
class Channel:
    """One raw source-detector-wavelength measurement."""

    receiver: int  # Rx number as printed in the file (1-based)
    transmitter: int  # Tx number as printed in the file (1-based)
    wavelength: int  # nm
    optical_density: np.ndarray


@dataclass
class Sensor:
    label: str
    sys_id: str
    header: dict[str, str | list[str]]
    channels: list[Channel]
    # Concentration changes computed by the app, keyed by (chromophore, receiver, transmitter).
    hb: dict[tuple[str, int, int], np.ndarray]
    # Remaining columns (TSI, IMU ...), keyed by column name.
    aux: dict[str, np.ndarray]

    @property
    def dpfs(self) -> list[float]:
        return [float(v) for v in self.header.get("DPFs", [])]


@dataclass
class Recording:
    header: dict[str, str]
    events: list[Event]
    controller: str
    sensors: list[Sensor]
    time: np.ndarray  # seconds from first sample
    start: datetime  # wall-clock time of the first sample
    source_file: Path = field(default_factory=Path)

    @property
    def sample_rate(self) -> float:
        return float(self.header["Sample rate"])

    @property
    def subject(self) -> str:
        return self.header.get("Subject name", "")


class PortaLiteFormatError(ValueError):
    pass


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1]
    return value


def _rows(text: str) -> list[list[str]]:
    # Exports use "\r\r\n" line endings; normalising every CR/LF to "\n" and dropping empty
    # lines handles that and plain "\n" / "\r\n" files alike.
    lines = [line for line in text.replace("\r", "\n").split("\n") if line.strip()]
    return list(csv.reader(lines))


def _is_separator(row: list[str]) -> bool:
    return len(row) == 1 and set(row[0].strip()) == {"-"}


def read_portalite_csv(path: str | Path) -> Recording:
    path = Path(path)
    rows = _rows(path.read_text(encoding="utf-8-sig"))
    rows = [row for row in rows if not _is_separator(row)]

    header: dict[str, str] = {}
    events: list[Event] = []
    controller = ""
    sensor_headers: list[dict[str, str | list[str]]] = []
    banners: list[tuple[int, str, str]] = []  # (start column, label, sys-id)
    columns: list[str] | None = None
    data_start = None

    section = "header"
    for i, row in enumerate(rows):
        first = row[0].strip()
        if first == "Events" and len(row) == 1:
            section = "events"
        elif first == "No." and section == "events":
            continue
        elif first.startswith("Controller"):
            section = "controller"
            controller = _unquote(row[1]) if len(row) > 1 else ""
        elif re.fullmatch(r"Sensor \d+", first):
            section = "sensor"
            sensor_headers.append({})
        elif first == "" and any(BANNER.match(cell.strip()) for cell in row):
            for col, cell in enumerate(row):
                if m := BANNER.match(cell.strip()):
                    banners.append((col, m.group(1), m.group(2)))
        elif first == "Sample":
            columns = [cell.strip() for cell in row]
            data_start = i + 1
            break
        elif section == "header":
            header[first] = _unquote(",".join(row[1:]))
        elif section == "events":
            number, timestamp, seconds, label, description, *rest = row + [""]
            events.append(
                Event(
                    number=int(number),
                    timestamp=timestamp.strip(),
                    seconds=float(seconds),
                    label=_unquote(label),
                    description=_unquote(description),
                    from_device=_unquote(rest[0]) if rest else "",
                )
            )
        elif section == "sensor":
            values = [_unquote(v) for v in row[1:]]
            sensor_headers[-1][first] = values if len(values) > 1 else (values[0] if values else "")

    if columns is None or data_start is None:
        raise PortaLiteFormatError(f"{path.name}: no 'Sample,...' data header found - is this a PortaLite CSV export?")
    if not banners:
        raise PortaLiteFormatError(f"{path.name}: no sensor banner row (,,,Sensor '...') found above the data header")
    if "Sample rate" not in header:
        raise PortaLiteFormatError(f"{path.name}: 'Sample rate' missing from the file header")

    data_rows = [row for row in rows[data_start:] if row[0].strip().isdigit()]
    if not data_rows:
        raise PortaLiteFormatError(f"{path.name}: the file contains no samples")
    bad = [row[0] for row in data_rows if len(row) != len(columns)]
    if bad:
        raise PortaLiteFormatError(
            f"{path.name}: {len(bad)} data rows do not have {len(columns)} columns (first bad sample: {bad[0]})"
        )

    timestamps = [row[1].strip() for row in data_rows]
    numeric = np.array(
        [[float(v) for j, v in enumerate(row) if j != 1] for row in data_rows],
        dtype=float,
    )
    sensors = []
    bounds = [b[0] for b in banners] + [len(columns)]
    for k, (start, label, sys_id) in enumerate(banners):
        channels, hb, aux = [], {}, {}
        for col in range(start, bounds[k + 1]):
            name = columns[col]
            values = numeric[:, col - 1]  # numeric has the Timestamp column (index 1) removed
            if m := RAW_COLUMN.match(name):
                channels.append(Channel(int(m.group(1)), int(m.group(2)), int(m.group(3)), values))
            elif m := HB_COLUMN.match(name):
                chromophore, kind, _, second = m.groups()
                # "Long-12" is receiver 1 with transmitter 1 (wavelength columns 1 and 2),
                # "Short-34" receiver 2 with transmitter 2, etc. Each concentration pair is an
                # exact linear function of that channel's raw columns.
                receiver = 1 if kind == "Long" else 2
                hb[(chromophore, receiver, int(second) // 2)] = values
            else:
                aux[name] = values
        sensor_header = sensor_headers[k] if k < len(sensor_headers) else {}
        sensors.append(Sensor(label, sys_id, sensor_header, channels, hb, aux))

    time = numeric[:, 1]
    start = datetime.fromisoformat(timestamps[0])
    return Recording(header, events, controller, sensors, time, start, path)
