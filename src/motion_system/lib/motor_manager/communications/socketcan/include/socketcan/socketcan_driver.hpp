#ifndef SOCKETCAN_SOCKETCAN_DRIVER_HPP_
#define SOCKETCAN_SOCKETCAN_DRIVER_HPP_

#include <cstdint>

#include "common_motor_interface/motor_frame.hpp"

namespace socketcan {

inline constexpr uint8_t MAX_SOCKETCAN_DATA_SIZE = 8;

struct socketcan_frame_t {
    uint32_t can_id{0};
    uint8_t can_dlc{0};
    uint8_t data[MAX_SOCKETCAN_DATA_SIZE]{};
};

class SocketcanDriver {
public:
    virtual ~SocketcanDriver() = default;

    virtual bool encodeSocketcanEnable(uint8_t can_id, socketcan_frame_t& frame) const = 0;

    virtual bool encodeSocketcanDisable(uint8_t can_id, socketcan_frame_t& frame) const = 0;

    virtual bool encodeSocketcanCommand(
        uint8_t can_id,
        const motor_interface::motor_frame_t& command,
        socketcan_frame_t& frame) const = 0;

    virtual bool acceptsSocketcanStatusFrame(
        uint8_t can_id,
        const socketcan_frame_t& frame) const = 0;

    virtual bool decodeSocketcanStatus(
        uint8_t can_id,
        const socketcan_frame_t& frame,
        motor_interface::motor_frame_t& status) const = 0;
};

} // namespace socketcan

#endif // SOCKETCAN_SOCKETCAN_DRIVER_HPP_
