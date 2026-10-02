#include <algorithm>
#include <chrono>
#include <cstring>
#include <filesystem>

#include <time.h>
#include <sched.h>
#include <errno.h>
#include <unistd.h>
#include <sys/mman.h>
#include <yaml-cpp/yaml.h>

#include "motor_manager/motor_manager.hpp"

#include "ethercat/ethercat_master.hpp"
#include "ethercat/ethercat_controller.hpp"
#include "canopen/canopen_master.hpp"
#include "canopen/canopen_controller.hpp"
#include "socketcan/socketcan_master.hpp"
#include "socketcan/socketcan_controller.hpp"
#include "serial/serial_master.hpp"
#include "serial/serial_controller.hpp"

#include "minas/minas_driver.hpp"
#include "zeroerr/zeroerr_driver.hpp"
#include "dynamixel/dynamixel_driver.hpp"
#include "cubemars/cubemars_driver.hpp"

namespace {

void unlock_memory()
{
    (void)munlockall();
}

void stack_prefault()
{
    unsigned char dummy[8 * 1024];
    std::memset(dummy, 0, sizeof(dummy));
}

} // namespace

motor_manager::MotorManager::MotorManager(const std::string& config_file)
{
    for (auto& request : controller_enable_requested_) {
        request.store(true, std::memory_order_release);
    }

    loadConfigurations(config_file);
    initialize();
}

motor_manager::MotorManager::~MotorManager()
{
    request_exit();
    stopSerial();
}

void motor_manager::MotorManager::write(const motor_interface::motor_frame_t* command, const uint8_t size)
{
    std::lock_guard<std::mutex> lock(frame_mutex_);
    const uint8_t n = std::min(size, motor_interface::MAX_CONTROLLER_SIZE);
    for (uint8_t i = 0; i < n; ++i) {
        const uint8_t controller_index = command[i].controller_index;
        if (controller_index >= number_of_controllers_) continue;

        command_[controller_index] = command[i];
        ++command_sequence_[controller_index];
    }
}

void motor_manager::MotorManager::read(motor_interface::motor_frame_t* status)
{
    std::lock_guard<std::mutex> lock(frame_mutex_);
    for (uint8_t i = 0; i < number_of_controllers_; ++i) {
        status[i] = status_[i];
    }
}

void motor_manager::MotorManager::request_stop()
{
    for (auto& request : controller_enable_requested_) {
        request.store(false, std::memory_order_release);
    }
}

void motor_manager::MotorManager::request(const int8_t* actions, const uint8_t size)
{
    if (actions == nullptr) {
        return;
    }

    const uint8_t n = std::min(size, static_cast<uint8_t>(motor_interface::MAX_CONTROLLER_SIZE));
    for (uint8_t controller_index = 0; controller_index < n; ++controller_index) {
        if (actions[controller_index] == 0) {
            controller_enable_requested_[controller_index].store(false, std::memory_order_release);
        } else if (actions[controller_index] == 1) {
            controller_enable_requested_[controller_index].store(true, std::memory_order_release);
        }
    }
}

void motor_manager::MotorManager::request_exit()
{
    running_.store(false, std::memory_order_release);
    serial_running_.store(false, std::memory_order_release);
}

