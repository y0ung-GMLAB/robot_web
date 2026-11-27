from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class State(Enum):
    HOMING = 0
    STOPPED = 1
    OPERATING = 2
    INVALID = 3


@dataclass
class state_frame_t:
    robot_index: int
    state: State
    progress: float = 0.0