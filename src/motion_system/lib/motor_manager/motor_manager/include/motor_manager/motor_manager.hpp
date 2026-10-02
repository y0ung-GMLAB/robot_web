#ifndef MOTOR_MANAGER_MOTOR_MANAGER_HPP_
#define MOTOR_MANAGER_MOTOR_MANAGER_HPP_

#include <atomic>
#include <cstdint>
#include <exception>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

#include "motor_interface/motor_master.hpp"
#include "motor_interface/motor_driver.hpp"
#include "motor_interface/motor_controller.hpp"

namespace motor_manager {

inline constexpr uint64_t NSEC_PER_SEC = 1000000000;

enum class CommunicationType {
    Ethercat,
    Canopen,
    Socketcan,
    Serial
};

enum class DriverType {
    Minas,
    Zeroerr,
    Dynamixel,
    Cubemars,
};

inline CommunicationType toCommunicationType(const std::string& type) {
    if (type == "ethercat") return CommunicationType::Ethercat;
    if (type == "canopen") return CommunicationType::Canopen;
    if (type == "socketcan") return CommunicationType::Socketcan;
    if (type == "serial") return CommunicationType::Serial;
    if (type == "dynamixel") return CommunicationType::Serial;
    throw std::runtime_error("Invalid communication type.");
}

inline DriverType toDriverType(const std::string& type) {
    if (type == "minas") return DriverType::Minas;
    if (type == "zeroerr") return DriverType::Zeroerr;
    if (type == "dynamixel") return DriverType::Dynamixel;
    if (type == "cubemars") return DriverType::Cubemars;
    throw std::runtime_error("Invalid driver type.");
}

class MotorManager {
public:
    explicit MotorManager(const std::string& config_file);

    virtual ~MotorManager();

    void run();

    void write(const motor_interface::motor_frame_t* command, const uint8_t size);

    void read(motor_interface::motor_frame_t* status);

    void request_stop();

    void request(const int8_t* actions, uint8_t size);

    void request_exit();

    uint32_t period() const { return period_; }

    uint8_t number_of_controllers() const { return number_of_controllers_; }

    bool is_enabled() const { return is_enabled_.load(std::memory_order_acquire); }

private:
    void loadConfigurations(const std::string& config_file);

    void initialize();

    void start();

    void stop();

    void enableController(uint8_t controller_index);

    void enableControllers(const std::vector<uint8_t>& controller_indices);

    void disableController(uint8_t controller_index);

    void disableControllers(const std::vector<uint8_t>& controller_indices);

    void updateController(uint8_t controller_index);

    void updateControllers(const std::vector<uint8_t>& controller_indices);

    void applyControllerRequests(const std::vector<uint8_t>& controller_indices);

    void refreshEnabled();

    void refreshDisabled();


    // Serial
    void startSerial();

    void stopSerial();

    void serialRun(uint8_t master_id);

    void setSerialException(std::exception_ptr exception);

    void rethrowSerialExceptionIfAny();


    std::unordered_map<uint8_t, std::unique_ptr<motor_interface::MotorMaster>> masters_;

    std::vector<uint8_t> controller_indices_;

    std::unordered_map<uint8_t, std::unique_ptr<motor_interface::MotorDriver>> drivers_;

    std::unique_ptr<motor_interface::MotorController> controllers_[motor_interface::MAX_CONTROLLER_SIZE];

    uint32_t period_{0};

    uint8_t number_of_controllers_{0};

    uint32_t frequency_{0};

    std::atomic<bool> is_disabled_{false};

    std::atomic<bool> controller_enabled_[motor_interface::MAX_CONTROLLER_SIZE]{};

    std::atomic<bool> controller_disabled_[motor_interface::MAX_CONTROLLER_SIZE]{};

    std::atomic<bool> is_enabled_{false};

    std::atomic<bool> controller_enable_requested_[motor_interface::MAX_CONTROLLER_SIZE]{};

    std::atomic<bool> running_{true};

    std::mutex frame_mutex_;

    motor_interface::motor_frame_t command_[motor_interface::MAX_CONTROLLER_SIZE];

    motor_interface::motor_frame_t status_[motor_interface::MAX_CONTROLLER_SIZE];

    uint64_t command_sequence_[motor_interface::MAX_CONTROLLER_SIZE]{};

    uint64_t applied_command_sequence_[motor_interface::MAX_CONTROLLER_SIZE]{};


    // Serial
    std::unordered_map<uint8_t, std::unique_ptr<motor_interface::MotorMaster>> serial_masters_;

    std::unordered_map<uint8_t, std::vector<uint8_t>> serial_controller_indices_;

    std::atomic<bool> serial_running_{false};

    std::mutex serial_exception_mutex_;

    std::exception_ptr serial_exception_{nullptr};

    std::vector<std::thread> serial_threads_;
};

} // namespace motor_manager
#endif // MOTOR_MANAGER_MOTOR_MANAGER_HPP_
