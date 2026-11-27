#include <algorithm>
#include <chrono>
#include <memory>
#include <stdexcept>

#include "common_motor_interface/motor_frame.hpp"

#include "motion_control_bridge/motor_manager_node.hpp"

namespace {

// 토픽(motor_command · motor_status)의 위치·속도는 rad · rad/s ·
// motor_manager 와 드라이버·모터 설정 파일은 원본 그대로 deg 라서 여기서만 바꾼다 ·
// robot_web 수정 목록 6-1 (2026-10-06 · 사용자 결정 「노드 경계만」)
constexpr double kPi = 3.14159265358979323846;
constexpr double kDegPerRad = 180.0 / kPi;
constexpr double kRadPerDeg = kPi / 180.0;

// robot_web fix-list 190: EtherCAT 프레임 손실 요약 주기 · 이만큼 연속 손실이면 경고 대신 오류
// (드라이브 SM2 워치독 약 100 ms 의 1/5)
constexpr int kCycleLossReportSec = 10;
constexpr uint64_t kCycleLossSevereNs = 20000000ULL;

}  // namespace

MotorManagerNode::MotorManagerNode(const rclcpp::NodeOptions& options)
    : Node("motor_manager_node", options)
{
    motor_command_subscriber_ = this->create_subscription<MotorStatus>(
        "motion_control/motor_command", rclcpp::QoS(1).best_effort(),
        [this](const MotorStatus::SharedPtr msg) {
            motor_command_callback(msg);
        }
    );

    request_subscriber_ = this->create_subscription<Int8MultiArray>(
        "motion_control/request", rclcpp::QoS(1).best_effort(),
        [this](const Int8MultiArray::SharedPtr msg) {
            request_callback(msg);
        }
    );

    motor_status_publisher_ = this->create_publisher<MotorStatus>(
        "motion_control/motor_status", rclcpp::QoS(1).best_effort()
    );

    motor_status_timer_ = this->create_wall_timer(
        std::chrono::milliseconds(1),
        [this]() {
            timer_callback();
        }
    );

    config_file_ = this->declare_parameter<std::string>("config_file", "");
    if (config_file_.empty()) {
        throw std::runtime_error(
            "Parameter 'config_file' is empty. Use e.g. "
            "`ros2 launch motion_control_bridge motor_manager_node.launch.py`.");
    }

    motor_manager_ = std::make_unique<motor_manager::MotorManager>(config_file_);

    cycle_loss_timer_ = this->create_wall_timer(
        std::chrono::seconds(kCycleLossReportSec),
        [this]() {
            cycle_loss_callback();
        }
    );

    manager_run_thread_ = std::thread([this]() {
        try {
            motor_manager_->run();
        } catch (const std::exception& e) {
            // robot_web fix-list 3-2 (2026-10-06): the control loop is gone, so
            // the node must not keep running with frozen status. Stop spinning;
            // main() exits non-zero and systemd (Restart=on-failure) restarts it.
            RCLCPP_FATAL(get_logger(), "MotorManager::run() failed: %s", e.what());
            run_failed_.store(true, std::memory_order_release);
            rclcpp::shutdown();
        } catch (...) {
            RCLCPP_FATAL(get_logger(), "MotorManager::run() failed: unknown exception");
            run_failed_.store(true, std::memory_order_release);
            rclcpp::shutdown();
        }
    });
}

MotorManagerNode::~MotorManagerNode()
{
    if (motor_manager_) {
        motor_manager_->request_exit();
    }
    if (manager_run_thread_.joinable()) {
        manager_run_thread_.join();
    }
}

