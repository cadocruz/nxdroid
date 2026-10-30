# Android host build (NDK, arm64-v8a) of this repository's host for one game profile, the shape of `make -C dm/host GAME=<id>`:
#   cmake -S dm/android -B <build dir> -DGAME=<base game title ID> -DCMAKE_TOOLCHAIN_FILE=<NDK>/build/cmake/android.toolchain.cmake -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=29
# GAME is required (there is no default game: without it the configure stops and lists the profiles, as the Makefile does); a profile outside the
# repository is found through DM_GAMES_DIR (the environment at configure, kept in the cache for the build), as everywhere else (dm/games/game.py).
# game_profile.h is generated from the profile's game.tsv into <build dir>/gen/<id>/ by the same game.py header the Apple build uses, so every
# per-game value stays in the profile and none in this file.
# The source list is not copied by hand: tools/host_sources.py takes SRC and GFX from dm/host/Makefile (the same idea as iOS's ios/tools/gen_build.py),
# dropping the Mac-only files (*.m, front_*.m) and main.c (built on its own: the command-line dmhost keeps the name main, the App's libdm.so builds it
# with -Dmain=dm_main). Dropping every .m also drops dm/gfx/vk/hle_vk.m and dm/gfx/gl/hle_gl.m, the Vulkan and OpenGL layers' HLE on Metal: a profile
# whose game renders through Vulkan or OpenGL (the games table names them) has no graphics layer on Android until those are ported. Assembly (Mach-O
# syntax) is converted to ELF by tools/asm_elf.py before assembling; compat/ is only on the Android build's header path, invisible to Apple builds;
# port_android.c is dm/host/port.h on bionic; tools/undef_scan.py reports at configure the functions the kept sources call and only a dropped .m defines.
# arm64 only (port_android.c packs tid << 32 into a uintptr_t: LP64), ANDROID_PLATFORM >= 29: the rewritten guest code finds its thread slots through
# bionic's TLS_SLOT_APP, which is the app's from Android 10 (API 29; errno before, port.h dm_kslot_*), and the slot table is ELF TLS, native in bionic
# from 29 (vulkan_present.cpp's Vulkan 1.1 entry points need 28, aaudio 26); the platform gate fails closed when the level cannot be read.
# Outputs: dmhost (command line, run from adb shell, for development checks); libdm.so (the App's JNI host) once the app shell (jni_android.c) is in.
cmake_minimum_required(VERSION 3.22)
project(dm_android C CXX ASM)
set(GAME "" CACHE STRING "base game title ID of the profile to build the host for (dm/games/<id>/, or DM_GAMES_DIR); required")
set(DM_GAMES_DIR "$ENV{DM_GAMES_DIR}" CACHE STRING "profile folders outside the repository, ':'-separated (dm/games/game.py); read from the environment at configure, passed to game.py at build")
set(DM ${CMAKE_CURRENT_SOURCE_DIR}/..)
set(HOST ${DM}/host)
get_filename_component(DM_REPO_ROOT ${DM}/.. ABSOLUTE)
find_package(Python3 REQUIRED COMPONENTS Interpreter)
if(NOT CMAKE_SIZEOF_VOID_P EQUAL 8)
  message(FATAL_ERROR "the Android host is arm64 (LP64) only: port_android.c packs tid << 32 into a uintptr_t, and the guest is AArch64")
endif()
if(CMAKE_SYSTEM_NAME STREQUAL "Android")
  if(NOT ANDROID_ABI STREQUAL "arm64-v8a")
    message(FATAL_ERROR "ANDROID_ABI=${ANDROID_ABI}: the Android host is arm64-v8a only")
  endif()
  # The platform level, from whichever variable the toolchain file gives (ANDROID_PLATFORM_LEVEL is the NDK toolchain's number; ANDROID_PLATFORM is
  # what the command line passed, "29" or "android-29"); none of them readable is an error, not a pass.
  if(DEFINED ANDROID_PLATFORM_LEVEL)
    set(dm_platform "${ANDROID_PLATFORM_LEVEL}")
  elseif(DEFINED ANDROID_PLATFORM)
    string(REGEX REPLACE "^android-" "" dm_platform "${ANDROID_PLATFORM}")
  else()
    message(FATAL_ERROR "cannot read the Android platform level (neither ANDROID_PLATFORM_LEVEL nor ANDROID_PLATFORM is set): pass -DANDROID_PLATFORM=29 or newer")
  endif()
  if(NOT dm_platform MATCHES "^[0-9]+$" OR dm_platform LESS 29)
    message(FATAL_ERROR "ANDROID_PLATFORM=${dm_platform}: at least 29 (the guest thread slots live in bionic's TLS_SLOT_APP, the app's from API 29, in an ELF TLS table, port.h dm_kslot_*; vulkan_present.cpp calls vkEnumerateInstanceVersion and vkGetPhysicalDeviceFeatures2 / Properties2 directly, exported by the NDK's libvulkan stub from API 28; aaudio needs 26)")
  endif()
