#include <algorithm>
#include <stdexcept>
#include <vector>

#include "ethercat/ethercat_controller.hpp"

void ethercat::EthercatController::initialize(motor_interface::MotorMaster& master, motor_interface::MotorDriver& driver)
{
    EthercatMaster* m = dynamic_cast<EthercatMaster*>(&master);
    if (!m) throw std::runtime_error("Failed to cast master to EthercatMaster.");

    master_ = m;
    driver_ = &driver;

    slave_config_ = ecrt_master_slave_config(master_->master(), alias_, position_, vendor_id_, product_id_);
    if (!slave_config_) throw std::runtime_error("Failed to create slave config.");

    registerEntries();

    ecrt_slave_config_dc(
        slave_config_,
        0x0300,
        1000000,
        0,
        0,
        0
    );
}

void ethercat::EthercatController::registerEntries()
{
    addSlaveConfigSdos();
    addSlaveConfigPdos();
}

bool ethercat::EthercatController::enable()
{
    uint8_t* domain_pd = master_->domain_pd();
    uint16_t sw = EC_READ_U16(domain_pd + offset_[motor_interface::ID_STATUSWORD]);

    uint8_t sw_data[2];
    motor_interface::fill<uint16_t>(sw, sw_data);

    uint8_t cw_data[2]{0};
    if (!(driver_->isEnabled(sw_data, current_driver_state_, cw_data))) {
        EC_WRITE_U16(
            domain_pd + offset_[motor_interface::ID_CONTROLWORD],
            motor_interface::value<uint16_t>(cw_data)
        );
        return false;
    }
    return true;
}

bool ethercat::EthercatController::disable()
{
    uint8_t* domain_pd = master_->domain_pd();
    uint16_t sw = EC_READ_U16(domain_pd + offset_[motor_interface::ID_STATUSWORD]);

    uint8_t sw_data[2];
    motor_interface::fill<uint16_t>(sw, sw_data);

    uint8_t cw_data[2]{0};
    if (!(driver_->isDisabled(sw_data, current_driver_state_, cw_data))) {
        EC_WRITE_U16(
            domain_pd + offset_[motor_interface::ID_CONTROLWORD],
            motor_interface::value<uint16_t>(cw_data)
        );
        return false;
    }
    return true;
}

void ethercat::EthercatController::check(const motor_interface::motor_frame_t& status)
{
    uint8_t* domain_pd = master_->domain_pd();

    uint8_t sw_data[2];
    motor_interface::fill<uint16_t>(status.statusword, sw_data);

    uint8_t cw_data[2]{0};
    if (driver_->isReceived(sw_data, cw_data)) {
        EC_WRITE_U16(
            domain_pd + offset_[motor_interface::ID_CONTROLWORD],
            motor_interface::value<uint16_t>(cw_data)
        );
    }
}

void ethercat::EthercatController::write(const motor_interface::motor_frame_t& command)
{
    motor_interface::entry_table_t rx_interfaces[motor_interface::MAX_INTERFACE_SIZE]{0};
    
    const uint8_t n_rx = std::min(command.number_of_target_interfaces,motor_interface::MAX_INTERFACE_SIZE);
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
}

