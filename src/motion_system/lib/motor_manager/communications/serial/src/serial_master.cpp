#include <algorithm>
#include <cerrno>
#include <chrono>
#include <cstring>
#include <fstream>
#include <stdexcept>
#include <iterator>
#include <thread>

#include <fcntl.h>
#include <termios.h>
#include <unistd.h>

#include "serial/serial_master.hpp"

namespace {

constexpr std::size_t MAX_PACKET_SIZE = 1024;
constexpr uint64_t NSEC_PER_MSEC = 1000000ULL;
constexpr uint64_t NSEC_PER_USEC = 1000ULL;
constexpr uint32_t DXL_DEFAULT_USB_LATENCY_TIMER_MS = 16;
constexpr uint32_t DXL_PACKET_TIMEOUT_MARGIN_MS = 2;
constexpr uint32_t SERIAL_TIMEOUT_MS = 20;
constexpr uint32_t SERIAL_RUNTIME_TIMEOUT_MS = 20;

uint64_t nowNs()
{
    timespec t{};
    if (::clock_gettime(CLOCK_MONOTONIC, &t) != 0) {
        throw std::runtime_error("clock_gettime failed.");
    }

    return static_cast<uint64_t>(t.tv_sec) * 1000000000ULL +
           static_cast<uint64_t>(t.tv_nsec);
}

void sleepBriefly()
{
    std::this_thread::sleep_for(std::chrono::microseconds(50));
}

void appendLe16(std::vector<uint8_t>& data, uint16_t value)
{
    data.push_back(static_cast<uint8_t>(value & 0xFF));
    data.push_back(static_cast<uint8_t>((value >> 8) & 0xFF));
}

uint16_t readLe16(const uint8_t low, const uint8_t high)
{
    return static_cast<uint16_t>(low) |
           static_cast<uint16_t>(static_cast<uint16_t>(high) << 8);
}

// Status packet error byte · bit 7 is the Alert flag ("the device has a
// hardware error"), bits 0-6 are the packet error code (1 result fail ...
// 7 access error). An Alert alone still carries valid data: dropping it froze
// Hardware Error Status, Torque Enable and Present Position at their last
// values, so the fault never reached the status (robot_web fix-list 23-1).
constexpr uint8_t DXL_ALERT_BIT = 0x80;

uint32_t remainingTimeoutMs(uint64_t deadline_ns)
{
    const uint64_t now = nowNs();
    if (now >= deadline_ns) return 0;

    const uint64_t remaining_ns = deadline_ns - now;
    return static_cast<uint32_t>((remaining_ns + NSEC_PER_MSEC - 1) / NSEC_PER_MSEC);
}

std::string deviceName(const std::string& port)
{
    const std::string::size_type slash = port.find_last_of('/');
    if (slash == std::string::npos) return port;
    return port.substr(slash + 1);
}

uint32_t readUsbLatencyTimerMs(const std::string& port)
{
    const std::string device = deviceName(port);
    if (device.empty()) return DXL_DEFAULT_USB_LATENCY_TIMER_MS;

    std::ifstream latency_file("/sys/bus/usb-serial/devices/" + device + "/latency_timer");
    uint32_t latency_ms = 0;
    if (latency_file >> latency_ms && latency_ms > 0) return latency_ms;

    return DXL_DEFAULT_USB_LATENCY_TIMER_MS;
}

uint32_t packetTimeoutMs(
    uint32_t configured_timeout_ms,
    unsigned int baudrate,
    std::size_t packet_length,
    uint32_t latency_timer_ms)
{
    if (baudrate == 0 || packet_length == 0) return configured_timeout_ms;

    const uint64_t wire_time_us =
        (static_cast<uint64_t>(packet_length) * 10ULL * 1000000ULL + baudrate - 1) / baudrate;
    const uint64_t wire_time_ms = (wire_time_us * NSEC_PER_USEC + NSEC_PER_MSEC - 1) / NSEC_PER_MSEC;
    const uint64_t sdk_like_timeout =
        wire_time_ms + static_cast<uint64_t>(latency_timer_ms) * 2ULL + DXL_PACKET_TIMEOUT_MARGIN_MS;

    return static_cast<uint32_t>(std::max<uint64_t>(configured_timeout_ms, sdk_like_timeout));
}

uint16_t updateCrc(uint16_t crc, const uint8_t* data, std::size_t size)
{
    for (std::size_t i = 0; i < size; ++i) {
        crc ^= static_cast<uint16_t>(data[i]) << 8;
        for (uint8_t bit = 0; bit < 8; ++bit) {
            if ((crc & 0x8000) != 0) {
                crc = static_cast<uint16_t>((crc << 1) ^ 0x8005);
            } else {
                crc = static_cast<uint16_t>(crc << 1);
            }
        }
    }

    return crc;
}

std::vector<uint8_t> stuffPayload(const std::vector<uint8_t>& payload)
{
    std::vector<uint8_t> stuffed;
    stuffed.reserve(payload.size() + payload.size() / 8);

    for (uint8_t byte : payload) {
        stuffed.push_back(byte);
        const std::size_t n = stuffed.size();
        if (n >= 3 &&
            stuffed[n - 3] == 0xFF &&
            stuffed[n - 2] == 0xFF &&
            stuffed[n - 1] == 0xFD)
        {
            stuffed.push_back(0xFD);
        }
    }

    return stuffed;
}

std::vector<uint8_t> unstuffPayload(const uint8_t* data, std::size_t size)
{
    std::vector<uint8_t> payload;
    payload.reserve(size);

    for (std::size_t i = 0; i < size; ++i) {
        payload.push_back(data[i]);

        const std::size_t n = payload.size();
        if (n >= 4 &&
            payload[n - 4] == 0xFF &&
            payload[n - 3] == 0xFF &&
            payload[n - 2] == 0xFD &&
            payload[n - 1] == 0xFD)
        {
            payload.pop_back();
        }
    }

    return payload;
}

speed_t baudToTermios(unsigned int baudrate)
{
    switch (baudrate) {
    case 9600: return B9600;
    case 19200: return B19200;
    case 38400: return B38400;
    case 57600: return B57600;
    case 115200: return B115200;
#ifdef B230400
    case 230400: return B230400;
#endif
#ifdef B460800
    case 460800: return B460800;
#endif
#ifdef B500000
    case 500000: return B500000;
#endif
#ifdef B576000
    case 576000: return B576000;
#endif
#ifdef B921600
    case 921600: return B921600;
#endif
#ifdef B1000000
    case 1000000: return B1000000;
#endif
#ifdef B1152000
    case 1152000: return B1152000;
#endif
#ifdef B1500000
    case 1500000: return B1500000;
#endif
#ifdef B2000000
    case 2000000: return B2000000;
#endif
#ifdef B2500000
    case 2500000: return B2500000;
#endif
#ifdef B3000000
    case 3000000: return B3000000;
#endif
#ifdef B3500000
    case 3500000: return B3500000;
#endif
#ifdef B4000000
    case 4000000: return B4000000;
#endif
    default:
        throw std::runtime_error("Unsupported serial baudrate.");
    }
}


// Feetech packet checksum · ~(ID + LEN + INST/ERR + parameters) · robot_web fix-list 158
uint8_t scsChecksum(const uint8_t* data, std::size_t size)
{
    uint32_t sum = 0;
    for (std::size_t i = 0; i < size; ++i) sum += data[i];
    return static_cast<uint8_t>(~sum & 0xFF);
}

} // namespace
serial::SerialMaster::SerialMaster(const motor_interface::master_config_t& config)
    : motor_interface::MotorMaster(config)
    , port_(config.serial_port)
    , baudrate_(config.serial_baudrate)
{
}

