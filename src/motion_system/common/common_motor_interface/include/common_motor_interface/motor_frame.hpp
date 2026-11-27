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
    // 과부하율 % (모터 정격 대비) · 음수 = 읽지 않음 (PDO 미매핑·미지원 드라이버)
    double overload_ratio{-1.0};
};

}  // namespace motor_interface

#endif  // COMMON_MOTOR_INTERFACE_MOTOR_FRAME_HPP_
