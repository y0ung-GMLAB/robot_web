#include <algorithm>
#include <cstring>
#include <iomanip>
#include <sstream>
#include <stdexcept>

#include "serial/serial_controller.hpp"

namespace {

bool isFilteredByProfile(uint8_t id, uint8_t profile_mode)
{
    if (profile_mode == 0) {
        return id == motor_interface::ID_TARGET_VELOCITY ||
               id == motor_interface::ID_TARGET_EFFORT;
    }

    if (profile_mode == 1) {
        return id == motor_interface::ID_TARGET_POSITION ||
               id == motor_interface::ID_TARGET_EFFORT;
    }

    if (profile_mode == 2) {
        return id == motor_interface::ID_TARGET_POSITION ||
               id == motor_interface::ID_TARGET_VELOCITY;
    }

    return false;
}

const motor_interface::entry_table_t* findInterface(
    const motor_interface::MotorDriver& driver,
    uint8_t id)
{
    const motor_interface::entry_table_t* interfaces = driver.interfaces();
    for (uint8_t i = 0; i < driver.number_of_interfaces(); ++i) {
        if (interfaces[i].id == id && interfaces[i].size > 0) return &interfaces[i];
    }

    return nullptr;
}

std::string packetErrorDescription(uint8_t error)
{
    const bool alert = (error & 0x80) != 0;
    const uint8_t code = static_cast<uint8_t>(error & 0x7F);

    std::string message;
    switch (code) {
    case 0:
        message = "no status response or timeout";
        break;
    case 1:
        message = "result fail";
        break;
    case 2:
        message = "instruction error";
        break;
    case 3:
        message = "crc error";
        break;
    case 4:
        message = "data range error";
        break;
    case 5:
        message = "data length error";
        break;
    case 6:
        message = "data limit error";
        break;
    case 7:
        message = "access error";
        break;
    default:
        message = "unknown packet error";
        break;
    }

    if (alert) message += " with hardware alert";
    return message;
}

std::string formatWriteFailure(
    const char* action,
    uint8_t bus_id,
    const motor_interface::entry_table_t& item,
    uint8_t packet_error)
{
    std::ostringstream oss;
    oss << action
        << " (bus_id=" << static_cast<unsigned int>(bus_id)
        << ", item_id=" << static_cast<unsigned int>(item.id)
        << ", address=" << item.index
        << ", size=" << static_cast<unsigned int>(item.size)
        << ", packet_error=0x"
        << std::hex << std::uppercase << std::setw(2) << std::setfill('0')
        << static_cast<unsigned int>(packet_error)
        << std::dec << ", " << packetErrorDescription(packet_error) << ")";

    return oss.str();
}

} // namespace

void serial::SerialController::initialize(motor_interface::MotorMaster& master, motor_interface::MotorDriver& driver)
{
    SerialMaster* m = dynamic_cast<SerialMaster*>(&master);
    if (!m) throw std::runtime_error("Failed to cast master to SerialMaster.");

    master_ = m;
    driver_ = &driver;
    serial_driver_ = dynamic_cast<SerialDriver*>(&driver);
    if (!serial_driver_) throw std::runtime_error("Driver does not provide a serial protocol.");

    master_->configureProtocol(serial_driver_->serial_protocol());

    master_->registerNode(bus_id_);

    node_ = master_->node(bus_id_);
    if (!node_) throw std::runtime_error("Failed to get serial node data.");

    registerEntries();
}

void serial::SerialController::registerEntries()
{
    addSlaveConfigItems();
    addBulkEntries();
}

bool serial::SerialController::enable()
{
    const motor_interface::entry_table_t* status = txInterface(motor_interface::ID_STATUSWORD);
    const motor_interface::entry_table_t* control = rxInterface(motor_interface::ID_CONTROLWORD);
    if (!status || !control) throw std::runtime_error("Dynamixel enable interfaces are not configured.");

    uint8_t status_data[motor_interface::MAX_DATA_SIZE]{};
    if (!master_->getBulkReadData(bus_id_, status->index, status_data, status->size)) {
        if (!master_->readRegister(bus_id_, status->index, status_data, status->size)) {
            return false;
        }
    }

    uint8_t control_data[motor_interface::MAX_DATA_SIZE]{};
    if (!driver_->isEnabled(status_data, current_driver_state_, control_data)) {
        if (!master_->setBulkWriteData(bus_id_, control->index, control_data, control->size)) {
            return master_->writeRegister(bus_id_, control->index, control_data, control->size);
        }

        return false;
    }

    return true;
}

