cmake_minimum_required(VERSION 3.16)
project(xtouch_midi CXX)

if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 17)
  set(CMAKE_CXX_STANDARD_REQUIRED ON)
endif()

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(midi_msgs REQUIRED)

find_package(PkgConfig REQUIRED)
pkg_check_modules(RTMIDI REQUIRED IMPORTED_TARGET rtmidi)

add_executable(xtouch_node
  src/xtouch_node.cpp
)
target_include_directories(xtouch_node PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>
)
ament_target_dependencies(xtouch_node
  rclcpp
  midi_msgs
)
target_link_libraries(xtouch_node
  PkgConfig::RTMIDI
)
target_compile_features(xtouch_node PUBLIC cxx_std_17)

install(TARGETS xtouch_node
  DESTINATION lib/${PROJECT_NAME}
)

install(DIRECTORY launch
  DESTINATION share/${PROJECT_NAME}
)

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  set(ament_cmake_copyright_FOUND TRUE)
  set(ament_cmake_cpplint_FOUND TRUE)
  ament_lint_auto_find_test_dependencies()
endif()

ament_package()
