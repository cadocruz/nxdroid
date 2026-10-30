# Desktop smoke build of the vendored Vulkan replay engine (dm/gfx/vulkan/engine), outside the
# vendored roots so that dm/tools/android_vendor.py --check stays clean.
#
# Targets:
#   make            build whatever builds into build/engine_smoke
#   make report     one line per translation unit: "ok", or the first error; also the two shared headers
#                   as C and as C++ (the engine includes them from C++)
#   make headers    compile dm/gfx/nvn/nvn_obj.h + nvn_mtl.h alone, as C (gcc, clang) and C++ (g++, clang++)
#   make map        regenerate opcode_map.txt; make check-map fails when it is stale
#   make run        run on Mesa lavapipe (VK_ICD_FILENAMES, no window, no surface)
#   make run-gpu    run on the machine's default Vulkan device (SMOKE_DEVICE selects by name)
#   make gaps       regenerate abi_gaps.txt; make check-gaps fails when it is stale
#   make clean
#
# The engine sources are compiled in place: nothing under dm/gfx/vulkan/ is copied. xbg_game.cpp carries one
# local adaptation (the compatibility block at its top, recorded in dm/tools/android_vendor.tsv), because
# dm/gfx/nvn/nvn_obj.h is this host's record format and the engine's fork of it numbered the op enum
# differently. It compiles with clang++ and g++ as it stands: no -fpermissive, no -D workaround.

ENGINE     := $(abspath $(CURDIR)/../../vulkan/engine)
REPO       := $(abspath $(CURDIR)/../../../..)
OBJ        := $(CURDIR)/build
VULKAN_INC ?= /usr/include

INCS := -I$(ENGINE) -I$(REPO)/dm/gfx -I$(REPO)/dm/gfx/nvn -I$(REPO)/dm/gfx/nvn/include \
        -I$(VULKAN_INC) -I$(CURDIR)

CC = gcc
CXX = g++
CFLAGS   := -std=gnu11 -D_GNU_SOURCE -O1 -g -Wall -Wextra
CXXFLAGS := -std=c++17 -O1 -g -Wall -Wextra
LDFLAGS  :=
LDLIBS   := -lvulkan -lpthread -ldl

# The headers the engine includes from C++ (dm/gfx/nvn/nvn_obj.h, nvn_mtl.h) are also this host's C ABI.
# There is no -fpermissive and no -D workaround any more: both headers compile as C and as C++ with the
# casts they need (nvn_obj.h) and the fork's own opcodes named after OP_COUNT_ (see `make map`).
XBG_GAME_EXTRA :=

ENGINE_C   := $(wildcard $(ENGINE)/*.c)
ENGINE_CXX := $(wildcard $(ENGINE)/*.cpp)
# Harness sources, then the two pieces of this repository's own texture code the engine calls
# (real code, linked as it is: nvn_tex.c is the Tegra layout, nvn_deswizzle.c the block-linear decoder).
LOCAL_C    := $(CURDIR)/smoke.c $(CURDIR)/host_stubs.c
REPO_C     := $(REPO)/dm/gfx/nvn/nvn_tex.c $(REPO)/dm/gfx/tex/nvn_deswizzle.c

ENGINE_OBJ := $(patsubst $(ENGINE)/%.c,$(OBJ)/%.o,$(ENGINE_C)) \
              $(patsubst $(ENGINE)/%.cpp,$(OBJ)/%.o,$(ENGINE_CXX))
LOCAL_OBJ  := $(patsubst $(CURDIR)/%.c,$(OBJ)/%.o,$(LOCAL_C)) \
              $(OBJ)/repo_nvn_tex.o $(OBJ)/repo_nvn_deswizzle.o
OBJ_ALL    := $(sort $(ENGINE_OBJ) $(LOCAL_OBJ))
BIN        := $(OBJ)/engine_smoke

LVP_ICD ?= /usr/share/vulkan/icd.d/lvp_icd.json

.PHONY: all report headers run run-gpu gaps check-gaps map check-map clean

all: $(BIN)

$(OBJ):
	@mkdir -p $(OBJ)

$(OBJ)/%.o: $(ENGINE)/%.c | $(OBJ)
	$(CC) $(CFLAGS) $(INCS) -c $< -o $@

$(OBJ)/%.o: $(ENGINE)/%.cpp | $(OBJ)
	$(CXX) $(CXXFLAGS) $(INCS) -c $< -o $@

# The harness initialises Vulkan structs the usual way (sType then the fields it uses), which
# -Wmissing-field-initializers flags for every pNext; the engine's own one-line style makes
# -Wmisleading-indentation very noisy too. Both are style, not defects: keep them out of the
# harness's own build so that its warnings stay worth reading. The engine keeps the full -Wextra.
$(OBJ)/smoke.o $(OBJ)/host_stubs.o: CFLAGS += -Wno-missing-field-initializers

$(OBJ)/%.o: $(CURDIR)/%.c | $(OBJ)
	$(CC) $(CFLAGS) $(INCS) -c $< -o $@

$(OBJ)/repo_nvn_tex.o: $(REPO)/dm/gfx/nvn/nvn_tex.c | $(OBJ)
	$(CC) $(CFLAGS) $(INCS) -c $< -o $@

$(OBJ)/repo_nvn_deswizzle.o: $(REPO)/dm/gfx/tex/nvn_deswizzle.c | $(OBJ)
	$(CC) $(CFLAGS) $(INCS) -c $< -o $@

$(BIN): $(OBJ_ALL)
	$(CXX) $(LDFLAGS) -o $@ $(OBJ_ALL) $(LDLIBS)

# One line per translation unit, so the state of the port is one command away.
report: headers
	CC="$(CC)" CXX="$(CXX)" CFLAGS="$(CFLAGS)" CXXFLAGS="$(CXXFLAGS)" INCS="$(INCS)" \
	ENGINE="$(ENGINE)" REPO="$(REPO)" sh $(CURDIR)/report.sh

# The two headers the engine includes from C++ compile alone, as C and as C++: the engine includes them
# from a .cpp, the host stays C, and both have to keep working. -Werror here: a header either compiles
# clean or it does not.
headers:
	@for cc in gcc clang; do printf 'ok      nvn_obj.h + nvn_mtl.h as C (%s)\n' "$$cc"; \
	    echo '#include "nvn_obj.h"' | $$cc -std=gnu11 -Wall -Wextra -Werror $(INCS) -x c -fsyntax-only - || exit 1; \
	    echo '#include "nvn_mtl.h"' | $$cc -std=gnu11 -Wall -Wextra -Werror $(INCS) -x c -fsyntax-only - || exit 1; done
	@for cxx in g++ clang++; do printf 'ok      nvn_obj.h + nvn_mtl.h as C++ (%s)\n' "$$cxx"; \
	    echo '#include "nvn_obj.h"' | $$cxx -std=c++17 -Wall -Wextra -Werror $(INCS) -x c++ -fsyntax-only - || exit 1; \
	    echo '#include "nvn_mtl.h"' | $$cxx -std=c++17 -Wall -Wextra -Werror $(INCS) -x c++ -fsyntax-only - || exit 1; done

map:
	python3 $(CURDIR)/opcode_map.py

check-map:
	python3 $(CURDIR)/opcode_map.py --check

run: $(BIN)
	VK_ICD_FILENAMES=$(LVP_ICD) $(BIN)

run-gpu: $(BIN)
	$(BIN)

gaps:
	python3 $(CURDIR)/abi_gaps.py

check-gaps:
	python3 $(CURDIR)/abi_gaps.py --check

clean:
	rm -rf $(OBJ)
