add_library(dynamixel src/dynamixel_driver.cpp)

target_include_directories(dynamixel PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>
)

target_link_libraries(dynamixel
  PUBLIC
    motor_interface::motor_interface
    serial::serial
  PRIVATE yaml-cpp
)

target_compile_features(dynamixel PUBLIC cxx_std_17)

add_library(dynamixel::dynamixel ALIAS dynamixel)
