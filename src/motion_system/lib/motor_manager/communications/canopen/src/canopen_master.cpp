#include <cerrno>
#include <cstring>
#include <stdexcept>
#include <string>

#include <fcntl.h>
#include <unistd.h>
#include <net/if.h>
#include <sys/ioctl.h>
#include <sys/socket.h>

#include "canopen/canopen_master.hpp"

namespace {

constexpr uint64_t SDO_TIMEOUT_NS = 1000000000ULL; // 1 second

uint64_t nowNs()
{
    timespec t{};
    if (::clock_gettime(CLOCK_MONOTONIC, &t) != 0) {
        throw std::runtime_error("clock_gettime failed.");
    }

    return static_cast<uint64_t>(t.tv_sec) * 1000000000ULL +
            static_cast<uint64_t>(t.tv_nsec);
}   
    
} // namespace

void canopen::CanopenMaster::initialize()
{
    socket_ = ::socket(PF_CAN, SOCK_RAW | SOCK_NONBLOCK, CAN_RAW);
    if (socket_ < 0) {
        ::close(socket_);
        socket_ = -1;
        throw std::runtime_error("Failed to create CAN socket.");
    }

    const int flags = ::fcntl(socket_, F_GETFL, 0);
    if (flags < 0) {
        ::close(socket_);
        socket_ = -1;
        throw std::runtime_error("Failed to get CAN socket flags.");
    }

    if (::fcntl(socket_, F_SETFL, flags | O_NONBLOCK) < 0) {
        ::close(socket_);
        socket_ = -1;
        throw std::runtime_error("Failed to set CAN socket flags.");
    }

    const std::string interface_name = "can" + std::to_string(interface_index_);

    ifreq ifr {};
    std::strncpy(ifr.ifr_name, interface_name.c_str(), IFNAMSIZ - 1);

    if (::ioctl(socket_, SIOCGIFINDEX, &ifr) < 0) {
        ::close(socket_);
        socket_ = -1;
        throw std::runtime_error("Failed to get CAN interface index.");
    }

    sockaddr_can addr {};
    addr.can_family = AF_CAN;
    addr.can_ifindex = ifr.ifr_ifindex;

    if (::bind(socket_, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) < 0) {
        ::close(socket_);
        socket_ = -1;
        throw std::runtime_error("Failed to bind CAN socket.");
    }
}

void canopen::CanopenMaster::activate()
{
    sendNmt(canopen::NMT_START, 0x00);
}

void canopen::CanopenMaster::deactivate()
{
    // Debug: Disable NMT STOP
    //sendNmt(canopen::NMT_STOP, 0x00);

    if (socket_ >= 0) {
        ::close(socket_);
        socket_ = -1;
    }
}

void canopen::CanopenMaster::transmit()
{
    for (uint8_t node_id = 1; node_id < motor_interface::MAX_CONTROLLER_SIZE; ++node_id) {
        canopen_node_data_t& node = nodes_[node_id];

        if (!node.rpdo_dirty) continue;
        if (node.rpdo_size == 0 || node.rpdo_size > 16) throw std::runtime_error("Invalid RPDO size.");

        can_frame rpdo1 {};
        rpdo1.can_id = canopen::COB_RPDO1_BASE + node_id;
        rpdo1.can_dlc = node.rpdo_size > 8 ? 8 : node.rpdo_size;
        std::memcpy(rpdo1.data, node.rpdo, rpdo1.can_dlc);
        sendFrame(rpdo1);

        if (node.rpdo_size > 8) {
        can_frame rpdo2 {};
        rpdo2.can_id = canopen::COB_RPDO2_BASE + node_id;
        rpdo2.can_dlc = node.rpdo_size - 8;
        std::memcpy(rpdo2.data, node.rpdo + 8, rpdo2.can_dlc);
        sendFrame(rpdo2);
        }

        node.rpdo_dirty = false;
    }
}

void canopen::CanopenMaster::receive()
{
    can_frame frame {};

    while (receiveFrame(frame)) {
        const uint16_t cob_id = frame.can_id & CAN_SFF_MASK;

        if ((cob_id >= canopen::COB_TPDO1_BASE &&
             cob_id < canopen::COB_TPDO1_BASE + motor_interface::MAX_CONTROLLER_SIZE) || 
            (cob_id >= canopen::COB_TPDO2_BASE &&
             cob_id < canopen::COB_TPDO2_BASE + motor_interface::MAX_CONTROLLER_SIZE))
        {
            processTpdo(frame);
        } else if (cob_id >= canopen::COB_HEARTBEAT &&
                   cob_id < canopen::COB_HEARTBEAT + motor_interface::MAX_CONTROLLER_SIZE)
        {
            processHeardbeat(frame);           
        }
    }
}

void canopen::CanopenMaster::apply_application_time(const timespec& time)
{
}

void canopen::CanopenMaster::save_clock()
{
}

void canopen::CanopenMaster::registerNodes(uint8_t node_id)
{
    if (node_id == 0 || node_id >= motor_interface::MAX_CONTROLLER_SIZE) throw std::runtime_error("Invalid node ID.");

    nodes_[node_id].node_id = node_id;
}

canopen::canopen_node_data_t* canopen::CanopenMaster::node(uint8_t node_id)
{
    nodes_[node_id].node_id = node_id;
    return &nodes_[node_id];
}

