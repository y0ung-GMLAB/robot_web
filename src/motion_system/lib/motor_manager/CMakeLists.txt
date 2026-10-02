cmake_minimum_required(VERSION 3.16)
project(motor_manager VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_POSITION_INDEPENDENT_CODE ON)

find_package(ament_cmake REQUIRED)
find_package(common_motor_interface REQUIRED)
find_package(yaml-cpp REQUIRED)

find_path(MOTOR_MANAGER_IGH_ETHERCAT_INCLUDE_DIR ecrt.h
  HINTS /usr/local/include /usr/include /opt/etherlab/include
  DOC "IgH EtherCAT Master client headers")
if(NOT MOTOR_MANAGER_IGH_ETHERCAT_INCLUDE_DIR)
  message(FATAL_ERROR
    "ecrt.h (IgH EtherCAT Master headers) not found. Install it or set MOTOR_MANAGER_IGH_ETHERCAT_INCLUDE_DIR.")
endif()

find_library(MOTOR_MANAGER_IGH_ETHERCAT_LIB ethercat
  HINTS /usr/local/lib /usr/lib/x86_64-linux-gnu /usr/lib /opt/etherlab/lib
  DOC "IgH EtherCAT Master client library (libethercat)")
if(NOT MOTOR_MANAGER_IGH_ETHERCAT_LIB)
  message(FATAL_ERROR
    "libethercat (IgH EtherCAT Master) not found. Install it or set MOTOR_MANAGER_IGH_ETHERCAT_LIB.")
endif()

add_subdirectory(core/motor_interface)
add_subdirectory(communications/ethercat)
add_subdirectory(communications/canopen)
add_subdirectory(communications/serial)
add_subdirectory(communications/socketcan)
add_subdirectory(hardware/minas)
add_subdirectory(hardware/zeroerr)
add_subdirectory(hardware/dynamixel)
add_subdirectory(hardware/cubemars)
add_subdirectory(motor_manager)

install(DIRECTORY core/motor_interface/include/ DESTINATION include)
install(DIRECTORY communications/ethercat/include/ DESTINATION include)
install(DIRECTORY communications/canopen/include/ DESTINATION include)
install(DIRECTORY communications/serial/include/ DESTINATION include)
install(DIRECTORY communications/socketcan/include/ DESTINATION include)
install(DIRECTORY hardware/minas/include/ DESTINATION include)
install(DIRECTORY hardware/zeroerr/include/ DESTINATION include)
install(DIRECTORY hardware/dynamixel/include/ DESTINATION include)
install(DIRECTORY hardware/cubemars/include/ DESTINATION include)
install(DIRECTORY motor_manager/include/ DESTINATION include)

install(
  TARGETS motor_manager ethercat canopen serial socketcan minas motor_interface zeroerr dynamixel cubemars
  EXPORT export_${PROJECT_NAME}
  ARCHIVE DESTINATION lib
  LIBRARY DESTINATION lib
  RUNTIME DESTINATION bin
)

ament_export_targets(export_${PROJECT_NAME} HAS_LIBRARY_TARGET)
ament_export_include_directories(include)
ament_export_dependencies(common_motor_interface)
ament_package()
