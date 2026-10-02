import os
import yaml

import numpy as np

from common_robot_interface.joint_frame import joint_frame_t
from common_robot_interface.state_frame import state_frame_t
from common_robot_interface.action_frame import action_frame_t

from robots.rocking_chair import RockingChair
from robots.robot import robot_config_t


robot_classes = {
    'rocking_chair': RockingChair,
}

class RobotManager:
    def __init__(self, config_file: str):
        self.config_file = config_file

        self.loadConfigurations()

    @property
    def number_of_robots(self) -> int:
        return self._number_of_robots

    @property
    def dt(self) -> float:
        return self._dt

    def robot_indices(self) -> list[int]:
        return [robot.index for robot in self.robots]

    def controller_indices(self) -> list[int]:
        return [
            controller_index
            for robot in self.robots
            for controller_index in robot.controller_indices
        ]

    def number_of_target_interfaces(self) -> list[int]:
        return [
            count
            for robot in self.robots
            for count in robot.number_of_target_interfaces
        ]

    def target_interface_ids(self) -> list[list[int]]:
        return [
            target_interface_ids
            for robot in self.robots
            for target_interface_ids in robot.target_interface_ids
        ]

    def loadConfigurations(self):
        with open(self.config_file, 'r') as f:
            self.config = yaml.load(f, Loader=yaml.FullLoader)
            config_dir = os.path.dirname(os.path.abspath(self.config_file))

            self._dt = self.config['dt']

            self.robots = []
            self._number_of_robots = 0

            for robot in self.config['robot']:
                r_cfg = robot_config_t()
                r_cfg.index = robot['index']
                r_cfg.name = robot['name']
                r_cfg.controller_indices = robot['controller_indices']
                r_cfg.home_positions = robot['home_positions']
                r_cfg.home_duration = robot['home_duration']
                r_cfg.move_duration = robot['move_duration']
                r_cfg.init_controlword = robot['init_controlword']

                motion_data_file_path = os.path.join(robot['motion_data_file_path'], f"{robot['name']}.csv")
                if not os.path.isabs(motion_data_file_path):
                    motion_data_file_path = os.path.join(config_dir, motion_data_file_path)
                r_cfg.motion_data_file_path = os.path.normpath(motion_data_file_path)

                for target_interface_ids in robot['target_interface_ids']:
                    r_cfg.target_interface_ids.append(list(target_interface_ids))

                robot_class = robot_classes.get(r_cfg.name)
                if robot_class is None:
                    raise ValueError(f"Unsupported robot: {r_cfg.name}.")

                self.robots.append(robot_class(r_cfg, self._dt))
                self._number_of_robots += 1

    def updateJointStatus(self, joint_status: joint_frame_t):
        for robot in self.robots:
            mask = np.isin(joint_status.controller_index, robot.controller_indices)
            robot_joint_status = joint_frame_t(
                controller_index=joint_status.controller_index[mask],
                controlword=joint_status.controlword[mask],
                position=joint_status.position[mask],
                velocity=joint_status.velocity[mask],
                effort=joint_status.effort[mask],
            )

            robot.updateJointStatus(robot_joint_status)

    def get_state_frames(self) -> list[state_frame_t]:
        state_frames = []

        for robot in self.robots:
            state_frames.append(robot.get_state_frame())

        return state_frames

    def set_action_frames(self, action_frames: list[action_frame_t]) -> joint_frame_t:
        commands = []

        for robot_index, robot in enumerate(self.robots):
            commands.append(robot.set_action_frame(action_frames[robot_index]))

        return joint_frame_t(
            controller_index=np.concatenate([robot.controller_indices for robot in self.robots]),
            controlword=np.concatenate([command.controlword for command in commands]),
            position=np.concatenate([command.position for command in commands]),
            velocity=np.concatenate([command.velocity for command in commands]),
            effort=np.concatenate([command.effort for command in commands]),
        )

    def reset_scheduler(self, robot_index: int):
        for robot in self.robots:
            if robot.index == robot_index:
                robot.reset_scheduler()
                break