void motor_manager::MotorManager::loadConfigurations(const std::string& config_file)
{
    YAML::Node root = YAML::LoadFile(config_file);
    if (!root) throw std::runtime_error("Failed to load configuration file.");

    period_ = root["period"].as<uint32_t>();
    if (period_ == 0) throw std::runtime_error("Motor manager period must be greater than zero.");

    YAML::Node masters = root["masters"];
    if (!masters || !masters.IsSequence()) throw std::runtime_error("Invalid masters configuration.");

    uint8_t s_idx{0};
    masters_.reserve(motor_interface::MAX_MASTER_SIZE);
    serial_masters_.reserve(motor_interface::MAX_MASTER_SIZE);
    controller_indices_.reserve(motor_interface::MAX_CONTROLLER_SIZE);
    for (const auto& m : masters) {
        motor_interface::master_config_t m_cfg{};
        m_cfg.id = m["id"].as<uint8_t>();
        m_cfg.number_of_slaves = m["number_of_slaves"].as<uint8_t>();

        if (masters_.find(m_cfg.id) != masters_.end() ||
            serial_masters_.find(m_cfg.id) != serial_masters_.end())
        {
            throw std::runtime_error("Duplicate master ID.");
        }

        YAML::Node slaves = m["slaves"];
        if (!slaves || !slaves.IsSequence()) throw std::runtime_error("Invalid slaves configuration.");

        switch (toCommunicationType(m["type"].as<std::string>()))
        {
        case CommunicationType::Ethercat: {
            m_cfg.ethercat_master_index = m["ethercat_master_index"].as<unsigned int>();
            masters_[m_cfg.id] = std::make_unique<ethercat::EthercatMaster>(m_cfg);

            for (uint8_t i = 0; i < m["number_of_slaves"].as<uint8_t>(); ++i) {
                motor_interface::slave_config_t s_cfg{};
                s_cfg.controller_index = slaves[i]["controller_index"].as<uint8_t>();
                s_cfg.master_id = m_cfg.id;
                s_cfg.driver_id = slaves[i]["driver_id"].as<uint8_t>();
                s_cfg.alias = slaves[i]["alias"].as<uint16_t>();
                s_cfg.position = slaves[i]["position"].as<uint16_t>();
                s_cfg.vendor_id = slaves[i]["vendor_id"].as<uint32_t>();
                s_cfg.product_id = slaves[i]["product_id"].as<uint32_t>();
                s_cfg.profile_mode = slaves[i]["profile_mode"].as<uint8_t>();

                controllers_[s_cfg.controller_index] = std::make_unique<ethercat::EthercatController>(s_cfg);
                controller_indices_.push_back(s_cfg.controller_index);
                s_idx++;
            }
            break;
        }
        case CommunicationType::Canopen: {
            m_cfg.can_interface_index = m["can_interface_index"].as<unsigned int>();
            m_cfg.can_bitrate = m["can_bitrate"].as<unsigned int>();
            masters_[m_cfg.id] = std::make_unique<canopen::CanopenMaster>(m_cfg);

            for (uint8_t i = 0; i < m["number_of_slaves"].as<uint8_t>(); ++i) {
                motor_interface::slave_config_t s_cfg{};
                s_cfg.controller_index = slaves[i]["controller_index"].as<uint8_t>();
                s_cfg.master_id = m_cfg.id;
                s_cfg.driver_id = slaves[i]["driver_id"].as<uint8_t>();
                s_cfg.can_id = slaves[i]["can_id"].as<uint8_t>();
                s_cfg.profile_mode = slaves[i]["profile_mode"].as<uint8_t>();

                controllers_[s_cfg.controller_index] = std::make_unique<canopen::CanopenController>(s_cfg);
                controller_indices_.push_back(s_cfg.controller_index);
                s_idx++;
            }
            break;
        }
        case CommunicationType::Serial: {
            m_cfg.serial_port = m["serial_port"].as<std::string>();
            m_cfg.serial_baudrate = m["serial_baudrate"].as<unsigned int>();
            serial_masters_[m_cfg.id] = std::make_unique<serial::SerialMaster>(m_cfg);
            std::vector<uint8_t>& controller_indices = serial_controller_indices_[m_cfg.id];
            controller_indices.reserve(m_cfg.number_of_slaves);

            for (uint8_t i = 0; i < m["number_of_slaves"].as<uint8_t>(); ++i) {
                motor_interface::slave_config_t s_cfg{};
                s_cfg.controller_index = slaves[i]["controller_index"].as<uint8_t>();
                s_cfg.master_id = m_cfg.id;
                s_cfg.driver_id = slaves[i]["driver_id"].as<uint8_t>();
                s_cfg.bus_id = slaves[i]["bus_id"].as<uint8_t>();
                s_cfg.profile_mode = slaves[i]["profile_mode"].as<uint8_t>();

                controllers_[s_cfg.controller_index] = std::make_unique<serial::SerialController>(s_cfg);
                controller_indices.push_back(s_cfg.controller_index);
                s_idx++;
            }
            break;
        }
        case CommunicationType::Socketcan: {
            m_cfg.can_interface_index = m["can_interface_index"].as<unsigned int>();
            m_cfg.can_bitrate = m["can_bitrate"].as<unsigned int>();

            masters_[m_cfg.id] = std::make_unique<socketcan::SocketcanMaster>(m_cfg);

            for (uint8_t i = 0; i < m["number_of_slaves"].as<uint8_t>(); ++i) {
                motor_interface::slave_config_t s_cfg{};
                s_cfg.controller_index = slaves[i]["controller_index"].as<uint8_t>();
                s_cfg.master_id = m_cfg.id;
                s_cfg.driver_id = slaves[i]["driver_id"].as<uint8_t>();
                s_cfg.can_id = slaves[i]["can_id"].as<uint8_t>();
                s_cfg.profile_mode = slaves[i]["profile_mode"].as<uint8_t>();

                controllers_[s_cfg.controller_index] = std::make_unique<socketcan::SocketcanController>(s_cfg);
                controller_indices_.push_back(s_cfg.controller_index);
                s_idx++;
            }
            break;
        } default: {
            throw std::runtime_error("Invalid communication type.");
        }
        }
    }
    number_of_controllers_ = s_idx;

    YAML::Node drivers = root["drivers"];
    if (!drivers || !drivers.IsSequence()) throw std::runtime_error("Invalid drivers configuration.");

    drivers_.reserve(motor_interface::MAX_DRIVER_SIZE);
    for (const auto& d : drivers) {
        const std::string driver_type = d["type"].as<std::string>();
        motor_interface::driver_config_t d_cfg{};
        d_cfg.id = d["id"].as<uint8_t>();
        d_cfg.pulse_per_revolution = d["pulse_per_revolution"].as<uint32_t>();
        d_cfg.rated_effort = d["rated_effort"].as<double>();
        d_cfg.unit_effort = d["unit_effort"].as<double>();
        d_cfg.lower = d["lower"].as<double>();
        d_cfg.upper = d["upper"].as<double>();
        d_cfg.speed = d["speed"].as<double>();
        d_cfg.acceleration = d["acceleration"].as<double>();
        d_cfg.deceleration = d["deceleration"].as<double>();
        d_cfg.profile_velocity = d["profile_velocity"].as<double>();
        d_cfg.profile_acceleration = d["profile_acceleration"].as<double>();
        d_cfg.profile_deceleration = d["profile_deceleration"].as<double>();
        d_cfg.profile_position_value = d["profile_position_value"].as<int8_t>();
        d_cfg.profile_velocity_value = d["profile_velocity_value"].as<int8_t>();
        d_cfg.profile_effort_value = d["profile_effort_value"].as<int8_t>();

        switch (toDriverType(driver_type)) {
        case DriverType::Minas: {
            drivers_[d_cfg.id] = std::make_unique<minas::MinasDriver>(d_cfg);
            break;
        } case DriverType::Zeroerr: {
            drivers_[d_cfg.id] = std::make_unique<zeroerr::ZeroerrDriver>(d_cfg);
            break;
        } case DriverType::Dynamixel: {
            drivers_[d_cfg.id] = std::make_unique<dynamixel::DynamixelDriver>(d_cfg);
            break;
        } case DriverType::Cubemars: {
            drivers_[d_cfg.id] = std::make_unique<cubemars::CubemarsDriver>(d_cfg);
            break;
        } default: {
            throw std::runtime_error("Invalid driver type.");
        }
        }

        std::filesystem::path param_path = d["param_file"].as<std::string>();
        if (param_path.is_absolute()) {
            param_path = param_path.lexically_normal();
        } else {
            param_path = (std::filesystem::path(config_file).parent_path() / param_path).lexically_normal();
        }

        const std::string ext = param_path.extension().string();
        if (ext != ".yaml" && ext != ".yml") {
            param_path /= driver_type + ".yaml";
        }

        drivers_.at(d_cfg.id)->loadParameters(param_path.lexically_normal().string());
    }
}

