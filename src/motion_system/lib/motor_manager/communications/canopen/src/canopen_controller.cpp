#include <algorithm>
#include <cstring>
#include <stdexcept>

#include <iostream>

#include "canopen/canopen_controller.hpp"

void canopen::CanopenController::initialize(motor_interface::MotorMaster& master, motor_interface::MotorDriver& driver)
{
    CanopenMaster* m = dynamic_cast<CanopenMaster*>(&master);
    if (!m) throw std::runtime_error("Failed to cast master to CanopenMaster.");

    master_ = m;
    driver_ = &driver;

    master_->registerNodes(node_id_);

    node_ = master_->node(node_id_);
    if (!node_) throw std::runtime_error("Failed to get CANopen node data.");

    registerEntries();
}

void canopen::CanopenController::registerEntries()
{
    addSlaveConfigSdos();
    addSlaveConfigPdos();
}

bool canopen::CanopenController::enable()
{
    uint8_t sw_data[2]{0};
    std::memcpy(sw_data, node_->tpdo + offset_[motor_interface::ID_STATUSWORD], sizeof(sw_data));

    uint8_t cw_data[2]{0};
    if (!driver_->isEnabled(sw_data, current_driver_state_, cw_data)) {
        std::memcpy(node_->rpdo + offset_[motor_interface::ID_CONTROLWORD], cw_data, sizeof(cw_data));

        node_->rpdo_dirty = true;
        return false;
    }

    return true;
}

bool canopen::CanopenController::disable()
{
    uint8_t sw_data[2]{0};
    std::memcpy(sw_data, node_->tpdo + offset_[motor_interface::ID_STATUSWORD], sizeof(sw_data));

    uint8_t cw_data[2]{0};
    if (!driver_->isDisabled(sw_data, current_driver_state_, cw_data)) {
        std::memcpy(node_->rpdo + offset_[motor_interface::ID_CONTROLWORD], cw_data, sizeof(cw_data));

        node_->rpdo_dirty = true;
        return false;
    }

    return true;
}

void canopen::CanopenController::check(const motor_interface::motor_frame_t& status)
{
    const bool ack = (status.statusword & 0x1000) != 0;

    switch (set_point_state_) {
    case canopen::SetPointState::Idle: {
        return;
    }

    case canopen::SetPointState::SendSet: {
        if (has_pending_setpoint_) {
            std::memcpy(node_->rpdo, pending_rpdo_, pending_rpdo_size_);
            node_->rpdo_size = pending_rpdo_size_;
            node_->rpdo_dirty = true;

            has_pending_setpoint_ = false;
            set_point_state_ = canopen::SetPointState::WaitAck;
        }
        return;
    }

    case canopen::SetPointState::WaitAck: {
        if (ack) {
            uint8_t cw_data[2]{};
            motor_interface::fill<uint16_t>(0x102F, cw_data);

            std::memcpy(
                node_->rpdo + offset_[motor_interface::ID_CONTROLWORD],
                cw_data,
                sizeof(cw_data));

            node_->rpdo_dirty = true;
            set_point_state_ = canopen::SetPointState::WaitAckClear;
        }
        return;
    }

    case canopen::SetPointState::WaitAckClear: {
        if (!ack) {
            set_point_state_ = canopen::SetPointState::Idle;
        }
        return;
    }

    default:
        set_point_state_ = canopen::SetPointState::Idle;
        return;
    }
}

void canopen::CanopenController::write(const motor_interface::motor_frame_t& command)
{
    motor_interface::entry_table_t rx_interfaces[motor_interface::MAX_INTERFACE_SIZE]{0};

    const uint8_t n_rx = std::min(command.number_of_target_interfaces, motor_interface::MAX_INTERFACE_SIZE);
    for (uint8_t i = 0; i < n_rx; ++i) {
        const uint8_t id = command.target_interface_id[i];

        if (id == motor_interface::ID_CONTROLWORD) {
            rx_interfaces[i].id = id;
            rx_interfaces[i].type = motor_interface::DataType::U16;
            rx_interfaces[i].size = 2;
            motor_interface::fill<uint16_t>(command.controlword, rx_interfaces[i].data);
        } else if (id == motor_interface::ID_TARGET_POSITION) {
            rx_interfaces[i].id = id;
            rx_interfaces[i].type = motor_interface::DataType::S32;
            rx_interfaces[i].size = 4;
            motor_interface::fill<int32_t>(driver_->position(command.position), rx_interfaces[i].data);
        } else if (id == motor_interface::ID_TARGET_VELOCITY) {
            rx_interfaces[i].id = id;
            rx_interfaces[i].type = motor_interface::DataType::S32;
            rx_interfaces[i].size = 4;
            motor_interface::fill<int32_t>(driver_->velocity(command.velocity), rx_interfaces[i].data);
        } else if (id == motor_interface::ID_TARGET_EFFORT) {
            rx_interfaces[i].id = id;
            rx_interfaces[i].type = motor_interface::DataType::S16;
            rx_interfaces[i].size = 2;
            motor_interface::fill<int16_t>(driver_->effort(command.effort), rx_interfaces[i].data);
        } else {
            throw std::runtime_error("Invalid RX interface ID.");
        }
    }

    writeData(rx_interfaces, n_rx);

    if ((command.controlword & 0x0010) != 0) {
        std::memcpy(pending_rpdo_, node_->rpdo, node_->rpdo_size);
        pending_rpdo_size_ = node_->rpdo_size;
        has_pending_setpoint_ = true;
    
        uint16_t cw_clear =
            static_cast<uint16_t>(command.controlword & ~0x0010);
    
        uint8_t cw_data[2]{};
        motor_interface::fill<uint16_t>(cw_clear, cw_data);
    
        std::memcpy(
            node_->rpdo + offset_[motor_interface::ID_CONTROLWORD],
            cw_data,
            sizeof(cw_data));
    
        node_->rpdo_dirty = true;
        set_point_state_ = canopen::SetPointState::SendSet;
    }
}

