#ifndef MOTOR_INTERFACE_MOTOR_DRIVER_HPP_
#define MOTOR_INTERFACE_MOTOR_DRIVER_HPP_

#include <string>
#include <cstdint>
#include <cstddef>
#include <stdexcept>
#include <type_traits>

#include "common_motor_interface/motor_frame.hpp"

namespace motor_interface {

inline constexpr uint8_t MAX_DRIVER_SIZE = 8;

inline constexpr uint8_t MAX_DATA_SIZE = 4;

enum class DataType {
    U8,
    U16,
    U32,
    U64,
    S8,
    S16,
    S32
};

struct entry_table_t {
    uint8_t id;
    uint16_t index;
    uint8_t subindex;

    DataType type;
    uint8_t size;
    uint8_t data[MAX_DATA_SIZE];
};

inline constexpr uint8_t MAX_ITEM_SIZE = 32;

inline constexpr uint8_t ID_CONTROLWORD      = 0;
inline constexpr uint8_t ID_TARGET_POSITION  = 1;
inline constexpr uint8_t ID_TARGET_VELOCITY  = 2;
inline constexpr uint8_t ID_TARGET_EFFORT    = 3;
inline constexpr uint8_t ID_STATUSWORD       = 4;
inline constexpr uint8_t ID_ERRORCODE        = 5;
inline constexpr uint8_t ID_CURRENT_POSITION = 6;
inline constexpr uint8_t ID_CURRENT_VELOCITY = 7;
inline constexpr uint8_t ID_CURRENT_EFFORT   = 8;
inline constexpr uint8_t ID_TARGET_KP        = 9;
inline constexpr uint8_t ID_TARGET_KD        = 10;
inline constexpr uint8_t ID_CURRENT_TEMPERATURE = 11;

inline constexpr uint8_t ID_OPERATING_MODE = 30;

inline constexpr uint8_t ID_MAX_EFFORT           = 50;
inline constexpr uint8_t ID_MIN_POSITION_LIMIT   = 51;
inline constexpr uint8_t ID_MAX_POSITION_LIMIT   = 52;
inline constexpr uint8_t ID_MAX_MOTOR_SPEED      = 53;
inline constexpr uint8_t ID_PROFILE_VELOCITY     = 54;
inline constexpr uint8_t ID_PROFILE_ACCELERATION = 55;
inline constexpr uint8_t ID_PROFILE_DECELERATION = 56;
inline constexpr uint8_t ID_MAX_ACCELERATION     = 57;
inline constexpr uint8_t ID_MAX_DECELERATION     = 58;
inline constexpr uint8_t ID_RXPDO                = 98;
inline constexpr uint8_t ID_TXPDO                = 99;


enum class DriverState {
    Fault,
    SwitchOnDisabled,
    ReadyToSwitchOn,
    SwitchedOn,
    OperationEnabled
};

struct driver_config_t {
    uint8_t id;
    uint32_t pulse_per_revolution;
    double rated_effort;
    double unit_effort;
    double lower;
    double upper;
    double speed;
    double acceleration;
    double deceleration;
    double profile_velocity;
    double profile_acceleration;
    double profile_deceleration;
    int8_t profile_position_value;
    int8_t profile_velocity_value;
    int8_t profile_effort_value;
};

inline DataType toDataType(const std::string& type) {
    if (type == "u8") return DataType::U8;
    if (type == "u16") return DataType::U16;
    if (type == "u32") return DataType::U32;
    if (type == "u64") return DataType::U64;
    if (type == "s8") return DataType::S8;
    if (type == "s16") return DataType::S16;
    if (type == "s32") return DataType::S32;
    throw std::runtime_error("Invalid data type.");
}

template <typename T>
inline T value(const uint8_t* data) {
    using U = std::make_unsigned_t<T>;
    U u = 0;
    for (std::size_t i = 0; i < sizeof(T); ++i) {
        u |= (static_cast<U>(data[i]) << (i * 8));
    }
    return static_cast<T>(u);
}

template <typename T>
inline void fill(const T& value, uint8_t* data) {
    using U = std::make_unsigned_t<T>;
    U u = static_cast<U>(value);
    for (std::size_t i = 0; i < sizeof(T); ++i) {
        data[i] = static_cast<uint8_t>(
            (u >> (i * 8)) & static_cast<U>(0xFF)
        );
    }
}

class MotorDriver {
public:
    explicit MotorDriver(const driver_config_t& config)
    : config_(config) {}

    virtual ~MotorDriver() = default;

    virtual void loadParameters(const std::string& param_file) = 0;

    virtual bool isEnabled(const uint8_t* data, DriverState& driver_state, uint8_t* out) = 0;

    virtual bool isDisabled(const uint8_t* data, DriverState& driver_state, uint8_t* out) = 0;

    virtual bool isReceived(const uint8_t* data, uint8_t* out) = 0;

    virtual double position(const int32_t value) = 0;

    virtual double velocity(const int32_t value) = 0;

    virtual double effort(const int16_t value) = 0;

    virtual int32_t position(const double value) = 0;

    virtual int32_t velocity(const double value) = 0;

    virtual int16_t effort(const double value) = 0;

    const entry_table_t* items() const { return items_; }

    const entry_table_t* interfaces() const { return interfaces_; }

    uint8_t number_of_items() const { return number_of_items_; }

    uint8_t number_of_interfaces() const { return number_of_interfaces_; }

    uint8_t number_of_rx_interfaces() const { return number_of_rx_interfaces_; }

    uint8_t number_of_tx_interfaces() const { return number_of_tx_interfaces_; }

    int8_t profile_position_value() const { return config_.profile_position_value; }

    int8_t profile_velocity_value() const { return config_.profile_velocity_value; }

    int8_t profile_effort_value() const { return config_.profile_effort_value; }

protected:
    entry_table_t items_[MAX_ITEM_SIZE];

    entry_table_t interfaces_[MAX_INTERFACE_SIZE];

    uint8_t number_of_items_{0};

    uint8_t number_of_interfaces_{0};

    uint8_t number_of_rx_interfaces_{0};

    uint8_t number_of_tx_interfaces_{0};

    const driver_config_t config_;
};

} // namespace motor_interface
#endif // MOTOR_INTERFACE_MOTOR_DRIVER_HPP_
