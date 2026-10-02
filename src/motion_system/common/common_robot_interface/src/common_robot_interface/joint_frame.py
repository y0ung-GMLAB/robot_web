from __future__ import annotations

from dataclasses import dataclass
import numpy as np


@dataclass
class joint_frame_t:
    controller_index: np.ndarray
    controlword: np.ndarray
    position: np.ndarray
    velocity: np.ndarray
    effort: np.ndarray