void MotorManagerNode::motor_command_callback(const MotorStatus::SharedPtr msg)
{    
    const size_t size = std::min({
        msg->controller_index.size(),
        static_cast<size_t>(motor_interface::MAX_CONTROLLER_SIZE),
    });
    
    motor_interface::motor_frame_t motor_frame[motor_interface::MAX_CONTROLLER_SIZE] = {};

    for (uint8_t i = 0; i < static_cast<uint8_t>(size); i++) {
        const size_t n_if = std::min({
            static_cast<size_t>(msg->number_of_target_interfaces[i]),
            static_cast<size_t>(motor_interface::MAX_INTERFACE_SIZE),
        });
        motor_frame[i].number_of_target_interfaces = static_cast<uint8_t>(n_if);

        for (uint8_t j = 0; j < n_if; j++) {
            motor_frame[i].target_interface_id[j] = msg->target_interface_id[i].data[j];
        }
        motor_frame[i].controller_index = msg->controller_index[i];
        motor_frame[i].controlword = msg->controlword[i];
        //motor_frame[i].statusword = msg->statusword[i];
        //motor_frame[i].errorcode = msg->errorcode[i];
        motor_frame[i].position = msg->position[i] * kDegPerRad;
        motor_frame[i].velocity = msg->velocity[i] * kDegPerRad;
        motor_frame[i].effort = msg->effort[i];
    }

    motor_manager_->write(motor_frame, static_cast<uint8_t>(size));
}

void MotorManagerNode::request_callback(const Int8MultiArray::SharedPtr msg)
{
    const size_t size = std::min({
        msg->data.size(),
        static_cast<size_t>(motor_interface::MAX_CONTROLLER_SIZE),
    });
    motor_manager_->request(msg->data.data(), static_cast<uint8_t>(size));
}

void MotorManagerNode::timer_callback()
{
    const uint8_t n = motor_manager_->number_of_controllers();
    if (n == 0) {
        return;
    }

    motor_interface::motor_frame_t status[motor_interface::MAX_CONTROLLER_SIZE] = {};
    motor_manager_->read(status);

    MotorStatus msg;
    msg.number_of_target_interfaces.resize(n);
    msg.controller_index.resize(n);
    msg.controlword.resize(n);
    msg.statusword.resize(n);
    msg.errorcode.resize(n);
    msg.position.resize(n);
    msg.velocity.resize(n);
    msg.effort.resize(n);
    msg.overload_ratio.resize(n);

    for (uint8_t i = 0; i < n; i++) {
        msg.controller_index[i] = status[i].controller_index;
        msg.controlword[i] = status[i].controlword;
        msg.statusword[i] = status[i].statusword;
        msg.errorcode[i] = status[i].errorcode;
        msg.position[i] = status[i].position * kRadPerDeg;
        msg.velocity[i] = status[i].velocity * kRadPerDeg;
        msg.effort[i] = status[i].effort;
        msg.overload_ratio[i] = status[i].overload_ratio;   // 음수 = 읽지 않음
    }

    motor_status_publisher_->publish(msg);
}

void MotorManagerNode::cycle_loss_callback()
{
    // robot_web fix-list 190 (NY 2026-11-09): the kernel logged "Working counter changed
    // to 0/15" daily but nothing in the application saw it, so nobody knew how long the
    // longest gap was. Summarise every 10 s, only when something was lost.
    const auto stats = motor_manager_->take_cycle_loss_stats();
    if (stats.events == 0) {
        return;
    }
    const double period_ms = static_cast<double>(motor_manager_->period()) / 1e6;
    const uint64_t longest_ns = static_cast<uint64_t>(stats.longest_cycles) * motor_manager_->period();
    if (longest_ns >= kCycleLossSevereNs) {
        RCLCPP_ERROR(get_logger(),
            "[EtherCAT 프레임 손실] 지난 %d s · %u번 · 모두 %u주기 · 가장 긴 연속 %u주기(%.0f ms) · "
            "드라이브 워치독(약 100 ms)에 가까워짐",
            kCycleLossReportSec, stats.events, stats.lost_cycles, stats.longest_cycles,
            stats.longest_cycles * period_ms);
    } else {
        RCLCPP_WARN(get_logger(),
            "[EtherCAT 프레임 손실] 지난 %d s · %u번 · 모두 %u주기 · 가장 긴 연속 %u주기(%.0f ms)",
            kCycleLossReportSec, stats.events, stats.lost_cycles, stats.longest_cycles,
            stats.longest_cycles * period_ms);
    }
}

int main(int argc, char* argv[])
{
    rclcpp::init(argc, argv);
    auto node = std::make_shared<MotorManagerNode>();
    rclcpp::spin(node);
    const bool failed = node->run_failed();
    node.reset();
    rclcpp::shutdown();
    // 70 = EX_SOFTWARE · systemd restarts on non-zero (78 stays reserved for config errors)
    return failed ? 70 : 0;
}
