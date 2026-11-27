#ifndef ETHERCAT_ETHERCAT_CONTROLLER_HPP_
#define ETHERCAT_ETHERCAT_CONTROLLER_HPP_

#include "motor_interface/motor_controller.hpp"
#include "ethercat/ethercat_master.hpp"

namespace ethercat {

class EthercatController : public motor_interface::MotorController {
public:
    explicit EthercatController(const motor_interface::slave_config_t& config)
    : motor_interface::MotorController(config)
    , alias_(config.alias)
    , position_(config.position)
    , vendor_id_(config.vendor_id)
    , product_id_(config.product_id) {}

    virtual ~EthercatController() = default;

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

    void addSlaveConfigSdos();

    void addSlaveConfigPdos();

    EthercatMaster* master_{nullptr};

    ec_slave_config_t* slave_config_{nullptr};

    unsigned int offset_[motor_interface::MAX_INTERFACE_SIZE];

    motor_interface::entry_table_t tx_interfaces_[motor_interface::MAX_INTERFACE_SIZE];

    const uint16_t alias_;

    const uint16_t position_;

    const uint32_t vendor_id_;

    const uint32_t product_id_;
};

} // namespace ethercat
#endif // ETHERCAT_ETHERCAT_CONTROLLER_HPP_
