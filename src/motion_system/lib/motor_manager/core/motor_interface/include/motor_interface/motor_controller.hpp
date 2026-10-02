#ifndef MOTOR_INTERFACE_MOTOR_CONTROLLER_HPP_
#define MOTOR_INTERFACE_MOTOR_CONTROLLER_HPP_

#include "common_motor_interface/motor_frame.hpp"
#include "motor_interface/motor_master.hpp"
#include "motor_interface/motor_driver.hpp"

namespace motor_interface {

inline constexpr uint8_t MAX_CONTROLLER_SIZE = 32;

struct slave_config_t {
    uint8_t controller_index;
    uint8_t master_id;
    uint8_t driver_id;
    uint16_t alias{};
    uint16_t position{};
    uint32_t vendor_id{};
    uint32_t product_id{};
    uint8_t can_id{};
    uint8_t bus_id{};
    uint8_t profile_mode{};
};

class MotorController {
public:
    explicit MotorController(const slave_config_t& config)
    : index_(config.controller_index)
    , master_id_(config.master_id)
    , driver_id_(config.driver_id)
    , profile_mode_(config.profile_mode) {}

    virtual ~MotorController() = default;

    virtual void initialize(MotorMaster& master, MotorDriver& driver) = 0;

    virtual bool enable() = 0;

    virtual bool disable() = 0;

    virtual void check(const motor_frame_t& status) = 0;

    virtual void write(const motor_frame_t& command) = 0;

    virtual void read(motor_frame_t& status) = 0;

    uint8_t master_id() const { return master_id_; }

    uint8_t driver_id() const { return driver_id_; }

protected:
    virtual void registerEntries() = 0;

    virtual void writeData(const entry_table_t* rx_interfaces, uint8_t number_of_rx_interfaces) = 0;

    virtual void readData(entry_table_t* tx_interfaces, uint8_t number_of_tx_interfaces) = 0;

    MotorDriver* driver_{nullptr};

    DriverState current_driver_state_{DriverState::Fault};

    const uint8_t index_;

    const uint8_t master_id_;

    const uint8_t driver_id_;

    const uint8_t profile_mode_;
};

} // namespace motor_interface
#endif // MOTOR_INTERFACE_MOTOR_CONTROLLER_HPP_
