add_library(zeroerr src/zeroerr_driver.cpp)

target_include_directories(zeroerr PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>
)

target_link_libraries(zeroerr PUBLIC motor_interface::motor_interface)

target_compile_features(zeroerr PUBLIC cxx_std_17)

add_library(zeroerr::zeroerr ALIAS zeroerr)
