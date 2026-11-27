add_library(socketcan
  src/socketcan_master.cpp
  src/socketcan_controller.cpp
)

target_include_directories(socketcan PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>
)

target_link_libraries(socketcan
  PUBLIC
    motor_interface::motor_interface
)

target_compile_features(socketcan PUBLIC cxx_std_17)

add_library(socketcan::socketcan ALIAS socketcan)
