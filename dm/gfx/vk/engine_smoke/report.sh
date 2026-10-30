#!/bin/sh
# Per-translation-unit state of the vendored engine's build on this machine, one line each:
# "ok", or "FAIL" with the first error. Invoked by `make report`, which passes the flags in.
#
# Every engine translation unit is reported with the same flags, xbg_game.cpp included: since the
# compatibility block at its top (and the casts in dm/gfx/nvn/nvn_obj.h) it needs no -fpermissive and no
# -D, which is the whole point - clang, the Android toolchain, has neither. `make headers` reports the two
# shared headers as C and as C++ with -Werror before this loop runs.
set -u
fail=0

first_error() {
    grep -m1 -E 'error:|fatal error:' | sed 's/^[^:]*:[0-9]*:[0-9]*: //'
}

for f in "$ENGINE"/*.c; do
    if out=$("$CC" $CFLAGS $INCS -fsyntax-only "$f" 2>&1); then
        printf 'ok      %s\n' "$(basename "$f")"
    else
        printf 'FAIL    %s: %s\n' "$(basename "$f")" "$(printf '%s\n' "$out" | first_error)"
        fail=1
    fi
done

for f in "$ENGINE"/*.cpp; do
    name=$(basename "$f")
    if out=$("$CXX" $CXXFLAGS $INCS -fsyntax-only "$f" 2>&1); then
        printf 'ok      %s\n' "$name"
    else
        printf 'FAIL    %s: %s\n' "$name" "$(printf '%s\n' "$out" | first_error)"
        fail=1
    fi
done

for f in "$REPO"/dm/gfx/nvn/nvn_tex.c "$REPO"/dm/gfx/tex/nvn_deswizzle.c; do
    if out=$("$CC" $CFLAGS $INCS -fsyntax-only "$f" 2>&1); then
        printf 'ok      %s (this repository)\n' "$(basename "$f")"
    else
        printf 'FAIL    %s (this repository): %s\n' "$(basename "$f")" "$(printf '%s\n' "$out" | first_error)"
        fail=1
    fi
done

for f in smoke.c host_stubs.c; do
    if out=$("$CC" $CFLAGS $INCS -fsyntax-only "$(dirname "$0")/$f" 2>&1); then
        printf 'ok      %s (harness)\n' "$f"
    else
        printf 'FAIL    %s (harness): %s\n' "$f" "$(printf '%s\n' "$out" | first_error)"
        fail=1
    fi
done

if [ "$fail" = 0 ]; then
    printf 'summary: every translation unit compiles with %s (xbg_game.cpp included, no workaround)\n' "$CXX"
fi
exit $fail