endif()
# The Makefile's -O1 -g with no NDEBUG, for C and C++ alike, whatever the build type: CMake's per-config flags are emptied for every configuration
# (-DCMAKE_BUILD_TYPE=Release would otherwise add -O3 -DNDEBUG next to the -O1), and a default is set so that single-config generators have one.
# The engine subdirectory keeps its own -O2 -g.
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE RelWithDebInfo CACHE STRING "build type (the host's flags do not depend on it)" FORCE)
endif()
foreach(cfg DEBUG RELEASE RELWITHDEBINFO MINSIZEREL)
  set(CMAKE_C_FLAGS_${cfg} "")
  set(CMAKE_CXX_FLAGS_${cfg} "")
  set(CMAKE_ASM_FLAGS_${cfg} "")
endforeach()

# ---- The game profile (dm/games/game.py; GAME as in dm/host/Makefile) ----
# game.py reads DM_GAMES_DIR from the environment. The cache (the environment of the first configure, or -DDM_GAMES_DIR=) is the one value every
# game.py call sees, at configure and at build time: set, it is passed in; empty, the variable is unset for the call, so a configure run under an
# environment the cache does not have cannot find a profile the build would then miss. A configure whose environment differs from the cache says so.
if(DEFINED ENV{DM_GAMES_DIR} AND NOT "$ENV{DM_GAMES_DIR}" STREQUAL "${DM_GAMES_DIR}")
  if(DM_GAMES_DIR)
    message(STATUS "DM_GAMES_DIR: the environment says '$ENV{DM_GAMES_DIR}', the cache keeps '${DM_GAMES_DIR}' from the first configure; configure and build use the cache (pass -DDM_GAMES_DIR=... to change it)")
  else()
    message(STATUS "DM_GAMES_DIR='$ENV{DM_GAMES_DIR}' in the environment is ignored: the cache from the first configure is empty, and configure and build both run game.py without it (pass -DDM_GAMES_DIR=$ENV{DM_GAMES_DIR} to use it)")
  endif()
endif()
if(DM_GAMES_DIR)
  set(GAME_PY ${CMAKE_COMMAND} -E env "DM_GAMES_DIR=${DM_GAMES_DIR}" ${Python3_EXECUTABLE} ${DM}/games/game.py)
else()
  set(GAME_PY ${CMAKE_COMMAND} -E env --unset=DM_GAMES_DIR ${Python3_EXECUTABLE} ${DM}/games/game.py)
endif()
if(NOT GAME)
  execute_process(COMMAND ${GAME_PY} list OUTPUT_VARIABLE profiles OUTPUT_STRIP_TRAILING_WHITESPACE)
  string(REPLACE "\n" "\n  " profiles "${profiles}")
  message(FATAL_ERROR "GAME is not set: cmake -DGAME=<base game title ID>; the profiles (id, title id, name):\n  ${profiles}")
endif()
execute_process(COMMAND ${GAME_PY} dir ${GAME} OUTPUT_VARIABLE GAME_DIR RESULT_VARIABLE game_result OUTPUT_STRIP_TRAILING_WHITESPACE)
file(TO_CMAKE_PATH "${GAME_DIR}" GAME_DIR)   # forward slashes whatever the host OS prints
if(NOT game_result EQUAL 0 OR NOT EXISTS ${GAME_DIR}/game.tsv)
  execute_process(COMMAND ${GAME_PY} list OUTPUT_VARIABLE profiles OUTPUT_STRIP_TRAILING_WHITESPACE)
  string(REPLACE "\n" "\n  " profiles "${profiles}")
  message(FATAL_ERROR "no game profile ${GAME} (neither in dm/games nor in DM_GAMES_DIR='${DM_GAMES_DIR}'); the profiles:\n  ${profiles}")
