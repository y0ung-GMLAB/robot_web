#include <cmath>
#include <algorithm>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <vector>

#include <yaml-cpp/yaml.h>

#include "dynamixel/dynamixel_driver.hpp"

namespace {

constexpr double DEGREE_PER_REVOLUTION = 360.0;
constexpr double RAD_TO_DEG = 180.0 / M_PI;
constexpr double DEG_TO_RAD = M_PI / 180.0;
constexpr double DXL_ACCEL_REV_PER_MIN2_PER_UNIT = 214.577;

std::string trim(const std::string& value)
{
    const std::size_t begin = value.find_first_not_of(" \t\r\n");
    if (begin == std::string::npos) return "";

    const std::size_t end = value.find_last_not_of(" \t\r\n");
    return value.substr(begin, end - begin + 1);
}

std::vector<std::string> splitTabs(const std::string& line)
{
    std::vector<std::string> parts;
    std::stringstream ss(line);
    std::string part;

    while (std::getline(ss, part, '\t')) {
        parts.push_back(trim(part));
    }

    return parts;
}

uint32_t accelerationRawFromDegreePerSec2(double value)
{
    if (value <= 0.0) return 0;
    const double rev_per_min2 = value * 3600.0 / DEGREE_PER_REVOLUTION;
    return static_cast<uint32_t>(std::lround(rev_per_min2 / DXL_ACCEL_REV_PER_MIN2_PER_UNIT));
}

void fillYamlValue(const YAML::Node& node, motor_interface::entry_table_t& entry)
{
    if (!node["value"]) throw std::runtime_error("Dynamixel entry requires value.");

    switch (entry.type) {
    case motor_interface::DataType::U8:
        motor_interface::fill<uint8_t>(node["value"].as<uint8_t>(), entry.data);
        break;
    case motor_interface::DataType::U16:
        motor_interface::fill<uint16_t>(node["value"].as<uint16_t>(), entry.data);
        break;
    case motor_interface::DataType::U32:
        motor_interface::fill<uint32_t>(node["value"].as<uint32_t>(), entry.data);
        break;
    case motor_interface::DataType::U64:
        throw std::runtime_error("Dynamixel data cannot exceed 4 bytes.");
    case motor_interface::DataType::S8:
        motor_interface::fill<int8_t>(node["value"].as<int8_t>(), entry.data);
        break;
    case motor_interface::DataType::S16:
        motor_interface::fill<int16_t>(node["value"].as<int16_t>(), entry.data);
        break;
    case motor_interface::DataType::S32:
        motor_interface::fill<int32_t>(node["value"].as<int32_t>(), entry.data);
        break;
    default:
        throw std::runtime_error("Invalid Dynamixel data type.");
    }
}

uint8_t readProtocolByte(const YAML::Node& protocol, const char* key)
{
    if (!protocol[key]) throw std::runtime_error(std::string("Dynamixel protocol requires ") + key + ".");

    const unsigned int value = protocol[key].as<unsigned int>();
    if (value > 0xFF) throw std::runtime_error(std::string("Invalid Dynamixel protocol byte: ") + key + ".");

    return static_cast<uint8_t>(value);
}

} // namespace

dynamixel::DynamixelDriver::DynamixelDriver(const motor_interface::driver_config_t& config)
    : motor_interface::MotorDriver(config)
{
}