serial::SerialMaster::~SerialMaster()
{
    deactivate();
}

void serial::SerialMaster::initialize()
{
    if (port_.empty()) throw std::runtime_error("Serial port is empty.");

    latency_timer_ms_ = readUsbLatencyTimerMs(port_);

    fd_ = ::open(port_.c_str(), O_RDWR | O_NOCTTY | O_NONBLOCK);
    if (fd_ < 0) throw std::runtime_error("Failed to open serial port.");

    termios tio{};
    tio.c_cflag = baudToTermios(baudrate_) | CS8 | CLOCAL | CREAD;
    tio.c_iflag = IGNPAR;
    tio.c_oflag = 0;
    tio.c_lflag = 0;
    tio.c_cc[VTIME] = 0;
    tio.c_cc[VMIN] = 0;

    if (::tcflush(fd_, TCIOFLUSH) != 0) {
        deactivate();
        throw std::runtime_error("Failed to flush serial port.");
    }

    if (::tcsetattr(fd_, TCSANOW, &tio) != 0) {
        deactivate();
        throw std::runtime_error("Failed to configure serial port.");
    }
}

void serial::SerialMaster::activate()
{
}

void serial::SerialMaster::deactivate()
{
    if (fd_ >= 0) {
        ::close(fd_);
        fd_ = -1;
    }
}

void serial::SerialMaster::markOffline()
{
    deactivate();
    rx_buffer_.clear();
    last_tx_.clear();

    // A goal written before the failure must not go out after the reconnect
    for (auto& node : nodes_) {
        if (!node.registered) continue;
        node.missed_responses = UINT16_MAX;
        for (uint8_t j = 0; j < node.number_of_rx_entries; ++j) {
            node.rx_entries[j].dirty = false;
        }
    }
}

void serial::SerialMaster::reopen()
{
    deactivate();
    rx_buffer_.clear();
    last_tx_.clear();
    initialize();
    ++generation_;
}

void serial::SerialMaster::transmit()
{
    if (fd_ < 0) return;

    bool sent[motor_interface::MAX_CONTROLLER_SIZE][motor_interface::MAX_INTERFACE_SIZE]{};

    for (uint8_t i = 0; i < motor_interface::MAX_CONTROLLER_SIZE; ++i) {
        serial_node_data_t& node = nodes_[i];
        if (!node.registered) continue;

        for (uint8_t j = 0; j < node.number_of_rx_entries; ++j) {
            serial_bulk_entry_t& entry = node.rx_entries[j];
            if (!entry.dirty || sent[i][j]) continue;

            std::vector<serial_node_data_t*> group;
            for (uint8_t ni = i; ni < motor_interface::MAX_CONTROLLER_SIZE; ++ni) {
                serial_node_data_t& candidate = nodes_[ni];
                if (!candidate.registered) continue;

                for (uint8_t ei = 0; ei < candidate.number_of_rx_entries; ++ei) {
                    serial_bulk_entry_t& other = candidate.rx_entries[ei];
                    if (!other.dirty || sent[ni][ei]) continue;
                    if (other.address != entry.address || other.size != entry.size) continue;

                    group.push_back(&candidate);
                    sent[ni][ei] = true;
                    break;
                }
            }

            if (isScs()) {
                syncWrite(entry.address, entry.size, group);
            } else {
                bulkWrite(entry.address, entry.size, group);
            }
        }
    }
}