endif()
set(GAME_GEN ${CMAKE_CURRENT_BINARY_DIR}/gen/${GAME})
set(GAME_H ${GAME_GEN}/game_profile.h)
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS ${GAME_DIR}/game.tsv ${DM}/games/game.py)
add_custom_command(OUTPUT ${GAME_H}
  COMMAND ${GAME_PY} header ${GAME} ${GAME_H}
  DEPENDS ${GAME_DIR}/game.tsv ${DM}/games/game.py VERBATIM
  COMMENT "game_profile.h for ${GAME} (${GAME_DIR}/game.tsv)")
add_custom_target(game_profile DEPENDS ${GAME_H})

# No local paths in the products (__FILE__ in assertions and the source / generated / NDK paths in debug info all end up in libdm.so, exposing the
# user name and directory layout): replace them with neutral prefixes, longer ones first (the build directory is inside the source tree).
foreach(map "${CMAKE_BINARY_DIR}=build" "${CMAKE_ANDROID_NDK}=ndk" "${DM_REPO_ROOT}=src")
  if(NOT map MATCHES "^=")   # a desktop configure (no NDK) has no NDK path to map
    add_compile_options("-ffile-prefix-map=${map}")
  endif()
endforeach()

# SPIRV-Tools (Apache-2.0, not imported: docs/reference/android.md, Licensing) is optional: without it the engine's gfx-inline mitigation for the
# Adreno 750-799 family is not built (the target Adreno 740 is outside that family). Before the engine, which looks for the dm_spirv_opt target.
if(EXISTS ${DM}/third_party/spirv-tools/CMakeLists.txt)
  add_subdirectory(${DM}/third_party/spirv-tools ${CMAKE_CURRENT_BINARY_DIR}/spirv-tools)
else()
  message(STATUS "dm/third_party/spirv-tools is not in the tree: the engine builds without helper inlining (gfx-inline)")
endif()
add_subdirectory(../gfx/vulkan ${CMAKE_CURRENT_BINARY_DIR}/vulkan)

# ---- The host's sources, from dm/host/Makefile (Python keeps the Makefile's continuations; CMake's list escaping would join lines) ----
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS ${HOST}/Makefile ${CMAKE_CURRENT_SOURCE_DIR}/tools/host_sources.py)
execute_process(COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tools/host_sources.py
  ${HOST}/Makefile ${CMAKE_CURRENT_BINARY_DIR}/host_sources.cmake
  RESULT_VARIABLE parse_result)
if(NOT parse_result EQUAL 0)
  message(FATAL_ERROR "Cannot read the host's source list from dm/host/Makefile (tools/host_sources.py)")
endif()
include(${CMAKE_CURRENT_BINARY_DIR}/host_sources.cmake)
# Functions the kept sources call and only a dropped .m defines would fail the -Wl,--no-undefined link: say so at configure, before the NDK does
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS ${CMAKE_CURRENT_SOURCE_DIR}/tools/undef_scan.py)
execute_process(COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tools/undef_scan.py ${CMAKE_CURRENT_BINARY_DIR}/host_sources.cmake
  RESULT_VARIABLE undef_result OUTPUT_VARIABLE undef_out ERROR_VARIABLE undef_err)
if(NOT undef_result EQUAL 0)
  message(WARNING "tools/undef_scan.py: functions the Android build calls and does not define (the link will fail):\n${undef_out}${undef_err}")
endif()

