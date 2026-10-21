cmake_minimum_required(VERSION 3.16)
project(motor_manager VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_POSITION_INDEPENDENT_CODE ON)

find_package(ament_cmake REQUIRED)
find_package(common_motor_interface REQUIRED)
find_package(yaml-cpp REQUIRED)

# EtherCAT (AC servos) · ON = as before, ecrt.h and libethercat required ·
# OFF only for a serial-only PC or a development build · robot_web fix-list 158
option(MOTOR_MANAGER_WITH_ETHERCAT "Build the IgH EtherCAT master (AC servos)" ON)

if(MOTOR_MANAGER_WITH_ETHERCAT)
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
endif()

add_subdirectory(core/motor_interface)
if(MOTOR_MANAGER_WITH_ETHERCAT)
  add_subdirectory(communications/ethercat)
endif()
add_subdirectory(communications/canopen)
add_subdirectory(communications/serial)
add_subdirectory(communications/socketcan)
add_subdirectory(hardware/minas)
add_subdirectory(hardware/zeroerr)
add_subdirectory(hardware/dynamixel)
add_subdirectory(hardware/feetech)
add_subdirectory(hardware/cubemars)
add_subdirectory(motor_manager)

install(DIRECTORY core/motor_interface/include/ DESTINATION include)
if(MOTOR_MANAGER_WITH_ETHERCAT)
  install(DIRECTORY communications/ethercat/include/ DESTINATION include)
endif()
install(DIRECTORY communications/canopen/include/ DESTINATION include)
install(DIRECTORY communications/serial/include/ DESTINATION include)
install(DIRECTORY communications/socketcan/include/ DESTINATION include)
install(DIRECTORY hardware/minas/include/ DESTINATION include)
install(DIRECTORY hardware/zeroerr/include/ DESTINATION include)
install(DIRECTORY hardware/dynamixel/include/ DESTINATION include)
install(DIRECTORY hardware/feetech/include/ DESTINATION include)
install(DIRECTORY hardware/cubemars/include/ DESTINATION include)
install(DIRECTORY motor_manager/include/ DESTINATION include)

set(MOTOR_MANAGER_INSTALL_TARGETS motor_manager canopen serial socketcan minas motor_interface zeroerr dynamixel feetech cubemars)
if(MOTOR_MANAGER_WITH_ETHERCAT)
  list(APPEND MOTOR_MANAGER_INSTALL_TARGETS ethercat)
endif()

install(
  TARGETS ${MOTOR_MANAGER_INSTALL_TARGETS}
  EXPORT export_${PROJECT_NAME}
  ARCHIVE DESTINATION lib
  LIBRARY DESTINATION lib
  RUNTIME DESTINATION bin
)

ament_export_targets(export_${PROJECT_NAME} HAS_LIBRARY_TARGET)
ament_export_include_directories(include)
ament_export_dependencies(common_motor_interface)
ament_package()
