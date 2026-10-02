#ifndef DYNAMIXEL_DYNAMIXEL_DRIVER_HPP_
#define DYNAMIXEL_DYNAMIXEL_DRIVER_HPP_

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

private:
    struct model_entry_t {
        uint16_t address{0};
        uint8_t size{0};
    };

    void loadModelFile(const std::string& model_file);

    bool loadEntry(const YAML::Node& node, motor_interface::entry_table_t& entry, bool marker_allowed) const;

    double positionUnit() const;

    std::unordered_map<std::string, model_entry_t> model_entries_;

    double zero_position_{0.0};

    double min_position_{0.0};

    double max_position_{0.0};

    double min_radian_{0.0};

    double max_radian_{0.0};

    double velocity_unit_{0.0239691227};

    double current_unit_{1.0};

    bool has_position_model_{false};
};

} // namespace dynamixel

#endif // DYNAMIXEL_DYNAMIXEL_DRIVER_HPP_
