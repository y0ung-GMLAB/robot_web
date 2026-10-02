#ifndef SERIAL_SERIAL_CONTROLLER_HPP_
#define SERIAL_SERIAL_CONTROLLER_HPP_

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

private:
    void writeData(const motor_interface::entry_table_t* rx_interfaces, uint8_t number_of_rx_interfaces) override;

    void readData(motor_interface::entry_table_t* tx_interfaces, uint8_t number_of_tx_interfaces) override;

    void addSlaveConfigItems();

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
};

} // namespace serial
#endif // SERIAL_SERIAL_CONTROLLER_HPP_
