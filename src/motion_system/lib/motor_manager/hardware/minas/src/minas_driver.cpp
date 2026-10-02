#include <stdexcept>

#include <yaml-cpp/yaml.h>

#include "minas/minas_driver.hpp"

namespace {

constexpr double DEGREE_PER_REVOLUTION = 360.0;

constexpr uint16_t CW_SHUTDOWN = 0x0006;
constexpr uint16_t CW_SWITCH_ON = 0x0007;
constexpr uint16_t CW_ENABLE_OPERATION = 0x000F;
constexpr uint16_t CW_DISABLE_VOLTAGE = 0x0000;
constexpr uint16_t CW_DISABLE_OPERATION = 0x0007;
constexpr uint16_t CW_FAULT_RESET = 0x0080;

bool isFault(uint16_t sw)
{
    return (sw & 0x0008) != 0;
}

bool isReadyToSwitchOn(uint16_t sw)
{
    return (sw & 0x006F) == 0x0021;
}

bool isSwitchedOn(uint16_t sw)
{
    return (sw & 0x006F) == 0x0023;
}

bool isOperationEnabled(uint16_t sw)
{
    return (sw & 0x006F) == 0x0027;
}

bool isSwitchOnDisabled(uint16_t sw)
{
    return (sw & 0x004F) == 0x0040;
}

bool isSetpointAcknowledge(uint16_t sw)
{
    return (sw & 0x1000) != 0;
}

} // namespace

minas::MinasDriver::MinasDriver(const motor_interface::driver_config_t& config)
    : motor_interface::MotorDriver(config)
{
}

