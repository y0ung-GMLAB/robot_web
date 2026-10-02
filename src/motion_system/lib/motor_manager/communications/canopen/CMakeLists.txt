add_library(canopen
  src/canopen_master.cpp
  src/canopen_controller.cpp
)

target_include_directories(canopen PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>
)

target_link_libraries(canopen
  PUBLIC
    motor_interface::motor_interface
)

target_compile_features(canopen PUBLIC cxx_std_17)

add_library(canopen::canopen ALIAS canopen)
