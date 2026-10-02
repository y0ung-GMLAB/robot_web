#ifndef SOCKETCAN_SOCKETCAN_CONTROLLER_HPP_
#define SOCKETCAN_SOCKETCAN_CONTROLLER_HPP_

#include <chrono>

#include "motor_interface/motor_controller.hpp"
#include "socketcan/socketcan_driver.hpp"
#include "socketcan/socketcan_master.hpp"

namespace socketcan {

class SocketcanController : public motor_interface::MotorController {
public:
    explicit SocketcanController(const motor_interface::slave_config_t& config)
    : motor_interface::MotorController(config)
    , can_id_(config.can_id) {}

    virtual ~SocketcanController() = default;

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

    void sendCommandFrame(const motor_interface::motor_frame_t& command);

    void enqueueDriverFrame(const socketcan_frame_t& frame);

    socketcan_frame_t toDriverFrame(const can_frame& frame) const;

    SocketcanMaster* master_{nullptr};

    socketcan_node_data_t* node_{nullptr};

    SocketcanDriver* socketcan_driver_{nullptr};

    motor_interface::motor_frame_t status_cache_{};

    motor_interface::motor_frame_t last_command_{};

    bool has_last_command_{false};

    std::chrono::steady_clock::time_point next_periodic_send_{};

    uint8_t can_id_{0};
};

} // namespace socketcan
#endif // SOCKETCAN_SOCKETCAN_CONTROLLER_HPP_
