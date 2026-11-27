#ifndef SOCKETCAN_SOCKETCAN_MASTER_HPP_
#define SOCKETCAN_SOCKETCAN_MASTER_HPP_

#include <functional>

#include "motor_interface/motor_master.hpp"
#include "motor_interface/motor_controller.hpp" // MAX_CONTROLLER_SIZE

#include <linux/can.h>

namespace socketcan {

inline constexpr uint16_t MAX_SOCKETCAN_TX_QUEUE_SIZE = 128;
inline constexpr uint16_t MAX_SOCKETCAN_RX_QUEUE_SIZE = 128;

struct socketcan_node_data_t {
    uint8_t node_id{0};

    bool active{false};
};

class SocketcanMaster : public motor_interface::MotorMaster {
public:
    explicit SocketcanMaster(const motor_interface::master_config_t& config)
    : motor_interface::MotorMaster(config)
    , interface_index_(config.can_interface_index)
    , bitrate_(config.can_bitrate) {}

    virtual ~SocketcanMaster() = default;

    void initialize() override;

    void activate() override;

    void deactivate() override;

    void transmit() override;

    void receive() override;

    void apply_application_time(const timespec& time) override;

    void save_clock() override;

    void registerNode(uint8_t node_id);

    socketcan_node_data_t* node(uint8_t node_id);

    void enqueueFrame(const can_frame& frame);

    bool takeReceivedFrame(
        const std::function<bool(const can_frame&)>& predicate,
        can_frame& frame);

private:
    void sendFrame(const can_frame& frame);

    bool receiveFrame(can_frame& frame);

    void pushRxFrame(const can_frame& frame);

    bool pushTxFrame(const can_frame& frame);

    bool isValidNodeId(uint8_t node_id) const;

    int socket_{-1};

    unsigned int interface_index_{0};

    unsigned int bitrate_{0};

    can_frame tx_queue_[MAX_SOCKETCAN_TX_QUEUE_SIZE]{};

    uint16_t tx_head_{0};

    uint16_t tx_tail_{0};

    uint16_t tx_count_{0};

    can_frame rx_queue_[MAX_SOCKETCAN_RX_QUEUE_SIZE]{};

    uint16_t rx_head_{0};

    uint16_t rx_tail_{0};

    uint16_t rx_count_{0};

    socketcan_node_data_t nodes_[motor_interface::MAX_CONTROLLER_SIZE]{};
};

} // namespace socketcan
#endif // SOCKETCAN_SOCKETCAN_MASTER_HPP_
