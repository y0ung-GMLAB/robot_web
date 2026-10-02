add_library(minas src/minas_driver.cpp)

target_include_directories(minas PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>
)

target_link_libraries(minas PUBLIC motor_interface::motor_interface)

target_compile_features(minas PUBLIC cxx_std_17)

add_library(minas::minas ALIAS minas)