void motor_manager::MotorManager::initialize()
{
    frequency_ = NSEC_PER_SEC / period_;

    for (auto& m_iter : masters_) m_iter.second->initialize();
    for (auto& m_iter : serial_masters_) m_iter.second->initialize();

    for (uint8_t i : controller_indices_) {
        const uint8_t m_id = controllers_[i]->master_id();
        const uint8_t d_id = controllers_[i]->driver_id();

        controllers_[i]->initialize(*masters_.at(m_id), *drivers_.at(d_id));
    }

    for (auto& controller_indices_iter : serial_controller_indices_) {
        motor_interface::MotorMaster& master = *serial_masters_.at(controller_indices_iter.first);
        for (uint8_t i : controller_indices_iter.second) {
            const uint8_t d_id = controllers_[i]->driver_id();
            controllers_[i]->initialize(master, *drivers_.at(d_id));
        }
    }
}

void motor_manager::MotorManager::start()
{
    for (auto& m_iter : masters_) m_iter.second->activate();
    for (auto& m_iter : serial_masters_) m_iter.second->activate();
}

void motor_manager::MotorManager::stop()
{
    for (auto& m_iter : masters_) m_iter.second->deactivate();
    for (auto& m_iter : serial_masters_) m_iter.second->deactivate();
}

