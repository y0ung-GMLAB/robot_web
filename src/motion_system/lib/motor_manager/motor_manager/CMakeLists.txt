add_library(motor_manager SHARED src/motor_manager.cpp)

target_include_directories(motor_manager PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>
)

target_link_libraries(motor_manager
  PUBLIC  motor_interface::motor_interface
  PUBLIC  "${MOTOR_MANAGER_IGH_ETHERCAT_LIB}"
  PRIVATE ethercat::ethercat
  PRIVATE canopen::canopen
  PRIVATE serial::serial
  PRIVATE socketcan::socketcan
  PRIVATE minas::minas
  PRIVATE zeroerr::zeroerr
  PRIVATE dynamixel::dynamixel
  PRIVATE cubemars::cubemars
  PRIVATE yaml-cpp
)

target_compile_features(motor_manager PUBLIC cxx_std_17)

add_library(motor_manager::motor_manager ALIAS motor_manager)