void dynamixel::DynamixelDriver::loadParameters(const std::string& param_file)
{
    YAML::Node root = YAML::LoadFile(param_file);
    if (!root) throw std::runtime_error("Failed to load Dynamixel parameter file.");

    YAML::Node protocol = root["protocol"];
    if (!protocol || !protocol.IsMap()) throw std::runtime_error("Dynamixel protocol configuration is required.");

    serial_protocol_.configured = true;
    serial_protocol_.broadcast_id = readProtocolByte(protocol, "broadcast_id");
    serial_protocol_.instruction_read = readProtocolByte(protocol, "read");
    serial_protocol_.instruction_write = readProtocolByte(protocol, "write");
    serial_protocol_.instruction_status = readProtocolByte(protocol, "status");
    serial_protocol_.instruction_bulk_read = readProtocolByte(protocol, "bulk_read");
    serial_protocol_.instruction_bulk_write = readProtocolByte(protocol, "bulk_write");

    if (root["model_file"]) {
        std::filesystem::path model_path(root["model_file"].as<std::string>());
        if (!model_path.is_absolute()) {
            model_path = std::filesystem::path(param_file).parent_path() / model_path;
        }
        loadModelFile(model_path.lexically_normal().string());
    }

    if (root["value_of_zero_radian_position"]) {
        zero_position_ = root["value_of_zero_radian_position"].as<double>();
        has_position_model_ = true;
    }
    if (root["value_of_max_radian_position"]) {
        max_position_ = root["value_of_max_radian_position"].as<double>();
    }
    if (root["value_of_min_radian_position"]) {
        min_position_ = root["value_of_min_radian_position"].as<double>();
    }
    if (root["min_radian"]) {
        min_radian_ = root["min_radian"].as<double>();
    }
    if (root["max_radian"]) {
        max_radian_ = root["max_radian"].as<double>();
    }
    if (root["velocity_unit"]) {
        velocity_unit_ = root["velocity_unit"].as<double>();
    }
    if (root["current_unit"]) {
        current_unit_ = root["current_unit"].as<double>();
    }

    YAML::Node items = root["items"];
    if (!items || !items.IsSequence()) throw std::runtime_error("Invalid Dynamixel items configuration.");

    uint8_t i_idx{0};
    for (const auto& i : items) {
        if (i_idx >= motor_interface::MAX_ITEM_SIZE) throw std::runtime_error("Too many Dynamixel items.");

        motor_interface::entry_table_t e_cfg{};
        if (!loadEntry(i, e_cfg, false)) continue;

        if (e_cfg.id == motor_interface::ID_MIN_POSITION_LIMIT) {
            motor_interface::fill<int32_t>(position(config_.lower), e_cfg.data);
        } else if (e_cfg.id == motor_interface::ID_MAX_POSITION_LIMIT) {
            motor_interface::fill<int32_t>(position(config_.upper), e_cfg.data);
        } else if (e_cfg.id == motor_interface::ID_MAX_MOTOR_SPEED) {
            motor_interface::fill<uint32_t>(
                static_cast<uint32_t>(std::llround(std::fabs(config_.speed) * DEG_TO_RAD / velocity_unit_)),
                e_cfg.data
            );
        } else if (e_cfg.id == motor_interface::ID_PROFILE_VELOCITY) {
            motor_interface::fill<uint32_t>(
                static_cast<uint32_t>(std::llround(std::fabs(config_.profile_velocity) * DEG_TO_RAD / velocity_unit_)),
                e_cfg.data
            );
        } else if (e_cfg.id == motor_interface::ID_PROFILE_ACCELERATION ||
                   e_cfg.id == motor_interface::ID_MAX_ACCELERATION)
        {
            const double value = config_.profile_acceleration > 0.0 ?
                config_.profile_acceleration : config_.acceleration;
            motor_interface::fill<uint32_t>(accelerationRawFromDegreePerSec2(value), e_cfg.data);
        } else if (e_cfg.id == motor_interface::ID_MAX_EFFORT) {
            const int16_t current = effort(config_.rated_effort);
            if (e_cfg.type == motor_interface::DataType::U16) {
                motor_interface::fill<uint16_t>(static_cast<uint16_t>(std::max<int16_t>(current, 0)), e_cfg.data);
            } else {
                motor_interface::fill<int16_t>(current, e_cfg.data);
            }
        } else {
            fillYamlValue(i, e_cfg);
        }

        items_[i_idx++] = e_cfg;
    }
    number_of_items_ = i_idx;

    YAML::Node interfaces = root["interfaces"];
    if (!interfaces || !interfaces.IsSequence()) throw std::runtime_error("Invalid Dynamixel interfaces configuration.");

    uint8_t a_idx{0}, r_idx{0}, t_idx{0};
    for (const auto& i : interfaces) {
        if (a_idx >= motor_interface::MAX_INTERFACE_SIZE) throw std::runtime_error("Too many Dynamixel interfaces.");

        motor_interface::entry_table_t e_cfg{};
        if (!loadEntry(i, e_cfg, true)) continue;

        if (e_cfg.id != motor_interface::ID_RXPDO && e_cfg.id != motor_interface::ID_TXPDO) {
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

bool dynamixel::DynamixelDriver::isEnabled(
    const uint8_t* data,
    motor_interface::DriverState& driver_state,
    uint8_t* out)
{
    if (data[0] == 1) {
        driver_state = motor_interface::DriverState::OperationEnabled;
        return true;
    }

    driver_state = motor_interface::DriverState::SwitchOnDisabled;
    motor_interface::fill<uint8_t>(1, out);
    return false;
}

bool dynamixel::DynamixelDriver::isDisabled(
    const uint8_t* data,
    motor_interface::DriverState& driver_state,
    uint8_t* out)
{
    if (data[0] == 0) {
        driver_state = motor_interface::DriverState::SwitchOnDisabled;
        return true;
    }

    motor_interface::fill<uint8_t>(0, out);
    return false;
}

bool dynamixel::DynamixelDriver::isReceived(const uint8_t* data, uint8_t* out)
{
    (void)data;
    (void)out;
    return false;
}

double dynamixel::DynamixelDriver::position(const int32_t value)
{
    if (has_position_model_) {
        return (static_cast<double>(value) - zero_position_) * positionUnit() * RAD_TO_DEG;
    }

    return static_cast<double>(value) / static_cast<double>(config_.pulse_per_revolution) * DEGREE_PER_REVOLUTION;
}

double dynamixel::DynamixelDriver::velocity(const int32_t value)
{
    return static_cast<double>(value) * velocity_unit_ * RAD_TO_DEG;
}

double dynamixel::DynamixelDriver::effort(const int16_t value)
{
    return static_cast<double>(value) * current_unit_ * config_.unit_effort;
}

int32_t dynamixel::DynamixelDriver::position(const double value)
{
    if (has_position_model_) {
        const int32_t raw_position =
            static_cast<int32_t>(std::lround(zero_position_ + value * DEG_TO_RAD / positionUnit()));
        const int32_t min_raw =
            static_cast<int32_t>(std::lround(std::min(min_position_, max_position_)));
        const int32_t max_raw =
            static_cast<int32_t>(std::lround(std::max(min_position_, max_position_)));

        if (min_raw < max_raw) {
            return std::clamp(raw_position, min_raw, max_raw);
        }

        return raw_position;
    }

    return static_cast<int32_t>(std::lround(value / DEGREE_PER_REVOLUTION * config_.pulse_per_revolution));
}

int32_t dynamixel::DynamixelDriver::velocity(const double value)
{
    if (velocity_unit_ == 0.0) return 0;
    return static_cast<int32_t>(std::lround(value * DEG_TO_RAD / velocity_unit_));
}

int16_t dynamixel::DynamixelDriver::effort(const double value)
{
    const double unit = current_unit_ * config_.unit_effort;
    if (unit == 0.0) return 0;
    return static_cast<int16_t>(std::lround(value / unit));
}

void dynamixel::DynamixelDriver::loadModelFile(const std::string& model_file)
{
    std::ifstream file(model_file);
    if (!file.is_open()) throw std::runtime_error("Failed to open Dynamixel model file.");

    enum class Section {
        None,
        TypeInfo,
        UnitInfo,
        ControlTable
    };

    Section section = Section::None;
    std::string line;
    while (std::getline(file, line)) {
        line = trim(line);
        if (line.empty()) continue;

        if (line == "[type info]") {
            section = Section::TypeInfo;
            continue;
        }
        if (line == "[unit info]") {
            section = Section::UnitInfo;
            continue;
        }
        if (line == "[control table]") {
            section = Section::ControlTable;
            continue;
        }
        if (line.rfind("name\t", 0) == 0 ||
            line.rfind("Data Name\t", 0) == 0 ||
            line.rfind("Address\t", 0) == 0)
        {
            continue;
        }

        const std::vector<std::string> parts = splitTabs(line);
        if (section == Section::TypeInfo && parts.size() >= 2) {
            if (parts[0] == "value_of_zero_radian_position") {
                zero_position_ = std::stod(parts[1]);
                has_position_model_ = true;
            } else if (parts[0] == "value_of_max_radian_position") {
                max_position_ = std::stod(parts[1]);
            } else if (parts[0] == "value_of_min_radian_position") {
                min_position_ = std::stod(parts[1]);
            } else if (parts[0] == "min_radian") {
                min_radian_ = std::stod(parts[1]);
            } else if (parts[0] == "max_radian") {
                max_radian_ = std::stod(parts[1]);
            }
            continue;
        }

        if (section == Section::UnitInfo && parts.size() >= 4) {
            if (parts[0] == "Goal Velocity" || parts[0] == "Present Velocity") {
                velocity_unit_ = std::stod(parts[1]);
            } else if (parts[0] == "Goal Current" || parts[0] == "Present Current") {
                current_unit_ = std::stod(parts[1]);
            }
            continue;
        }

        if (section == Section::ControlTable && parts.size() >= 3) {
            model_entry_t entry{};
            entry.address = static_cast<uint16_t>(std::stoul(parts[0]));
            entry.size = static_cast<uint8_t>(std::stoul(parts[1]));
            model_entries_[parts[2]] = entry;
        }
    }
}

bool dynamixel::DynamixelDriver::loadEntry(
    const YAML::Node& node,
    motor_interface::entry_table_t& entry,
    bool marker_allowed) const
{
    entry = motor_interface::entry_table_t{};
    entry.id = node["id"].as<uint8_t>();

    if (marker_allowed &&
        (entry.id == motor_interface::ID_RXPDO || entry.id == motor_interface::ID_TXPDO))
    {
        entry.index = node["index"] ? node["index"].as<uint16_t>() : 0;
        return true;
    }

    const bool optional = node["optional"] && node["optional"].as<bool>();

    if (node["name"]) {
        const std::string name = node["name"].as<std::string>();
        auto iter = model_entries_.find(name);
        if (iter == model_entries_.end()) {
            if (optional) return false;
            throw std::runtime_error("Dynamixel control table name not found: " + name);
        }

        entry.index = iter->second.address;
        entry.size = iter->second.size;
    } else {
        if (!node["index"] || !node["size"]) {
            if (optional) return false;
            throw std::runtime_error("Dynamixel entry requires either name or index/size.");
        }

        entry.index = node["index"].as<uint16_t>();
        entry.size = node["size"].as<uint8_t>();
    }

    entry.subindex = node["subindex"] ? node["subindex"].as<uint8_t>() : 0;
    if (node["size"]) entry.size = node["size"].as<uint8_t>();
    entry.type = motor_interface::toDataType(node["type"].as<std::string>());

    if (entry.size == 0 || entry.size > motor_interface::MAX_DATA_SIZE) {
        throw std::runtime_error("Invalid Dynamixel entry size.");
    }

    return true;
}

double dynamixel::DynamixelDriver::positionUnit() const
{
    const double raw_range = max_position_ - min_position_;
    const double rad_range = max_radian_ - min_radian_;
    if (raw_range == 0.0 || rad_range == 0.0) {
        return (2.0 * M_PI) / static_cast<double>(config_.pulse_per_revolution);
    }

    return rad_range / raw_range;
}