void motor_manager::MotorManager::enableController(const uint8_t controller_index)
{
    if (controller_index >= motor_interface::MAX_CONTROLLER_SIZE || !controllers_[controller_index]) return;

    if (!controller_enabled_[controller_index].load(std::memory_order_acquire)) {
        const bool enabled = controllers_[controller_index]->enable();
        controller_enabled_[controller_index].store(enabled, std::memory_order_release);
        if (enabled) {
            controller_disabled_[controller_index].store(false, std::memory_order_release);
        }
    }
}

void motor_manager::MotorManager::enableControllers(const std::vector<uint8_t>& controller_indices)
{
    for (uint8_t i : controller_indices) {
        enableController(i);
    }

    refreshEnabled();
}

void motor_manager::MotorManager::disableController(const uint8_t controller_index)
{
    if (controller_index >= motor_interface::MAX_CONTROLLER_SIZE || !controllers_[controller_index]) return;

    if (!controller_disabled_[controller_index].load(std::memory_order_acquire)) {
        const bool disabled = controllers_[controller_index]->disable();
        controller_disabled_[controller_index].store(disabled, std::memory_order_release);
        if (disabled) {
            controller_enabled_[controller_index].store(false, std::memory_order_release);
        }
    }
}

void motor_manager::MotorManager::disableControllers(const std::vector<uint8_t>& controller_indices)
{
    for (uint8_t i : controller_indices) {
        disableController(i);
    }

    refreshDisabled();
}

