"""The rewriter's thread slot sequences (patch_nso.py emit_thread_base, --target=apple|android), run on a small AArch64 interpreter, without capstone or game files.

Each of the 13 stubs that reach a thread slot (site_plain, site_sp, site_cond, site_pcrel, site_br, site_br_tab, site_blr, site_br_call, site_sysreg_read,
site_tpidr_write, emit_gate_call through site_gate, site_window, site_retry_window) is executed from its first word, on hand-made instructions (capstone's
decoding and the x18 substitution are given, not computed): the interpreter decodes the words from the
architecture's encodings (not through nso_asm), models the two thread registers the way each platform has them (Darwin: TPIDRRO_EL0 is the pthread TSD array;
a Linux task: TPIDRRO_EL0 reads 0 and bionic's thread control block is at TPIDR_EL0, whose word 2 is TLS_SLOT_APP) and refuses the register the target must not
read. A stub passes when it reaches the slot the host wrote (port.h dm_kslot_*), leaves every borrowed register as it found it and jumps where the original did.
A structural check over patch_nso.py's source pins what the runs cannot see: every function that adds a slot offset first takes the thread base with
emit_thread_base on that same register, no other function spells a thread-register read, and an Android fixups.tsv says KSLOT_TP_OFF = port.h's DM_KSLOT_TP_OFF."""
from types import SimpleNamespace
import ast
from pathlib import Path
import re
import struct
import sys
import unittest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import nso_asm

# patch_nso.py is a command-line program whose top level loads and rewrites an image: compile only the emitters and the stubs that reach a thread slot
text = (TOOLS / 'patch_nso.py').read_text(encoding='utf-8')
tree = ast.parse(text)
SITES = {'site_plain', 'site_sp', 'site_cond', 'site_pcrel', 'site_br', 'site_br_tab', 'site_blr', 'site_br_call', 'site_sysreg_read', 'site_tpidr_write', 'emit_gate_call',
         'site_window', 'site_retry_window'}
FUNCS = SITES | {'here', 'emit', 'emit_key_addr', 'emit_slot_addr', 'emit_thread_base', 'pick', 'sp_delta', 'has18', 'site_gate'}
CONSTS = {'KEY_INDEX', 'TLS_SLOT_APP'}
body = [n for n in tree.body if (isinstance(n, ast.FunctionDef) and n.name in FUNCS)
        or (isinstance(n, ast.Assign) and any(getattr(t, 'id', None) in CONSTS for t in n.targets))]
assert {n.name for n in body if isinstance(n, ast.FunctionDef)} == FUNCS, 'patch_nso.py lost an emitter this test runs'

KEY_PAGE_OFF, PATCH_OFF = 0x100000, 0x110000
SP, TSD, TP, TABLE = 0x7000_0000, 0x5000_0000, 0x6000_0000, 0x6800_0000
KEYS = {'apple': {'K18': 0x10b, 'KTLS': 0x10c, 'KTLR': 0x10d, 'KGATE': 0x10e},   # pthread key numbers, as Darwin hands them out
        'android': {'K18': 1, 'KTLS': 2, 'KTLR': 3, 'KGATE': 4}}                   # dm_kslot_new's table indices (word 0 is the tag)
SLOT = {'K18': 0x1111_0000, 'KTLS': 0x2222_0000, 'KTLR': 0x3333_0000, 'KGATE': 0x4444_0000}


def sx(v, bits): return v - (1 << bits) if v & (1 << (bits - 1)) else v


class Ins:   # what the stubs read of a capstone instruction
    def __init__(self, word, address, op_str='', mnemonic='', target=None):
        self.bytes, self.address, self.op_str, self.mnemonic = struct.pack('<I', word), address, op_str, mnemonic
        self.operands = [SimpleNamespace(imm=0), SimpleNamespace(imm=target)] if target is not None else []