bool serial::SerialController::disable()
{
    const motor_interface::entry_table_t* status = txInterface(motor_interface::ID_STATUSWORD);
    const motor_interface::entry_table_t* control = rxInterface(motor_interface::ID_CONTROLWORD);
    if (!status || !control) throw std::runtime_error("Dynamixel disable interfaces are not configured.");

    uint8_t status_data[motor_interface::MAX_DATA_SIZE]{};
    if (!master_->getBulkReadData(bus_id_, status->index, status_data, status->size)) {
        if (!master_->readRegister(bus_id_, status->index, status_data, status->size)) {
            return false;
        }
    }

    uint8_t control_data[motor_interface::MAX_DATA_SIZE]{};
    if (!driver_->isDisabled(status_data, current_driver_state_, control_data)) {
        if (!master_->setBulkWriteData(bus_id_, control->index, control_data, control->size)) {
            return master_->writeRegister(bus_id_, control->index, control_data, control->size);
        }

        return false;
    }

    return true;
}

void serial::SerialController::check(const motor_interface::motor_frame_t& status)
{
    (void)status;

    const motor_interface::entry_table_t* status_interface = txInterface(motor_interface::ID_STATUSWORD);
    const motor_interface::entry_table_t* control_interface = rxInterface(motor_interface::ID_CONTROLWORD);
    if (!status_interface || !control_interface) return;

    uint8_t status_data[motor_interface::MAX_DATA_SIZE]{};
    if (!master_->getBulkReadData(bus_id_, status_interface->index, status_data, status_interface->size)) return;

    uint8_t control_data[motor_interface::MAX_DATA_SIZE]{};
    if (driver_->isReceived(status_data, control_data)) {
        (void)master_->setBulkWriteData(bus_id_, control_interface->index, control_data, control_interface->size);
    }
}

void serial::SerialController::write(const motor_interface::motor_frame_t& command)
{
    motor_interface::entry_table_t rx_interfaces[motor_interface::MAX_INTERFACE_SIZE]{};

    const uint8_t n_rx = std::min(command.number_of_target_interfaces, motor_interface::MAX_INTERFACE_SIZE);
    for (uint8_t i = 0; i < n_rx; ++i) {
        const uint8_t id = command.target_interface_id[i];
        const motor_interface::entry_table_t* descriptor = rxInterface(id);
        if (!descriptor) throw std::runtime_error("Invalid serial RX interface ID.");

        if (id == motor_interface::ID_CONTROLWORD) {
            fillInterfaceValue(*descriptor, command.controlword, rx_interfaces[i]);
        } else if (id == motor_interface::ID_TARGET_POSITION) {
            fillInterfaceValue(*descriptor, driver_->position(command.position), rx_interfaces[i]);
        } else if (id == motor_interface::ID_TARGET_VELOCITY) {
            fillInterfaceValue(*descriptor, driver_->velocity(command.velocity), rx_interfaces[i]);
        } else if (id == motor_interface::ID_TARGET_EFFORT) {
            fillInterfaceValue(*descriptor, driver_->effort(command.effort), rx_interfaces[i]);
        } else {
            throw std::runtime_error("Invalid serial target interface ID.");
        }
    }

    writeData(rx_interfaces, n_rx);
}

void serial::SerialController::read(motor_interface::motor_frame_t& status)
{
    readData(tx_interfaces_, driver_->number_of_tx_interfaces());

    for (uint8_t i = 0; i < driver_->number_of_tx_interfaces(); ++i) {
        const motor_interface::entry_table_t& e = tx_interfaces_[i];

        if (e.id == motor_interface::ID_STATUSWORD) {
            status.statusword = static_cast<uint16_t>(readUnsignedValue(e));
        } else if (e.id == motor_interface::ID_ERRORCODE) {
            status.errorcode = static_cast<uint16_t>(readUnsignedValue(e));
        } else if (e.id == motor_interface::ID_CURRENT_POSITION) {
            status.position = driver_->position(static_cast<int32_t>(readSignedValue(e)));
        } else if (e.id == motor_interface::ID_CURRENT_VELOCITY) {
            status.velocity = driver_->velocity(static_cast<int32_t>(readSignedValue(e)));
        } else if (e.id == motor_interface::ID_CURRENT_EFFORT) {
            status.effort = driver_->effort(static_cast<int16_t>(readSignedValue(e)));
        } else {
            throw std::runtime_error("Invalid serial TX interface ID.");
        }
    }

    status.controller_index = index_;
}

void serial::SerialController::writeData(const motor_interface::entry_table_t* rx_interfaces, uint8_t number_of_rx_interfaces)
{
    for (uint8_t i = 0; i < number_of_rx_interfaces; ++i) {
        const motor_interface::entry_table_t& e = rx_interfaces[i];
        if (e.size == 0) continue;

        if (!master_->setBulkWriteData(bus_id_, e.index, e.data, e.size)) {
            if (!master_->writeRegister(bus_id_, e.index, e.data, e.size)) {
                throw std::runtime_error("Failed to write Dynamixel register.");
            }
        }
    }
}

void serial::SerialController::readData(motor_interface::entry_table_t* tx_interfaces, uint8_t number_of_tx_interfaces)
{
    for (uint8_t i = 0; i < number_of_tx_interfaces; ++i) {
        motor_interface::entry_table_t& e = tx_interfaces[i];
        if (e.size == 0) continue;

        if (!master_->getBulkReadData(bus_id_, e.index, e.data, e.size)) {
            continue;
        }
    }
}