void serial::SerialMaster::receive()
{
    if (fd_ < 0) {
        for (auto& node : nodes_) {
            if (node.registered) node.missed_responses = UINT16_MAX;
        }
        return;
    }

    if (read_plan_dirty_) buildReadPlan();

    uint8_t max_spans = 0;
    for (auto& node : nodes_) {
        if (!node.registered) continue;
        for (uint8_t k = 0; k < node.number_of_spans; ++k) node.spans[k].answered = false;
        max_spans = std::max(max_spans, node.number_of_spans);
    }

    for (uint8_t k = 0; k < max_spans; ++k) {
        std::vector<serial_node_data_t*> nodes;
        for (auto& node : nodes_) {
            if (node.registered && node.number_of_spans > k) nodes.push_back(&node);
        }

        if (isScs()) {
            syncReadSpans(k, nodes);
        } else {
            bulkReadSpans(k, nodes);
        }
    }

    // A node counts as answering only when every span came back this cycle ·
    // the controller reports COMMUNICATION_UNAVAILABLE after a run of misses
    for (auto& node : nodes_) {
        if (!node.registered || node.number_of_spans == 0) continue;

        bool answered = true;
        for (uint8_t k = 0; k < node.number_of_spans; ++k) {
            answered = answered && node.spans[k].answered;
        }

        if (answered) {
            node.missed_responses = 0;
        } else if (node.missed_responses < UINT16_MAX) {
            ++node.missed_responses;
        }
    }
}

void serial::SerialMaster::apply_application_time(const timespec& time)
{
    (void)time;
}

void serial::SerialMaster::save_clock()
{
}

void serial::SerialMaster::registerNode(uint8_t node_id)
{
    ensureProtocolConfigured();

    if (node_id >= protocol_.broadcast_id) throw std::runtime_error("Invalid serial node ID.");
    if (findNode(node_id)) return;

    for (auto& node : nodes_) {
        if (node.registered) continue;
        node = serial_node_data_t{};
        node.registered = true;
        node.node_id = node_id;
        read_plan_dirty_ = true;
        return;
    }

    throw std::runtime_error("Too many serial nodes.");
}

void serial::SerialMaster::configureProtocol(const serial::serial_protocol_config_t& protocol)
{
    if (!protocol.configured) throw std::runtime_error("Serial protocol is not configured by driver.");

    if (protocol_.configured) {
        const bool same =
            protocol_.packet == protocol.packet &&
            protocol_.broadcast_id == protocol.broadcast_id &&
            protocol_.instruction_read == protocol.instruction_read &&
            protocol_.instruction_write == protocol.instruction_write &&
            protocol_.instruction_status == protocol.instruction_status &&
            protocol_.instruction_bulk_read == protocol.instruction_bulk_read &&
            protocol_.instruction_bulk_write == protocol.instruction_bulk_write &&
            protocol_.instruction_sync_read == protocol.instruction_sync_read &&
            protocol_.instruction_sync_write == protocol.instruction_sync_write &&
            protocol_.instruction_reboot == protocol.instruction_reboot;

        // One port carries one kind of servo (Dynamixel and Feetech never share a bus)
        if (!same) throw std::runtime_error("Conflicting serial protocol configuration on one master.");
        return;
    }

    protocol_ = protocol;
}

serial::serial_node_data_t* serial::SerialMaster::node(uint8_t node_id)
{
    return findNode(node_id);
}

void serial::SerialMaster::registerBulkWrite(uint8_t node_id, uint16_t address, uint8_t size)
{
    if (size == 0 || size > motor_interface::MAX_DATA_SIZE) {
        throw std::runtime_error("Invalid Dynamixel bulk-write size.");
    }
    if (isScs() && address + size > 0x100) {
        throw std::runtime_error("Feetech register address must be below 256.");
    }

    serial_node_data_t* n = findNode(node_id);
    if (!n) throw std::runtime_error("Serial node is not registered.");

    if (findEntry(n->rx_entries, n->number_of_rx_entries, address, size)) return;
    if (n->number_of_rx_entries >= motor_interface::MAX_INTERFACE_SIZE) {
        throw std::runtime_error("Too many serial bulk-write entries.");
    }

    n->rx_entries[n->number_of_rx_entries++] = serial_bulk_entry_t{address, size, {0}, false, false};
}