void ethercat::EthercatController::read(motor_interface::motor_frame_t& status)
{
    readData(tx_interfaces_, driver_->number_of_tx_interfaces());
    for (uint8_t i = 0; i < driver_->number_of_tx_interfaces(); ++i) {
        const motor_interface::entry_table_t& e = tx_interfaces_[i];

        if (e.id == motor_interface::ID_STATUSWORD) {
            status.statusword = motor_interface::value<uint16_t>(e.data);
        } else if (e.id == motor_interface::ID_ERRORCODE) {
            status.errorcode = motor_interface::value<uint16_t>(e.data);
        } else if (e.id == motor_interface::ID_CURRENT_POSITION) {
            int32_t value = motor_interface::value<int32_t>(tx_interfaces_[i].data);
            status.position = driver_->position(value);
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

void ethercat::EthercatController::writeData(const motor_interface::entry_table_t* rx_interfaces, uint8_t number_of_rx_interfaces)
{
    uint8_t* domain_pd = master_->domain_pd();
    for (uint8_t i = 0; i < number_of_rx_interfaces; ++i) {
        switch (rx_interfaces[i].type) {
        case motor_interface::DataType::U8: {
            EC_WRITE_U8(
                domain_pd + offset_[rx_interfaces[i].id],
                motor_interface::value<uint8_t>(rx_interfaces[i].data)
            );
            break;
        } case motor_interface::DataType::U16: {
            EC_WRITE_U16(
                domain_pd + offset_[rx_interfaces[i].id],
                motor_interface::value<uint16_t>(rx_interfaces[i].data)
            );
            break;
        } case motor_interface::DataType::U32: {
            EC_WRITE_U32(
                domain_pd + offset_[rx_interfaces[i].id],
                motor_interface::value<uint32_t>(rx_interfaces[i].data)
            );
            break;
        } case motor_interface::DataType::U64: {
            EC_WRITE_U64(
                domain_pd + offset_[rx_interfaces[i].id],
                motor_interface::value<uint64_t>(rx_interfaces[i].data)
            );
            break;
        } case motor_interface::DataType::S8: {
            EC_WRITE_S8(
                domain_pd + offset_[rx_interfaces[i].id],
                motor_interface::value<int8_t>(rx_interfaces[i].data)
            );
            break;
        } case motor_interface::DataType::S16: {
            EC_WRITE_S16(
                domain_pd + offset_[rx_interfaces[i].id],
                motor_interface::value<int16_t>(rx_interfaces[i].data)
            );
            break;
        } case motor_interface::DataType::S32: {
            EC_WRITE_S32(
                domain_pd + offset_[rx_interfaces[i].id],
                motor_interface::value<int32_t>(rx_interfaces[i].data)
            );
            break;
        } default: {
            throw std::runtime_error("Invalid interface data type.");
        }
        }
    }
}

void ethercat::EthercatController::readData(motor_interface::entry_table_t* tx_interfaces, uint8_t number_of_tx_interfaces)
{
    uint8_t* domain_pd = master_->domain_pd();
    for (uint8_t i = 0; i < number_of_tx_interfaces; ++i) {
        switch (tx_interfaces[i].type) {
        case motor_interface::DataType::U8: {
            motor_interface::fill<uint8_t>(
                EC_READ_U8(domain_pd + offset_[tx_interfaces[i].id]),
                tx_interfaces[i].data
            );
            break;
        } case motor_interface::DataType::U16: {
            motor_interface::fill<uint16_t>(
                EC_READ_U16(domain_pd + offset_[tx_interfaces[i].id]),
                tx_interfaces[i].data
            );
            break;
        } case motor_interface::DataType::U32: {
            motor_interface::fill<uint32_t>(
                EC_READ_U32(domain_pd + offset_[tx_interfaces[i].id]),
                tx_interfaces[i].data
            );
            break;
        } case motor_interface::DataType::U64: {
            motor_interface::fill<uint64_t>(
                EC_READ_U64(domain_pd + offset_[tx_interfaces[i].id]),
                tx_interfaces[i].data
            );
            break;
        } case motor_interface::DataType::S8: {
            motor_interface::fill<int8_t>(
                EC_READ_S8(domain_pd + offset_[tx_interfaces[i].id]),
                tx_interfaces[i].data
            );
            break;
        } case motor_interface::DataType::S16: {
            motor_interface::fill<int16_t>(
                EC_READ_S16(domain_pd + offset_[tx_interfaces[i].id]),
                tx_interfaces[i].data
            );
            break;
        } case motor_interface::DataType::S32: {
            motor_interface::fill<int32_t>(
                EC_READ_S32(domain_pd + offset_[tx_interfaces[i].id]),
                tx_interfaces[i].data
            );
            break;
        } default: {
            throw std::runtime_error("Invalid interface data type.");
        }
        }
    }
}

void ethercat::EthercatController::addSlaveConfigSdos()
{
    const motor_interface::entry_table_t* items = driver_->items();
    
    for (uint8_t i = 0; i < driver_->number_of_items(); ++i) {
        switch (items[i].type) {
        case motor_interface::DataType::U8: {
            uint8_t value = motor_interface::value<uint8_t>(items[i].data);
            ecrt_slave_config_sdo8(slave_config_, items[i].index, items[i].subindex, value);
            break;
        } case motor_interface::DataType::U16: {
            uint16_t value = motor_interface::value<uint16_t>(items[i].data);
            ecrt_slave_config_sdo16(slave_config_, items[i].index, items[i].subindex, value);
            break;
        } case motor_interface::DataType::U32: {
            uint32_t value = motor_interface::value<uint32_t>(items[i].data);
            ecrt_slave_config_sdo32(slave_config_, items[i].index, items[i].subindex, value);
            break;
        } case motor_interface::DataType::S8: {
            int8_t value = motor_interface::value<int8_t>(items[i].data);
            if (items[i].id == motor_interface::ID_OPERATING_MODE) {
                if (profile_mode_ == 0) {
                    value = static_cast<int8_t>(driver_->profile_position_value());
                } else if (profile_mode_ == 1) {
                    value = static_cast<int8_t>(driver_->profile_velocity_value());
                } else if (profile_mode_ == 2) {
                    value = static_cast<int8_t>(driver_->profile_effort_value());
                }
            }
            ecrt_slave_config_sdo8(slave_config_, items[i].index, items[i].subindex, value);
            break;
        } case motor_interface::DataType::S16: {
            int16_t value = motor_interface::value<int16_t>(items[i].data);
            ecrt_slave_config_sdo16(slave_config_, items[i].index, items[i].subindex, value);
            break;
        } case motor_interface::DataType::S32: {
            int32_t value = motor_interface::value<int32_t>(items[i].data);
            ecrt_slave_config_sdo32(slave_config_, items[i].index, items[i].subindex, value);
            break;
        } default: {
            throw std::runtime_error("Invalid item data type.");
        }
        }
    }
}

void ethercat::EthercatController::addSlaveConfigPdos()
{
    const motor_interface::entry_table_t* interfaces = driver_->interfaces();

    uint8_t num_interfaces    = driver_->number_of_interfaces();
    uint8_t num_rx_interfaces = driver_->number_of_rx_interfaces();
    uint8_t num_tx_interfaces = driver_->number_of_tx_interfaces();

    std::vector<ec_pdo_entry_info_t> pdo_entry_infos;
    std::vector<ec_pdo_entry_reg_t> pdo_entry_regs;

    pdo_entry_infos.reserve(num_interfaces - 2 - 2);
    pdo_entry_regs.reserve(num_interfaces - 1 - 2);

    uint16_t rpdo_index = interfaces[0].index;
    uint16_t tpdo_index = interfaces[num_rx_interfaces + 1].index;

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

        pdo_entry_infos.push_back({
            e.index,
            e.subindex,
            static_cast<uint8_t>(e.size * 8)
        });

        unsigned int& offset = offset_[e.id];
        pdo_entry_regs.push_back({
            alias_,
            position_,
            vendor_id_,
            product_id_,
            e.index,
            e.subindex,
            &offset,
            0
        });
    }

    for (uint8_t i = 0; i < num_tx_interfaces; ++i) {
        const motor_interface::entry_table_t& e = interfaces[i + num_rx_interfaces + 2];

        pdo_entry_infos.push_back({
            e.index,
            e.subindex,
            static_cast<uint8_t>(e.size * 8)
        });

        unsigned int& offset = offset_[e.id];
        pdo_entry_regs.push_back({
            alias_,
            position_,
            vendor_id_,
            product_id_,
            e.index,
            e.subindex,
            &offset,
            0
        });

        tx_interfaces_[i] = motor_interface::entry_table_t{
            e.id,
            e.index,
            e.subindex,
            e.type,
            e.size,
            0
        };
    }

    pdo_entry_regs.push_back(ec_pdo_entry_reg_t{});

    ec_pdo_info_t pdo_infos[] = {
        {rpdo_index, static_cast<uint8_t>(num_rx_interfaces-2), pdo_entry_infos.data()},
        {tpdo_index, num_tx_interfaces, pdo_entry_infos.data() + num_rx_interfaces-2}
    };

    ec_sync_info_t sync_infos[] = {
        {0, EC_DIR_OUTPUT, 0, nullptr,       EC_WD_DISABLE},
        {1, EC_DIR_INPUT,  0, nullptr,       EC_WD_DISABLE},
        {2, EC_DIR_OUTPUT, 1, pdo_infos,     EC_WD_ENABLE },
        {3, EC_DIR_INPUT,  1, pdo_infos + 1, EC_WD_DISABLE},
        {0xFF}
    };

    if (ecrt_slave_config_pdos(slave_config_, EC_END, sync_infos)) {
        throw std::runtime_error("Failed to configure PDOs on slave.");
    }

    if (ecrt_domain_reg_pdo_entry_list(master_->domain(), pdo_entry_regs.data())) {
        throw std::runtime_error("Failed to register PDO entries on slave.");
    }
}
