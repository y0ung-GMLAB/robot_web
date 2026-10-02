#ifndef SERIAL_SERIAL_DRIVER_HPP_
#define SERIAL_SERIAL_DRIVER_HPP_

#include <cstdint>

namespace serial {

struct serial_protocol_config_t {
    bool configured{false};
    uint8_t broadcast_id{0};
    uint8_t instruction_read{0};
    uint8_t instruction_write{0};
    uint8_t instruction_status{0};
    uint8_t instruction_bulk_read{0};
    uint8_t instruction_bulk_write{0};
};

class SerialDriver {
public:
    virtual ~SerialDriver() = default;

    const serial_protocol_config_t& serial_protocol() const { return serial_protocol_; }

protected:
    serial_protocol_config_t serial_protocol_{};
};

} // namespace serial

#endif // SERIAL_SERIAL_DRIVER_HPP_
