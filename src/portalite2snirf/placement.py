"""Place PortaLite MKII optodes on the forehead of a standard 10-5 head.

The landmarks (RAS, mm) come from the NIRWizard example recordings, so the SNIRF file carries
the same head frame NIRWizard registers to. Each sensor is centred on AFp4 (right) or AFp3 (left),
just above the eyebrows, and worn level: it follows the scalp at that landmark's height rather
than the AFp row, which drops away towards the temples. The optodes are solved onto the
scalp so their straight-line distances equal the sensor's real inter-optode distances, which is
what analysis tools use for the Beer-Lambert law.
"""

from __future__ import annotations

import json
from functools import cache
from importlib import resources

import numpy as np

# Optodes in the sensor's own frame (mm): along the sensor from Rx1, and across it (positive =
# towards the top of the head). Distances: Rx1-Tx1/Tx2/Tx3 = 29/35/41, Rx2-Tx1/Tx2/Tx3 = 7.2/8.0/7.2,
# from the spec sheet and confirmed from the app's own Beer-Lambert pathlengths.
SENSOR_LAYOUT = {
    ("Rx", 1): (0.0, 0.0),
    ("Tx", 1): (29.0, 0.0),
    ("Tx", 2): (34.76875, -4.01671),
    ("Tx", 3): (41.0, 0.0),
    ("Rx", 2): (35.0, 3.97995),
}
DISTANCES = {
    (("Rx", 1), ("Tx", 1)): 29.0,
    (("Rx", 1), ("Tx", 2)): 35.0,
    (("Rx", 1), ("Tx", 3)): 41.0,
    (("Rx", 2), ("Tx", 1)): 7.2,
    (("Rx", 2), ("Tx", 2)): 8.0,
    (("Rx", 2), ("Tx", 3)): 7.2,
}
# Which end of the sensor points towards the midline. The export does not record this. We wear it
# with the transmitter cluster (Tx1-3 around Rx2) medially and the long detector Rx1, at the cable
# end, laterally, as in Artinis' product photos.
RX1_MEDIAL = False

CENTRES = {"right": "AFp4", "left": "AFp3"}


@cache
def landmarks() -> tuple[list[str], np.ndarray]:
    """Landmark labels and an (N, 4) array of x, y, z, index as stored in SNIRF."""
    data = json.loads(resources.files(__package__).joinpath("landmarks_10-5.json").read_text())
    return data["labels"], np.array(data["positions"], dtype=float)


def _point(name: str) -> np.ndarray:
    labels, positions = landmarks()
    return positions[labels.index(name), :3]


@cache
def head_sphere() -> tuple[np.ndarray, float]:
    """Least-squares sphere through all landmarks: (centre, radius)."""
    points = landmarks()[1][:, :3]
    solution = np.linalg.lstsq(np.c_[2 * points, np.ones(len(points))], (points**2).sum(1), rcond=None)[0]
    centre = solution[:3]
    return centre, float(np.sqrt(solution[3] + centre @ centre))


def _scalp_radius(direction: np.ndarray) -> float:
    """Distance from the head centre to the scalp in this direction, interpolated between the
    nearest landmarks."""
    vectors = landmarks()[1][:, :3] - head_sphere()[0]
    radii = np.linalg.norm(vectors, axis=1)
    angles = np.arccos(np.clip((vectors / radii[:, None]) @ direction, -1, 1))
    nearest = np.argsort(angles)[:6]
    if angles[nearest[0]] < 1e-9:
        return float(radii[nearest[0]])
    weights = 1 / angles[nearest] ** 2
    return float(weights @ radii[nearest] / weights.sum())


def _level_row(side: str) -> tuple[np.ndarray, int]:
    """Scalp points at the height of the sensor's centre landmark, every 5 degrees from the
    midline outwards, and the index of the landmark itself among them."""
    centre = head_sphere()[0]
    target = _point(CENTRES[side]) - centre
    sign = 1.0 if side == "right" else -1.0
    through = np.arctan2(sign * target[0], target[1])  # azimuth from the nose, outwards
    azimuths = np.union1d(np.radians(np.arange(0, 91, 5)), [through])
    points = []
    for azimuth in azimuths:
        horizontal = np.array([sign * np.sin(azimuth), np.cos(azimuth), 0.0])
        radius = np.linalg.norm(target)
        for _ in range(20):  # the scalp radius depends on the direction, which depends on it
            point = np.sqrt(radius**2 - target[2] ** 2) * horizontal + [0, 0, target[2]]
            radius = _scalp_radius(point / np.linalg.norm(point))
        points.append(centre + point)
    return np.array(points), int(np.flatnonzero(azimuths == through)[0])


