"""dm/android/tools/undef_scan.py's Mach-O assembly gate: the spellings the ELF assembler or the --no-undefined link refuses in a kept C source's inline assembly, and
the ones it must leave alone (port.h's DM_ASM_* forms and plain ELF), on synthetic lines; and the two lists it reads from dm/android/CMakeLists.txt instead of copying."""
from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / 'dm/android/tools'))
import undef_scan   # noqa: E402

MACHO = [   # each a line of a C source; each must be reported
    r'__asm__(".private_extern _dm_x");',
    r'__asm__(".linker_option \"-lcompression\"");',
    r'__asm__(".weak_definition _dm_x");',
    r'__asm__(".subsections_via_symbols");',
    r'"adrp x16, _dm_top@PAGE\n"',
    r'"ldr x16, [x16, _dm_top@PAGEOFF]\n"',
    r'"adrp x0, _g@GOTPAGE\n"',
    r'"ldr x0, [x0, _g@GOTPAGEOFF]\n"',
    r'"adrp x0, _t@TLVPPAGE\n"',
    r'"add x0, x0, _t@TLVPPAGEOFF\n"',
    r'"\nbl _dm_bigstack_top"',          # the escape's letter before the mnemonic: \b alone missed these
    r'"\n\tbl _dm_bigstack_top"',
    r'"mov x0, x1\n\tb _dm_tail\n"',
    r'"bl _" #name "\n"',                # a stringified symbol
    r'"adrp x16, _dm_top\n"',            # register operand first: the old (adrp|adr) alternative never matched
    r'"adr x1, _dm_top\n"',
    r'"b.eq _dm_out\n"',
    r'"cbz x0, _dm_out\n"',
    r'"cbnz w3, _dm_out\n"',
    r'"tbnz x2, #3, _dm_out\n"',
    r'".globl _dm_entry\n"',
    r'".global _dm_entry\n"',
    r'".quad _dm_table\n"',
    r'".section __TEXT,__text,regular,pure_instructions\n"',
    r'static int e __attribute__((used, section("__DATA,swhle")));',
    r'"bl\t_foo\n"',                     # a \t escape between the mnemonic and its operand
    r'".globl\t_foo\n"',
    r'"bl\t_" #name "\n"',
    r'"bl " "_foo\n"',                    # the operand in the next string literal
    r'"adrp x16, " "_foo@PAGE\n"',
    r'"cbz x0,\t_out\n"',
    r'".xword _t\n"', r'".8byte _t\n"', r'".4byte _t\n"', r'".int _t\n"',
    r'"ldr x0, =_foo\n"',
    r'"ldr x0, _foo\n"',
    r'".set _foo, 1\n"',
    r'".alt_entry _foo\n"', r'".no_dead_strip _foo\n"', r'".weak_reference _foo\n"', r'".zerofill __DATA,__bss,_b,8\n"',
    r'".loh AdrpAdd Lloh0, Lloh1\n"', r'".tbss _t$tlv$init, 8, 3\n"', r'".const_data\n"', r'".cstring\n"',
    r'".section\t__DATA,__const\n"',
]
ELF = [   # the same constructs spelled for ELF, or through port.h's macros: never reported
    r'__asm__(DM_ASM_HIDDEN " " DM_ASM_SYM("dm_x"));',
    r'"adrp x16, " DM_ASM_HI("dm_top") "\n"',
    r'"ldr x16, [x16, " DM_ASM_LO("dm_top") "]\n"',
    r'"\n\tbl dm_bigstack_top"',
    r'"\nbl " DM_ASM_SYM("dm_bigstack_top")',
    r'"adrp x16, dm_top\n\tadd x16, x16, :lo12:dm_top\n"',
    r'"cbz x0, 1f\n\tb.ne 2f\n"',
    r'".hidden dm_x\n\t.globl dm_entry\n\t.quad dm_table\n"',
    r'".section .text.dm,\"ax\",%progbits\n"',
    r'static int e __attribute__((used, section(DM_SECTION_NAME("swhle"))));',
    r'__attribute__((section("swhle"))) static int e;',
    r'int b_x = a_b _c;',                # C, not assembly
    r'x = cbz_x(1, _y);',
    r'printf("%s", tbl _x);',
    r'"bl\tdm_foo\n"',
    r'".globl\tdm_x\n\t.type dm_x, %function\n"',
    r'"bl " "dm_foo\n"',
    r'".xword dm_t\n\t.8byte dm_t\n\t.4byte 0\n\t.int 1\n"',
    r'"ldr x0, =dm_foo\n\tldr x1, [x0, #8]\n"',
    r'".set dm_foo, 1\n"',
    r'".section .rodata.str1.1,\"aMS\",@progbits,1\n"',
    r'int tbss_x = loh_y + cstring_z;',     # identifiers that contain the directive names
    r'x.cstring = 1;',
]


class MachoAsm(unittest.TestCase):
    def scan(self, line):
        return [m.group(0) for m in [undef_scan.MACHO_ASM.search(line)] if m]

    def test_macho_spellings_are_reported(self):
        for line in MACHO:
            with self.subTest(line=line):
                self.assertTrue(self.scan(line), line)

    def test_elf_spellings_are_not(self):
        for line in ELF:
            with self.subTest(line=line):
                self.assertEqual(self.scan(line), [], line)

    def test_comments_are_blanked_strings_kept(self):
        text = 'a = "http://x"; __asm__("\\n\\tbl _dm_top"); // bl _in_comment\n/* .private_extern _x\n */ b = \'/\'; c = "/*"; __asm__("bl _y");\n'
        out = undef_scan.uncomment(text)
        self.assertEqual(out.count('\n'), text.count('\n'))
        self.assertIn('"http://x"', out)
        self.assertNotIn('_in_comment', out)
        self.assertNotIn('private_extern', out)
        self.assertEqual([bool(undef_scan.MACHO_ASM.search(line)) for line in out.split('\n')], [True, False, True, False])

    def test_macho_asm_reads_files_and_exempts_port_h(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'k.c'
            p.write_text('/* "bl _x" in a comment */\n// .private_extern _x\n__asm__("\\n\\tbl _dm_top");\nconst char *u = "http://h/"; __asm__("b _dm_y");\n', encoding='utf-8')
            orig = undef_scan.REPO
            try:
                undef_scan.REPO = Path(d)
                out = undef_scan.macho_asm([p, REPO / 'dm/host/port.h'])
            finally:
                undef_scan.REPO = orig
        self.assertEqual([o.split(':')[1] for o in out], ['3', '4'], out)   # a "//" inside a string does not hide the rest of its line


class CMakeLists(unittest.TestCase):
    def test_lists_are_read_from_the_build(self):
        asm = undef_scan.cmake_list('ASM_IN')
        self.assertEqual([p.name for p in asm], ['entry.S', 'nvn_entry.S', 'nvn_thunks.S'])
        self.assertTrue(all(p.is_file() for p in asm))
        srcs = undef_scan.android_srcs()
        self.assertIn('port_android.c', [p.name for p in srcs])
        self.assertEqual(srcs[-1], REPO / 'dm/host/main.c')


if __name__ == '__main__':
    unittest.main()
