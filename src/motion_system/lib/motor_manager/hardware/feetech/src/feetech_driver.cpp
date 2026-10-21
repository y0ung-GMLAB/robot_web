#include <stdexcept>

#include "feetech/feetech_driver.hpp"

feetech::FeetechDriver::FeetechDriver(const motor_interface::driver_config_t& config)
    : dynamixel::DynamixelDriver(config)
{
}

void feetech::FeetechDriver::loadParameters(const std::string& param_file)
{
    dynamixel::DynamixelDriver::loadParameters(param_file);

    // A Dynamixel file given to a Feetech driver would put Protocol 2.0 on a
    // Feetech bus · refuse it at start
    if (serial_protocol().packet != serial::PacketFormat::Scs) {
        throw std::runtime_error("Feetech parameter file must set protocol.packet: scs.");
    }
    if (serial_protocol().instruction_reboot != 0) {
        throw std::runtime_error("Feetech has no reboot instruction (protocol.reboot must be 0).");
    }
}
