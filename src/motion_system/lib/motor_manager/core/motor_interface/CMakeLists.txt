add_library(motor_interface INTERFACE)

target_include_directories(motor_interface INTERFACE
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>
)

target_link_libraries(motor_interface INTERFACE common_motor_interface::common_motor_interface)

target_compile_features(motor_interface INTERFACE cxx_std_17)

add_library(motor_interface::motor_interface ALIAS motor_interface)
