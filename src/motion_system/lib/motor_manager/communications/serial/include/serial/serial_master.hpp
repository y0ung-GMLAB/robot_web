#ifndef SERIAL_SERIAL_MASTER_HPP_
#define SERIAL_SERIAL_MASTER_HPP_

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

#include "motor_interface/motor_master.hpp"
#include "motor_interface/motor_controller.hpp" // MAX_CONTROLLER_SIZE
#include "serial/serial_driver.hpp"

namespace serial {

struct serial_bulk_entry_t {
    uint16_t address{0};
    uint8_t size{0};
    uint8_t data[motor_interface::MAX_DATA_SIZE]{0};
    bool dirty{false};
    bool updated{false};
};

struct serial_node_data_t {
    bool registered{false};
    uint8_t node_id{0};
    uint8_t last_packet_error{0};
    serial_bulk_entry_t rx_entries[motor_interface::MAX_INTERFACE_SIZE]{};
    serial_bulk_entry_t tx_entries[motor_interface::MAX_INTERFACE_SIZE]{};
    uint8_t number_of_rx_entries{0};
    uint8_t number_of_tx_entries{0};
};

class SerialMaster : public motor_interface::MotorMaster {
public:
    explicit SerialMaster(const motor_interface::master_config_t& config);

    virtual ~SerialMaster();

    void initialize() override;

    void activate() override;

    void deactivate() override;

    void transmit() override;

    void receive() override;

    void apply_application_time(const timespec& time) override;

    void save_clock() override;

    void registerNode(uint8_t node_id);

    void configureProtocol(const serial::serial_protocol_config_t& protocol);

    serial_node_data_t* node(uint8_t node_id);

    void registerBulkWrite(uint8_t node_id, uint16_t address, uint8_t size);

    void registerBulkRead(uint8_t node_id, uint16_t address, uint8_t size);

    bool setBulkWriteData(uint8_t node_id, uint16_t address, const uint8_t* data, uint8_t size);

    bool getBulkReadData(uint8_t node_id, uint16_t address, uint8_t* data, uint8_t size);

    bool writeRegister(uint8_t node_id, uint16_t address, const uint8_t* data, uint8_t size);

    bool readRegister(uint8_t node_id, uint16_t address, uint8_t* data, uint8_t size);

private:
    struct status_packet_t {
        uint8_t id{0};
        uint8_t error{0};
        std::vector<uint8_t> parameters;
    };

    serial_node_data_t* findNode(uint8_t node_id);

    const serial_node_data_t* findNode(uint8_t node_id) const;

    serial_bulk_entry_t* findEntry(
        serial_bulk_entry_t* entries,
        uint8_t count,
        uint16_t address,
        uint8_t size);

    const serial_bulk_entry_t* findEntry(
        const serial_bulk_entry_t* entries,
        uint8_t count,
        uint16_t address,
        uint8_t size) const;

    void sendPacket(uint8_t id, uint8_t instruction, const std::vector<uint8_t>& parameters);

    bool receiveStatus(status_packet_t& packet, uint32_t timeout_ms);

    bool readExact(uint8_t* data, std::size_t size, uint64_t deadline_ns);

    void writeExact(const uint8_t* data, std::size_t size);

    void flushInput();

    void ensureProtocolConfigured() const;

    void bulkRead(uint16_t address, uint8_t size, const std::vector<uint8_t>& node_ids);

    void bulkWrite(uint16_t address, uint8_t size, const std::vector<serial_node_data_t*>& nodes);

    int fd_{-1};

    std::string port_;

    unsigned int baudrate_{57600};

    unsigned int latency_timer_ms_{16};

    std::vector<uint8_t> rx_buffer_;

    serial::serial_protocol_config_t protocol_{};

    serial_node_data_t nodes_[motor_interface::MAX_CONTROLLER_SIZE]{};

    uint8_t next_receive_node_{0};

    uint8_t next_receive_entry_{0};
};

} // namespace serial
#endif // SERIAL_SERIAL_MASTER_HPP_
