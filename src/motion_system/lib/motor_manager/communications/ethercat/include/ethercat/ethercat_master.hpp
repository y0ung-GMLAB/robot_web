#ifndef ETHERCAT_ETHERCAT_MASTER_HPP_
#define ETHERCAT_ETHERCAT_MASTER_HPP_

#include "ecrt.h"

#include "motor_interface/motor_master.hpp"

namespace ethercat {

class EthercatMaster : public motor_interface::MotorMaster {
public:
    explicit EthercatMaster(const motor_interface::master_config_t& config)
    : motor_interface::MotorMaster(config)
    , master_index_(config.ethercat_master_index) {}

    virtual ~EthercatMaster() = default;

    virtual void initialize() override;

    virtual void activate() override;

    virtual void deactivate() override;

    virtual void transmit() override;

    virtual void receive() override;

    virtual void apply_application_time(const timespec& time) override;

    virtual void save_clock() override;

    ec_master_t* master() const { return master_; }

    ec_domain_t* domain() const { return domain_; }

    uint8_t* domain_pd() const { return domain_pd_; }

    unsigned int master_index() const { return master_index_; }

private:
    ec_master_t* master_{nullptr};

    ec_domain_t* domain_{nullptr};

    uint8_t* domain_pd_{nullptr};

    const unsigned int master_index_{0};
};

} // namespace ethercat
#endif // ETHERCAT_ETHERCAT_MASTER_HPP_