void minas::MinasDriver::loadParameters(const std::string& param_file)
{
    YAML::Node root = YAML::LoadFile(param_file);
    if (!root) throw std::runtime_error("Failed to load parameter file.");

    YAML::Node items = root["items"];
    if (!items || !items.IsSequence()) throw std::runtime_error("Invalid items configuration.");

    uint8_t i_idx{0};
    for (const auto& i : items) {
        motor_interface::entry_table_t e_cfg{};
        e_cfg.id = i["id"].as<uint8_t>();
        e_cfg.index = i["index"].as<uint16_t>();
        e_cfg.subindex = i["subindex"].as<uint8_t>();
        e_cfg.type = motor_interface::toDataType(i["type"].as<std::string>());

        if (e_cfg.id == motor_interface::ID_MAX_EFFORT) {
            motor_interface::fill<uint16_t>(
                static_cast<uint16_t>(2.0 / config_.unit_effort * 100.0),
                e_cfg.data
            );
        } else if (e_cfg.id == motor_interface::ID_MIN_POSITION_LIMIT) {
            motor_interface::fill<int32_t>(
                static_cast<int32_t>(config_.lower / DEGREE_PER_REVOLUTION * config_.pulse_per_revolution),
                e_cfg.data
            );
        } else if (e_cfg.id == motor_interface::ID_MAX_POSITION_LIMIT) {
            motor_interface::fill<int32_t>(
                static_cast<int32_t>(config_.upper / DEGREE_PER_REVOLUTION * config_.pulse_per_revolution),
                e_cfg.data
            );
        } else if (e_cfg.id == motor_interface::ID_MAX_MOTOR_SPEED) {
            motor_interface::fill<uint32_t>(
                static_cast<uint32_t>(config_.speed),
                e_cfg.data
            );
        } else if (e_cfg.id == motor_interface::ID_PROFILE_VELOCITY) {
            motor_interface::fill<uint32_t>(
                static_cast<uint32_t>(config_.profile_velocity / DEGREE_PER_REVOLUTION * config_.pulse_per_revolution),
                e_cfg.data
            );
        } else if (e_cfg.id == motor_interface::ID_PROFILE_ACCELERATION) {
            motor_interface::fill<uint32_t>(
                static_cast<uint32_t>(config_.profile_acceleration / DEGREE_PER_REVOLUTION * config_.pulse_per_revolution),
                e_cfg.data
            );
        } else if (e_cfg.id == motor_interface::ID_PROFILE_DECELERATION) {
            motor_interface::fill<uint32_t>(
                static_cast<uint32_t>(config_.profile_deceleration / DEGREE_PER_REVOLUTION * config_.pulse_per_revolution),
                e_cfg.data
            );
        } else if (e_cfg.id == motor_interface::ID_MAX_ACCELERATION) {
            motor_interface::fill<uint32_t>(
                static_cast<uint32_t>(config_.acceleration / DEGREE_PER_REVOLUTION * config_.pulse_per_revolution),
                //uint32_t(5000000),
                e_cfg.data
            );
        } else if (e_cfg.id == motor_interface::ID_MAX_DECELERATION) {
            motor_interface::fill<uint32_t>(
                static_cast<uint32_t>(config_.deceleration / DEGREE_PER_REVOLUTION * config_.pulse_per_revolution),
                e_cfg.data
            );
        } else {
            switch (e_cfg.type) {
            case motor_interface::DataType::U8: {
                motor_interface::fill<uint8_t>(
                    i["value"].as<uint8_t>(),
                    e_cfg.data
                );
                break;
            } case motor_interface::DataType::U16: {
                motor_interface::fill<uint16_t>(
                    i["value"].as<uint16_t>(),
                    e_cfg.data
                );
                break;
            } case motor_interface::DataType::U32: {
                motor_interface::fill<uint32_t>(
                    i["value"].as<uint32_t>(),
                    e_cfg.data
                );
                break;
            } case motor_interface::DataType::U64: {
                motor_interface::fill<uint64_t>(
                    i["value"].as<uint64_t>(),
                    e_cfg.data
                );
                break;
            } case motor_interface::DataType::S8: {
                motor_interface::fill<int8_t>(
                    i["value"].as<int8_t>(),
                    e_cfg.data
                );
                break;
            } case motor_interface::DataType::S16: {
                motor_interface::fill<int16_t>(
                    i["value"].as<int16_t>(),
                    e_cfg.data
                );
                break;
            } case motor_interface::DataType::S32: {
                motor_interface::fill<int32_t>(
                    i["value"].as<int32_t>(),
                    e_cfg.data
                );
                break;
            } default: {
                throw std::runtime_error("Invalid data type.");
            }
            }
        }
        items_[i_idx++] = e_cfg;
    }
    number_of_items_ = i_idx;

    YAML::Node interfaces = root["interfaces"];
    if (!interfaces || !interfaces.IsSequence()) throw std::runtime_error("Invalid interfaces configuration.");

    uint8_t a_idx{0}, r_idx{0}, t_idx{0};
    for (const auto& i : interfaces) {
        motor_interface::entry_table_t e_cfg{};
        e_cfg.id = i["id"].as<uint8_t>();
        e_cfg.index = i["index"].as<uint16_t>();

        if (e_cfg.id != motor_interface::ID_RXPDO && e_cfg.id != motor_interface::ID_TXPDO) {
            e_cfg.subindex = i["subindex"].as<uint8_t>();
            e_cfg.size = i["size"].as<uint8_t>();
            e_cfg.type = motor_interface::toDataType(i["type"].as<std::string>());

            if (e_cfg.id <= motor_interface::ID_TARGET_EFFORT) {
                r_idx++;
            } else {
                t_idx++;
            }
        }
        interfaces_[a_idx++] = e_cfg;
    }
    number_of_interfaces_ = a_idx;
    number_of_rx_interfaces_ = r_idx;
    number_of_tx_interfaces_ = t_idx;
}

