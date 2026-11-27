import numpy as np
import rclpy

from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSReliabilityPolicy, QoSHistoryPolicy, QoSDurabilityPolicy

from sensor_msgs.msg import Joy
from std_msgs.msg import Int8MultiArray
from motion_control_msgs.msg import MotorStatus

from common_robot_interface.joint_frame import joint_frame_t
from common_robot_interface.state_frame import State
from common_robot_interface.action_frame import Action, action_frame_t

from robot_manager.robot_manager import RobotManager

JOY_BUTTON_MAX = 10

JOY_BUTTON_CROSS = 0
JOY_BUTTON_CIRCLE = 1
JOY_BUTTON_TRIANGLE = 2
JOY_BUTTON_SQUARE = 3

JOY_BUTTON_L1 = 4
JOY_BUTTON_R1 = 5


class RobotManagerNode(Node):
    QOS_BEKL1V = QoSProfile(
        reliability=QoSReliabilityPolicy.BEST_EFFORT,
        history=QoSHistoryPolicy.KEEP_LAST,
        depth=1,
        durability=QoSDurabilityPolicy.VOLATILE,
    )

    def __init__(self):
        super().__init__('robot_manager_node')

        self.config_file = (
            self.declare_parameter(
                'config_file',
                'src/ros2/motion_system_ros2/motion_control_robot/config/rocking_chair.yaml',
            )
            .get_parameter_value()
            .string_value
        )
        self.robot_manager = RobotManager(self.config_file)
        self.number_of_robots = self.robot_manager.number_of_robots
        self.dt = self.robot_manager.dt
        self.robot_indices = self.robot_manager.robot_indices()
        if not self.robot_indices:
            raise RuntimeError('Robot configuration requires at least one robot.')
        self.robot_action_indices = {
            robot_index: i
            for i, robot_index in enumerate(self.robot_indices)
        }

        self.request_publisher = self.create_publisher(
            Int8MultiArray,
            'motion_control/request',
            self.QOS_BEKL1V,
        )
        self.motor_status_subscriber = self.create_subscription(
            MotorStatus,
            'motion_control/motor_status',
            self.motor_status_callback,
            self.QOS_BEKL1V,
        )
        self.motor_command_publisher = self.create_publisher(
            MotorStatus,
            'motion_control/motor_command',
            self.QOS_BEKL1V,
        )

        self.joy_subscriber = self.create_subscription(
            Joy,
            'joy',
            self.joy_callback,
            10,
        )
        self.timer = self.create_timer(
            self.dt,
            self.timer_callback,
        )

        self.joy_buttons: list[bool] = [False] * JOY_BUTTON_MAX
        self.joy_buttons_prev: list[bool] = [False] * JOY_BUTTON_MAX
        self.joy_button_action: dict[int, Action] = {
            JOY_BUTTON_TRIANGLE: Action.HOME,
            JOY_BUTTON_CIRCLE: Action.MOVE,
            JOY_BUTTON_SQUARE: Action.STOP,
        }

        self.is_valid_joint_status: bool = False

        self.selected_robot_index: int = self.robot_indices[0]
        self.robot_actions: list[action_frame_t] = [
            action_frame_t(robot_index=robot_index, action=Action.STOP)
            for robot_index in self.robot_indices
        ]

    def motor_status_callback(self, msg: MotorStatus):
        joint_status = joint_frame_t(
            controller_index=np.asarray(msg.controller_index, dtype=np.uint8),
            controlword=np.asarray(msg.controlword, dtype=np.uint16),
            position=np.asarray(msg.position, dtype=np.float64),
            velocity=np.asarray(msg.velocity, dtype=np.float64),
            effort=np.asarray(msg.effort, dtype=np.float64),
        )
        self.robot_manager.updateJointStatus(joint_status)

        statuswords = np.asarray(msg.statusword, dtype=np.uint16)
        if np.all(statuswords != 0):
            self.is_valid_joint_status = True

    def publish_motor_command(self, commands: joint_frame_t):
        msg = MotorStatus()
        msg.number_of_target_interfaces = [
            int(count)
            for count in self.robot_manager.number_of_target_interfaces()
        ]
        msg.target_interface_id = [
            Int8MultiArray(data=[int(interface_id) for interface_id in target_interface_ids])
            for target_interface_ids in self.robot_manager.target_interface_ids()
        ]
        msg.controller_index = [int(index) for index in commands.controller_index]
        msg.controlword = [int(controlword) for controlword in commands.controlword]
        msg.position = [float(position) for position in commands.position]
        msg.velocity = [float(velocity) for velocity in commands.velocity]
        msg.effort = [float(effort) for effort in commands.effort]
        self.motor_command_publisher.publish(msg)

    def joy_callback(self, msg: Joy):
        for btn in range(JOY_BUTTON_MAX):
            self.joy_buttons[btn] = btn < len(msg.buttons) and bool(msg.buttons[btn])

    def selected_robot_action_index(self) -> int:
        return self.robot_action_indices[self.selected_robot_index]

    def timer_callback(self):
        if not self.is_valid_joint_status:
            return

        if self.joy_buttons[JOY_BUTTON_CROSS] and not self.joy_buttons_prev[JOY_BUTTON_CROSS]:
            controller_indices = self.robot_manager.controller_indices()
            if controller_indices:
                request = Int8MultiArray()
                request.data = [2] * (max(controller_indices) + 1)
                for controller_index in controller_indices:
                    request.data[controller_index] = 0
                self.request_publisher.publish(request)

        # Check if the robot is stopped because of the homing is completed
        state_frames = self.robot_manager.get_state_frames()

        for state_frame in state_frames:
            robot_action_index = self.robot_action_indices[state_frame.robot_index]
            if state_frame.state == State.STOPPED and self.robot_actions[robot_action_index].action != Action.STOP:
                self.robot_actions[robot_action_index].action = Action.STOP

        # Select the robot by the DPAD
        if self.joy_buttons[JOY_BUTTON_L1] and not self.joy_buttons_prev[JOY_BUTTON_L1]:
            selected_action_index = self.selected_robot_action_index()
            selected_action_index = selected_action_index - 1 if selected_action_index > 0 else self.number_of_robots - 1
            self.selected_robot_index = self.robot_indices[selected_action_index]
        elif self.joy_buttons[JOY_BUTTON_R1] and not self.joy_buttons_prev[JOY_BUTTON_R1]:
            selected_action_index = (self.selected_robot_action_index() + 1) % self.number_of_robots
            self.selected_robot_index = self.robot_indices[selected_action_index]

        # Check if action button is pressed
        for btn, action in self.joy_button_action.items():
            if self.joy_buttons[btn] and not self.joy_buttons_prev[btn]:
                self.robot_actions[self.selected_robot_action_index()].action = action
                break

        # Send the action to the robot
        commands: joint_frame_t = self.robot_manager.set_action_frames(self.robot_actions)
        self.publish_motor_command(commands)

        self.joy_buttons_prev = self.joy_buttons.copy()


def main(args=None):
    rclpy.init(args=args)
    node = RobotManagerNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
