#include <stdexcept>

#include "serial/serial_driver.hpp"

// Moved here unchanged from SerialController (fillInterfaceValue · readUnsignedValue ·
// readSignedValue) so a driver can override the layout · robot_web fix-list 158

void serial::SerialDriver::encode(
    const motor_interface::entry_table_t& descriptor,
    int64_t value,
    uint8_t* out) const
{
    switch (descriptor.type) {
    case motor_interface::DataType::U8:
        motor_interface::fill<uint8_t>(static_cast<uint8_t>(value), out);
        break;
    case motor_interface::DataType::U16:
        motor_interface::fill<uint16_t>(static_cast<uint16_t>(value), out);
        break;
    case motor_interface::DataType::U32:
        motor_interface::fill<uint32_t>(static_cast<uint32_t>(value), out);
        break;
    case motor_interface::DataType::S8:
        motor_interface::fill<int8_t>(static_cast<int8_t>(value), out);
        break;
    case motor_interface::DataType::S16:
        motor_interface::fill<int16_t>(static_cast<int16_t>(value), out);
        break;
    case motor_interface::DataType::S32:
        motor_interface::fill<int32_t>(static_cast<int32_t>(value), out);
        break;
    default:
        throw std::runtime_error("Invalid serial interface data type.");
    }
}

uint64_t serial::SerialDriver::decodeUnsigned(const motor_interface::entry_table_t& entry) const
{
    switch (entry.size) {
    case 1:
        return motor_interface::value<uint8_t>(entry.data);
    case 2:
        return motor_interface::value<uint16_t>(entry.data);
    case 4:
        return motor_interface::value<uint32_t>(entry.data);
    default:
        throw std::runtime_error("Invalid unsigned serial data size.");
    }
}

int64_t serial::SerialDriver::decodeSigned(const motor_interface::entry_table_t& entry) const
{
    switch (entry.type) {
    case motor_interface::DataType::U8:
        return motor_interface::value<uint8_t>(entry.data);
    case motor_interface::DataType::U16:
        return motor_interface::value<uint16_t>(entry.data);
    case motor_interface::DataType::U32:
        return motor_interface::value<uint32_t>(entry.data);
    case motor_interface::DataType::S8:
        return motor_interface::value<int8_t>(entry.data);
    case motor_interface::DataType::S16:
        return motor_interface::value<int16_t>(entry.data);
    case motor_interface::DataType::S32:
        return motor_interface::value<int32_t>(entry.data);
    default:
        throw std::runtime_error("Invalid signed serial data type.");
    }
}
