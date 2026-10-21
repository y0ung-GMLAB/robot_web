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

// Read plan · each node's TX entries are merged into address spans and every
// span is read on every cycle (robot_web fix-list 158 · before, one entry per
// cycle round-robin, so the position was refreshed once per N entries)
inline constexpr uint8_t MAX_READ_SPANS = 4;
inline constexpr uint16_t MAX_READ_SPAN_SIZE = 128;
inline constexpr uint16_t READ_SPAN_MERGE_GAP = 16;

struct serial_bulk_entry_t {
    uint16_t address{0};
    uint8_t size{0};
    uint8_t data[motor_interface::MAX_DATA_SIZE]{0};
    bool dirty{false};
    bool updated{false};
};

struct serial_read_span_t {
    uint16_t address{0};
    uint16_t size{0};
    bool answered{false};
};

struct serial_node_data_t {
    bool registered{false};
    uint8_t node_id{0};
    uint8_t last_packet_error{0};
    // Cycles in a row this node did not answer every read span (robot_web
    // fix-list 23-3 · counted per cycle since 158, was per bulk read)
    uint16_t missed_responses{0};
    serial_bulk_entry_t rx_entries[motor_interface::MAX_INTERFACE_SIZE]{};
    serial_bulk_entry_t tx_entries[motor_interface::MAX_INTERFACE_SIZE]{};
    uint8_t number_of_rx_entries{0};
    uint8_t number_of_tx_entries{0};
    serial_read_span_t spans[MAX_READ_SPANS]{};
    uint8_t number_of_spans{0};
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

    bool reboot(uint8_t node_id);

    bool supportsReboot() const { return protocol_.instruction_reboot != 0; }

    // Port state · robot_web fix-list 27-1 · 27-2 (158) · a serial failure takes
    // only this port offline; motor_manager reopens it and every other bus runs on
    const std::string& port() const { return port_; }

    bool online() const { return fd_ >= 0; }

    // Close the port, drop pending writes and mark every node silent
    void markOffline();

    // Open the port again · throws like initialize() when it fails
    void reopen();

    // Bumped on every successful reopen · controllers re-check their items
    uint32_t generation() const { return generation_; }

private:
    struct status_packet_t {
        uint8_t id{0};
        uint8_t error{0};
        std::vector<uint8_t> parameters;
    };

    serial_node_data_t* findNode(uint8_t node_id);

    const serial_node_data_t* findNode(uint8_t node_id) const;

    void noteResponse(uint8_t node_id, uint8_t error);

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

    bool isScs() const { return protocol_.packet == PacketFormat::Scs; }

    bool isPacketFailure(uint8_t error) const;

    void appendAddress(std::vector<uint8_t>& data, uint16_t address) const;

    void appendLength(std::vector<uint8_t>& data, uint16_t length) const;

    std::size_t statusOverhead() const;

    void sendPacket(uint8_t id, uint8_t instruction, const std::vector<uint8_t>& parameters);

    bool receiveStatus(status_packet_t& packet, uint32_t timeout_ms);

    bool parseDxl2Status(status_packet_t& packet);

    bool parseScsStatus(status_packet_t& packet);

    bool readExact(uint8_t* data, std::size_t size, uint64_t deadline_ns);

    void writeExact(const uint8_t* data, std::size_t size);

    void flushInput();

    void ensureProtocolConfigured() const;

    void buildReadPlan();

    void storeSpan(serial_node_data_t& node, uint8_t span_index, const std::vector<uint8_t>& parameters);

    // Dxl2 · one Bulk Read with span `span_index` of every node that has one
    void bulkReadSpans(uint8_t span_index, const std::vector<serial_node_data_t*>& nodes);

    // Scs · one Sync Read (same address and size) or one READ per node
    void syncReadSpans(uint8_t span_index, const std::vector<serial_node_data_t*>& nodes);

    void readSpanSingle(serial_node_data_t& node, uint8_t span_index);

    void bulkWrite(uint16_t address, uint8_t size, const std::vector<serial_node_data_t*>& nodes);

    void syncWrite(uint16_t address, uint8_t size, const std::vector<serial_node_data_t*>& nodes);

    int fd_{-1};

    std::string port_;

    unsigned int baudrate_{57600};

    unsigned int latency_timer_ms_{16};

    std::vector<uint8_t> rx_buffer_;

    // Last packet sent · an echoing adapter hands it back (Scs parser skips it)
    std::vector<uint8_t> last_tx_;

    serial::serial_protocol_config_t protocol_{};

    serial_node_data_t nodes_[motor_interface::MAX_CONTROLLER_SIZE]{};

    bool read_plan_dirty_{true};

    uint32_t generation_{0};
};

} // namespace serial
#endif // SERIAL_SERIAL_MASTER_HPP_
