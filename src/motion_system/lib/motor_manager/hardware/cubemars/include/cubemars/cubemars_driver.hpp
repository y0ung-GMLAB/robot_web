#ifndef CUBEMARS_CUBEMARS_DRIVER_HPP_
#define CUBEMARS_CUBEMARS_DRIVER_HPP_

#include <string>

#include "motor_interface/motor_driver.hpp"
#include "socketcan/socketcan_driver.hpp"

namespace YAML {
class Node;
}

namespace cubemars {

class CubemarsDriver : public motor_interface::MotorDriver, public socketcan::SocketcanDriver {
public:
    explicit CubemarsDriver(const motor_interface::driver_config_t& config);

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

    bool encodeSocketcanEnable(uint8_t node_id, socketcan::socketcan_frame_t& frame) const override;

    bool encodeSocketcanDisable(uint8_t node_id, socketcan::socketcan_frame_t& frame) const override;

    bool encodeSocketcanCommand(
        uint8_t node_id,
        const motor_interface::motor_frame_t& command,
        socketcan::socketcan_frame_t& frame) const override;

    bool acceptsSocketcanStatusFrame(
        uint8_t node_id,
        const socketcan::socketcan_frame_t& frame) const override;

    bool decodeSocketcanStatus(
        uint8_t node_id,
        const socketcan::socketcan_frame_t& frame,
        motor_interface::motor_frame_t& status) const override;

private:
    struct mit_params_t {
        double p_min{-12.5};
        double p_max{12.5};
        double v_min{-22.5};
        double v_max{22.5};
        double t_min{-12.0};
        double t_max{12.0};
        double kp_min{0.0};
        double kp_max{500.0};
        double kd_min{0.0};
        double kd_max{5.0};
        int axis_direction{-1};
    };

    void applyMotorTypeDefaults(const std::string& motor_type);

    void loadInterfaces(const YAML::Node& interfaces);

    bool targetRequested(const motor_interface::motor_frame_t& command, uint8_t id) const;

    bool rxFieldEnabled(uint8_t id) const;

    bool txFieldEnabled(uint8_t id) const;

    int floatToUint(double value, double min, double max, int bits) const;

    double uintToFloat(int value, double min, double max, int bits) const;

    void fillMagicFrame(uint8_t node_id, uint8_t command, socketcan::socketcan_frame_t& frame) const;

    mit_params_t params_{};

    bool rx_fields_[motor_interface::MAX_INTERFACE_SIZE]{};

    bool tx_fields_[motor_interface::MAX_INTERFACE_SIZE]{};

    double default_kp_{0.0};

    double default_kd_{0.0};

    double servo_position_scale_{0.0219726562};

    double servo_velocity_scale_{0.0572957795};

    double servo_current_scale_{0.01};
};

} // namespace cubemars

#endif // CUBEMARS_CUBEMARS_DRIVER_HPP_
