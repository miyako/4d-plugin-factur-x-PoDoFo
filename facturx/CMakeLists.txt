cmake_minimum_required(VERSION 3.20)

set(PLUGIN_NAME "facturx" CACHE STRING "Plugin name")

project(${PLUGIN_NAME} LANGUAGES C CXX)

# Where the finished plugin lands. It defaults to the test project's Plugins
# folder so a plain build is immediately testable; release builds override it
# to keep the two macOS architecture slices apart before they are merged.
set(FACTURX_PLUGIN_OUTPUT_DIR "${CMAKE_CURRENT_SOURCE_DIR}/${PLUGIN_NAME}-test/Plugins"
    CACHE PATH "Directory the built plugin is written to")

# PoDoFo requires C++17; the plugin itself is written against C++17 too so the
# same standard applies to every translation unit.
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_C_STANDARD 11)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

set(ROOT_DIR "${CMAKE_CURRENT_SOURCE_DIR}/..")
set(SDK_DIR "${ROOT_DIR}/4D-Plugin-SDK/4D Plugin API")

if(NOT EXISTS "${SDK_DIR}")
    message(FATAL_ERROR
        "Missing ${SDK_DIR}. Run: git submodule update --init --recursive")
endif()

# Static CRT on Windows. Must be set before any dependency is resolved.
if(MSVC)
    set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>" CACHE STRING "" FORCE)
endif()

# --------------------------------------------------------------------
# PoDoFo (LGPL-2.0-or-later OR MPL-2.0)
#
# Resolved as a prebuilt package rather than a submodule: PoDoFo pulls in
# zlib, freetype, libxml2 and OpenSSL, and letting the platform package
# manager (vcpkg on Windows, Homebrew on macOS) resolve that graph is far
# more reliable than vendoring five build systems.
#
#   macOS   : brew install podofo
#   Windows : vcpkg install podofo:x64-windows-static
#             cmake -A x64 -DCMAKE_TOOLCHAIN_FILE=<vcpkg>/scripts/buildsystems/vcpkg.cmake
# --------------------------------------------------------------------
find_package(podofo CONFIG QUIET)

if(TARGET podofo::podofo)
    set(PODOFO_TARGET podofo::podofo)
elseif(TARGET podofo_shared)
    set(PODOFO_TARGET podofo_shared)
elseif(TARGET podofo_static)
    set(PODOFO_TARGET podofo_static)
else()
    find_package(PkgConfig REQUIRED)
    pkg_check_modules(PODOFO REQUIRED IMPORTED_TARGET libpodofo)
    set(PODOFO_TARGET PkgConfig::PODOFO)
endif()

message(STATUS "PoDoFo target: ${PODOFO_TARGET}")

# --------------------------------------------------------------------
# plugin
# --------------------------------------------------------------------
set(PLUGIN_SOURCES
    "${CMAKE_CURRENT_SOURCE_DIR}/${PLUGIN_NAME}-4dplugin.cpp"
    "${SDK_DIR}/4DPluginAPI.c")

set(PLUGIN_HEADERS
    "${CMAKE_CURRENT_SOURCE_DIR}/${PLUGIN_NAME}-4dplugin.h")

set(PLUGIN_RESOURCES
    "${CMAKE_CURRENT_SOURCE_DIR}/manifest.json"
    "${CMAKE_CURRENT_SOURCE_DIR}/constants.xlf")

set_source_files_properties("${SDK_DIR}/4DPluginAPI.c" PROPERTIES LANGUAGE CXX)

if(APPLE)
    add_library(${PLUGIN_NAME} MODULE
        ${PLUGIN_SOURCES} ${PLUGIN_HEADERS} ${PLUGIN_RESOURCES})

    set_target_properties(${PLUGIN_NAME} PROPERTIES
        BUNDLE TRUE
        BUNDLE_EXTENSION "bundle"
        MACOSX_BUNDLE_INFO_PLIST "${CMAKE_CURRENT_SOURCE_DIR}/Info.plist.in"
        MACOSX_BUNDLE_GUI_IDENTIFIER "com.4d.${PLUGIN_NAME}"
        MACOSX_BUNDLE_BUNDLE_VERSION "1.0"
        MACOSX_BUNDLE_SHORT_VERSION_STRING "1.0")

    set_source_files_properties(${PLUGIN_RESOURCES} PROPERTIES
        MACOSX_PACKAGE_LOCATION Resources)

    # The SDK's C sources predate -Wint-conversion being an error and use
    # multi-character constants.
    set_source_files_properties("${SDK_DIR}/4DPluginAPI.c" PROPERTIES
        COMPILE_FLAGS "-Wno-int-conversion -Wno-multichar")

    find_library(COREGRAPHICS_FRAMEWORK CoreGraphics REQUIRED)
    find_library(COREFOUNDATION_FRAMEWORK CoreFoundation REQUIRED)
    target_link_libraries(${PLUGIN_NAME} PRIVATE
        ${COREGRAPHICS_FRAMEWORK} ${COREFOUNDATION_FRAMEWORK})

    set_target_properties(${PLUGIN_NAME} PROPERTIES
        LIBRARY_OUTPUT_DIRECTORY "${FACTURX_PLUGIN_OUTPUT_DIR}"
        LIBRARY_OUTPUT_DIRECTORY_DEBUG "${FACTURX_PLUGIN_OUTPUT_DIR}"
        LIBRARY_OUTPUT_DIRECTORY_RELEASE "${FACTURX_PLUGIN_OUTPUT_DIR}")

elseif(WIN32)
    add_library(${PLUGIN_NAME} SHARED ${PLUGIN_SOURCES} ${PLUGIN_HEADERS})

    set_target_properties(${PLUGIN_NAME} PROPERTIES
        SUFFIX ".4DX"
        LINK_FLAGS "/DEF:\"${CMAKE_CURRENT_SOURCE_DIR}/${PLUGIN_NAME}.def\"")

    target_compile_definitions(${PLUGIN_NAME} PRIVATE
        _CRT_SECURE_NO_WARNINGS UNICODE _UNICODE NOMINMAX)
    target_compile_options(${PLUGIN_NAME} PRIVATE
        /bigobj /utf-8 /EHsc /wd4267 /wd4244 /wd4305 /wd4996)

    set(PLUGIN_OUT_DIR "${FACTURX_PLUGIN_OUTPUT_DIR}/${PLUGIN_NAME}/Contents/Windows64")
    set(RESOURCE_OUT_DIR "${FACTURX_PLUGIN_OUTPUT_DIR}/${PLUGIN_NAME}/Contents/Resources")

    set_target_properties(${PLUGIN_NAME} PROPERTIES
        RUNTIME_OUTPUT_DIRECTORY "${PLUGIN_OUT_DIR}"
        RUNTIME_OUTPUT_DIRECTORY_DEBUG "${PLUGIN_OUT_DIR}"
        RUNTIME_OUTPUT_DIRECTORY_RELEASE "${PLUGIN_OUT_DIR}")

    add_custom_command(TARGET ${PLUGIN_NAME} POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E make_directory "${RESOURCE_OUT_DIR}"
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            ${PLUGIN_RESOURCES} "${RESOURCE_OUT_DIR}"
        COMMENT "Copying manifest.json and constants.xlf into Contents/Resources")
else()
    message(FATAL_ERROR "Only macOS and Windows are supported targets.")
endif()

target_include_directories(${PLUGIN_NAME} PRIVATE "${SDK_DIR}")
target_link_libraries(${PLUGIN_NAME} PRIVATE ${PODOFO_TARGET})