class _Row:
    """A smooth curve through points on the scalp: great-circle steps between them around the
    head centre, with the radius interpolated so it stays on the scalp."""

    def __init__(self, points: np.ndarray):
        self.centre = head_sphere()[0]
        vectors = points - self.centre
        self.radii = np.linalg.norm(vectors, axis=1)
        self.directions = vectors / self.radii[:, None]
        steps = [np.linalg.norm(b - a) for a, b in zip(vectors[:-1], vectors[1:])]
        self.knots = np.concatenate([[0.0], np.cumsum(steps)])

    def at(self, s: float) -> np.ndarray:
        i = int(np.clip(np.searchsorted(self.knots, s) - 1, 0, len(self.knots) - 2))
        f = (s - self.knots[i]) / (self.knots[i + 1] - self.knots[i])
        a, b = self.directions[i], self.directions[i + 1]
        omega = np.arccos(np.clip(a @ b, -1, 1))
        direction = (np.sin((1 - f) * omega) * a + np.sin(f * omega) * b) / np.sin(omega)
        radius = (1 - f) * self.radii[i] + f * self.radii[i + 1]
        return self.centre + radius * direction

    def surface(self, s: float, across: float) -> np.ndarray:
        """Scalp point `across` mm from the row at arc position `s` (positive = upwards)."""
        q = self.at(s)
        tangent = self.at(s + 0.5) - self.at(s - 0.5)
        normal = q - self.centre
        up = np.cross(normal, tangent)
        up /= np.linalg.norm(up)
        if up[2] < 0:
            up = -up
        p = q + across * up
        return self.centre + (p - self.centre) * np.linalg.norm(q - self.centre) / np.linalg.norm(p - self.centre)


def place_sensor(side: str) -> dict[tuple[str, int], np.ndarray]:
    """3D positions (mm) of one sensor's optodes, keyed by ("Rx"|"Tx", number)."""
    points, middle = _level_row(side)
    row = _Row(points)
    span = SENSOR_LAYOUT[("Tx", 3)][0]
    sign = 1.0 if RX1_MEDIAL else -1.0  # rows run from the midline outwards
    start = row.knots[middle] - sign * span / 2

    optodes = list(SENSOR_LAYOUT)
    free = optodes[1:]  # Rx1 is pinned; the others slide along and across the row

    def positions(params: np.ndarray) -> dict:
        out = {optodes[0]: row.surface(start, 0.0)}
        for k, optode in enumerate(free):
            out[optode] = row.surface(start + sign * params[2 * k], params[2 * k + 1])
        return out

    def residual(params: np.ndarray) -> np.ndarray:
        pos = positions(params)
        distances = [np.linalg.norm(pos[a] - pos[b]) - d for (a, b), d in DISTANCES.items()]
        # Tx1 and Tx3 sit on the sensor's long axis
        on_axis = [params[2 * free.index(("Tx", 1)) + 1], params[2 * free.index(("Tx", 3)) + 1]]
        return np.array(distances + on_axis)

    # Gauss-Newton from the flat layout; the forehead is only gently curved so this converges fast.
    params = np.array([v for optode in free for v in SENSOR_LAYOUT[optode]])
    for _ in range(50):
        r = residual(params)
        if np.max(np.abs(r)) < 1e-9:
            break
        jacobian = np.column_stack(
            [(residual(params + h) - r) / 1e-6 for h in np.eye(len(params)) * 1e-6]
        )
        params -= np.linalg.lstsq(jacobian, r, rcond=None)[0]
    else:
        raise RuntimeError(f"could not place the {side} PortaLite sensor on the head")
    return positions(params)


def to_2d(points: np.ndarray) -> np.ndarray:
    """Flatten 3D head positions to a top-down map: azimuthal equidistant projection around Cz,
    nose up, right to the right, with distances from Cz kept in mm along the scalp."""
    centre, radius = head_sphere()
    up = _point("Cz") - centre
    up /= np.linalg.norm(up)
    right = np.array([1.0, 0.0, 0.0]) - up[0] * up
    right /= np.linalg.norm(right)
    front = np.cross(up, right)
    v = np.atleast_2d(points) - centre
    v /= np.linalg.norm(v, axis=1)[:, None]
    theta = np.arccos(np.clip(v @ up, -1, 1))
    azimuth = np.arctan2(v @ front, v @ right)
    return np.column_stack([radius * theta * np.cos(azimuth), radius * theta * np.sin(azimuth)])


def sensor_sides(labels: list[str]) -> list[str]:
    """Head side of each sensor from its label ("Right PFC"), else right first, then left."""
    sides = []
    for k, label in enumerate(labels):
        name = label.lower()
        sides.append("left" if "left" in name else "right" if "right" in name else ("right", "left")[min(k, 1)])
    if len(set(sides)) != len(sides):
        raise ValueError(f"two sensors would be placed on the same side of the forehead: {labels}")
    return sides
