#include <spawn.h>
#include <stdexcept>
#include <string>
#include <sys/wait.h>
#include <thread>

extern char** environ;

#include "ethercat/ethercat_master.hpp"

void ethercat::EthercatMaster::initialize()
{
    master_ = ecrt_request_master(master_index_);
    if (master_ == nullptr) throw std::runtime_error("Failed to request master.");

    domain_ = ecrt_master_create_domain(master_);
    if (domain_ == nullptr) throw std::runtime_error("Failed to create domain.");
}

void ethercat::EthercatMaster::activate()
{
    if (ecrt_master_activate(master_)) throw std::runtime_error("Failed to activate master.");

    if (!(domain_pd_ = ecrt_domain_data(domain_))) throw std::runtime_error("Failed to get domain data.");
}

void ethercat::EthercatMaster::deactivate()
{
    if (ecrt_master_deactivate(master_)) throw std::runtime_error("Failed to deactivate master.");
}

void ethercat::EthercatMaster::transmit()
{
    if (ecrt_domain_queue(domain_)) throw std::runtime_error("Failed to queue datagrams.");

    if (ecrt_master_send(master_)) throw std::runtime_error("Failed to send datagrams.");
}

void ethercat::EthercatMaster::receive()
{
    if (ecrt_master_receive(master_)) throw std::runtime_error("Failed to receive frames.");

    if (ecrt_domain_process(domain_)) throw std::runtime_error("Failed to determine the states of the domain.");
}

void ethercat::EthercatMaster::apply_application_time(const timespec& time)
{
    const uint64_t nanoseconds =
        static_cast<uint64_t>(time.tv_sec) * 1000000000ULL + static_cast<uint64_t>(time.tv_nsec);
    ecrt_master_application_time(master_, nanoseconds);
}

void ethercat::EthercatMaster::save_clock()
{
    ecrt_master_sync_slave_clocks(master_);
}

void ethercat::EthercatMaster::request_safe_state()
{
    // robot_web fix-list 188 (NY 2026-11-09): deactivating straight from OP stopped the
    // PDO cycle while every slave still had its SM2 watchdog armed; the master's state
    // machine then walked them down one by one, and the last ones hit the watchdog first
    // (AL 0x001B "Sync manager watchdog", SAFEOP + ERROR) on every service stop, which
    // then often came back as PREOP + ERROR on the next start. Ask for PREOP while the
    // application keeps cycling. Same CLI the start-up retry already uses (fix-list 187).
    const std::string index = std::to_string(master_index_);
    std::thread([index]() {
        char arg0[] = "ethercat";
        char arg1[] = "states";
        char arg2[] = "-m";
        std::string m = index;
        char arg4[] = "PREOP";
        char* argv[] = {arg0, arg1, arg2, m.data(), arg4, nullptr};
        pid_t pid = 0;
        if (posix_spawnp(&pid, "ethercat", nullptr, nullptr, argv, environ) == 0) {
            int status = 0;
            (void)waitpid(pid, &status, 0);
        }
    }).detach();
}

bool ethercat::EthercatMaster::safe_state_reached()
{
    ec_master_state_t state{};
    if (ecrt_master_state(master_, &state) != 0) return true;   // cannot tell · do not hold the stop
    if (state.slaves_responding == 0) return true;
    // al_states is the OR of all slaves' states · only INIT/PREOP bits left = nobody in SAFEOP/OP
    return (state.al_states & (EC_AL_STATE_SAFEOP | EC_AL_STATE_OP)) == 0;
}
