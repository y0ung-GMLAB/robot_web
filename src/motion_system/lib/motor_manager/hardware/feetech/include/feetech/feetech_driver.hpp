#ifndef FEETECH_FEETECH_DRIVER_HPP_
#define FEETECH_FEETECH_DRIVER_HPP_

#include <string>

#include "dynamixel/dynamixel_driver.hpp"

namespace feetech {

// Feetech STS bus servo · robot_web fix-list 158 (2026-10-21)
// Same parameter yaml and model file layout as the Dynamixel driver · the
// param yaml selects the Feetech packet (`protocol.packet: scs`), the
// sign-magnitude position/speed (`sign_bit: 15`) and the one-turn range
// (`position_raw_min/max`). Torque Enable is written 0/1 only (128 recentres
// the encoder) and there is no reboot (0x06 RESET is a factory reset).
class FeetechDriver : public dynamixel::DynamixelDriver {
public:
    explicit FeetechDriver(const motor_interface::driver_config_t& config);

    void loadParameters(const std::string& param_file) override;
};

} // namespace feetech

#endif // FEETECH_FEETECH_DRIVER_HPP_
