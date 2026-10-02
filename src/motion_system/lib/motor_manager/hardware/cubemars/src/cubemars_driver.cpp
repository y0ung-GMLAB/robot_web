#include <algorithm>
#include <cmath>
#include <cstring>
#include <iterator>
#include <stdexcept>

#include <yaml-cpp/yaml.h>

#include "cubemars/cubemars_driver.hpp"

namespace {

bool isRxField(uint8_t id)
{
    return id == motor_interface::ID_TARGET_POSITION ||
           id == motor_interface::ID_TARGET_VELOCITY ||
           id == motor_interface::ID_TARGET_EFFORT ||
           id == motor_interface::ID_TARGET_KP ||
           id == motor_interface::ID_TARGET_KD;
}

bool isTxField(uint8_t id)
{
    return id == motor_interface::ID_STATUSWORD ||
           id == motor_interface::ID_ERRORCODE ||
           id == motor_interface::ID_CURRENT_POSITION ||
           id == motor_interface::ID_CURRENT_VELOCITY ||
           id == motor_interface::ID_CURRENT_EFFORT ||
           id == motor_interface::ID_CURRENT_TEMPERATURE;
}

uint8_t defaultFieldSize(uint8_t id)
{
    if (id == motor_interface::ID_ERRORCODE ||
        id == motor_interface::ID_CURRENT_TEMPERATURE)
    {
        return 1;
    }

    return 2;
}

motor_interface::DataType defaultFieldType(uint8_t id)
{
    if (id == motor_interface::ID_ERRORCODE ||
        id == motor_interface::ID_CURRENT_TEMPERATURE)
    {
        return motor_interface::DataType::U8;
    }

    return motor_interface::DataType::U16;
}

void setFrameBytes(socketcan::socketcan_frame_t& frame, const uint8_t (&bytes)[8])
{
    frame.can_dlc = 8;
    std::memcpy(frame.data, bytes, sizeof(bytes));
}

constexpr uint32_t CUBEMARS_EXTENDED_STATUS_BASE = 0x2900;
constexpr double DEGREE_SCALE = 57.29577951308232;

constexpr double degrees(double value)
{
    return value * DEGREE_SCALE;
}

bool isExtendedServoStatusFrame(uint8_t node_id, const socketcan::socketcan_frame_t& frame)
{
    return frame.can_dlc >= 8 &&
           frame.can_id == CUBEMARS_EXTENDED_STATUS_BASE + static_cast<uint32_t>(node_id);
}

int16_t readBeI16(uint8_t high, uint8_t low)
{
    return static_cast<int16_t>(
        static_cast<uint16_t>(static_cast<uint16_t>(high) << 8) |
        static_cast<uint16_t>(low));
}

double clampRange(double value, double lower, double upper)
{
    if (upper < lower) std::swap(lower, upper);
    return std::clamp(value, lower, upper);
}

double clampAbs(double value, double limit)
{
    if (limit <= 0.0) return value;
    return std::clamp(value, -limit, limit);
}

} // namespace

cubemars::CubemarsDriver::CubemarsDriver(const motor_interface::driver_config_t& config)
    : motor_interface::MotorDriver(config)
{
}

