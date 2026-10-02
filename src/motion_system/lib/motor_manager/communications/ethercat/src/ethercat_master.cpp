#include <stdexcept>

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