# libvpx (movie decoding, hle_movie.c): the Makefile builds it file by file into a static library with its arm64 configuration headers in config/
file(GLOB_RECURSE VPX_SRCS CONFIGURE_DEPENDS ${VPX_DIR}/*.c)
add_library(dm_vpx STATIC ${VPX_SRCS})
target_include_directories(dm_vpx PUBLIC ${VPX_DIR} ${VPX_DIR}/config)
target_compile_options(dm_vpx PRIVATE -O2 -g -w)
set_target_properties(dm_vpx PROPERTIES POSITION_INDEPENDENT_CODE ON)

# ---- Assembly: Mach-O -> ELF ----
# ASM_IN is the one list of the host's .S files: tools/undef_scan.py reads it from here (their labels define for the link) instead of copying it.
set(ASM_IN ${HOST}/entry.S ${DM}/gfx/nvn/nvn_entry.S ${DM}/gfx/nvn/nvn_thunks.S)
set(ASM_SRCS)
foreach(s ${ASM_IN})
  get_filename_component(n ${s} NAME)
  set(out ${CMAKE_CURRENT_BINARY_DIR}/asm/${n})
  add_custom_command(OUTPUT ${out} COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tools/asm_elf.py ${s} ${out}
                     DEPENDS ${s} ${CMAKE_CURRENT_SOURCE_DIR}/tools/asm_elf.py VERBATIM)
  list(APPEND ASM_SRCS ${out})
endforeach()

# The Android side of the host: the front end (front.h), presentation (WSI), dm/host/port.h on bionic, the Apple-API shims and the NVN replay adapter.
set(ANDROID_SRCS
  ${CMAKE_CURRENT_SOURCE_DIR}/front_android.c
  ${CMAKE_CURRENT_SOURCE_DIR}/vulkan_present.cpp
  ${CMAKE_CURRENT_SOURCE_DIR}/port_android.c
  ${CMAKE_CURRENT_SOURCE_DIR}/apple_stubs.c
  ${CMAKE_CURRENT_SOURCE_DIR}/compat/clonefile.c
  ${CMAKE_CURRENT_SOURCE_DIR}/compat/digest.c
  ${CMAKE_CURRENT_SOURCE_DIR}/compat/mach_thread.c
  ${CMAKE_CURRENT_SOURCE_DIR}/compat/mach_symbols.c
  ${DM}/gfx/vulkan/nvn_vk.c)

add_library(dmcore STATIC ${HOST_SRCS} ${GFX_SRCS} ${ASM_SRCS} ${ANDROID_SRCS} ${GAME_H})
target_include_directories(dmcore PUBLIC ${HOST} ${GAME_GEN} ${DM}/gfx/nvn/include ${DM}/third_party/vulkan-headers/include
  ${DM}/third_party/stb_vorbis ${CMAKE_CURRENT_SOURCE_DIR}/compat/include ${CMAKE_CURRENT_SOURCE_DIR}/apple_stubs/include)
# Same optimization level as the Makefile (-O1 -g); dm_android_compat.h force-included; -fno-strict-aliasing matches the host's habit of reading and
# writing guest memory under Apple clang's default behaviour
set(DM_CFLAGS -O1 -g -Wall -Wno-unused-function -fno-strict-aliasing -include ${CMAKE_CURRENT_SOURCE_DIR}/compat/include/dm_android_compat.h)
target_compile_options(dmcore PUBLIC $<$<COMPILE_LANGUAGE:C>:${DM_CFLAGS} -std=gnu17>)
# The C++ side (vulkan_present.cpp): the same level and aliasing rule, without the compat force-include (it includes no host header)
target_compile_options(dmcore PUBLIC $<$<COMPILE_LANGUAGE:CXX>:-O1 -g -Wall -fno-strict-aliasing>)
target_compile_features(dmcore PUBLIC cxx_std_17)
target_link_libraries(dmcore PUBLIC dm_vulkan_engine dm_vpx aaudio android log m dl)

# Command-line host: main.c as is
add_executable(dmhost ${HOST}/main.c)
target_link_libraries(dmhost PRIVATE -Wl,--whole-archive dmcore -Wl,--no-whole-archive)
target_link_options(dmhost PRIVATE -Wl,--no-undefined -Wl,-z,nostart-stop-gc -Wl,--export-dynamic)   # export symbols: dladdr in crash backtraces can name host functions

# Shared library for the App: main.c built with -Dmain=dm_main (as on iOS), JNI entry jni_android.c. The app shell (jni_android.c, its Java activity)
# is upstream's and not imported (docs/reference/android.md); the target exists once it is in. Kept in a separate target: a source property would
# also rename main in the command-line dmhost target in this directory.
if(EXISTS ${CMAKE_CURRENT_SOURCE_DIR}/jni_android.c)
  add_library(dm_app_main OBJECT ${HOST}/main.c)
  target_link_libraries(dm_app_main PRIVATE dmcore)
  target_compile_definitions(dm_app_main PRIVATE main=dm_main)
  add_library(dm SHARED $<TARGET_OBJECTS:dm_app_main> ${CMAKE_CURRENT_SOURCE_DIR}/jni_android.c)
  target_include_directories(dm PRIVATE ${CMAKE_CURRENT_BINARY_DIR})
  target_compile_definitions(dm PRIVATE $<$<CONFIG:Debug>:DM_ANDROID_DEBUG_ENV=1>)
  target_link_libraries(dm PRIVATE -Wl,--whole-archive dmcore -Wl,--no-whole-archive android)
  target_link_options(dm PRIVATE -Wl,--no-undefined -Wl,-z,nostart-stop-gc -Wl,-Bsymbolic)   # assembly addresses host globals by page (adrp + :lo12:): symbols bind locally inside the library and cannot be preempted
else()
  message(STATUS "dm/android/jni_android.c is not in the tree: only the command-line dmhost is built (libdm.so needs the app shell)")
endif()
