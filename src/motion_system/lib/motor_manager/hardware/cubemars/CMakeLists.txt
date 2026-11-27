add_library(cubemars src/cubemars_driver.cpp)

target_include_directories(cubemars PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>
)

target_link_libraries(cubemars
  PUBLIC
    motor_interface::motor_interface
    socketcan::socketcan
  PRIVATE yaml-cpp
)

target_compile_features(cubemars PUBLIC cxx_std_17)

add_library(cubemars::cubemars ALIAS cubemars)
