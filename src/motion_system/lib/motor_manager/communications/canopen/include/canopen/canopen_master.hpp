#ifndef CANOPEN_CANOPEN_MASTER_HPP_
#define CANOPEN_CANOPEN_MASTER_HPP_

#include <linux/can.h>

#include "motor_interface/motor_master.hpp"
#include "motor_interface/motor_controller.hpp" // MAX_CONTROLLER_SIZE

namespace canopen {

inline constexpr uint16_t COB_NMT        = 0x000;

inline constexpr uint16_t COB_TPDO1_BASE = 0x180;
inline constexpr uint16_t COB_TPDO2_BASE = 0x280;

inline constexpr uint16_t COB_RPDO1_BASE = 0x200;
inline constexpr uint16_t COB_RPDO2_BASE = 0x300;

inline constexpr uint16_t COB_SDO_TX     = 0x580;
inline constexpr uint16_t COB_SDO_RX     = 0x600;
inline constexpr uint16_t COB_HEARTBEAT  = 0x700;

inline constexpr uint8_t NMT_START = 0x01;
inline constexpr uint8_t NMT_STOP  = 0x02;

inline constexpr uint8_t SDO_WRITE_1BYTE = 0x2F;
inline constexpr uint8_t SDO_WRITE_2BYTE = 0x2B;
inline constexpr uint8_t SDO_WRITE_4BYTE = 0x23;

inline constexpr uint8_t SDO_READ_REQ    = 0x40;
inline constexpr uint8_t SDO_WRITE_RES   = 0x60;
inline constexpr uint8_t SDO_ABORT       = 0x80;

struct canopen_node_data_t {
    uint8_t node_id{0};
    
    uint8_t rpdo[16]{0}; // RPDO1 8 bytes, RPDO2 8 bytes
    uint8_t tpdo[16]{0}; // TPDO1 8 bytes, TPDO2 8 bytes
    
    uint8_t rpdo_size{8};
    uint8_t tpdo_size{0};
    
    bool tpdo_updated{false};
    bool rpdo_dirty{false};
};

class CanopenMaster : public motor_interface::MotorMaster {
public:
    explicit CanopenMaster(const motor_interface::master_config_t& config)
    : motor_interface::MotorMaster(config)
    , interface_index_(config.can_interface_index)
    , bitrate_(config.can_bitrate) {}

    virtual ~CanopenMaster() = default;

    void initialize() override;

    void activate() override;

    void deactivate() override;

    void transmit() override;

    void receive() override;

    void apply_application_time(const timespec& time) override;

    void save_clock() override;

    void registerNodes(uint8_t node_id);

    canopen_node_data_t* node(uint8_t node_id);

    bool writeSdo(uint8_t node_id, uint16_t index, uint8_t subindex, const uint8_t* data, uint8_t size);

    bool readSdo(uint8_t node_id, uint16_t index, uint8_t subindex, uint8_t* data, uint8_t size);

private:
    void sendNmt(uint8_t command, uint8_t node_id);

    void sendFrame(const can_frame& frame);

    bool receiveFrame(can_frame& frame);

    void processTpdo(const can_frame& frame);

    void processHeardbeat(const can_frame& frame);

    int socket_{-1};

    unsigned int interface_index_{0};

    unsigned int bitrate_{0};

    canopen_node_data_t nodes_[motor_interface::MAX_CONTROLLER_SIZE]{};
};

} // namespace canopen
#endif // CANOPEN_CANOPEN_MASTER_HPP_