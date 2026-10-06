#include <algorithm>
#include <chrono>
#include <cstring>
#include <iomanip>
#include <sstream>
#include <stdexcept>

#include "serial/serial_controller.hpp"

namespace {

// robot_web fix-list 23 · 24 · 25 (2026-10-06)
constexpr uint8_t DXL_ACCESS_ERROR = 7;                       // e.g. EEPROM write while torque is on
constexpr uint16_t DXL_COMMUNICATION_LOSS_MISSES = 20;        // bulk reads in a row · about 1 s when silent
constexpr uint16_t COMMUNICATION_UNAVAILABLE_ERROR = 0xFFFF;  // same code the state monitor already reads
constexpr uint16_t DXL_REBOOT_CONTROLWORD_BIT = 0x0080;       // the fault-reset bit · REBOOT for a Dynamixel
constexpr auto DXL_REBOOT_SETTLE = std::chrono::milliseconds(1000);
constexpr auto DXL_REAPPLY_RETRY = std::chrono::milliseconds(1000);

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

    // A reboot puts RAM items (profile velocity and so on) back to their
    // defaults · write the configured items again once the device is back.
    // EEPROM items survive the reboot, so this never needs torque off.
    if (reapply_items_pending_ && std::chrono::steady_clock::now() >= next_reapply_at_) {
        std::string error;
        if (applyConfigItems(false, error)) {
            reapply_items_pending_ = false;
        } else {
            next_reapply_at_ = std::chrono::steady_clock::now() + DXL_REAPPLY_RETRY;
        }
    }

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

    // The controlword lands in Torque Enable (0/1), so the fault-reset bit has
    // no meaning there · for a Dynamixel it asks for a REBOOT, the only way to
    // clear a latched hardware error short of a power cycle. It passes the
    // motor_manager alarm gate like an AC servo fault reset (fix-list 1, 24-1).
    for (uint8_t i = 0; i < n_rx; ++i) {
        if (command.target_interface_id[i] == motor_interface::ID_CONTROLWORD &&
            (command.controlword & DXL_REBOOT_CONTROLWORD_BIT) != 0)
        {
            rebootNode();
            return;
        }
    }

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

    // No answer for a run of bulk reads · say so instead of repeating the last
    // values (robot_web fix-list 23-3). The next answer clears it.
    if (node_ && node_->missed_responses >= DXL_COMMUNICATION_LOSS_MISSES) {
        status.errorcode = COMMUNICATION_UNAVAILABLE_ERROR;
    }
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
    std::string error;
    if (!applyConfigItems(true, error)) throw std::runtime_error(error);
}

bool serial::SerialController::applyConfigItems(bool allow_torque_off, std::string& error)
{
    // robot_web fix-list 25-2 (2026-10-06) · this used to turn torque off and
    // rewrite every item on each start. A Dynamixel has no brake, so every
    // restart (apply to device, auto restart, update) let the joints sag, and
    // the EEPROM took the same write again. Now: read each item, write only
    // the ones that differ, and turn torque off only when the device refuses a
    // write because torque is on (Access Error · EEPROM area).
    const motor_interface::entry_table_t* items = driver_->items();
    bool torque_disabled = false;

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

        uint8_t current[motor_interface::MAX_DATA_SIZE]{};
        if (master_->readRegister(bus_id_, item.index, current, item.size) &&
            std::memcmp(current, item.data, item.size) == 0)
        {
            continue;
        }

        if (writeConfigItem(item)) continue;

        const uint8_t packet_error = node_ ? node_->last_packet_error : 0;
        if (allow_torque_off && !torque_disabled && (packet_error & 0x7F) == DXL_ACCESS_ERROR) {
            if (!disableTorqueForConfiguration(error)) return false;
            torque_disabled = true;
            if (writeConfigItem(item)) continue;
        }

        error = formatWriteFailure(
            "Failed to write Dynamixel item",
            bus_id_,
            item,
            node_ ? node_->last_packet_error : 0);
        return false;
    }

    return true;
}

bool serial::SerialController::writeConfigItem(const motor_interface::entry_table_t& item)
{
    if (node_) node_->last_packet_error = 0;
    return master_->writeRegister(bus_id_, item.index, item.data, item.size);
}

bool serial::SerialController::disableTorqueForConfiguration(std::string& error)
{
    const motor_interface::entry_table_t* control =
        findInterface(*driver_, motor_interface::ID_CONTROLWORD);
    if (!control) return true;

    uint8_t disable_data[motor_interface::MAX_DATA_SIZE]{};
    if (node_) node_->last_packet_error = 0;
    const bool disabled = master_->writeRegister(
        bus_id_,
        control->index,
        disable_data,
        control->size);

    if (!disabled && node_ && node_->last_packet_error != 0) {
        error = formatWriteFailure(
            "Failed to disable Dynamixel effort before configuration",
            bus_id_,
            *control,
            node_->last_packet_error);
        return false;
    }

    return true;
}

void serial::SerialController::rebootNode()
{
    // A failed reboot leaves the alarm as it is · the operator sees no change
    // and can try again or power-cycle. It must not throw: that would stop
    // motor_manager for every axis.
    if (!master_->reboot(bus_id_)) return;

    reapply_items_pending_ = true;
    next_reapply_at_ = std::chrono::steady_clock::now() + DXL_REBOOT_SETTLE;
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
