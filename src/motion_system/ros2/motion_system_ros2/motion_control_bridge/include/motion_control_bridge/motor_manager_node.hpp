#ifndef MOTOR_MANAGER_NODE_HPP_
#define MOTOR_MANAGER_NODE_HPP_

#include <atomic>
#include <memory>
#include <thread>

#include "rclcpp/rclcpp.hpp"
#include "motion_control_msgs/msg/motor_status.hpp"
#include "std_msgs/msg/int8_multi_array.hpp"

#include "motor_manager/motor_manager.hpp"

class MotorManagerNode : public rclcpp::Node {
public:
    using MotorStatus = motion_control_msgs::msg::MotorStatus;
    using Int8MultiArray = std_msgs::msg::Int8MultiArray;

    explicit MotorManagerNode(const rclcpp::NodeOptions& options = rclcpp::NodeOptions());

    ~MotorManagerNode();

    // robot_web fix-list 3-2: true when MotorManager::run() ended with an
    // exception. main() then exits non-zero so systemd restarts the service.
    bool run_failed() const { return run_failed_.load(std::memory_order_acquire); }

private:
    void motor_command_callback(const MotorStatus::SharedPtr msg);

    void request_callback(const Int8MultiArray::SharedPtr msg);

    void timer_callback();

    rclcpp::Subscription<MotorStatus>::SharedPtr motor_command_subscriber_;

    rclcpp::Subscription<Int8MultiArray>::SharedPtr request_subscriber_;

    rclcpp::Publisher<MotorStatus>::SharedPtr motor_status_publisher_;

    rclcpp::TimerBase::SharedPtr motor_status_timer_;

    std::string config_file_;

    std::unique_ptr<motor_manager::MotorManager> motor_manager_;

    std::thread manager_run_thread_;

    std::atomic<bool> run_failed_{false};
};

#endif // MOTOR_MANAGER_NODE_HPP_