void serial::SerialMaster::registerBulkRead(uint8_t node_id, uint16_t address, uint8_t size)
{
    if (size == 0 || size > motor_interface::MAX_DATA_SIZE) {
        throw std::runtime_error("Invalid Dynamixel bulk-read size.");
    }
    if (isScs() && address + size > 0x100) {
        throw std::runtime_error("Feetech register address must be below 256.");
    }

    serial_node_data_t* n = findNode(node_id);
    if (!n) throw std::runtime_error("Serial node is not registered.");

    if (findEntry(n->tx_entries, n->number_of_tx_entries, address, size)) return;
    if (n->number_of_tx_entries >= motor_interface::MAX_INTERFACE_SIZE) {
        throw std::runtime_error("Too many serial bulk-read entries.");
    }

    n->tx_entries[n->number_of_tx_entries++] = serial_bulk_entry_t{address, size, {0}, false, false};
    read_plan_dirty_ = true;
}

bool serial::SerialMaster::setBulkWriteData(uint8_t node_id, uint16_t address, const uint8_t* data, uint8_t size)
{
    serial_node_data_t* n = findNode(node_id);
    if (!n) return false;

    serial_bulk_entry_t* e = findEntry(n->rx_entries, n->number_of_rx_entries, address, size);
    if (!e) return false;

    std::memcpy(e->data, data, size);
    e->dirty = true;
    return true;
}

bool serial::SerialMaster::getBulkReadData(uint8_t node_id, uint16_t address, uint8_t* data, uint8_t size)
{
    serial_node_data_t* n = findNode(node_id);
    if (!n) return false;

    serial_bulk_entry_t* e = findEntry(n->tx_entries, n->number_of_tx_entries, address, size);
    if (!e || !e->updated) return false;

    std::memcpy(data, e->data, size);
    return true;
}

bool serial::SerialMaster::writeRegister(uint8_t node_id, uint16_t address, const uint8_t* data, uint8_t size)
{
    ensureProtocolConfigured();

    if (size == 0 || size > motor_interface::MAX_DATA_SIZE || node_id >= protocol_.broadcast_id) return false;
    if (isScs() && address + size > 0x100) return false;

    std::vector<uint8_t> parameters;
    parameters.reserve(2 + size);
    appendAddress(parameters, address);
    parameters.insert(parameters.end(), data, data + size);

    sendPacket(node_id, protocol_.instruction_write, parameters);

    const uint64_t deadline = nowNs() + SERIAL_TIMEOUT_MS * NSEC_PER_MSEC;
    while (nowNs() < deadline) {
        status_packet_t status{};
        if (!receiveStatus(status, SERIAL_TIMEOUT_MS)) return false;
        if (status.id != node_id) continue;

        noteResponse(node_id, status.error);
        return !isPacketFailure(status.error);
    }

    return false;
}

bool serial::SerialMaster::readRegister(uint8_t node_id, uint16_t address, uint8_t* data, uint8_t size)
{
    ensureProtocolConfigured();

    if (size == 0 || size > motor_interface::MAX_DATA_SIZE || node_id >= protocol_.broadcast_id) return false;
    if (isScs() && address + size > 0x100) return false;

    std::vector<uint8_t> parameters;
    parameters.reserve(4);
    appendAddress(parameters, address);
    appendLength(parameters, size);

    sendPacket(node_id, protocol_.instruction_read, parameters);

    const uint64_t deadline = nowNs() + SERIAL_TIMEOUT_MS * NSEC_PER_MSEC;
    while (nowNs() < deadline) {
        status_packet_t status{};
        if (!receiveStatus(status, SERIAL_TIMEOUT_MS)) return false;
        if (status.id != node_id) continue;

        noteResponse(node_id, status.error);
        if (isPacketFailure(status.error) || status.parameters.size() < size) return false;

        std::memcpy(data, status.parameters.data(), size);
        return true;
    }

    return false;
}

bool serial::SerialMaster::reboot(uint8_t node_id)
{
    ensureProtocolConfigured();

    // No reboot on this bus (Feetech) · never fall back to another instruction:
    // Feetech 0x06 RESET is a factory reset (ID · baud rate · limits) · fix-list 158
    if (!supportsReboot()) return false;
    if (node_id >= protocol_.broadcast_id) return false;

    // The device answers first, then restarts (torque off, RAM items back to
    // defaults, hardware error cleared) · robot_web fix-list 24-1
    sendPacket(node_id, protocol_.instruction_reboot, {});

    const uint64_t deadline = nowNs() + SERIAL_TIMEOUT_MS * NSEC_PER_MSEC;
    while (nowNs() < deadline) {
        status_packet_t status{};
        if (!receiveStatus(status, SERIAL_TIMEOUT_MS)) return false;
        if (status.id != node_id) continue;

        noteResponse(node_id, status.error);
        return !isPacketFailure(status.error);
    }

    return false;
}

void serial::SerialMaster::noteResponse(uint8_t node_id, uint8_t error)
{
    // Only the packet error · the cycle read (receive) owns missed_responses
    serial_node_data_t* n = findNode(node_id);
    if (!n) return;
    n->last_packet_error = error;
}

serial::serial_node_data_t* serial::SerialMaster::findNode(uint8_t node_id)
{
    for (auto& node : nodes_) {
        if (node.registered && node.node_id == node_id) return &node;
    }

    return nullptr;
}

const serial::serial_node_data_t* serial::SerialMaster::findNode(uint8_t node_id) const
{
    for (const auto& node : nodes_) {
        if (node.registered && node.node_id == node_id) return &node;
    }

    return nullptr;
}

