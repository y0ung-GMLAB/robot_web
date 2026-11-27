add_library(serial
  src/serial_master.cpp
  src/serial_controller.cpp
)

target_include_directories(serial PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>
)

target_link_libraries(serial
  PUBLIC
    motor_interface::motor_interface
)

target_compile_features(serial PUBLIC cxx_std_17)

add_library(serial::serial ALIAS serial)
