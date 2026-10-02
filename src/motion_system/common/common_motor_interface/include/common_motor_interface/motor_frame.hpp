#ifndef COMMON_MOTOR_INTERFACE_MOTOR_FRAME_HPP_
#define COMMON_MOTOR_INTERFACE_MOTOR_FRAME_HPP_

#include <cstdint>

namespace motor_interface {

inline constexpr uint8_t MAX_INTERFACE_SIZE = 16;

struct motor_frame_t {
    uint8_t number_of_target_interfaces{0};
    uint8_t target_interface_id[MAX_INTERFACE_SIZE]{0};

    uint8_t controller_index{};
    uint16_t controlword{};
    uint16_t statusword{};
    uint16_t errorcode{};
    double position{};
    double velocity{};
    double effort{};
};

}  // namespace motor_interface

#endif  // COMMON_MOTOR_INTERFACE_MOTOR_FRAME_HPP_