serial::serial_bulk_entry_t* serial::SerialMaster::findEntry(
    serial_bulk_entry_t* entries,
    uint8_t count,
    uint16_t address,
    uint8_t size)
{
    for (uint8_t i = 0; i < count; ++i) {
        if (entries[i].address == address && entries[i].size == size) return &entries[i];
    }

    return nullptr;
}

const serial::serial_bulk_entry_t* serial::SerialMaster::findEntry(
    const serial_bulk_entry_t* entries,
    uint8_t count,
    uint16_t address,
    uint8_t size) const
{
    for (uint8_t i = 0; i < count; ++i) {
        if (entries[i].address == address && entries[i].size == size) return &entries[i];
    }

    return nullptr;
}

bool serial::SerialMaster::isPacketFailure(uint8_t error) const
{
    // Scs status error byte = servo state bits (voltage · sensor · temperature ·
    // current · overload), not a packet error · the data is still valid
    if (isScs()) return false;
    return (error & static_cast<uint8_t>(~DXL_ALERT_BIT)) != 0;
}

void serial::SerialMaster::appendAddress(std::vector<uint8_t>& data, uint16_t address) const
{
    if (isScs()) {
        data.push_back(static_cast<uint8_t>(address & 0xFF));
    } else {
        appendLe16(data, address);
    }
}

void serial::SerialMaster::appendLength(std::vector<uint8_t>& data, uint16_t length) const
{
    if (isScs()) {
        data.push_back(static_cast<uint8_t>(length & 0xFF));
    } else {
        appendLe16(data, length);
    }
}

std::size_t serial::SerialMaster::statusOverhead() const
{
    // Dxl2 · FF FF FD 00 · ID · LEN(2) · INST · ERR · CRC(2) · Scs · FF FF · ID · LEN · ERR · CHK
    return isScs() ? 6U : 11U;
}

void serial::SerialMaster::sendPacket(uint8_t id, uint8_t instruction, const std::vector<uint8_t>& parameters)
{
    ensureProtocolConfigured();

    if (fd_ < 0) throw std::runtime_error("Serial port is not initialized.");

    std::vector<uint8_t> packet;

    if (isScs()) {
        if (parameters.size() + 2 > 0xFF) throw std::runtime_error("Feetech packet is too large.");

        packet.reserve(6 + parameters.size());
        packet.push_back(0xFF);
        packet.push_back(0xFF);
        packet.push_back(id);
        packet.push_back(static_cast<uint8_t>(parameters.size() + 2));
        packet.push_back(instruction);
        packet.insert(packet.end(), parameters.begin(), parameters.end());
        packet.push_back(scsChecksum(packet.data() + 2, packet.size() - 2));
    } else {
        std::vector<uint8_t> payload;
        payload.reserve(1 + parameters.size());
        payload.push_back(instruction);
        payload.insert(payload.end(), parameters.begin(), parameters.end());

        const std::vector<uint8_t> stuffed_payload = stuffPayload(payload);
        if (stuffed_payload.size() + 2 > 0xFFFF) throw std::runtime_error("Dynamixel packet is too large.");

        packet.reserve(7 + stuffed_payload.size() + 2);
        packet.push_back(0xFF);
        packet.push_back(0xFF);
        packet.push_back(0xFD);
        packet.push_back(0x00);
        packet.push_back(id);
        appendLe16(packet, static_cast<uint16_t>(stuffed_payload.size() + 2));
        packet.insert(packet.end(), stuffed_payload.begin(), stuffed_payload.end());

        const uint16_t crc = updateCrc(0, packet.data(), packet.size());
        appendLe16(packet, crc);
    }

    flushInput();
    writeExact(packet.data(), packet.size());
    last_tx_ = packet;
}

bool serial::SerialMaster::receiveStatus(status_packet_t& packet, uint32_t timeout_ms)
{
    ensureProtocolConfigured();

    if (fd_ < 0) throw std::runtime_error("Serial port is not initialized.");

    rx_buffer_.reserve(MAX_PACKET_SIZE);

    const uint64_t deadline = nowNs() + static_cast<uint64_t>(timeout_ms) * NSEC_PER_MSEC;
    while (nowNs() < deadline) {
        uint8_t temp[128]{};
        const ssize_t n = ::read(fd_, temp, sizeof(temp));
        if (n > 0) {
            rx_buffer_.insert(rx_buffer_.end(), temp, temp + n);
        } else if (n < 0 && errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR) {
            return false;
        }

        if (isScs() ? parseScsStatus(packet) : parseDxl2Status(packet)) return true;

        if (n <= 0) sleepBriefly();
    }

    return false;
}

