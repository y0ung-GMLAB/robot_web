#ifndef SERIAL_SERIAL_CONTROLLER_HPP_
#define SERIAL_SERIAL_CONTROLLER_HPP_

#include <chrono>
#include <string>

#include "motor_interface/motor_controller.hpp"
#include "serial/serial_driver.hpp"
#include "serial/serial_master.hpp"

namespace serial {

class SerialController : public motor_interface::MotorController {
public:
    explicit SerialController(const motor_interface::slave_config_t& config)
    : motor_interface::MotorController(config)
    , bus_id_(config.bus_id) {}

    virtual ~SerialController() = default;

    void initialize(motor_interface::MotorMaster& master, motor_interface::MotorDriver& driver) override;

    void registerEntries() override;

    bool enable() override;

    bool disable() override;

    void check(const motor_interface::motor_frame_t& status) override;

    void write(const motor_interface::motor_frame_t& command) override;

    void read(motor_interface::motor_frame_t& status) override;

    // Boot items not written yet (port closed · device silent · refused) ·
    // torque on and commands wait · errorcode 0xFFFE · robot_web fix-list 158
    bool configPending() const { return config_pending_; }

private:
    void writeData(const motor_interface::entry_table_t* rx_interfaces, uint8_t number_of_rx_interfaces) override;

    void readData(motor_interface::entry_table_t* tx_interfaces, uint8_t number_of_tx_interfaces) override;

    void addSlaveConfigItems();

    bool applyConfigItems(bool allow_torque_off, std::string& error);

    bool writeConfigItem(const motor_interface::entry_table_t& item);

    bool disableTorqueForConfiguration(std::string& error);

    void rebootNode();

    // Alarm reset where the bus has no REBOOT (Feetech) · Torque Enable 0
    void torqueOffForReset();

    // After a reconnect the items are checked again (the device may have lost power)
    void noteReconnect();

    bool retryConfig(bool allow_torque_off);

    void log(const std::string& message) const;

    void addBulkEntries();

    const motor_interface::entry_table_t* rxInterface(uint8_t id) const;

    const motor_interface::entry_table_t* txInterface(uint8_t id) const;

    void fillInterfaceValue(
        const motor_interface::entry_table_t& descriptor,
        int64_t value,
        motor_interface::entry_table_t& out) const;

    uint64_t readUnsignedValue(const motor_interface::entry_table_t& entry) const;

    int64_t readSignedValue(const motor_interface::entry_table_t& entry) const;

    SerialMaster* master_{nullptr};

    serial_node_data_t* node_{nullptr};

    SerialDriver* serial_driver_{nullptr};

    motor_interface::entry_table_t rx_interfaces_[motor_interface::MAX_INTERFACE_SIZE]{};

    motor_interface::entry_table_t tx_interfaces_[motor_interface::MAX_INTERFACE_SIZE]{};

    uint8_t number_of_active_rx_interfaces_{0};

    uint8_t bus_id_{0};

    // Write the items again after a REBOOT (fix-list 24-1)
    bool reapply_items_pending_{false};

    std::chrono::steady_clock::time_point next_reapply_at_{};

    bool config_pending_{false};

    std::string config_error_;

    std::chrono::steady_clock::time_point next_config_retry_{};

    uint32_t master_generation_{0};

    // Last write/command problem logged · the same one is not repeated every cycle
    std::string last_write_error_;
};

} // namespace serial
#endif // SERIAL_SERIAL_CONTROLLER_HPP_
