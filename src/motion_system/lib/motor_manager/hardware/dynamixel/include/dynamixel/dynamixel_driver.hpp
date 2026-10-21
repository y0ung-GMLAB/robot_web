#ifndef DYNAMIXEL_DYNAMIXEL_DRIVER_HPP_
#define DYNAMIXEL_DYNAMIXEL_DRIVER_HPP_

#include <array>
#include <string>
#include <unordered_map>

#include "motor_interface/motor_driver.hpp"
#include "serial/serial_driver.hpp"

namespace YAML {
class Node;
} // namespace YAML

namespace dynamixel {

class DynamixelDriver : public motor_interface::MotorDriver, public serial::SerialDriver {
public:
    explicit DynamixelDriver(const motor_interface::driver_config_t& config);

    void loadParameters(const std::string& param_file) override;

    bool isEnabled(const uint8_t* data, motor_interface::DriverState& driver_state, uint8_t* out) override;

    bool isDisabled(const uint8_t* data, motor_interface::DriverState& driver_state, uint8_t* out) override;

    bool isReceived(const uint8_t* data, uint8_t* out) override;

    double position(const int32_t value) override;

    double velocity(const int32_t value) override;

    double effort(const int16_t value) override;

    int32_t position(const double value) override;

    int32_t velocity(const double value) override;

    int16_t effort(const double value) override;

    // Byte order and sign-magnitude fields from the param yaml (Feetech) ·
    // without those keys the layout is the Dynamixel one as before · fix-list 158
    void encode(const motor_interface::entry_table_t& descriptor, int64_t value, uint8_t* out) const override;

    int64_t decodeSigned(const motor_interface::entry_table_t& entry) const override;

    uint64_t decodeUnsigned(const motor_interface::entry_table_t& entry) const override;

private:
    struct model_entry_t {
        uint16_t address{0};
        uint8_t size{0};
    };

    void loadModelFile(const std::string& model_file);

    bool loadEntry(const YAML::Node& node, motor_interface::entry_table_t& entry, bool marker_allowed) const;

    double positionUnit() const;

    uint32_t accelerationRaw(double degree_per_sec2) const;

    motor_interface::entry_table_t nativeOrder(const motor_interface::entry_table_t& entry) const;

    std::unordered_map<std::string, model_entry_t> model_entries_;

    double zero_position_{0.0};

    double min_position_{0.0};

    double max_position_{0.0};

    double min_radian_{0.0};

    double max_radian_{0.0};

    double velocity_unit_{0.0239691227};

    double current_unit_{1.0};

    bool has_position_model_{false};

    // Extended Position(멀티턴) Goal Position 허용 raw · X 시리즈 ±1,048,575(±256 바퀴)
    // param yaml `extended_position_raw_limit` 로 바꾼다 · robot_web 2026-10-04
    int32_t extended_position_raw_limit_{1048575};

    // param yaml `position_raw_min` / `position_raw_max` · Feetech STS 0~4095 (one turn) ·
    // used instead of ±extended_position_raw_limit_ when given · fix-list 158
    bool has_position_raw_range_{false};

    int64_t position_raw_min_{0};

    int64_t position_raw_max_{0};

    // param yaml `acceleration_unit` · deg/s² per raw · 0 = Dynamixel X 214.577 rev/min² as before
    double acceleration_unit_{0.0};

    // param yaml `byte_order: big` (Feetech SCS) · default little
    bool big_endian_{false};

    // interfaces[].sign_bit by interface id · -1 = two's complement
    std::array<int8_t, 256> sign_bits_{};
};

} // namespace dynamixel

#endif // DYNAMIXEL_DYNAMIXEL_DRIVER_HPP_