void cubemars::CubemarsDriver::loadParameters(const std::string& param_file)
{
    YAML::Node root = YAML::LoadFile(param_file);
    if (!root) throw std::runtime_error("Failed to load CubeMars parameter file.");

    applyMotorTypeDefaults(root["motor_type"] ? root["motor_type"].as<std::string>() : "AK80_6_V1p1");

    if (root["p_min"]) params_.p_min = root["p_min"].as<double>();
    if (root["p_max"]) params_.p_max = root["p_max"].as<double>();
    if (root["v_min"]) params_.v_min = root["v_min"].as<double>();
    if (root["v_max"]) params_.v_max = root["v_max"].as<double>();
    if (root["t_min"]) params_.t_min = root["t_min"].as<double>();
    if (root["t_max"]) params_.t_max = root["t_max"].as<double>();
    if (root["kp_min"]) params_.kp_min = root["kp_min"].as<double>();
    if (root["kp_max"]) params_.kp_max = root["kp_max"].as<double>();
    if (root["kd_min"]) params_.kd_min = root["kd_min"].as<double>();
    if (root["kd_max"]) params_.kd_max = root["kd_max"].as<double>();
    if (root["axis_direction"]) params_.axis_direction = root["axis_direction"].as<int>();
    if (root["servo_position_scale"]) servo_position_scale_ = root["servo_position_scale"].as<double>();
    if (root["servo_velocity_scale"]) servo_velocity_scale_ = root["servo_velocity_scale"].as<double>();
    if (root["servo_current_scale"]) servo_current_scale_ = root["servo_current_scale"].as<double>();

    default_kp_ = root["kp"] ? root["kp"].as<double>() :
        (root["default_kp"] ? root["default_kp"].as<double>() : 0.0);
    default_kd_ = root["kd"] ? root["kd"].as<double>() :
        (root["default_kd"] ? root["default_kd"].as<double>() : 0.0);

    YAML::Node items = root["items"];
    if (items && items.IsSequence()) {
        uint8_t i_idx{0};
        for (const auto& i : items) {
            if (i_idx >= motor_interface::MAX_ITEM_SIZE) {
                throw std::runtime_error("Too many CubeMars items.");
            }

            motor_interface::entry_table_t e{};
            e.id = i["id"].as<uint8_t>();
            e.index = i["index"] ? i["index"].as<uint16_t>() : 0;
            e.subindex = i["subindex"] ? i["subindex"].as<uint8_t>() : 0;
            e.size = i["size"] ? i["size"].as<uint8_t>() : defaultFieldSize(e.id);
            e.type = i["type"] ?
                motor_interface::toDataType(i["type"].as<std::string>()) :
                defaultFieldType(e.id);

            items_[i_idx++] = e;
        }
        number_of_items_ = i_idx;
    }

    YAML::Node interfaces = root["interfaces"];
    if (!interfaces || !interfaces.IsSequence()) {
        throw std::runtime_error("Invalid CubeMars interfaces configuration.");
    }

    loadInterfaces(interfaces);
}

bool cubemars::CubemarsDriver::isEnabled(
    const uint8_t* data,
    motor_interface::DriverState& driver_state,
    uint8_t* out)
{
    (void)data;
    (void)out;
    driver_state = motor_interface::DriverState::OperationEnabled;
    return true;
}

bool cubemars::CubemarsDriver::isDisabled(
    const uint8_t* data,
    motor_interface::DriverState& driver_state,
    uint8_t* out)
{
    (void)data;
    (void)out;
    driver_state = motor_interface::DriverState::SwitchOnDisabled;
    return true;
}

bool cubemars::CubemarsDriver::isReceived(const uint8_t* data, uint8_t* out)
{
    (void)data;
    (void)out;
    return false;
}

double cubemars::CubemarsDriver::position(const int32_t value)
{
    return uintToFloat(value, params_.p_min, params_.p_max, 16) *
           static_cast<double>(params_.axis_direction);
}

double cubemars::CubemarsDriver::velocity(const int32_t value)
{
    return uintToFloat(value, params_.v_min, params_.v_max, 12) *
           static_cast<double>(params_.axis_direction);
}

double cubemars::CubemarsDriver::effort(const int16_t value)
{
    return uintToFloat(value, params_.t_min, params_.t_max, 12) *
           static_cast<double>(params_.axis_direction);
}

int32_t cubemars::CubemarsDriver::position(const double value)
{
    return floatToUint(
        value * static_cast<double>(params_.axis_direction),
        params_.p_min,
        params_.p_max,
        16);
}

int32_t cubemars::CubemarsDriver::velocity(const double value)
{
    return floatToUint(
        value * static_cast<double>(params_.axis_direction),
        params_.v_min,
        params_.v_max,
        12);
}

int16_t cubemars::CubemarsDriver::effort(const double value)
{
    return static_cast<int16_t>(floatToUint(
        value * static_cast<double>(params_.axis_direction),
        params_.t_min,
        params_.t_max,
        12));
}

bool cubemars::CubemarsDriver::encodeSocketcanEnable(
    uint8_t node_id,
    socketcan::socketcan_frame_t& frame) const
{
    fillMagicFrame(node_id, 0xFC, frame);
    return true;
}

bool cubemars::CubemarsDriver::encodeSocketcanDisable(
    uint8_t node_id,
    socketcan::socketcan_frame_t& frame) const
{
    fillMagicFrame(node_id, 0xFD, frame);
    return true;
}

