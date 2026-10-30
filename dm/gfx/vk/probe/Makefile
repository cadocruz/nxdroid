# Vulkan capability probe for the Android port. Standalone: not part of the host build, not wired
# into CI. See README.md.

TOP := $(abspath ../../../..)
VULKAN_INCLUDE := $(TOP)/dm/third_party/vulkan-headers/include

CC ?= cc
CFLAGS ?= -std=c11 -O2 -Wall -Wextra -Werror
CFLAGS += -I$(VULKAN_INCLUDE)

SRC := vk_probe.c
BIN := vk_probe
ANDROID_BIN := vk_probe_android

# The NDK is only needed by the `android` target; the probe does not pick one up implicitly.
NDK ?= $(ANDROID_NDK)
UNAME_S := $(shell uname -s)
ifeq ($(UNAME_S),Darwin)
HOST_TAG ?= darwin-x86_64
else
HOST_TAG ?= linux-x86_64
endif
NDK_CLANG := $(NDK)/toolchains/llvm/prebuilt/$(HOST_TAG)/bin/clang

# Only the PIE executable target is given here: libvulkan.so does not exist on the
# platform before API 24 (Vulkan arrived with Android 7.0), so the NDK sysroot carries
# no stub below 24 and `-lvulkan` fails to link. Keep the floor at the platform's, not
# the app's, since the probe must also run on emulators that report an older apiVersion.
ANDROID_API ?= 24

.PHONY: desktop android run clean

desktop: $(BIN)

$(BIN): $(SRC)
	$(CC) $(CFLAGS) -o $@ $< -lvulkan

run: $(BIN)
	./$(BIN) $(ARGS)

android:
	@if [ -z "$(NDK)" ]; then \
		echo "vk_probe: set NDK (or ANDROID_NDK) to an Android NDK root, e.g." >&2; \
		echo "  make android NDK=\$$HOME/Android/Sdk/ndk/27.2.12479018" >&2; \
		exit 1; \
	fi
	@if [ ! -x "$(NDK_CLANG)" ]; then \
		echo "vk_probe: $(NDK_CLANG) does not exist; is $(NDK) an NDK root?" >&2; \
		exit 1; \
	fi
	$(NDK_CLANG) --target=aarch64-linux-android$(ANDROID_API) -std=c11 -O2 -Wall -Wextra -Werror \
		-I$(VULKAN_INCLUDE) -fPIE -pie -o $(ANDROID_BIN) $(SRC) -lvulkan -llog

clean:
	rm -f $(BIN) $(ANDROID_BIN)