void motor_manager::MotorManager::updateController(const uint8_t controller_index)
{
    if (controller_index >= motor_interface::MAX_CONTROLLER_SIZE || !controllers_[controller_index]) return;
    if (!controller_enabled_[controller_index].load(std::memory_order_acquire)) return;

    motor_interface::motor_frame_t controller_status{};
    controllers_[controller_index]->read(controller_status);

    motor_interface::motor_frame_t pending_command{};
    uint64_t pending_sequence{0};
    bool has_pending_command{false};

    {
        std::lock_guard<std::mutex> lock(frame_mutex_);
        status_[controller_index] = controller_status;

        if (controller_status.errorcode == 0 &&
            command_sequence_[controller_index] != applied_command_sequence_[controller_index])
        {
            pending_command = command_[controller_index];
            pending_sequence = command_sequence_[controller_index];
            has_pending_command = true;
        }
    }

    controllers_[controller_index]->check(controller_status);

    if (has_pending_command) {
        controllers_[controller_index]->write(pending_command);

        std::lock_guard<std::mutex> lock(frame_mutex_);
        if (applied_command_sequence_[controller_index] < pending_sequence) {
            applied_command_sequence_[controller_index] = pending_sequence;
        }
    }
}

void motor_manager::MotorManager::updateControllers(const std::vector<uint8_t>& controller_indices)
{
    for (uint8_t i : controller_indices) {
        updateController(i);
    }
}

void motor_manager::MotorManager::applyControllerRequests(const std::vector<uint8_t>& controller_indices)
{
    for (uint8_t i : controller_indices) {
        if (i >= motor_interface::MAX_CONTROLLER_SIZE || !controllers_[i]) continue;

        if (controller_enable_requested_[i].load(std::memory_order_acquire)) {
            enableController(i);
            updateController(i);
        } else {
            disableController(i);
        }
    }

    refreshEnabled();
    refreshDisabled();
}

void motor_manager::MotorManager::refreshEnabled()
{
    bool all_enabled = true;
    for (uint8_t i : controller_indices_) {
        all_enabled = all_enabled && controller_enabled_[i].load(std::memory_order_acquire);
    }
    for (const auto& controller_indices_iter : serial_controller_indices_) {
        for (uint8_t i : controller_indices_iter.second) {
            all_enabled = all_enabled && controller_enabled_[i].load(std::memory_order_acquire);
        }
    }
    is_enabled_.store(all_enabled, std::memory_order_release);
}

void motor_manager::MotorManager::refreshDisabled()
{
    bool all_disabled = true;
    for (uint8_t i : controller_indices_) {
        all_disabled = all_disabled && controller_disabled_[i].load(std::memory_order_acquire);
    }
    for (const auto& controller_indices_iter : serial_controller_indices_) {
        for (uint8_t i : controller_indices_iter.second) {
            all_disabled = all_disabled && controller_disabled_[i].load(std::memory_order_acquire);
        }
    }
    is_disabled_.store(all_disabled, std::memory_order_release);
}

void motor_manager::MotorManager::startSerial()
{
    stopSerial();

    {
        std::lock_guard<std::mutex> lock(serial_exception_mutex_);
        serial_exception_ = nullptr;
    }

    if (serial_masters_.empty()) return;

    serial_running_.store(true, std::memory_order_release);
    serial_threads_.reserve(serial_masters_.size());
    for (auto& m_iter : serial_masters_) {
        serial_threads_.emplace_back(&MotorManager::serialRun, this, m_iter.first);
    }
}

void motor_manager::MotorManager::stopSerial()
{
    serial_running_.store(false, std::memory_order_release);

    for (std::thread& thread : serial_threads_) {
        if (thread.joinable()) thread.join();
    }
    serial_threads_.clear();
}

void motor_manager::MotorManager::serialRun(uint8_t master_id)
{
    try {
        auto master_iter = serial_masters_.find(master_id);
        if (master_iter == serial_masters_.end()) {
            throw std::runtime_error("Serial worker master does not exist.");
        }

        auto controller_indices_iter = serial_controller_indices_.find(master_id);
        if (controller_indices_iter == serial_controller_indices_.end()) {
            throw std::runtime_error("Serial worker controller indices do not exist.");
        }

        const auto cycle = std::chrono::nanoseconds(period_);
        auto next_wakeup = std::chrono::steady_clock::now();

        while (serial_running_.load(std::memory_order_acquire) &&
               running_.load(std::memory_order_acquire))
        {
            next_wakeup += cycle;
            std::this_thread::sleep_until(next_wakeup);

            if (!serial_running_.load(std::memory_order_acquire) ||
                !running_.load(std::memory_order_acquire))
            {
                break;
            }

            motor_interface::MotorMaster& master = *master_iter->second;
            master.receive();

            applyControllerRequests(controller_indices_iter->second);

            master.transmit();

            const auto now = std::chrono::steady_clock::now();
            if (next_wakeup < now - cycle) {
                next_wakeup = now;
            }
        }
    } catch (...) {
        setSerialException(std::current_exception());
        serial_running_.store(false, std::memory_order_release);
        running_.store(false, std::memory_order_release);
    }
}

