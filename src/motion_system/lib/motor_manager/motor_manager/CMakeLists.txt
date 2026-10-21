add_library(motor_manager SHARED src/motor_manager.cpp)

target_include_directories(motor_manager PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>
)

# Same link order as before when EtherCAT is on · robot_web fix-list 158
set(MOTOR_MANAGER_ETHERCAT_PUBLIC "")
set(MOTOR_MANAGER_ETHERCAT_PRIVATE "")
if(MOTOR_MANAGER_WITH_ETHERCAT)
  set(MOTOR_MANAGER_ETHERCAT_PUBLIC "${MOTOR_MANAGER_IGH_ETHERCAT_LIB}")
  set(MOTOR_MANAGER_ETHERCAT_PRIVATE ethercat::ethercat)
  target_compile_definitions(motor_manager PRIVATE MOTOR_MANAGER_WITH_ETHERCAT)
endif()

target_link_libraries(motor_manager
  PUBLIC  motor_interface::motor_interface
  PUBLIC  ${MOTOR_MANAGER_ETHERCAT_PUBLIC}
  PRIVATE ${MOTOR_MANAGER_ETHERCAT_PRIVATE}
  PRIVATE canopen::canopen
  PRIVATE serial::serial
  PRIVATE socketcan::socketcan
  PRIVATE minas::minas
  PRIVATE zeroerr::zeroerr
  PRIVATE dynamixel::dynamixel
  PRIVATE feetech::feetech
  PRIVATE cubemars::cubemars
  PRIVATE yaml-cpp
)

target_compile_features(motor_manager PUBLIC cxx_std_17)

add_library(motor_manager::motor_manager ALIAS motor_manager)