bool canopen::CanopenMaster::writeSdo(uint8_t node_id, uint16_t index, uint8_t subindex, const uint8_t* data, uint8_t size)
{
    can_frame req {};
    req.can_id = canopen::COB_SDO_RX + node_id;
    req.can_dlc = 8;

    if (size == 1) {
        req.data[0] = canopen::SDO_WRITE_1BYTE;
    } else if (size == 2) {
        req.data[0] = canopen::SDO_WRITE_2BYTE;
    } else if (size == 4) {
        req.data[0] = canopen::SDO_WRITE_4BYTE;
    } else {
        throw std::runtime_error("Invalid SDO size.");
    }

    req.data[1] = static_cast<uint8_t>(index & 0xFF);
    req.data[2] = static_cast<uint8_t>((index >> 8) & 0xFF);
    req.data[3] = subindex;

    std::memcpy(&req.data[4], data, size);
    sendFrame(req);

    can_frame res {};
    const uint64_t deadline = nowNs() + SDO_TIMEOUT_NS;

    while (nowNs() < deadline) {
        if (!receiveFrame(res)) {
            if (errno == EAGAIN || errno == EWOULDBLOCK) continue;
            return false;
        }

        const uint16_t cob_id = res.can_id & CAN_SFF_MASK;
        if (cob_id != canopen::COB_SDO_TX + node_id)  continue;

        if (res.data[0] == canopen::SDO_ABORT) return false;

        return res.data[0] == canopen::SDO_WRITE_RES &&
               res.data[1] == req.data[1] &&
               res.data[2] == req.data[2] &&
               res.data[3] == req.data[3];
    }

    return false;
}

bool canopen::CanopenMaster::readSdo(uint8_t node_id, uint16_t index, uint8_t subindex, uint8_t* data, uint8_t size)
{
    can_frame req {};
    req.can_id = canopen::COB_SDO_RX + node_id;
    req.can_dlc = 8;
    req.data[0] = canopen::SDO_READ_REQ;
    req.data[1] = static_cast<uint8_t>(index & 0xFF);
    req.data[2] = static_cast<uint8_t>((index >> 8) & 0xFF);
    req.data[3] = subindex;

    sendFrame(req);

    can_frame res {};
    const uint64_t deadline = nowNs() + SDO_TIMEOUT_NS;

    while (nowNs() < deadline) {
        if (!receiveFrame(res)) {
            if (errno == EAGAIN || errno == EWOULDBLOCK) continue;
            return false;
        }

        const uint16_t cob_id = res.can_id & CAN_SFF_MASK;
        if (cob_id != canopen::COB_SDO_TX + node_id) continue;

        if (res.data[0] == canopen::SDO_ABORT) return false;

        if (res.data[1] != req.data[1] ||
            res.data[2] != req.data[2] ||
            res.data[3] != req.data[3]) return false;

        std::memcpy(data, &res.data[4], size);
        return true;
    }

    return false;
}

void canopen::CanopenMaster::sendNmt(uint8_t command, uint8_t node_id)
{
    can_frame frame {};
    frame.can_id = canopen::COB_NMT;
    frame.can_dlc = 2;
    frame.data[0] = command;
    frame.data[1] = node_id;

    sendFrame(frame);
}

void canopen::CanopenMaster::sendFrame(const can_frame& frame)
{
    if (socket_ < 0) throw std::runtime_error("CAN socket not initialized.");

    const ssize_t n = ::write(socket_, &frame, sizeof(frame));
    if (n != static_cast<ssize_t>(sizeof(frame))) throw std::runtime_error("Failed to send CAN frame.");
}

bool canopen::CanopenMaster::receiveFrame(can_frame& frame)
{
    if (socket_ < 0) throw std::runtime_error("CAN socket not initialized.");

    const ssize_t n = ::read(socket_, &frame, sizeof(frame));
    if (n < 0) return false;

    return n == static_cast<ssize_t>(sizeof(frame));
}

void canopen::CanopenMaster::processTpdo(const can_frame& frame)
{
    const uint16_t cob_id = frame.can_id & CAN_SFF_MASK;

    uint8_t node_id = 0;
    uint8_t offset = 0;

    if (cob_id >= canopen::COB_TPDO1_BASE &&
        cob_id < canopen::COB_TPDO1_BASE + motor_interface::MAX_CONTROLLER_SIZE)
    {
        node_id = static_cast<uint8_t>(cob_id - canopen::COB_TPDO1_BASE);
        offset = 0;
    } else if (cob_id >= canopen::COB_TPDO2_BASE &&
               cob_id < canopen::COB_TPDO2_BASE + motor_interface::MAX_CONTROLLER_SIZE)
    {
        node_id = static_cast<uint8_t>(cob_id - canopen::COB_TPDO2_BASE);
        offset = 8;
    } else {
        return;
    }

    if (node_id ==0 || node_id > motor_interface::MAX_CONTROLLER_SIZE) return;
    if (offset + frame.can_dlc > 16) return;

    canopen_node_data_t& node = nodes_[node_id];

    node.node_id = node_id;
    std::memcpy(node.tpdo + offset, frame.data, frame.can_dlc);

    const uint8_t end = offset + frame.can_dlc;
    if (end > node.tpdo_size) node.tpdo_size = end;

    node.tpdo_updated = true;
}

void canopen::CanopenMaster::processHeardbeat(const can_frame& frame)
{
    const uint16_t cob_id = frame.can_id & CAN_SFF_MASK;
    const uint8_t node_id = static_cast<uint8_t>(cob_id - canopen::COB_HEARTBEAT);

    if (node_id == 0 || node_id > motor_interface::MAX_CONTROLLER_SIZE) return;

    nodes_[node_id].node_id = node_id;
}