def dis(w, pc):   # capstone's answer for the branches the window and condition stubs re-aim: cbz / cbnz and b.ne
    if w & 0x7E000000 == 0x34000000: return SimpleNamespace(mnemonic='cbnz' if w >> 24 & 1 else 'cbz', operands=[SimpleNamespace(imm=pc + sx(w >> 5 & 0x7FFFF, 19) * 4)])
    if w & 0xFF00001F == 0x54000001: return SimpleNamespace(mnemonic='b.ne', operands=[SimpleNamespace(imm=pc + sx(w >> 5 & 0x7FFFF, 19) * 4)])
    raise AssertionError(f'{w:#010x}: not a branch this test decodes')


class Machine:
    """x0..x30, sp, a word memory, and the two thread registers of one platform; run() executes from pc until control leaves the stub."""
    def __init__(self, target):
        self.target, self.x, self.sp, self.mem, self.z = target, {r: 0x1000 + r for r in range(31)}, SP, {}, False
        keys = KEYS[target]
        for kind, i in rewriter(target)['KEY_INDEX'].items(): self.mem[KEY_PAGE_OFF + 8 * i] = keys[kind] * 8   # loader.c install_key_page
        base = TSD if target == 'apple' else TABLE
        if target == 'android': self.mem[TP + 16] = TABLE; self.mem[TABLE] = 0x31746f6c736b6d64   # TLS_SLOT_APP -> the table, its tag
        for kind, v in SLOT.items(): self.mem[base + 8 * keys[kind]] = v
        self.base = base

    def slot(self, kind): return self.mem.get(self.base + 8 * KEYS[self.target][kind])
    def reg(self, r, sp_ok): return (self.sp if sp_ok else 0) if r == 31 else self.x[r]
    def set(self, r, v, sp_ok=False):
        if r == 31:
            if sp_ok: self.sp = v & (2 ** 64 - 1)
            return
        self.x[r] = v & (2 ** 64 - 1)
    def load(self, a):
        assert a % 8 == 0 and a in self.mem or SP - 64 <= a < SP, f'load from {a:#x}, which nothing wrote'
        return self.mem.get(a, 0)
    def store(self, a, v):
        assert a % 8 == 0 and (SP - 128 <= a < SP or a in self.mem and a != KEY_PAGE_OFF), f'store to {a:#x}'
        self.mem[a] = v & (2 ** 64 - 1)

    def run(self, code, pc, limit=200):
        for _ in range(limit):
            w = struct.unpack_from('<I', code, pc - PATCH_OFF)[0]
            rt, rn = w & 31, (w >> 5) & 31
            if w & ~31 == 0xD53BD040:   # mrs xt, tpidr_el0
                assert self.target == 'android', 'the Apple stub read TPIDR_EL0: on Darwin that is not the TSD array'
                self.set(rt, TP)
            elif w & ~31 == 0xD53BD060:   # mrs xt, tpidrro_el0
                assert self.target == 'apple', 'the Android stub read TPIDRRO_EL0, which a Linux task reads as 0'
                self.set(rt, TSD)
            elif w & 0xFFC00000 == 0xF9400000: self.set(rt, self.load(self.reg(rn, True) + 8 * ((w >> 10) & 0xFFF)))   # ldr xt, [xn, #imm]
            elif w & 0xFFC00000 == 0xF9000000: self.store(self.reg(rn, True) + 8 * ((w >> 10) & 0xFFF), self.reg(rt, False))   # str xt, [xn, #imm]
            elif w & 0xFFE00C00 == 0xF8400000: self.set(rt, self.load(self.reg(rn, True) + sx((w >> 12) & 0x1FF, 9)))   # ldur
            elif w & 0xFFE00C00 == 0xF8000000: self.store(self.reg(rn, True) + sx((w >> 12) & 0x1FF, 9), self.reg(rt, False))   # stur
            elif w & 0xFF200000 == 0x8B000000:   # add xd, xn, xm (no shift)
                assert (w >> 10) & 63 == 0 and (w >> 22) & 3 == 0
                self.set(rt, self.reg(rn, False) + self.reg((w >> 16) & 31, False))
            elif w & 0xFF800000 == 0x91000000: self.set(rt, self.reg(rn, True) + (((w >> 10) & 0xFFF) << (12 * ((w >> 22) & 1))), True)   # add xd|sp, xn|sp, #imm
            elif w & 0xFF800000 == 0xD1000000: self.set(rt, self.reg(rn, True) - (((w >> 10) & 0xFFF) << (12 * ((w >> 22) & 1))), True)   # sub
            elif w & 0x9F000000 == 0x90000000:   # adrp
                imm = sx((((w >> 5) & 0x7FFFF) << 2) | ((w >> 29) & 3), 21) << 12
                self.set(rt, (pc & ~0xFFF) + imm)
            elif w & 0xFFC00000 in (0xA9000000, 0xA9400000, 0xA9800000, 0xA8C00000):   # stp / ldp (offset), stp pre-index, ldp post-index
                op, off, rt2 = w & 0xFFC00000, sx((w >> 15) & 0x7F, 7) * 8, (w >> 10) & 31
                a = self.reg(rn, True) + (0 if op == 0xA8C00000 else off)
                if op in (0xA9000000, 0xA9800000): self.store(a, self.reg(rt, False)); self.store(a + 8, self.reg(rt2, False))
                else: v1, v2 = self.load(a), self.load(a + 8); self.set(rt, v1); self.set(rt2, v2)
                if op == 0xA9800000: self.set(rn, a, True)
                if op == 0xA8C00000: self.set(rn, a + off, True)
            elif w & 0xFC000000 == 0x14000000:   # b
                to = pc + sx(w & 0x3FFFFFF, 26) * 4
                if not PATCH_OFF <= to < PATCH_OFF + len(code): return ('b', to)
                pc = to; continue
            elif w & 0xFFFFFC1F == 0xD61F0000:   # br: into the stub's own landing pads (site_br), or out
                if not PATCH_OFF <= self.x[rn] < PATCH_OFF + len(code): return ('br', self.x[rn])
                pc = self.x[rn]; continue
            elif w & 0xFFFFFC1F == 0xD63F0000: return ('blr', self.x[rn])
            elif w & 0xFF20FC1F == 0xEB00001F: self.z = self.reg(rn, False) == self.reg((w >> 16) & 31, False)   # cmp xn, xm
            elif w & 0x7E000000 == 0x34000000 or w & 0xFF00001E == 0x54000000:   # cbz / cbnz xt; b.eq / b.ne
                if w & 0x7E000000 == 0x34000000: taken = (self.reg(rt, False) == 0) != bool(w >> 24 & 1)
                else: taken = self.z != bool(w & 1)
                if taken:
                    to = pc + sx(w >> 5 & 0x7FFFF, 19) * 4
                    if not PATCH_OFF <= to < PATCH_OFF + len(code): return ('b', to)
                    pc = to; continue
            elif w & 0xFFE0001F == 0xD4200000: raise AssertionError('brk: no jump-table target matched')
            elif w == 0xD503201F: pass
            else: raise AssertionError(f'{w:#010x} at {pc:#x}: not an instruction this interpreter knows')
            pc += 4
        raise AssertionError('the stub did not leave')


