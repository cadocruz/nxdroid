// The host side of the engine's ABI that no engine translation unit defines, and that
// xbg_game_initialize / xbg_game_shutdown need. In a real port both live in the host's NVN layer
// (dm/gfx/nvn/hle_nvn.c): the serial counter that names a recorded object, and the record writer
// into the game's own command memory.
//
// Everything else xbg_game_internal.h declares is already defined by the engine itself
// (xbg_game.cpp: xbg_logf, xbg_fatalf, the xbg_legacy_* pool and fence calls, xbg_submit,
// xbg_present_texture, xbg_shader_control_key, ...; xbg_command_clone.c: the clone/copy helpers).
// Verified with nm over the engine objects, not by reading:
//   nm --defined-only build/xbg_*.o | awk '$2=="T"{print $3}' | grep '^xbg_'
#include "xbg_game_internal.h"

#include <stdatomic.h>
#include <stdio.h>

// hle_nvn.c defines this as a global counter (dm/gfx/nvn/hle_nvn.c, nvn_new_serial): each texture,
// program and event object the host registers gets a serial, and the replay layer finds its host
// object by it. Only uniqueness matters here.
uint64_t nvn_new_serial(void) {
    static _Atomic uint64_t serial;
    return atomic_fetch_add(&serial, 1) + 1;
}

// hle_nvn.c writes one record (op_hdr + payload) into the command memory the game gave the command
// buffer. The smoke run never records a command -- it has no guest and no command buffer -- so it
// says so loudly instead of pretending to have stored one.
void xbg_record_command(cmd_t *command, const void *record, uint32_t bytes) {
    (void)command; (void)record; (void)bytes;
    fprintf(stderr, "[stub] xbg_record_command reached\n");
    fflush(stderr);
}
