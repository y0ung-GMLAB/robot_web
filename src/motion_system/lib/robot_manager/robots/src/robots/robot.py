import copy

from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from typing import List, Optional

import numpy as np

from common_robot_interface.joint_frame import joint_frame_t
from common_robot_interface.state_frame import State, state_frame_t
from common_robot_interface.action_frame import Action, action_frame_t


class Scheduler(ABC):
    def __init__(self, robot_index: int, dt: float):
        self.robot_index = robot_index
        self.dt = dt
        self.current_state = state_frame_t(robot_index=robot_index, state=State.STOPPED)

        self.duration = 0.0
        self.time = 0.0

    def get_state_frame(self) -> state_frame_t:
        return self.current_state

    def progress(self, t: float) -> float:
        if self.duration <= 0.0:
            return 1.0
        return float(np.clip(t / self.duration, 0.0, 1.0))

    def step(self):
        self.time += self.dt

    def reset(self, duration: float):
        self.duration = duration
        self.time = 0.0

    @abstractmethod
    def tick(self, action_frame: action_frame_t, duration: float) -> bool:
        pass


class Planner(ABC):
    def __init__(self):
        self.initial_state: Optional[np.ndarray] = None
        self.goal_state: Optional[np.ndarray] = None

    def set_initial_state(self, initial_state: np.ndarray):
        self.initial_state = np.asarray(initial_state).reshape(-1)

    def update_goal_state(self, goal_state: np.ndarray):
        self.goal_state = np.asarray(goal_state).reshape(-1)

    @abstractmethod
    def eval(self, progress: float, duration: float, action: Action) -> np.ndarray:
        pass

class Controller(ABC):
    def __init__(self, robot_index: int):
        self.robot_index = robot_index


@dataclass
class robot_config_t:
    index: int = 0
    name: str = ''
    controller_indices: List[int] = field(default_factory=list)
    target_interface_ids: List[List[int]] = field(default_factory=list)
    home_positions: List[float] = field(default_factory=list)
    home_duration: float = 0.0
    move_duration: float = 0.0
    init_controlword: int = 0
    motion_data_file_path: str = ''

class Robot(ABC):
    def __init__(self, config: robot_config_t, dt: float):
        self.config = config
        self.index = config.index
        self.name = config.name
        self._controller_indices = np.array(config.controller_indices)
        self._target_interface_ids = config.target_interface_ids
        self.home_positions = np.array(config.home_positions)
        self.home_duration = config.home_duration
        self.move_duration = config.move_duration
        self.init_controlword = config.init_controlword
        self.motion_data_file_path = config.motion_data_file_path

        self.number_of_controllers = len(self._controller_indices)

        self.motion_data = np.loadtxt(self.motion_data_file_path, delimiter=',').reshape(self.number_of_controllers, -1)
        self.motion_data = self.motion_data[self._controller_indices]

        self.init_joint_status: Optional[joint_frame_t] = joint_frame_t(
            controller_index=self._controller_indices,
            controlword=np.array([self.init_controlword] * self.number_of_controllers),
            position=np.zeros(self.number_of_controllers),
            velocity=np.zeros(self.number_of_controllers),
            effort=np.zeros(self.number_of_controllers),
        )
        self.curr_joint_status: Optional[joint_frame_t] = None #copy.deepcopy(self.init_joint_status)
        self.stop_joint_status: Optional[joint_frame_t] = None #copy.deepcopy(self.init_joint_status)

    @property
    def controller_indices(self):
        return self._controller_indices

    @property
    def number_of_target_interfaces(self):
        return [len(target_interface_ids) for target_interface_ids in self._target_interface_ids]

    @property
    def target_interface_ids(self):
        return self._target_interface_ids

    def updateJointStatus(self, joint_status: joint_frame_t):
        self.curr_joint_status = joint_status

    @abstractmethod
    def reset_scheduler(self):
        pass

    @abstractmethod
    def get_state_frame(self) -> state_frame_t:
        pass

    @abstractmethod
    def set_action_frame(self, action_frame: action_frame_t) -> joint_frame_t:
        pass
