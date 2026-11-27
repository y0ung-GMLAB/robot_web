import copy

import numpy as np

from common_robot_interface.joint_frame import joint_frame_t
from common_robot_interface.state_frame import State, state_frame_t
from common_robot_interface.action_frame import Action, action_frame_t

from robots.robot import Planner, Robot, Scheduler, robot_config_t

transition_table = {
    (State.HOMING, Action.HOME): State.HOMING,
    (State.HOMING, Action.STOP): State.STOPPED,
    (State.STOPPED, Action.HOME): State.HOMING,
    (State.STOPPED, Action.STOP): State.STOPPED,
    (State.STOPPED, Action.MOVE): State.OPERATING,
    (State.OPERATING, Action.STOP): State.STOPPED,
    (State.OPERATING, Action.MOVE): State.OPERATING,
}

class RockingChairScheduler(Scheduler):
    def __init__(self, robot_index: int, dt: float):
        super().__init__(robot_index, dt)

        self.prev_time = 0.0

    def tick(self, action_frame: action_frame_t, duration: float) -> bool:
        current_state = self.get_state_frame()
        next_state = transition_table.get(
            (current_state.state, action_frame.action),
            current_state.state,
        )

        is_event = next_state != current_state.state

        if is_event and action_frame.action == Action.STOP:
            self.prev_time = self.time

        if is_event and action_frame.action == Action.HOME:
            self.prev_time = 0.0

        if action_frame.action == Action.STOP:
            self.duration = 0.0
            self.time = 0.0
            self.current_state = state_frame_t(robot_index=self.robot_index, state=State.STOPPED, progress=0.0)
            return is_event

        if is_event:
            self.duration = duration
            self.time = 0.0

        if is_event and action_frame.action == Action.MOVE and self.prev_time != 0.0:
            self.time = self.prev_time
        
        progress = self.progress(self.time + self.dt)
        if next_state == State.HOMING and progress >= 1.0:
            self.current_state = state_frame_t(robot_index=self.robot_index, state=State.STOPPED, progress=1.0)
        else:
            self.current_state = state_frame_t(robot_index=self.robot_index, state=next_state, progress=progress)
        return is_event

class RockingChairPlanner(Planner):
    def __init__(self, motion_data: np.ndarray):
        super().__init__()
        self.motion_data = np.asarray(motion_data)

    def eval(self, progress: float, duration: float, action: Action) -> np.ndarray:
        progress = float(np.clip(progress, 0.0, 1.0))

        if action == Action.HOME:
            if self.initial_state is None or self.goal_state is None:
                raise RuntimeError("HOME action requires initial_state and goal_state.")

            delta = self.goal_state - self.initial_state

            scale = 10.0 * progress**3 - 15.0 * progress**4 + 6.0 * progress**5
            position = self.initial_state + scale * delta

            return position

        elif action == Action.MOVE:
            sample_count = self.motion_data.shape[1]
            if sample_count == 0:
                raise RuntimeError("MOVE action requires motion_data.")
            if sample_count == 1:
                return self.motion_data[:, 0].copy()

            sample_index = progress * (sample_count - 1)
            lower_index = int(np.floor(sample_index))
            upper_index = min(lower_index + 1, sample_count - 1)
            ratio = sample_index - lower_index
            position = (
                (1.0 - ratio) * self.motion_data[:, lower_index] +
                ratio * self.motion_data[:, upper_index]
            )
            return position

        raise ValueError(f"Unsupported action: {action}.")


class RockingChair(Robot):
    def __init__(self, config: robot_config_t, dt: float):
        super().__init__(config, dt)

        self.number_of_controllers = len(self.controller_indices)

        self.scheduler = RockingChairScheduler(self.index, dt)
        self.planner = RockingChairPlanner(self.motion_data)

    def reset_scheduler(self):
        self.scheduler.reset()

    def get_state_frame(self) -> state_frame_t:
        return self.scheduler.get_state_frame()

    def set_action_frame(self, action_frame: action_frame_t) -> joint_frame_t:
        duration = 0
        if action_frame.action == Action.HOME:
            duration = self.home_duration
        elif action_frame.action == Action.MOVE:
            duration = self.move_duration

        is_event = self.scheduler.tick(action_frame, duration)

        if action_frame.action == Action.STOP:
            if is_event or self.stop_joint_status is None:
                self.stop_joint_status = copy.deepcopy(self.curr_joint_status)
            command = copy.deepcopy(self.stop_joint_status)
            command.controlword = self.init_joint_status.controlword.copy()
            return command

        if is_event:
            if action_frame.action == Action.HOME:
                self.planner.set_initial_state(self.curr_joint_status.position)
                self.planner.update_goal_state(self.home_positions)

        progress = self.scheduler.get_state_frame().progress
        position = self.planner.eval(progress, self.scheduler.duration, action_frame.action)
        command = copy.deepcopy(self.init_joint_status)
        command.position = position

        if action_frame.action == Action.HOME and progress >= 1.0:
            self.stop_joint_status.position = self.home_positions
        elif action_frame.action == Action.MOVE and progress >= 1.0:
            self.stop_joint_status.position = position
            self.scheduler.reset(duration)

        self.scheduler.step()
        return command