bool serial::SerialMaster::parseDxl2Status(status_packet_t& packet)
{
    while (rx_buffer_.size() >= 4) {
        static constexpr uint8_t HEADER[] = {0xFF, 0xFF, 0xFD};
        auto header = std::search(
            rx_buffer_.begin(),
            rx_buffer_.end(),
            std::begin(HEADER),
            std::end(HEADER));

        if (header == rx_buffer_.end()) {
            if (rx_buffer_.size() > 3) rx_buffer_.erase(rx_buffer_.begin(), rx_buffer_.end() - 3);
            break;
        }

        if (header != rx_buffer_.begin()) {
            rx_buffer_.erase(rx_buffer_.begin(), header);
        }

        if (rx_buffer_.size() < 7) break;

        if (rx_buffer_[3] != 0x00) {
            rx_buffer_.erase(rx_buffer_.begin());
            continue;
        }

        const uint16_t length = readLe16(rx_buffer_[5], rx_buffer_[6]);
        if (length < 4 || length > MAX_PACKET_SIZE - 7) {
            rx_buffer_.erase(rx_buffer_.begin());
            continue;
        }

        const std::size_t total = static_cast<std::size_t>(length) + 7;
        if (rx_buffer_.size() < total) break;

        const uint16_t expected_crc = readLe16(rx_buffer_[total - 2], rx_buffer_[total - 1]);
        const uint16_t actual_crc = updateCrc(0, rx_buffer_.data(), total - 2);
        if (actual_crc != expected_crc) {
            rx_buffer_.erase(rx_buffer_.begin());
            continue;
        }

        const std::size_t encoded_payload_size = static_cast<std::size_t>(length) - 2;
        const std::vector<uint8_t> payload = unstuffPayload(rx_buffer_.data() + 7, encoded_payload_size);
        if (payload.size() < 2 || payload[0] != protocol_.instruction_status) {
            rx_buffer_.erase(rx_buffer_.begin());
            continue;
        }

        packet.id = rx_buffer_[4];
        packet.error = payload[1];
        packet.parameters.assign(payload.begin() + 2, payload.end());
        rx_buffer_.erase(rx_buffer_.begin(), rx_buffer_.begin() + total);
        return true;
    }

    return false;
}

bool serial::SerialMaster::parseScsStatus(status_packet_t& packet)
{
    while (rx_buffer_.size() >= 2) {
        static constexpr uint8_t HEADER[] = {0xFF, 0xFF};
        auto header = std::search(
            rx_buffer_.begin(),
            rx_buffer_.end(),
            std::begin(HEADER),
            std::end(HEADER));

        if (header == rx_buffer_.end()) {
            // Keep a trailing FF · it may be the first half of the next header
            if (rx_buffer_.back() == 0xFF) {
                rx_buffer_.erase(rx_buffer_.begin(), rx_buffer_.end() - 1);
            } else {
                rx_buffer_.clear();
            }
            break;
        }

        if (header != rx_buffer_.begin()) {
            rx_buffer_.erase(rx_buffer_.begin(), header);
        }

        if (rx_buffer_.size() < 4) break;

        const uint8_t id = rx_buffer_[2];
        const uint8_t length = rx_buffer_[3];
        if (id == 0xFF || length < 2) {
            rx_buffer_.erase(rx_buffer_.begin());
            continue;
        }

        const std::size_t total = static_cast<std::size_t>(length) + 4;
        if (rx_buffer_.size() < total) break;

        if (scsChecksum(rx_buffer_.data() + 2, total - 3) != rx_buffer_[total - 1]) {
            rx_buffer_.erase(rx_buffer_.begin());
            continue;
        }

        // An adapter that echoes what we sent would hand our own instruction
        // back as a "status" (same layout) · skip it
        const bool echo =
            id == protocol_.broadcast_id ||
            (last_tx_.size() == total && std::equal(last_tx_.begin(), last_tx_.end(), rx_buffer_.begin()));
        if (echo) {
            rx_buffer_.erase(rx_buffer_.begin(), rx_buffer_.begin() + total);
            continue;
        }

        packet.id = id;
        packet.error = rx_buffer_[4];
        packet.parameters.assign(rx_buffer_.begin() + 5, rx_buffer_.begin() + total - 1);
        rx_buffer_.erase(rx_buffer_.begin(), rx_buffer_.begin() + total);
        return true;
    }

    return false;
}

bool serial::SerialMaster::readExact(uint8_t* data, std::size_t size, uint64_t deadline_ns)
{
    std::size_t offset = 0;
    while (offset < size && nowNs() < deadline_ns) {
        const ssize_t n = ::read(fd_, data + offset, size - offset);
        if (n > 0) {
            offset += static_cast<std::size_t>(n);
        } else if (n < 0 && errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR) {
            return false;
        } else {
            sleepBriefly();
        }
    }

    return offset == size;
}

void serial::SerialMaster::writeExact(const uint8_t* data, std::size_t size)
{
    std::size_t offset = 0;
    while (offset < size) {
        const ssize_t n = ::write(fd_, data + offset, size - offset);
        if (n > 0) {
            offset += static_cast<std::size_t>(n);
        } else if (n < 0 && errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR) {
            throw std::runtime_error("Failed to write serial packet.");
        } else {
            sleepBriefly();
        }
    }

    if (::tcdrain(fd_) != 0) throw std::runtime_error("Failed to drain serial port.");
}

void serial::SerialMaster::flushInput()
{
    rx_buffer_.clear();
    if (fd_ >= 0) (void)::tcflush(fd_, TCIFLUSH);
}

void serial::SerialMaster::ensureProtocolConfigured() const
{
    if (!protocol_.configured) throw std::runtime_error("Serial protocol is not configured.");
}

