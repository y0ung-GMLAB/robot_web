#ifndef CANOPEN_CANOPEN_CONTROLLER_HPP_
#define CANOPEN_CANOPEN_CONTROLLER_HPP_

#include "motor_interface/motor_controller.hpp"
#include "canopen/canopen_master.hpp"

namespace canopen {

enum class SetPointState {
    Idle,
    SendSet,
    WaitAck,
    SendClear,
    WaitAckClear,
};

class CanopenController : public motor_interface::MotorController {
public:
    explicit CanopenController(const motor_interface::slave_config_t& config)
    : motor_interface::MotorController(config)
    , node_id_(config.can_id) {}

    virtual ~CanopenController() = default;

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

    void copyToPdo(uint8_t* pdo, uint8_t offset, const uint8_t* data, uint8_t size);

    void copyFromPdo(const uint8_t* pdo, uint8_t offset, uint8_t* data, uint8_t size);

    CanopenMaster* master_{nullptr};

    canopen_node_data_t* node_{nullptr};

    uint8_t offset_[motor_interface::MAX_INTERFACE_SIZE]{0};

    motor_interface::entry_table_t tx_interfaces_[motor_interface::MAX_INTERFACE_SIZE];

    uint8_t node_id_{0};

    uint8_t rpdo_size_{0};

    uint8_t tpdo_size_{0};

    SetPointState set_point_state_{SetPointState::Idle};

    uint8_t pending_rpdo_[16]{0};

    uint8_t pending_rpdo_size_{0};

    bool has_pending_setpoint_{false};
};

} // namespace canopen
#endif // CANOPEN_CANOPEN_CONTROLLER_HPP_
