add_library(feetech src/feetech_driver.cpp)

target_include_directories(feetech PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>
)

target_link_libraries(feetech
  PUBLIC
    motor_interface::motor_interface
    serial::serial
    dynamixel::dynamixel
)

target_compile_features(feetech PUBLIC cxx_std_17)

add_library(feetech::feetech ALIAS feetech)
