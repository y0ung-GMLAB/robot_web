add_library(ethercat
  src/ethercat_master.cpp
  src/ethercat_controller.cpp
)

target_include_directories(ethercat PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<BUILD_INTERFACE:${MOTOR_MANAGER_IGH_ETHERCAT_INCLUDE_DIR}>
  $<INSTALL_INTERFACE:include>
)

# IgH libethercat must be PUBLIC: our ethercat target is usually a static archive, so
# ecrt_* stay undefined in the .a until the final link; consumers (e.g. libmotor_manager.so)
# must see this library on the link line.
target_link_libraries(ethercat
  PUBLIC
    motor_interface::motor_interface
    "${MOTOR_MANAGER_IGH_ETHERCAT_LIB}"
)

target_compile_features(ethercat PUBLIC cxx_std_17)

add_library(ethercat::ethercat ALIAS ethercat)