void serial::SerialController::addSlaveConfigItems()
{
    const motor_interface::entry_table_t* control =
        findInterface(*driver_, motor_interface::ID_CONTROLWORD);
    if (control) {
        uint8_t disable_data[motor_interface::MAX_DATA_SIZE]{};
        if (node_) node_->last_packet_error = 0;
        const bool disabled = master_->writeRegister(
            bus_id_,
            control->index,
            disable_data,
            control->size);

        if (!disabled && node_ && node_->last_packet_error != 0) {
            throw std::runtime_error(formatWriteFailure(
                "Failed to disable Dynamixel effort before configuration",
                bus_id_,
                *control,
                node_->last_packet_error));
        }
    }

    const motor_interface::entry_table_t* items = driver_->items();

    for (uint8_t i = 0; i < driver_->number_of_items(); ++i) {
        motor_interface::entry_table_t item = items[i];

        if (item.id == motor_interface::ID_OPERATING_MODE) {
            int8_t mode = motor_interface::value<int8_t>(item.data);
            if (profile_mode_ == 0) {
                mode = driver_->profile_position_value();
            } else if (profile_mode_ == 1) {
                mode = driver_->profile_velocity_value();
            } else if (profile_mode_ == 2) {
                mode = driver_->profile_effort_value();
            }
            motor_interface::fill<int8_t>(mode, item.data);
        }

        if (node_) node_->last_packet_error = 0;
        if (!master_->writeRegister(bus_id_, item.index, item.data, item.size)) {
            const uint8_t packet_error = node_ ? node_->last_packet_error : 0;
            throw std::runtime_error(formatWriteFailure(
                "Failed to write Dynamixel item",
                bus_id_,
                item,
                packet_error));
        }
    }
}

void serial::SerialController::addBulkEntries()
{
    const motor_interface::entry_table_t* interfaces = driver_->interfaces();
    const uint8_t num_rx_interfaces = driver_->number_of_rx_interfaces();
    const uint8_t num_tx_interfaces = driver_->number_of_tx_interfaces();

    number_of_active_rx_interfaces_ = 0;

    for (uint8_t i = 0; i < num_rx_interfaces; ++i) {
        const motor_interface::entry_table_t& e = interfaces[i + 1];
        if (isFilteredByProfile(e.id, profile_mode_)) continue;

        rx_interfaces_[number_of_active_rx_interfaces_++] = e;
        master_->registerBulkWrite(bus_id_, e.index, e.size);
    }

    for (uint8_t i = 0; i < num_tx_interfaces; ++i) {
        const motor_interface::entry_table_t& e = interfaces[i + num_rx_interfaces + 2];

        tx_interfaces_[i] = motor_interface::entry_table_t{
            e.id,
            e.index,
            e.subindex,
            e.type,
            e.size,
            {0}
        };

        master_->registerBulkRead(bus_id_, e.index, e.size);
    }
}

const motor_interface::entry_table_t* serial::SerialController::rxInterface(uint8_t id) const
{
    for (uint8_t i = 0; i < number_of_active_rx_interfaces_; ++i) {
        if (rx_interfaces_[i].id == id) return &rx_interfaces_[i];
    }

    return nullptr;
}

const motor_interface::entry_table_t* serial::SerialController::txInterface(uint8_t id) const
{
    for (uint8_t i = 0; i < driver_->number_of_tx_interfaces(); ++i) {
        if (tx_interfaces_[i].id == id) return &tx_interfaces_[i];
    }

    return nullptr;
}

void serial::SerialController::fillInterfaceValue(
    const motor_interface::entry_table_t& descriptor,
    int64_t value,
    motor_interface::entry_table_t& out) const
{
    out = motor_interface::entry_table_t{
        descriptor.id,
        descriptor.index,
        descriptor.subindex,
        descriptor.type,
        descriptor.size,
        {0}
    };

    switch (descriptor.type) {
    case motor_interface::DataType::U8:
        motor_interface::fill<uint8_t>(static_cast<uint8_t>(value), out.data);
        break;
    case motor_interface::DataType::U16:
        motor_interface::fill<uint16_t>(static_cast<uint16_t>(value), out.data);
        break;
    case motor_interface::DataType::U32:
        motor_interface::fill<uint32_t>(static_cast<uint32_t>(value), out.data);
        break;
    case motor_interface::DataType::S8:
        motor_interface::fill<int8_t>(static_cast<int8_t>(value), out.data);
        break;
    case motor_interface::DataType::S16:
        motor_interface::fill<int16_t>(static_cast<int16_t>(value), out.data);
        break;
    case motor_interface::DataType::S32:
        motor_interface::fill<int32_t>(static_cast<int32_t>(value), out.data);
        break;
    default:
        throw std::runtime_error("Invalid serial interface data type.");
    }
}

uint64_t serial::SerialController::readUnsignedValue(const motor_interface::entry_table_t& entry) const
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

int64_t serial::SerialController::readSignedValue(const motor_interface::entry_table_t& entry) const
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