bool cubemars::CubemarsDriver::encodeSocketcanCommand(
    uint8_t node_id,
    const motor_interface::motor_frame_t& command,
    socketcan::socketcan_frame_t& frame) const
{
    const bool use_position =
        rxFieldEnabled(motor_interface::ID_TARGET_POSITION) &&
        targetRequested(command, motor_interface::ID_TARGET_POSITION);
    const bool use_velocity =
        rxFieldEnabled(motor_interface::ID_TARGET_VELOCITY) &&
        targetRequested(command, motor_interface::ID_TARGET_VELOCITY);
    const bool use_effort =
        rxFieldEnabled(motor_interface::ID_TARGET_EFFORT) &&
        targetRequested(command, motor_interface::ID_TARGET_EFFORT);

    const double direction = static_cast<double>(params_.axis_direction);
    const double position = use_position ?
        clampRange(command.position, config_.lower, config_.upper) : 0.0;
    const double velocity = use_velocity ? clampAbs(command.velocity, config_.speed) : 0.0;
    const double effort = use_effort ? clampAbs(command.effort, config_.rated_effort) : 0.0;
    const double p_des = position * direction;
    const double v_des = velocity * direction;
    const double tau_ff = effort * direction;
    const double kp = rxFieldEnabled(motor_interface::ID_TARGET_KP) && use_position ?
        default_kp_ : 0.0;
    const double kd = rxFieldEnabled(motor_interface::ID_TARGET_KD) && (use_position || use_velocity) ?
        default_kd_ : 0.0;

    const int p_int = floatToUint(p_des, params_.p_min, params_.p_max, 16);
    const int v_int = floatToUint(v_des, params_.v_min, params_.v_max, 12);
    const int kp_int = floatToUint(kp, params_.kp_min, params_.kp_max, 12);
    const int kd_int = floatToUint(kd, params_.kd_min, params_.kd_max, 12);
    const int t_int = floatToUint(tau_ff, params_.t_min, params_.t_max, 12);

    frame = socketcan::socketcan_frame_t{};
    frame.can_id = node_id;
    frame.can_dlc = 8;
    frame.data[0] = static_cast<uint8_t>(p_int >> 8);
    frame.data[1] = static_cast<uint8_t>(p_int & 0xFF);
    frame.data[2] = static_cast<uint8_t>(v_int >> 4);
    frame.data[3] = static_cast<uint8_t>(((v_int & 0xF) << 4) | (kp_int >> 8));
    frame.data[4] = static_cast<uint8_t>(kp_int & 0xFF);
    frame.data[5] = static_cast<uint8_t>(kd_int >> 4);
    frame.data[6] = static_cast<uint8_t>(((kd_int & 0xF) << 4) | (t_int >> 8));
    frame.data[7] = static_cast<uint8_t>(t_int & 0xFF);

    return true;
}

bool cubemars::CubemarsDriver::acceptsSocketcanStatusFrame(
    uint8_t node_id,
    const socketcan::socketcan_frame_t& frame) const
{
    if (isExtendedServoStatusFrame(node_id, frame)) return true;

    return frame.can_dlc >= 6 && frame.data[0] == node_id;
}

bool cubemars::CubemarsDriver::decodeSocketcanStatus(
    uint8_t node_id,
    const socketcan::socketcan_frame_t& frame,
    motor_interface::motor_frame_t& status) const
{
    if (!acceptsSocketcanStatusFrame(node_id, frame)) return false;

    if (isExtendedServoStatusFrame(node_id, frame)) {
        const int16_t p_int = readBeI16(frame.data[0], frame.data[1]);
        const int16_t v_int = readBeI16(frame.data[2], frame.data[3]);
        const int16_t i_int = readBeI16(frame.data[4], frame.data[5]);
        const double direction = static_cast<double>(params_.axis_direction);

        if (txFieldEnabled(motor_interface::ID_CURRENT_POSITION)) {
            status.position = static_cast<double>(p_int) * servo_position_scale_ * direction;
        }
        if (txFieldEnabled(motor_interface::ID_CURRENT_VELOCITY)) {
            status.velocity = static_cast<double>(v_int) * servo_velocity_scale_ * direction;
        }
        if (txFieldEnabled(motor_interface::ID_CURRENT_EFFORT)) {
            status.effort = static_cast<double>(i_int) * servo_current_scale_ * direction;
        }

        status.statusword = 1;
        status.errorcode = frame.data[7];
        return true;
    }

    const int p_int = (static_cast<int>(frame.data[1]) << 8) |
                      static_cast<int>(frame.data[2]);
    const int v_int = (static_cast<int>(frame.data[3]) << 4) |
                      (static_cast<int>(frame.data[4]) >> 4);
    const int t_int = ((static_cast<int>(frame.data[4]) & 0x0F) << 8) |
                      static_cast<int>(frame.data[5]);

    const double direction = static_cast<double>(params_.axis_direction);
    if (txFieldEnabled(motor_interface::ID_CURRENT_POSITION)) {
        status.position = uintToFloat(p_int, params_.p_min, params_.p_max, 16) * direction;
    }
    if (txFieldEnabled(motor_interface::ID_CURRENT_VELOCITY)) {
        status.velocity = uintToFloat(v_int, params_.v_min, params_.v_max, 12) * direction;
    }
    if (txFieldEnabled(motor_interface::ID_CURRENT_EFFORT)) {
        status.effort = uintToFloat(t_int, params_.t_min, params_.t_max, 12) * direction;
    }

    status.statusword = 1;
    status.errorcode = frame.can_dlc > 7 ? frame.data[7] : 0;
    return true;
}