def rewriter(target):
    scope = dict(vars(nso_asm), re=re, struct=struct, TARGET=target, KEY_PAGE_OFF=KEY_PAGE_OFF, PATCH_OFF=PATCH_OFF, patch=bytearray(), fix=[], gates=[], dis=dis)
    exec(compile(ast.Module(body=body, type_ignores=[]), str(TOOLS / 'patch_nso.py'), 'exec'), scope)
    return scope


class ThreadSlots(unittest.TestCase):
    def stub(self, target, name, *args, **stubs):
        r = rewriter(target); r.update(stubs)
        start = r[name](*args)
        start = start[0] if isinstance(start, tuple) else start
        return r, bytes(r['patch']), start

    def test_sysreg_read_reaches_the_slot(self):   # mrs xN, tpidr_el0 / tpidrro_el0
        for target in ('apple', 'android'):
            for kind, word in (('KTLS', 0xD53BD040), ('KTLR', 0xD53BD060)):
                for n in (0, 16, 17, 30):
                    _, code, start = self.stub(target, 'site_sysreg_read', Ins(word | n, 0x4000), kind)
                    m = Machine(target); before = dict(m.x)
                    self.assertEqual(m.run(code, start), ('b', 0x4004))
                    self.assertEqual(m.x[n], SLOT[kind], (kind, n))
                    self.assertEqual({r: v for r, v in m.x.items() if r != n}, {r: v for r, v in before.items() if r != n})
                    self.assertEqual(m.sp, SP)

    def test_tpidr_write_reaches_the_slot(self):   # msr tpidr_el0, xN
        for target in ('apple', 'android'):
            for n in (0, 16, 17, 30):
                _, code, start = self.stub(target, 'site_tpidr_write', Ins(0xD51BD040 | n, 0x4000))
                m = Machine(target); before = dict(m.x)
                self.assertEqual(m.run(code, start), ('b', 0x4004))
                self.assertEqual(m.slot('KTLS'), before[n])
                self.assertEqual(m.x, before)

    def test_x18_read_modify_write(self):   # add x18, x18, #1 through site_plain (the instruction itself is given: subst needs capstone)
        for target in ('apple', 'android'):
            r, code, start = self.stub(target, 'site_plain', Ins(0x91000652, 0x4000, 'x18, x18, #1'),
                                       regs_in=lambda ins: {18}, subst=lambda ins, S: nso_asm.ADDI(S, S, 1))
            m = Machine(target); before = dict(m.x)
            self.assertEqual(m.run(code, start), ('b', 0x4004))
            self.assertEqual(m.slot('K18'), SLOT['K18'] + 1)
            self.assertEqual(m.x, before)
            self.assertEqual(m.sp, SP)

    def test_x18_tail_call_and_call(self):   # br x18 as a tail call, blr x18
        for target in ('apple', 'android'):
            _, code, start = self.stub(target, 'site_br_call', Ins(0xD61F0240, 0x4000))
            m = Machine(target)
            self.assertEqual(m.run(code, start), ('br', SLOT['K18']))
            _, code, start = self.stub(target, 'site_blr', Ins(0xD63F0240, 0x4000))
            m = Machine(target)
            self.assertEqual(m.run(code, start), ('br', SLOT['K18']))
            self.assertEqual(m.x[30], 0x4004)

    def test_jump_table_fits_and_lands(self):   # br x18 over equally spaced targets: the prologue, at most 12 adds and the br fit in 24 words on both targets
        for target in ('apple', 'android'):
            base, count = 0x2000, 4
            for i in range(count):
                _, code, start = self.stub(target, 'site_br', Ins(0xD61F0240, 0x4000), base, count)
                m = Machine(target); m.mem[m.base + 8 * KEYS[target]['K18']] = base + 4 * i; before = dict(m.x)
                self.assertEqual(m.run(code, start), ('b', base + 4 * i))
                self.assertEqual(m.x, before)

    def test_x18_as_the_source_of_sp(self):   # mov sp, x18 (site_sp): sp takes the slot, the scratch registers come back from the old stack
        for target in ('apple', 'android'):
            _, code, start = self.stub(target, 'site_sp', Ins(0x9100025F, 0x4000, 'sp, x18'), regs_in=lambda ins: {18}, subst=lambda ins, S: nso_asm.ADDI(31, S, 0))
            m = Machine(target); before = dict(m.x)
            self.assertEqual(m.run(code, start), ('b', 0x4004))
            self.assertEqual(m.sp, SLOT['K18'])
            self.assertEqual(m.x, before)

    def test_x18_condition(self):   # cbnz x18, 0x4800 (site_cond), taken and not taken
        for target in ('apple', 'android'):
            for k18, want in ((SLOT['K18'], 0x4800), (0, 0x4004)):
                _, code, start = self.stub(target, 'site_cond', Ins(0xB5004012, 0x4000, 'x18, #0x4800', 'cbnz', 0x4800), regs_in=lambda ins: {18})
                m = Machine(target); m.mem[m.base + 8 * KEYS[target]['K18']] = k18; before = dict(m.x)
                self.assertEqual(m.run(code, start), ('b', want))
                self.assertEqual(m.x, before)
                self.assertEqual(m.sp, SP)

    def test_x18_as_a_pc_relative_destination(self):   # adrp x18, page / adr x18, address (site_pcrel): the slot takes the address
        for target in ('apple', 'android'):
            for mnem, tgt, want in (('adrp', 0x2345000, 0x2345000), ('adr', 0x2345678, 0x2345678)):
                _, code, start = self.stub(target, 'site_pcrel', Ins(0x90000012, 0x4000, 'x18, #%#x' % tgt, mnem, tgt))
                m = Machine(target); before = dict(m.x)
                self.assertEqual(m.run(code, start), ('b', 0x4004))
                self.assertEqual(m.slot('K18'), want)
                self.assertEqual(m.x, before)

    def test_offset_table_jump(self):   # br x18 after ldrsw / add (site_br_tab): x18 is compared with each constant target
        for target in ('apple', 'android'):
            targets = [0x3000, 0x3040, 0x3100]
            for t in targets:
                _, code, start = self.stub(target, 'site_br_tab', Ins(0xD61F0240, 0x4000), targets)
                m = Machine(target); m.mem[m.base + 8 * KEYS[target]['K18']] = t; before = dict(m.x)
                self.assertEqual(m.run(code, start), ('b', t))
                self.assertEqual(m.x, before)

    def window(self):   # add x18, x18, #1; add x0, x0, #2; cbnz x0, 0x5000 (out of the window): x18's stand-in loaded once, stored back at every exit
        return [Ins(0x91000652, 0x4000, 'x18, x18, #1', 'add'), Ins(0x91000800, 0x4004, 'x0, x0, #2', 'add'), Ins(0xB5007FC0, 0x4008, 'x0, #0x5000', 'cbnz', 0x5000)]

    def test_window(self):
        for target in ('apple', 'android'):
            for x0, want in ((0x40, 0x5000), (-2 & (2 ** 64 - 1), 0x400c)):
                _, code, start = self.stub(target, 'site_window', self.window(), regs_in=lambda ins: {0, 18},
                                           subst=lambda ins, S: nso_asm.ADDI(S, S, 1))
                m = Machine(target); m.x[0] = x0; before = dict(m.x)
                self.assertEqual(m.run(code, start), ('b', want))
                self.assertEqual(m.slot('K18'), SLOT['K18'] + 1)
                self.assertEqual(m.x, {**before, 0: (x0 + 2) & (2 ** 64 - 1)})
                self.assertEqual(m.sp, SP)

    def test_retry_window(self):   # a retry block and the window's tail under one prologue (site_retry_window): the retry block's fall-through leaves first
        for target in ('apple', 'android'):
            seg = self.window()
            _, code, start = self.stub(target, 'site_retry_window', [(seg[:1], 0x6000), (seg[1:], 0x400c)], regs_in=lambda ins: {0, 18},
                                       subst=lambda ins, S: nso_asm.ADDI(S, S, 1))
            m = Machine(target); before = dict(m.x)
            self.assertEqual(m.run(code, start), ('b', 0x6000))
            self.assertEqual(m.slot('K18'), SLOT['K18'] + 1)
            self.assertEqual(m.x, before)

    def test_every_slot_site_takes_its_thread_base(self):
        # each emit_slot_addr(reg, ...) is preceded, in the same function, by emit_thread_base(reg): a site that spelled the thread register itself
        # (emit(0xD53BD060 | T), the Darwin word) would run on Apple and fault on Android, which no run of another site would notice
        funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
        slot_users = set()
        for name, fn in funcs.items():
            calls = [c for c in ast.walk(fn) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)]
            calls.sort(key=lambda c: (c.lineno, c.col_offset))
            base = None
            for c in calls:
                if c.func.id == 'emit_thread_base': base = ast.unparse(c.args[0])
                if c.func.id == 'emit_slot_addr' and name not in ('emit_slot_addr',):
                    slot_users.add(name)
                    self.assertEqual(base, ast.unparse(c.args[0]), f'{name}: emit_slot_addr on {ast.unparse(c.args[0])} without emit_thread_base of it first')
            if name != 'emit_thread_base':
                src = ast.get_source_segment(text, fn) or ''
                self.assertNotRegex(src, r'(?i)0xd53bd0[46]0|MRS_TPIDR', f'{name} spells a thread-register read; only emit_thread_base may')
        self.assertEqual(slot_users, SITES, 'the functions that reach a slot are not the ones this test runs')

    def test_android_fixups_carry_the_table_offset(self):
        # the KSLOT_TP_OFF line an Android fixups.tsv gets, evaluated from patch_nso.py, is what loader.c reads and what port.h's bionic DM_KSLOT_TP_OFF says
        lines = []
        for n in ast.walk(tree):
            if isinstance(n, ast.If) and ast.unparse(n.test) in ("TARGET == 'android'", 'TARGET == "android"'):
                for c in ast.walk(n):
                    if isinstance(c, ast.Call) and ast.unparse(c.func) == 'f.write':
                        lines.append(eval(compile(ast.Expression(c.args[0]), 'patch_nso.py', 'eval'), {'TLS_SLOT_APP': rewriter('android')['TLS_SLOT_APP']}))
        self.assertIn('# KSLOT_TP_OFF\t0x10\n', lines)
        repo = TOOLS.parents[1]
        port = (repo / 'dm/host/port.h').read_text(encoding='utf-8')
        self.assertRegex(port, r'#define DM_KSLOT_TP_OFF 16\b')
        self.assertIn('"KSLOT_TP_OFF"', (repo / 'dm/host/loader.c').read_text(encoding='utf-8'))

    def test_gate_reads_kgate_and_keeps_x29(self):   # svc: the gate address from KGATE, x29 the guest's own at the call (the crash backtrace walks it)
        for target in ('apple', 'android'):
            _, code, start = self.stub(target, 'site_gate', Ins(0xD4000001, 0x4000), 'svc', 0)
            m = Machine(target); fp = m.x[29]
            self.assertEqual(m.run(code, start), ('blr', SLOT['KGATE']))
            self.assertEqual(m.x[29], fp)
            self.assertEqual(m.sp, SP - 16)

    def test_apple_words_are_the_darwin_sequence(self):   # --target=apple writes what the rewriter wrote before the switch existed
        A = nso_asm
        r, code, _ = self.stub('apple', 'site_sysreg_read', Ins(0xD53BD040 | 3, 0x4000), 'KTLS')
        k = r['KEY_INDEX']['KTLS']
        want = [A.STUR(16, 31, -16), A.MRS_TPIDRRO(3), A.ADRP(16, PATCH_OFF + 8, KEY_PAGE_OFF), A.LDRX(16, 16, k), A.ADDR(3, 3, 16), A.LDRX(3, 3), A.LDUR(16, 31, -16),
                A.B(PATCH_OFF + 28, 0x4004)]
        self.assertEqual(list(struct.unpack('<%dI' % (len(code) // 4), code)), want)

    def test_android_words(self):   # mrs tpidr_el0 then ldr [.., #16] (TLS_SLOT_APP), then the key page as on Apple
        A = nso_asm
        r, code, _ = self.stub('android', 'site_sysreg_read', Ins(0xD53BD060 | 3, 0x4000), 'KTLR')
        k = r['KEY_INDEX']['KTLR']
        want = [A.STUR(16, 31, -16), 0xD53BD043, 0xF9400863, A.ADRP(16, PATCH_OFF + 12, KEY_PAGE_OFF), A.LDRX(16, 16, k), A.ADDR(3, 3, 16), A.LDRX(3, 3),
                A.LDUR(16, 31, -16), A.B(PATCH_OFF + 32, 0x4004)]
        self.assertEqual(list(struct.unpack('<%dI' % (len(code) // 4), code)), want)   # 0xd53bd043 = mrs x3, tpidr_el0; 0xf9400863 = ldr x3, [x3, #16]
        self.assertEqual(r['TLS_SLOT_APP'] * 8, 16)

    def test_no_stub_reads_the_other_platforms_register(self):
        text = (TOOLS / 'patch_nso.py').read_text(encoding='utf-8')
        self.assertEqual(re.findall(r'MRS_TPIDRRO\(|MRS_TPIDR\(', text), ['MRS_TPIDRRO(', 'MRS_TPIDR('], 'only emit_thread_base may emit a thread register read')


if __name__ == '__main__':
    unittest.main()
