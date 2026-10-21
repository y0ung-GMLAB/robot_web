#ifndef SERIAL_SERIAL_DRIVER_HPP_
#define SERIAL_SERIAL_DRIVER_HPP_

#include <cstdint>

#include "motor_interface/motor_driver.hpp"

namespace serial {

// Packet format on one bus · robot_web fix-list 158 (2026-10-21)
//   Dxl2 · Dynamixel Protocol 2.0 (FF FF FD 00 · CRC16 · 2-byte address) · what this layer always spoke
//   Scs  · Feetech SCS/STS (FF FF · 1-byte length · checksum · 1-byte address)
enum class PacketFormat : uint8_t {
    Dxl2,
    Scs
};

struct serial_protocol_config_t {
    bool configured{false};
    PacketFormat packet{PacketFormat::Dxl2};
    uint8_t broadcast_id{0};
    uint8_t instruction_read{0};
    uint8_t instruction_write{0};
    uint8_t instruction_status{0};
    uint8_t instruction_bulk_read{0};
    uint8_t instruction_bulk_write{0};
    // Scs group read/write (0x82 · 0x83) · 0 = not supported (single READ per node)
    uint8_t instruction_sync_read{0};
    uint8_t instruction_sync_write{0};
    // Protocol 2.0 REBOOT · clears a latched hardware error (robot_web fix-list 24-1)
    // 0 = the device has no reboot (Feetech · its 0x06 is a factory reset, never sent)
    uint8_t instruction_reboot{0x08};
};

class SerialDriver {
public:
    virtual ~SerialDriver() = default;

    const serial_protocol_config_t& serial_protocol() const { return serial_protocol_; }

    // Raw value ↔ register bytes · default = little endian two's complement, the
    // Dynamixel layout this layer always used. A driver overrides the byte order
    // or a sign-magnitude field (Feetech position/speed · bit 15) · fix-list 158
    virtual void encode(const motor_interface::entry_table_t& descriptor, int64_t value, uint8_t* out) const;

    virtual int64_t decodeSigned(const motor_interface::entry_table_t& entry) const;

    virtual uint64_t decodeUnsigned(const motor_interface::entry_table_t& entry) const;

protected:
    serial_protocol_config_t serial_protocol_{};
};

} // namespace serial

#endif // SERIAL_SERIAL_DRIVER_HPP_