void cubemars::CubemarsDriver::applyMotorTypeDefaults(const std::string& motor_type)
{
    if (motor_type == "AK80_6_V1") {
        params_ = mit_params_t{
            -degrees(95.5), degrees(95.5),
            -degrees(45.0), degrees(45.0),
            -18.0, 18.0,
            0.0, 500.0, 0.0, 5.0, -1};
    } else if (motor_type == "AK80_6_V1p1") {
        params_ = mit_params_t{
            -degrees(12.5), degrees(12.5),
            -degrees(22.5), degrees(22.5),
            -12.0, 12.0,
            0.0, 500.0, 0.0, 5.0, -1};
    } else if (motor_type == "AK80_6_V2") {
        params_ = mit_params_t{
            -degrees(12.5), degrees(12.5),
            -degrees(38.2), degrees(38.2),
            -12.0, 12.0,
            0.0, 500.0, 0.0, 5.0, 1};
    } else if (motor_type == "AK80_9_V1p1") {
        params_ = mit_params_t{
            -degrees(12.5), degrees(12.5),
            -degrees(22.5), degrees(22.5),
            -18.0, 18.0,
            0.0, 500.0, 0.0, 5.0, 1};
    } else if (motor_type == "AK80_9_V2") {
        params_ = mit_params_t{
            -degrees(12.5), degrees(12.5),
            -degrees(25.64), degrees(25.64),
            -18.0, 18.0,
            0.0, 500.0, 0.0, 5.0, 1};
    } else if (motor_type == "AK70_10_V1p1" || motor_type == "AK70_10V1p1") {
        params_ = mit_params_t{
            -degrees(12.5), degrees(12.5),
            -degrees(50.0), degrees(50.0),
            -25.0, 25.0,
            0.0, 500.0, 0.0, 5.0, 1};
    } else if (motor_type == "AK10_9_V1p1") {
        params_ = mit_params_t{
            -degrees(12.5), degrees(12.5),
            -degrees(50.0), degrees(50.0),
            -65.0, 65.0,
            0.0, 500.0, 0.0, 5.0, 1};
    } else if (motor_type == "AK60_6_V2p2") {
        params_ = mit_params_t{
            -degrees(12.5), degrees(12.5),
            -degrees(45.0), degrees(45.0),
            -15.0, 15.0,
            0.0, 500.0, 0.0, 5.0, 1};
    } else if (motor_type == "AK45_36_KV80" ||
               motor_type == "AK45-36_KV80" ||
               motor_type == "AK45-36-KV80" ||
               motor_type == "AK45_36" ||
               motor_type == "AK45-36")
    {
        params_ = mit_params_t{
            -degrees(12.5), degrees(12.5),
            -degrees(22.5), degrees(22.5),
            -12.0, 12.0,
            0.0, 500.0, 0.0, 5.0, -1};
    } else if (motor_type == "AK10_30" || motor_type == "AK10_30_cubemars") {
        params_ = mit_params_t{
            -degrees(12.5), degrees(12.5),
            -degrees(45.0), degrees(45.0),
            -18.0, 18.0,
            0.0, 500.0, 0.0, 5.0, 1};
    } else {
        throw std::runtime_error("Unsupported CubeMars motor_type.");
    }
}