void canopen::CanopenController::read(motor_interface::motor_frame_t& status)
{
    readData(tx_interfaces_, driver_->number_of_tx_interfaces());

    for (uint8_t i = 0; i < driver_->number_of_tx_interfaces(); ++i) {
        const motor_interface::entry_table_t& e = tx_interfaces_[i];

        if (e.id == motor_interface::ID_STATUSWORD) {
            status.statusword = motor_interface::value<uint16_t>(e.data);
        } else if (e.id == motor_interface::ID_ERRORCODE) {
            status.errorcode = motor_interface::value<uint16_t>(e.data);
        } else if (e.id == motor_interface::ID_CURRENT_POSITION) {
            status.position = driver_->position(motor_interface::value<int32_t>(e.data));
        } else if (e.id == motor_interface::ID_CURRENT_VELOCITY) {
            status.velocity = driver_->velocity(motor_interface::value<int32_t>(e.data));
        } else if (e.id == motor_interface::ID_CURRENT_EFFORT) {
            status.effort = driver_->effort(motor_interface::value<int16_t>(e.data));
        } else {
            throw std::runtime_error("Invalid TX interface ID.");
        }
    }

    status.controller_index = index_;
}

void canopen::CanopenController::writeData(const motor_interface::entry_table_t* rx_interfaces, uint8_t number_of_rx_interfaces)
{
    for (uint8_t i = 0; i < number_of_rx_interfaces; ++i) {
        const motor_interface::entry_table_t& e = rx_interfaces[i];

        std::memcpy(node_->rpdo + offset_[e.id], e.data, e.size);
    }

    node_->rpdo_dirty = true;
}

void canopen::CanopenController::readData(motor_interface::entry_table_t* tx_interfaces, uint8_t number_of_tx_interfaces)
{
    for (uint8_t i = 0; i < number_of_tx_interfaces; ++i) {
        motor_interface::entry_table_t& e = tx_interfaces[i];

        std::memcpy(e.data, node_->tpdo + offset_[e.id], e.size);
    }

    node_->tpdo_updated = false;
}

void canopen::CanopenController::addSlaveConfigSdos()
{
    const motor_interface::entry_table_t* items = driver_->items();

    for (uint8_t i = 0; i < driver_->number_of_items(); ++i) {
        motor_interface::entry_table_t item = items[i];

        if (item.id == motor_interface::ID_OPERATING_MODE) {
            int8_t value = motor_interface::value<int8_t>(item.data);

            if (profile_mode_ == 0) {
                value = driver_->profile_position_value();
            } else if (profile_mode_ == 1) {
                value = driver_->profile_velocity_value();
            } else if (profile_mode_ == 2) {
                value = driver_->profile_effort_value();
            }

            motor_interface::fill<int8_t>(value, item.data);
        }

        if (!master_->writeSdo(
            node_id_,
            item.index,
            item.subindex,
            item.data,
            item.size
        )) throw std::runtime_error("Failed to write CANopen SDO.");
    }
}