void motor_manager::MotorManager::setSerialException(std::exception_ptr exception)
{
    std::lock_guard<std::mutex> lock(serial_exception_mutex_);
    if (!serial_exception_) serial_exception_ = exception;
}

void motor_manager::MotorManager::rethrowSerialExceptionIfAny()
{
    std::exception_ptr exception;
    {
        std::lock_guard<std::mutex> lock(serial_exception_mutex_);
        exception = serial_exception_;
    }

    if (exception) std::rethrow_exception(exception);
}

void motor_manager::MotorManager::run()
{
    running_.store(true, std::memory_order_release);
    start();
    bool memory_locked{false};

    try {
        startSerial();

        if (sysconf(_SC_PAGESIZE) == -1) {
            throw std::runtime_error("sysconf(_SC_PAGESIZE) failed.");
        }

        if (mlockall(MCL_CURRENT | MCL_FUTURE) == -1) {
            throw std::runtime_error("Failed to lock memory (mlockall).");
        }
        memory_locked = true;

        struct sched_param param = {};
        param.sched_priority = sched_get_priority_max(SCHED_FIFO);

        if (sched_setscheduler(0, SCHED_FIFO, &param) == -1) {
            throw std::runtime_error("Failed to set scheduler.");
        }

        if (mlockall(MCL_CURRENT | MCL_FUTURE) == -1) {
            throw std::runtime_error("Failed to lock memory (mlockall).");
        }

        stack_prefault();

        timespec cycle_time{};
        cycle_time.tv_sec = static_cast<time_t>(period_ / NSEC_PER_SEC);
        cycle_time.tv_nsec = static_cast<long>(period_ % NSEC_PER_SEC);

        timespec wakeup_time{};
        if (clock_gettime(CLOCK_MONOTONIC, &wakeup_time) == -1) {
            throw std::runtime_error("clock_gettime failed.");
        }

        while (running_.load(std::memory_order_acquire)) {
            wakeup_time.tv_nsec += cycle_time.tv_nsec;
            while (wakeup_time.tv_nsec >= NSEC_PER_SEC) {
                wakeup_time.tv_sec++;
                wakeup_time.tv_nsec -= NSEC_PER_SEC;
            }

            int sleep_rc;
            do {
                sleep_rc = clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &wakeup_time, nullptr);
            } while (sleep_rc == EINTR);

            if (sleep_rc != 0) {
                throw std::runtime_error("clock_nanosleep failed.");
            }

            rethrowSerialExceptionIfAny();

            for (auto& m_iter : masters_) {
                m_iter.second->apply_application_time(wakeup_time);
            }

            for (auto& m_iter : masters_) {
                m_iter.second->receive();
            }

            rethrowSerialExceptionIfAny();

            applyControllerRequests(controller_indices_);

            for (auto& m_iter : masters_) {
                m_iter.second->save_clock();
            }

            for (auto& m_iter : masters_) {
                m_iter.second->transmit();
            }
        }

        rethrowSerialExceptionIfAny();
    } catch (...) {
        if (memory_locked) unlock_memory();
        stopSerial();
        stop();
        throw;
    }

    if (memory_locked) unlock_memory();
    stopSerial();
    stop();
}
