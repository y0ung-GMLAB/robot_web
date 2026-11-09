#ifndef MOTOR_INTERFACE_MOTOR_MASTER_HPP_
#define MOTOR_INTERFACE_MOTOR_MASTER_HPP_

#include <cstdint>
#include <string>
#include <time.h>

namespace motor_interface {

inline constexpr uint8_t MAX_MASTER_SIZE = 8;

struct master_config_t {
    uint8_t id;
    uint8_t number_of_slaves;
    unsigned int ethercat_master_index{};
    unsigned int can_interface_index{};
    unsigned int can_bitrate{};
    std::string serial_port{};
    unsigned int serial_baudrate{};
};

class MotorMaster {
public:
    explicit MotorMaster(const master_config_t& config)
    : id_(config.id)
    , number_of_slaves_(config.number_of_slaves) {}

    virtual ~MotorMaster() = default;

    virtual void initialize() = 0;

    virtual void activate() = 0;

    virtual void deactivate() = 0;

    virtual void transmit() = 0;

    virtual void receive() = 0;

    virtual void apply_application_time(const timespec& time) = 0;

    virtual void save_clock() = 0;

    // robot_web fix-list 188: before deactivate, ask the slaves to leave OP while the
    // PDO cycle is still running, so no slave sees the cycle stop while its SM2
    // watchdog is armed. Default: nothing to do (CAN, serial).
    virtual void request_safe_state() {}

    virtual bool safe_state_reached() { return true; }

    uint8_t id() const { return id_; }

    uint8_t number_of_slaves() const { return number_of_slaves_; }

protected:
    const uint8_t id_;

    uint8_t number_of_slaves_;
};

} // namespace motor_interface
#endif // MOTOR_INTERFACE_MOTOR_MASTER_HPP_