void canopen::CanopenController::addSlaveConfigPdos()
{
    const motor_interface::entry_table_t* interfaces = driver_->interfaces();

    const uint8_t num_rx_interfaces = driver_->number_of_rx_interfaces();
    const uint8_t num_tx_interfaces = driver_->number_of_tx_interfaces();

    uint8_t rpdo1_count = 0;
    uint8_t rpdo2_count = 0;
    uint8_t tpdo1_count = 0;
    uint8_t tpdo2_count = 0;

    uint8_t tpdo1_size = 0;
    uint8_t tpdo2_size = 0;
    uint8_t rpdo1_size = 0;
    uint8_t rpdo2_size = 0;

    auto write_u8 = [&](uint16_t index, uint8_t subindex, uint8_t value) {
        uint8_t data[1]{};
        motor_interface::fill<uint8_t>(value, data);
        master_->writeSdo(node_id_, index, subindex, data, 1);
    };

    auto write_u16 = [&](uint16_t index, uint8_t subindex, uint16_t value) {
        uint8_t data[2]{};
        motor_interface::fill<uint16_t>(value, data);
        master_->writeSdo(node_id_, index, subindex, data, 2);
    };

    auto write_u32 = [&](uint16_t index, uint8_t subindex, uint32_t value) {
        uint8_t data[4]{};
        motor_interface::fill<uint32_t>(value, data);
        master_->writeSdo(node_id_, index, subindex, data, 4);
    };

    auto map_value = [](const motor_interface::entry_table_t& e) -> uint32_t {
        return (static_cast<uint32_t>(e.index) << 16) |
               (static_cast<uint32_t>(e.subindex) << 8) |
               (static_cast<uint32_t>(e.size) * 8);
    };

    write_u32(0x1400, 0x01, 0x80000000u | (canopen::COB_RPDO1_BASE + node_id_));
    write_u32(0x1401, 0x01, 0x80000000u | (canopen::COB_RPDO2_BASE + node_id_));
    write_u32(0x1800, 0x01, 0x80000000u | (canopen::COB_TPDO1_BASE + node_id_));
    write_u32(0x1801, 0x01, 0x80000000u | (canopen::COB_TPDO2_BASE + node_id_));

    write_u8(0x1600, 0x00, 0);
    write_u8(0x1601, 0x00, 0);
    write_u8(0x1A00, 0x00, 0);
    write_u8(0x1A01, 0x00, 0);

    for (uint8_t i = 0; i < num_rx_interfaces; ++i) {
        const motor_interface::entry_table_t& e = interfaces[i + 1];

        if (profile_mode_ == 0) {
            if (e.id == motor_interface::ID_TARGET_VELOCITY || e.id == motor_interface::ID_TARGET_EFFORT) {
                continue;
            }
        } else if (profile_mode_ == 1) {
            if (e.id == motor_interface::ID_TARGET_POSITION || e.id == motor_interface::ID_TARGET_EFFORT) {
                continue;
            }
        } else if (profile_mode_ == 2) {
            if (e.id == motor_interface::ID_TARGET_POSITION || e.id == motor_interface::ID_TARGET_VELOCITY) {
                continue;
            }
        }

        const uint32_t map = map_value(e);

        if (rpdo1_size + e.size <= 8) {
            offset_[e.id] = rpdo1_size;

            ++rpdo1_count;
            write_u32(0x1600, rpdo1_count, map);

            rpdo1_size += e.size;
        } else {
            if (rpdo2_size + e.size > 8) throw std::runtime_error("RPDO2 size exceeds 8 bytes.");

            offset_[e.id] = 8 + rpdo2_size;

            ++rpdo2_count;
            write_u32(0x1601, rpdo2_count, map);

            rpdo2_size += e.size;
        }
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

        const uint32_t map = map_value(e);

        if (tpdo1_size + e.size <= 8) {
            offset_[e.id] = tpdo1_size;

            ++tpdo1_count;
            write_u32(0x1A00, tpdo1_count, map);

            tpdo1_size += e.size;
        } else {
            if (tpdo2_size + e.size > 8) throw std::runtime_error("TPDO2 size exceeds 8 bytes.");

            offset_[e.id] = 8 + tpdo2_size;
            
            ++tpdo2_count;
            write_u32(0x1A01, tpdo2_count, map);

            tpdo2_size += e.size;
        }
    }

    write_u8(0x1600, 0x00, rpdo1_count);
    write_u8(0x1601, 0x00, rpdo2_count);
    write_u8(0x1A00, 0x00, tpdo1_count);
    write_u8(0x1A01, 0x00, tpdo2_count);

    write_u8(0x1400, 0x02, 255);
    write_u8(0x1401, 0x02, 255);

    write_u8(0x1800, 0x02, 254);
    write_u8(0x1801, 0x02, 254);

    write_u16(0x1800, 0x05, 1);
    write_u16(0x1801, 0x05, 1);

    write_u32(0x1400, 0x001, canopen::COB_RPDO1_BASE + node_id_);
    if (rpdo2_count > 0) write_u32(0x1401, 0x01, canopen::COB_RPDO2_BASE + node_id_);

    write_u32(0x1800, 0x001, canopen::COB_TPDO1_BASE + node_id_);
    if (tpdo2_count > 0) write_u32(0x1801, 0x01, canopen::COB_TPDO2_BASE + node_id_);

    rpdo_size_ = rpdo1_size + rpdo2_size;
    tpdo_size_ = tpdo1_size + tpdo2_size;

    node_->rpdo_size = rpdo_size_;
    node_->tpdo_size = tpdo_size_;
}
