#ifndef ZEROERR_ZEROERR_DRIVER_HPP_
#define ZEROERR_ZEROERR_DRIVER_HPP_

#include <string>

#include "motor_interface/motor_driver.hpp"

namespace zeroerr {

class ZeroerrDriver : public motor_interface::MotorDriver {
public:
    explicit ZeroerrDriver(const motor_interface::driver_config_t& config);

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
};

} // namespace zeroerr

#endif // ZEROERR_ZEROERR_DRIVER_HPP_