void serial::SerialMaster::buildReadPlan()
{
    for (auto& node : nodes_) {
        if (!node.registered) continue;

        std::vector<std::pair<uint16_t, uint16_t>> entries;
        for (uint8_t j = 0; j < node.number_of_tx_entries; ++j) {
            entries.emplace_back(node.tx_entries[j].address, node.tx_entries[j].size);
        }
        std::sort(entries.begin(), entries.end());

        node.number_of_spans = 0;
        for (const auto& [address, size] : entries) {
            const uint32_t end = static_cast<uint32_t>(address) + size;
            if (node.number_of_spans > 0) {
                serial_read_span_t& last = node.spans[node.number_of_spans - 1];
                const uint32_t last_end = static_cast<uint32_t>(last.address) + last.size;
                const uint32_t merged_end = std::max(last_end, end);
                if (address <= last_end + READ_SPAN_MERGE_GAP &&
                    merged_end - last.address <= MAX_READ_SPAN_SIZE)
                {
                    last.size = static_cast<uint16_t>(merged_end - last.address);
                    continue;
                }
            }

            if (node.number_of_spans >= MAX_READ_SPANS) {
                throw std::runtime_error("Serial read entries are too far apart (more than 4 read spans).");
            }
            node.spans[node.number_of_spans++] = serial_read_span_t{address, size, false};
        }
    }

    read_plan_dirty_ = false;
}

void serial::SerialMaster::storeSpan(
    serial_node_data_t& node,
    uint8_t span_index,
    const std::vector<uint8_t>& parameters)
{
    serial_read_span_t& span = node.spans[span_index];
    span.answered = true;
    if (parameters.size() < span.size) return;

    for (uint8_t j = 0; j < node.number_of_tx_entries; ++j) {
        serial_bulk_entry_t& entry = node.tx_entries[j];
        if (entry.address < span.address || entry.address + entry.size > span.address + span.size) continue;

        std::memcpy(entry.data, parameters.data() + (entry.address - span.address), entry.size);
        entry.updated = true;
    }
}

void serial::SerialMaster::bulkReadSpans(uint8_t span_index, const std::vector<serial_node_data_t*>& nodes)
{
    ensureProtocolConfigured();

    if (nodes.empty()) return;

    std::vector<uint8_t> parameters;
    parameters.reserve(nodes.size() * 5);
    std::size_t expected_response_bytes = 0;
    for (const serial_node_data_t* node : nodes) {
        const serial_read_span_t& span = node->spans[span_index];
        parameters.push_back(node->node_id);
        appendLe16(parameters, span.address);
        appendLe16(parameters, span.size);
        expected_response_bytes += static_cast<std::size_t>(span.size) + statusOverhead();
    }

    sendPacket(protocol_.broadcast_id, protocol_.instruction_bulk_read, parameters);

    // Dynamixel SDK waits for sum(data_length + 10) bytes and includes the
    // Linux USB-serial latency timer. A fixed 1-3 ms timeout drops valid
    // BulkRead replies on the default 16 ms latency setting.
    const uint32_t timeout_ms =
        packetTimeoutMs(SERIAL_RUNTIME_TIMEOUT_MS, baudrate_, expected_response_bytes, latency_timer_ms_);
    std::vector<serial_node_data_t*> remaining = nodes;
    const uint64_t deadline = nowNs() + static_cast<uint64_t>(timeout_ms) * NSEC_PER_MSEC;
    while (!remaining.empty() && nowNs() < deadline) {
        status_packet_t status{};
        const uint32_t receive_timeout_ms = remainingTimeoutMs(deadline);
        if (receive_timeout_ms == 0 || !receiveStatus(status, receive_timeout_ms)) break;

        auto it = std::find_if(remaining.begin(), remaining.end(), [&](const serial_node_data_t* node) {
            return node->node_id == status.id;
        });
        if (it == remaining.end()) continue;

        noteResponse(status.id, status.error);
        if (isPacketFailure(status.error)) {
            (*it)->spans[span_index].answered = true;
        } else {
            storeSpan(**it, span_index, status.parameters);
        }

        remaining.erase(it);
    }
}

