#include <cerrno>
#include <cstring>
#include <stdexcept>
#include <string>

#include <fcntl.h>
#include <net/if.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <unistd.h>

#include <linux/can/raw.h>

#include "socketcan/socketcan_master.hpp"

void socketcan::SocketcanMaster::initialize()
{
    socket_ = ::socket(PF_CAN, SOCK_RAW | SOCK_NONBLOCK, CAN_RAW);
    if (socket_ < 0) throw std::runtime_error("Failed to create SocketCAN socket.");

    const int flags = ::fcntl(socket_, F_GETFL, 0);
    if (flags < 0) {
        deactivate();
        throw std::runtime_error("Failed to get SocketCAN socket flags.");
    }

    if (::fcntl(socket_, F_SETFL, flags | O_NONBLOCK) < 0) {
        deactivate();
        throw std::runtime_error("Failed to set SocketCAN socket flags.");
    }

    const int loopback = 1;
    (void)::setsockopt(socket_, SOL_CAN_RAW, CAN_RAW_LOOPBACK, &loopback, sizeof(loopback));

    const int receive_own_messages = 0;
    (void)::setsockopt(
        socket_, SOL_CAN_RAW, CAN_RAW_RECV_OWN_MSGS,
        &receive_own_messages, sizeof(receive_own_messages));

    const std::string interface_name = "can" + std::to_string(interface_index_);

    ifreq ifr{};
    std::strncpy(ifr.ifr_name, interface_name.c_str(), IFNAMSIZ - 1);

    if (::ioctl(socket_, SIOCGIFINDEX, &ifr) < 0) {
        deactivate();
        throw std::runtime_error("Failed to get SocketCAN interface index.");
    }

    sockaddr_can addr{};
    addr.can_family = AF_CAN;
    addr.can_ifindex = ifr.ifr_ifindex;

    if (::bind(socket_, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) < 0) {
        deactivate();
        throw std::runtime_error("Failed to bind SocketCAN socket.");
    }

    (void)bitrate_;
}

void socketcan::SocketcanMaster::activate()
{
}

void socketcan::SocketcanMaster::deactivate()
{
    if (socket_ >= 0) {
        ::close(socket_);
        socket_ = -1;
    }
}

void socketcan::SocketcanMaster::transmit()
{
    while (tx_count_ > 0) {
        const can_frame frame = tx_queue_[tx_head_];
        sendFrame(frame);

        tx_head_ = static_cast<uint16_t>((tx_head_ + 1) % MAX_SOCKETCAN_TX_QUEUE_SIZE);
        --tx_count_;
    }
}

void socketcan::SocketcanMaster::receive()
{
    can_frame frame{};
    while (receiveFrame(frame)) {
        pushRxFrame(frame);
    }
}

void socketcan::SocketcanMaster::apply_application_time(const timespec& time)
{
    (void)time;
}

void socketcan::SocketcanMaster::save_clock()
{
}

void socketcan::SocketcanMaster::registerNode(uint8_t node_id)
{
    if (!isValidNodeId(node_id)) throw std::runtime_error("Invalid SocketCAN node ID.");
    if (node(node_id)) return;

    for (auto& n : nodes_) {
        if (n.active) continue;

        n = socketcan_node_data_t{};
        n.node_id = node_id;
        n.active = true;
        return;
    }

    throw std::runtime_error("Too many SocketCAN nodes.");
}

socketcan::socketcan_node_data_t* socketcan::SocketcanMaster::node(uint8_t node_id)
{
    for (auto& n : nodes_) {
        if (n.active && n.node_id == node_id) return &n;
    }

    return nullptr;
}

void socketcan::SocketcanMaster::enqueueFrame(const can_frame& frame)
{
    if (!pushTxFrame(frame)) throw std::runtime_error("SocketCAN TX queue is full.");
}

bool socketcan::SocketcanMaster::takeReceivedFrame(
    const std::function<bool(const can_frame&)>& predicate,
    can_frame& frame)
{
    for (uint16_t i = 0; i < rx_count_; ++i) {
        const uint16_t idx = static_cast<uint16_t>((rx_head_ + i) % MAX_SOCKETCAN_RX_QUEUE_SIZE);
        if (!predicate(rx_queue_[idx])) continue;

        frame = rx_queue_[idx];

        for (uint16_t j = i; j + 1 < rx_count_; ++j) {
            const uint16_t current = static_cast<uint16_t>((rx_head_ + j) % MAX_SOCKETCAN_RX_QUEUE_SIZE);
            const uint16_t next = static_cast<uint16_t>((rx_head_ + j + 1) % MAX_SOCKETCAN_RX_QUEUE_SIZE);
            rx_queue_[current] = rx_queue_[next];
        }

        rx_tail_ = static_cast<uint16_t>(
            (rx_tail_ + MAX_SOCKETCAN_RX_QUEUE_SIZE - 1) % MAX_SOCKETCAN_RX_QUEUE_SIZE);
        --rx_count_;
        return true;
    }

    return false;
}

void socketcan::SocketcanMaster::sendFrame(const can_frame& frame)
{
    if (socket_ < 0) throw std::runtime_error("SocketCAN socket is not initialized.");

    const ssize_t n = ::write(socket_, &frame, sizeof(frame));
    if (n != static_cast<ssize_t>(sizeof(frame))) {
        const int error = errno;
        throw std::runtime_error(
            "Failed to send SocketCAN frame: " + std::string(std::strerror(error)));
    }
}

bool socketcan::SocketcanMaster::receiveFrame(can_frame& frame)
{
    if (socket_ < 0) throw std::runtime_error("SocketCAN socket is not initialized.");

    const ssize_t n = ::read(socket_, &frame, sizeof(frame));
    if (n < 0) {
        if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR) return false;
        return false;
    }

    return n == static_cast<ssize_t>(sizeof(frame));
}

void socketcan::SocketcanMaster::pushRxFrame(const can_frame& frame)
{
    if (rx_count_ >= MAX_SOCKETCAN_RX_QUEUE_SIZE) {
        rx_head_ = static_cast<uint16_t>((rx_head_ + 1) % MAX_SOCKETCAN_RX_QUEUE_SIZE);
        --rx_count_;
    }

    rx_queue_[rx_tail_] = frame;
    rx_tail_ = static_cast<uint16_t>((rx_tail_ + 1) % MAX_SOCKETCAN_RX_QUEUE_SIZE);
    ++rx_count_;
}

bool socketcan::SocketcanMaster::pushTxFrame(const can_frame& frame)
{
    if (tx_count_ >= MAX_SOCKETCAN_TX_QUEUE_SIZE) return false;

    tx_queue_[tx_tail_] = frame;
    tx_tail_ = static_cast<uint16_t>((tx_tail_ + 1) % MAX_SOCKETCAN_TX_QUEUE_SIZE);
    ++tx_count_;
    return true;
}

bool socketcan::SocketcanMaster::isValidNodeId(uint8_t node_id) const
{
    return node_id != 0;
}