bool minas::MinasDriver::isEnabled(const uint8_t* data, motor_interface::DriverState& driver_state, uint8_t* out)
{
    uint16_t sw = motor_interface::value<uint16_t>(data);
    uint16_t cw = CW_ENABLE_OPERATION;

    switch (driver_state) {
    case motor_interface::DriverState::Fault: {
        cw = CW_FAULT_RESET;
        if (isSwitchOnDisabled(sw)) driver_state = motor_interface::DriverState::SwitchOnDisabled;
        break;
    } case motor_interface::DriverState::SwitchOnDisabled: {
        cw = CW_SHUTDOWN;
        if (isReadyToSwitchOn(sw)) driver_state = motor_interface::DriverState::ReadyToSwitchOn;
        break;
    } case motor_interface::DriverState::ReadyToSwitchOn: {
        cw = CW_SWITCH_ON;
        if (isSwitchedOn(sw)) driver_state = motor_interface::DriverState::SwitchedOn;
        break;
    } case motor_interface::DriverState::SwitchedOn: {
        cw = CW_ENABLE_OPERATION;
        if (isOperationEnabled(sw)) driver_state = motor_interface::DriverState::OperationEnabled;
        break;
    } case motor_interface::DriverState::OperationEnabled: {
        return true;
    } default: {
        throw std::runtime_error("Invalid driver state.");
    }
    }

    motor_interface::fill<uint16_t>(cw, out);
    return false;
}

bool minas::MinasDriver::isDisabled(const uint8_t* data, motor_interface::DriverState& driver_state, uint8_t* out)
{
    uint16_t sw = motor_interface::value<uint16_t>(data);
    uint16_t cw = CW_ENABLE_OPERATION;

    /*
    switch (driver_state) {
    case motor_interface::DriverState::SwitchOnDisabled: {
        return true;
    } case motor_interface::DriverState::ReadyToSwitchOn: {
        cw = CW_DISABLE_VOLTAGE;
        if (isSwitchOnDisabled(sw)) driver_state = motor_interface::DriverState::SwitchOnDisabled;
        break;
    } case motor_interface::DriverState::SwitchedOn: {
        cw = CW_SHUTDOWN;
        if (isReadyToSwitchOn(sw)) driver_state = motor_interface::DriverState::ReadyToSwitchOn;
        break;
    } case motor_interface::DriverState::OperationEnabled: {
        cw = CW_DISABLE_OPERATION;
        if (isSwitchedOn(sw)) driver_state = motor_interface::DriverState::SwitchedOn;
        break;
    } default: {
        throw std::runtime_error("Invalid driver state.");
    }
    }
    */

    switch (driver_state) {
    case motor_interface::DriverState::SwitchOnDisabled: {
        return true;
    } default: {
        cw = 0x100;
        if (isSwitchOnDisabled(sw)) driver_state = motor_interface::DriverState::SwitchOnDisabled;
    }
    }

    motor_interface::fill<uint16_t>(cw, out);
    return false;
}

bool minas::MinasDriver::isReceived(const uint8_t* data, uint8_t* out)
{
    uint16_t sw = motor_interface::value<uint16_t>(data);
    if (isSetpointAcknowledge(sw)) {
        motor_interface::fill<uint16_t>(0x0F, out);
        return true;
    }
    return false;
}

double minas::MinasDriver::position(const int32_t value)
{
    return static_cast<double>(value) / static_cast<double>(config_.pulse_per_revolution) * DEGREE_PER_REVOLUTION;
}

double minas::MinasDriver::velocity(const int32_t value)
{
    return static_cast<double>(value) / static_cast<double>(config_.pulse_per_revolution) * DEGREE_PER_REVOLUTION;
}

double minas::MinasDriver::effort(const int16_t value)
{
    return config_.rated_effort * 0.01 * static_cast<double>(value) * config_.unit_effort;
}

int32_t minas::MinasDriver::position(const double value)
{
    return static_cast<int32_t>(value / DEGREE_PER_REVOLUTION * config_.pulse_per_revolution);
}

int32_t minas::MinasDriver::velocity(const double value)
{
    return static_cast<int32_t>(value / DEGREE_PER_REVOLUTION * config_.pulse_per_revolution);
}

int16_t minas::MinasDriver::effort(const double value)
{
    return static_cast<int16_t>(value / config_.rated_effort * 100 / config_.unit_effort);
}