void serial::SerialMaster::syncReadSpans(uint8_t span_index, const std::vector<serial_node_data_t*>& nodes)
{
    ensureProtocolConfigured();

    if (protocol_.instruction_sync_read == 0) {
        for (serial_node_data_t* node : nodes) readSpanSingle(*node, span_index);
        return;
    }

    // Sync Read asks every node for the same address and size
    std::vector<bool> done(nodes.size(), false);
    for (std::size_t i = 0; i < nodes.size(); ++i) {
        if (done[i]) continue;

        const serial_read_span_t& span = nodes[i]->spans[span_index];
        std::vector<serial_node_data_t*> group;
        for (std::size_t j = i; j < nodes.size(); ++j) {
            const serial_read_span_t& other = nodes[j]->spans[span_index];
            if (done[j] || other.address != span.address || other.size != span.size) continue;
            group.push_back(nodes[j]);
            done[j] = true;
        }

        std::vector<uint8_t> parameters;
        parameters.reserve(2 + group.size());
        parameters.push_back(static_cast<uint8_t>(span.address & 0xFF));
        parameters.push_back(static_cast<uint8_t>(span.size & 0xFF));
        for (const serial_node_data_t* node : group) parameters.push_back(node->node_id);

        sendPacket(protocol_.broadcast_id, protocol_.instruction_sync_read, parameters);

        const std::size_t expected_response_bytes = group.size() * (static_cast<std::size_t>(span.size) + statusOverhead());
        const uint32_t timeout_ms =
            packetTimeoutMs(SERIAL_RUNTIME_TIMEOUT_MS, baudrate_, expected_response_bytes, latency_timer_ms_);
        const uint64_t deadline = nowNs() + static_cast<uint64_t>(timeout_ms) * NSEC_PER_MSEC;
        while (!group.empty() && nowNs() < deadline) {
            status_packet_t status{};
            const uint32_t receive_timeout_ms = remainingTimeoutMs(deadline);
            if (receive_timeout_ms == 0 || !receiveStatus(status, receive_timeout_ms)) break;

            auto it = std::find_if(group.begin(), group.end(), [&](const serial_node_data_t* node) {
                return node->node_id == status.id;
            });
            if (it == group.end()) continue;

            noteResponse(status.id, status.error);
            storeSpan(**it, span_index, status.parameters);
            group.erase(it);
        }
    }
}

void serial::SerialMaster::readSpanSingle(serial_node_data_t& node, uint8_t span_index)
{
    const serial_read_span_t& span = node.spans[span_index];

    std::vector<uint8_t> parameters;
    parameters.reserve(4);
    appendAddress(parameters, span.address);
    appendLength(parameters, span.size);

    sendPacket(node.node_id, protocol_.instruction_read, parameters);

    const uint32_t timeout_ms = packetTimeoutMs(
        SERIAL_RUNTIME_TIMEOUT_MS, baudrate_, static_cast<std::size_t>(span.size) + statusOverhead(), latency_timer_ms_);
    const uint64_t deadline = nowNs() + static_cast<uint64_t>(timeout_ms) * NSEC_PER_MSEC;
    while (nowNs() < deadline) {
        status_packet_t status{};
        const uint32_t receive_timeout_ms = remainingTimeoutMs(deadline);
        if (receive_timeout_ms == 0 || !receiveStatus(status, receive_timeout_ms)) return;
        if (status.id != node.node_id) continue;

        noteResponse(status.id, status.error);
        if (isPacketFailure(status.error)) {
            node.spans[span_index].answered = true;
        } else {
            storeSpan(node, span_index, status.parameters);
        }
        return;
    }
}

void serial::SerialMaster::bulkWrite(uint16_t address, uint8_t size, const std::vector<serial_node_data_t*>& nodes)
{
    ensureProtocolConfigured();

    if (nodes.empty()) return;

    std::vector<uint8_t> parameters;
    parameters.reserve(nodes.size() * (5 + size));

    for (serial_node_data_t* node : nodes) {
        if (!node) continue;

        serial_bulk_entry_t* entry = findEntry(node->rx_entries, node->number_of_rx_entries, address, size);
        if (!entry || !entry->dirty) continue;

        parameters.push_back(node->node_id);
        appendLe16(parameters, address);
        appendLe16(parameters, size);
        parameters.insert(parameters.end(), entry->data, entry->data + size);
    }

    if (parameters.empty()) return;

    sendPacket(protocol_.broadcast_id, protocol_.instruction_bulk_write, parameters);

    for (serial_node_data_t* node : nodes) {
        if (!node) continue;
        serial_bulk_entry_t* entry = findEntry(node->rx_entries, node->number_of_rx_entries, address, size);
        if (entry) entry->dirty = false;
    }
}

void serial::SerialMaster::syncWrite(uint16_t address, uint8_t size, const std::vector<serial_node_data_t*>& nodes)
{
    ensureProtocolConfigured();

    if (nodes.empty()) return;

    if (protocol_.instruction_sync_write == 0) {
        // No group write · one WRITE per node (each answers)
        for (serial_node_data_t* node : nodes) {
            if (!node) continue;
            serial_bulk_entry_t* entry = findEntry(node->rx_entries, node->number_of_rx_entries, address, size);
            if (!entry || !entry->dirty) continue;
            entry->dirty = false;
            (void)writeRegister(node->node_id, address, entry->data, size);
        }
        return;
    }

    std::vector<uint8_t> parameters;
    parameters.reserve(2 + nodes.size() * (1 + size));
    parameters.push_back(static_cast<uint8_t>(address & 0xFF));
    parameters.push_back(size);

    bool any = false;
    for (serial_node_data_t* node : nodes) {
        if (!node) continue;

        serial_bulk_entry_t* entry = findEntry(node->rx_entries, node->number_of_rx_entries, address, size);
        if (!entry || !entry->dirty) continue;

        parameters.push_back(node->node_id);
        parameters.insert(parameters.end(), entry->data, entry->data + size);
        any = true;
    }

    if (!any) return;

    sendPacket(protocol_.broadcast_id, protocol_.instruction_sync_write, parameters);

    for (serial_node_data_t* node : nodes) {
        if (!node) continue;
        serial_bulk_entry_t* entry = findEntry(node->rx_entries, node->number_of_rx_entries, address, size);
        if (entry) entry->dirty = false;
    }
}