void cubemars::CubemarsDriver::loadInterfaces(const YAML::Node& interfaces)
{
    std::fill(std::begin(rx_fields_), std::end(rx_fields_), false);
    std::fill(std::begin(tx_fields_), std::end(tx_fields_), false);

    enum class Section {
        None,
        Rx,
        Tx
    };

    Section section = Section::None;
    uint8_t a_idx{0};
    uint8_t r_idx{0};
    uint8_t t_idx{0};

    for (const auto& node : interfaces) {
        if (a_idx >= motor_interface::MAX_INTERFACE_SIZE) {
            throw std::runtime_error("Too many CubeMars interfaces.");
        }

        motor_interface::entry_table_t entry{};
        entry.id = node["id"].as<uint8_t>();
        entry.index = node["index"] ? node["index"].as<uint16_t>() : 0;
        entry.subindex = node["subindex"] ? node["subindex"].as<uint8_t>() : 0;

        if (entry.id == motor_interface::ID_RXPDO) {
            section = Section::Rx;
            interfaces_[a_idx++] = entry;
            continue;
        }

        if (entry.id == motor_interface::ID_TXPDO) {
            section = Section::Tx;
            interfaces_[a_idx++] = entry;
            continue;
        }

        entry.size = node["size"] ? node["size"].as<uint8_t>() : defaultFieldSize(entry.id);
        entry.type = node["type"] ?
            motor_interface::toDataType(node["type"].as<std::string>()) :
            defaultFieldType(entry.id);

        const bool rx = section == Section::Rx || (section == Section::None && isRxField(entry.id));
        const bool tx = section == Section::Tx || (section == Section::None && isTxField(entry.id));
        if (!rx && !tx) throw std::runtime_error("Invalid CubeMars interface ID.");

        if (entry.id >= motor_interface::MAX_INTERFACE_SIZE) {
            throw std::runtime_error("CubeMars interface ID exceeds local field table.");
        }

        if (rx) {
            rx_fields_[entry.id] = true;
            ++r_idx;
        } else {
            tx_fields_[entry.id] = true;
            ++t_idx;
        }

        interfaces_[a_idx++] = entry;
    }

    number_of_interfaces_ = a_idx;
    number_of_rx_interfaces_ = r_idx;
    number_of_tx_interfaces_ = t_idx;
}

bool cubemars::CubemarsDriver::targetRequested(
    const motor_interface::motor_frame_t& command,
    uint8_t id) const
{
    if (command.number_of_target_interfaces == 0) return false;

    const uint8_t count = std::min(
        command.number_of_target_interfaces,
        motor_interface::MAX_INTERFACE_SIZE);
    for (uint8_t i = 0; i < count; ++i) {
        if (command.target_interface_id[i] == id) return true;
    }

    return false;
}

bool cubemars::CubemarsDriver::rxFieldEnabled(uint8_t id) const
{
    return id < motor_interface::MAX_INTERFACE_SIZE && rx_fields_[id];
}

bool cubemars::CubemarsDriver::txFieldEnabled(uint8_t id) const
{
    return id < motor_interface::MAX_INTERFACE_SIZE && tx_fields_[id];
}

int cubemars::CubemarsDriver::floatToUint(double value, double min, double max, int bits) const
{
    if (max <= min) throw std::runtime_error("Invalid CubeMars MIT range.");

    value = std::min(std::max(value, min), max);
    const double span = max - min;
    const int max_int = (1 << bits) - 1;
    const int raw = static_cast<int>(std::lround((value - min) * max_int / span));

    return std::min(std::max(raw, 0), max_int);
}

double cubemars::CubemarsDriver::uintToFloat(int value, double min, double max, int bits) const
{
    if (max <= min) throw std::runtime_error("Invalid CubeMars MIT range.");

    const int max_int = (1 << bits) - 1;
    value = std::min(std::max(value, 0), max_int);

    return static_cast<double>(value) * (max - min) / static_cast<double>(max_int) + min;
}

void cubemars::CubemarsDriver::fillMagicFrame(
    uint8_t node_id,
    uint8_t command,
    socketcan::socketcan_frame_t& frame) const
{
    frame = socketcan::socketcan_frame_t{};
    frame.can_id = node_id;

    const uint8_t bytes[8] = {
        0xFF, 0xFF, 0xFF, 0xFF,
        0xFF, 0xFF, 0xFF, command
    };
    setFrameBytes(frame, bytes);
}
