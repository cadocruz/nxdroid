# 核对生产State完整字段清单及上一draw管线memo的失效接线；补足ABI padding内新增字段无法靠sizeof发现的情况。
# Check the full production State inventory and the previous-draw pipeline memo's invalidation wiring, including new fields
# hidden inside ABI padding.
# memo键按指针记着色器、布局定义和pass定义（xbg_game.cpp PipeMemoKey）；这些对象只在关闭时释放，且先于释放清掉memo。
# The memo key holds shader, layout-definition and pass-definition pointers (xbg_game.cpp PipeMemoKey); those objects are freed
# only at shutdown, after the clear_* calls that drop the memo.
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
from texture_cache_regression import balanced

root = Path(__file__).resolve().parent.parent
source = (root / 'xbg_game.cpp').read_text(encoding='utf-8')
start = source.index('struct State {')
body = source[source.index('{', start) + 1:source.index('\n} state;', start)]
body = re.sub(r'//[^\n]*', '', body)   # the field comments name other fields and functions; only the declarations count
while '{' in body:
    next_body = re.sub(r'\{[^{}]*\}', '', body)
    assert next_body != body, 'Cannot parse State initializer; audit the inventory checker'
    body = next_body
body = re.sub(r'\[[^]]*\]|=[^,;]+', '', body)
names = [re.findall(r'[A-Za-z_]\w*', part)[-1]
         for declaration in body.split(';') if declaration.strip()
         for part in declaration.split(',')]
expected = ['rt', 'shader', 'ub', 'sb', 'vb', 'tex', 'samp', 'img', 'texture_pool', 'sampler_pool',
            'attrib', 'stream', 'blend', 'color', 'mask', 'ms', 'poly', 'ds',
            'depth_clamp', 'rast_discard', 'restart_on', 'restart_index', 'vp_sw',   # pipeline state (PipeMemoKey restart)
            'viewport', 'depth_range', 'scissor',
            'blend_color', 'bias', 'stencil_compare', 'stencil_write', 'stencil_ref', 'copy_stride',
            'copy_image_stride', 'patch_size',
            'viewport_n',                                                            # pipeline input through draw_viewports() (PipeMemoKey viewports)
            'bounds', 'count_samples', 'samples_passed',
            'render_cond_skip', 'tf_on', 'tf']                                       # replay state, no pipeline input
assert names == expected, ('New or reordered State fields require explicit pipeline/dynamic/resource policy', names)
key = balanced(source, source.index('struct PipeMemoKey{'))
for part in ['offsetof(State,viewport)-offsetof(State,attrib)', 'offsetof(State,viewport)-offsetof(State,depth_clamp)',
             'offsetof(State,copy_stride)-offsetof(State,blend_color)', 'offsetof(State,count_samples)-offsetof(State,patch_size)',
             'uint32_t viewports;', 'uint32_t origin;']:
    assert part in key, part
# The viewport count the pipeline declares comes from draw_viewports() and goes into the memo key with the other pipeline inputs.
assert 'k.viewports=viewports;' in source and 'vp.viewportCount=vp.scissorCount=vpn;' in source
# The one-line style hides a whole statement sequence behind a // comment appended mid-line (a frontFace edit once swallowed rs.lineWidth,
# depthBiasEnable and depthBiasConstantFactor): every rasterization assignment the draw's pipeline needs is in code, not in a comment, and no
# line comment in the file is followed by what reads as code (a `;` and then a `name.field=` or `name=`).
def split_comments(text):
    """Return (code, comments): the same length as text, newlines kept; `//` and `/* */` comment characters are blanked
    in code and kept in comments (everything else is blanked there). String and character literals stay code, so a
    `//` inside "..." is not a comment."""
    code, comments = list(text), [' ' if c != '\n' else '\n' for c in text]
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in '"\'':
            j = i + 1
            while j < n and text[j] != c and text[j] != '\n':
                j += 2 if text[j] == '\\' else 1
            i = j + 1
        elif text.startswith('//', i) or text.startswith('/*', i):
            j = text.find('\n', i) if text[i + 1] == '/' else text.find('*/', i + 2) + 2
            if j < i + 2:   # no newline / no `*/` until the end
                j = n
            for k in range(i, j):
                if text[k] != '\n':
                    comments[k], code[k] = text[k], ' '
            i = j
        else:
            i += 1
    return ''.join(code), ''.join(comments)
code, comments = split_comments(source)
draw_code = code[code.index('VkPipelineVertexInputStateCreateInfo vi{'):code.index('PipelineLease pipeline;')]
for assignment in ['rs.depthClampEnable=', 'rs.rasterizerDiscardEnable=', 'rs.polygonMode=', 'rs.cullMode=', 'rs.frontFace=', 'rs.lineWidth=1;',
                   'rs.depthBiasEnable=', 'rs.depthBiasConstantFactor=', 'rs.depthBiasSlopeFactor=', 'rs.depthBiasClamp=',
                   'ia.topology=', 'ia.primitiveRestartEnable=', 'vp.viewportCount=vp.scissorCount=vpn;', 'ms.rasterizationSamples=',
                   'ds.depthTestEnable=', 'blend.attachmentCount=']:
    assert assignment in draw_code, ('rasterization / pipeline assignment missing from the draw code (swallowed by a comment?)', assignment)
# What reads as a statement inside a comment:
# - after a `;`: `name(`, `name.field`, `name->`, `name=`, `name[i]=`, `name++` / `name+=`, behind up to three type or qualifier words
#   (`const bool restart=`, `static const uint32_t x=`), a prefix `++name` / `--name`, or `return` / `break` / `continue` and what ends it;
# - a single trailing statement with no `;` before it: a call closed by `;` (`// bounds need(a,"...");`).
STATEMENT = re.compile(r';\s*(?:(?:[A-Za-z_][\w:<>*&]*\s+){0,3}[A-Za-z_][\w:]*\s*(?:\[[^\]]*\]\s*)*(?:\(|\.[A-Za-z_]|->|=(?!=)|\+\+|--|[-+*/%&|^]=)'
                       r'|(?:\+\+|--)\s*[A-Za-z_]|(?:return|break|continue)\s*(?:;|[A-Za-z_(-]))'
                       r'|[A-Za-z_][\w:.>-]*\((?:[^();]|\([^();]*\))*\)\s*;')   # `name(` with no space, arguments nesting one level
swallowed = [(n, comment.strip()) for n, (line, comment) in enumerate(zip(code.split('\n'), comments.split('\n')), 1)
             if line.strip() and comment.strip() and STATEMENT.search(comment)]   # a comment on a line that also holds code, not a comment line
assert not swallowed, ('a comment is followed by what reads as code', swallowed)
# Window origins: captured per submission when the host hands it over (xbg_submit -> sub_origin), so a later host call never reaches a submission
# already handed over; the draw reads no origin atomic. The queue's raster origin decides rs.frontFace and is in the memo key; the device origin
# flips every viewport the draw sets, after the viewport is built and before it is bounds-checked and set.
submit = balanced(code, code.index('extern "C" void xbg_submit(int n,const uint64_t *handles){'))
assert code.count('origin_ll.load(') == 2 and submit.count('origin_ll.load(') == 2, 'the origin atomics are read only where xbg_submit captures them'
assert 'const SubmitOrigin origin{origin_ll.load()!=0,queue_origin_ll.load()!=0};' in submit
assert submit.count('xbg_submit_now(n,handles,origin);') == 1 and submit.count('xbg_submit_now(int(list.size()),list.data(),origin);') == 1
assert 'static void xbg_submit_now(int n,const uint64_t *handles,SubmitOrigin origin){std::lock_guard<std::recursive_mutex> lock(mutex);sub_origin=origin;' in code
assert code.count('sub_origin=') == 1, 'sub_origin is written only by xbg_submit_now'
assert 'k.origin=uint32_t(sub_origin.queue_ll);' in code
assert 'rs.frontFace=((state.poly.front!=0)!=sub_origin.queue_ll)?VK_FRONT_FACE_COUNTER_CLOCKWISE:VK_FRONT_FACE_CLOCKWISE;' in draw_code
viewport_loop = balanced(code, code.index('for(uint32_t i=0;i<vpn;i++){VkViewport &viewport=viewports[i];'))
FLIP = 'if(sub_origin.device_ll){viewport.y+=viewport.height;viewport.height=-viewport.height;}'
assert viewport_loop.count(FLIP) == 1, ('lower-left window origin: every viewport is flipped about its centre', FLIP)
assert viewport_loop.index('xbg_nvn_viewport(&viewport,') < viewport_loop.index(FLIP) < viewport_loop.index('need(viewport.width<='), \
    'the origin flip comes after the viewport is built and before its bounds check'
assert code.index(viewport_loop) + len(viewport_loop) < code.index('vkCmdSetViewport(c.command,0,vpn,viewports);'), 'the flipped viewports are the ones set'
# The multi-viewport gates: a draw that declares more than one viewport needs multiViewport and at most maxViewports, and a ViewportIndex written
# by a vertex or tessellation stage needs shaderOutputViewportIndex enabled; both before the pipeline declares the count.
for gate in ['need(vpn==1 || (cfg.enabled_core.multiViewport && vpn<=properties.limits.maxViewports),"Multi-viewport draw needs the multiViewport feature");',
             'need(vpn==1 || s==state.shader[3] || viewport_index_enabled,"ViewportIndex from a vertex or tessellation stage needs shaderOutputViewportIndex '
             'enabled at device creation (xbg_game_set_viewport_features)");']:
    assert code.count(gate) == 1 and gate in draw_code, ('multi-viewport gate', gate[:60])
    assert draw_code.index('const uint32_t vpn=draw_viewports();') < draw_code.index(gate) < draw_code.index('vp.viewportCount=vp.scissorCount=vpn;'), \
        ('multi-viewport gate before the pipeline declares the count', gate[:60])
# OP_RENDER_COND (nvn_mtl.m rc_value): a pending timestamp report at exactly a counter field's address makes that field known 0; any other pending
# report or writeback over it keeps it unknown (drawn); only then is the field read from memory. Reverting to "any pending report is unknown" or to
# a direct read fails here.
render_cond = code[code.index('case OP_RENDER_COND:'):code.index('case OP_FENCE_SYNC:')]
for part in ['for(auto &w:pending_writebacks)if(xbg_wb_overlaps(f,8,w.addr,w.bytes))return false;',
             'for(size_t i=pending_reports.size();i--;){const PendingReport &r=pending_reports[i];if(!xbg_wb_overlaps(f,8,r.addr,sizeof(NVNcounterData)))continue;',
             'if(r.addr==f && xbg_counter_is_timestamp(r.type)){v=0;return true;}', 'return false;}',
             'v=*reinterpret_cast<const volatile uint64_t*>(f);return true;};',
             'const bool known=field(a.addr,x) && field(a.addr+16,y);', 'state.render_cond_skip=known && (a.mode?x==y:x!=y);']:
    assert part in render_cond, ('render-condition pending check', part)
assert render_cond.index('pending_writebacks') < render_cond.index('pending_reports') < render_cond.index('volatile uint64_t*>(f)')
assert 'return type==NVN_COUNTER_TYPE_TIMESTAMP || type==NVN_COUNTER_TYPE_TIMESTAMP_TOP;' in code
# ReportCounter accepts TIMESTAMP_TOP (top of the pipe) and does not stop on a pipeline statistic, as nvn_mtl.m does
report = code[code.index('case OP_REPORT_COUNTER:'):code.index('case OP_CLEAR_BUF:')]
assert 'Unsupported pipeline statistics query' not in code and 'Unsupported pipeline counter reset' not in code
assert 'type==NVN_COUNTER_TYPE_TIMESTAMP_TOP?VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT:VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT' in report
assert report.count('vkCmdWriteTimestamp(') == 2 and report.count(',stage,r.ts,r.ts_index)') == 2
# Each timestamp write has its query slot allocated just before it, in the in-pass fast path and in the pass-ending path.
report_case = balanced(code, code.index('case OP_REPORT_COUNTER:'))
fast_if = 'if(type!=NVN_COUNTER_TYPE_SAMPLES_PASSED && !heavy_timestamps && !ab_off("timestamps")){'
assert report_case.count(fast_if) == 1, ('only non-samples reports take the in-pass fast path', fast_if)   # a samples report must end the pass
fast = balanced(report_case, report_case.index(fast_if))
slow = report_case[report_case.index(fast_if) + len(fast):]
assert slow.lstrip().startswith('else{Commands c;'), 'the samples report path ends the pass (Commands) and so closes the occlusion run'
for branch, write in ((fast, 'vkCmdWriteTimestamp(ts.cmd,stage,r.ts,r.ts_index);'), (slow, 'vkCmdWriteTimestamp(c.command,stage,r.ts,r.ts_index);')):
    assert branch.count('timestamp_query(r.ts,r.ts_index,r.slot);') == 1 and branch.count(write) == 1, ('timestamp query slot and write', write)
    assert branch.index('timestamp_query(r.ts,r.ts_index,r.slot);') < branch.index(write), ('timestamp_query before the write', write)
assert report_case.index('pending_reports.push_back(r);') > report_case.index(fast_if)
# No fatal on the counter type: the only checks in ReportCounter are the record's, and ResetCounter has none.
reset_case = balanced(code, code.index('case OP_RESET_COUNTER:'))
def calls(text, name):
    found, at = [], text.find(name + '(')
    while at >= 0:
        depth, end = 0, at + len(name)
        while True:
            depth += (text[end] == '(') - (text[end] == ')')
            end += 1
            if not depth:
                break
        found.append(text[at:end])
        at = text.find(name + '(', end)
    return found
for case, allowed in ((report_case, ['need(n>=16,"Truncated counter report")', 'need(addr,"Null counter output")',
                                     'need(timestamp_bits,"Queue family does not support GPU timestamps")']), (reset_case, [])):
    assert calls(case, 'need') == allowed, ('counter type must not be fatal', calls(case, 'need'))
    for fatal in ('xbg_fatalf(', 'abort(', 'throw ', 'check('):
        assert fatal not in case, ('counter type must not be fatal', fatal)
# ResetCounter: anything but samples passed leaves before the samples reset (no epoch bump, no end of the occlusion query).
reset_if = 'if(type!=NVN_COUNTER_TYPE_SAMPLES_PASSED){'
assert reset_case.count(reset_if) == 1 and reset_case.index('if(') == reset_case.index(reset_if), 'the type test is the first branch of ResetCounter'
other = balanced(reset_case, reset_case.index(reset_if))
assert other.endswith('break;}') and 'counter_epoch' not in other and 'occlusion' not in other and 'samples_passed=' not in other
rest = reset_case[reset_case.index(reset_if) + len(other):]
assert rest.lstrip().startswith('state.samples_passed=0;end_occlusion_query();++counter_epoch;state.count_samples=true;')
assert reset_case.count('++counter_epoch') == 1 and reset_case.count('end_occlusion_query(') == 1
# write_report: a timestamp report's counter field is 0 (the premise of OP_RENDER_COND's known 0); only samples passed carries a count.
write = balanced(code, code.index('void write_report('))
TS_ZERO = 'write_report: a timestamp report must write 0 in the counter field (OP_RENDER_COND counts it as a known 0)'
assert calls(write, 'memcpy') == ['memcpy(reinterpret_cast<void*>(r.addr),&result,sizeof(result))'], TS_ZERO
assert write.count('result.counter') == 1 and 'result.counter=r.type==NVN_COUNTER_TYPE_SAMPLES_PASSED?samples:0;' in write, TS_ZERO
assert write.count('NVNcounterData result{};') == 1 and 'result=' not in write.replace('result.counter=', '').replace('result.timestamp=', ''), TS_ZERO
# The render-enable state: modes 2 / 3 set it unconditionally, a submission starts enabled, and the four draws and clears nvn_mtl.m guards are skipped.
squeezed = re.sub(r'\s+', ' ', render_cond)
assert squeezed.startswith('case OP_RENDER_COND:{auto a=payload<p_render_cond>(p,n); if(a.mode>=2)state.render_cond_skip=(a.mode==3); else if(a.addr){'), \
    'render enable: modes 2 / 3 decide unconditionally (3 = disabled), modes 0 / 1 compare the counters'
assert '}else state.render_cond_skip=false;' in render_cond and render_cond.count('state.render_cond_skip=') == 3
execute = balanced(code, code.index('void execute(const uint8_t *pc,unsigned depth,uint64_t &budget){'))
boundary = 'if(!depth)state.render_cond_skip=false;'
assert execute.count(boundary) == 1 and execute.index(boundary) < execute.index('for(;;)'), 'a submission (depth 0) starts with rendering enabled'
for op in ('OP_CLEAR_COLOR', 'OP_CLEAR_DS', 'OP_DRAW', 'OP_DRAW_IDX'):
    assert execute.count('case %s:{if(state.render_cond_skip)break;' % op) == 1, ('render_cond_skip guard', op)
assert execute.count('if(state.render_cond_skip)break;') == 4 and code.count('render_cond_skip') == 9, 'a render_cond_skip use was added or removed: audit the guards'
# Primitive restart: the index as the stream's width sees it (8-bit: `& 0xff`, widened to 0xffff; 16-bit: `& all_ones`), mapped onto Vulkan's all-ones
for part in ['const uint32_t rv=state.restart_index&0xffu;', 'expanded[i]=restart && src[i]==rv?0xffffu:src[i];',
             'if(restart && (state.restart_index&all_ones)!=all_ones && indexed!=&quad_indexed)',
             'const uint16_t rv=uint16_t(state.restart_index);', 'if(w[i]==state.restart_index)w[i]=0xffffffffu;',
             'ia.primitiveRestartEnable=state.restart_on!=0 && restart_topology;']:
    assert part in code, ('primitive restart mask', part)
for signature, first_destroy in [('void clear_pipeline_objects(){', None),
                                  ('void clear_descriptor_caches(){', 'vkDestroyDescriptorUpdateTemplate'),
                                  ('void clear_render_pass_cache(){', None)]:
    block = balanced(source, source.index(signature))
    assert 'pipe_memo_valid=false' in block, signature
    if first_destroy:
        assert block.index('pipe_memo_valid=false') < block.index(first_destroy), signature
lookup = balanced(source, source.index('void pipeline_lookup('))
assert lookup.index('pipe_memo_valid=false') < lookup.index('pipeline_objects.erase(oldest)')
shutdown = balanced(source, source.index('extern "C" int xbg_game_shutdown(){'))
for call in ['clear_pipeline_objects()', 'clear_descriptor_caches()', 'clear_render_pass_cache()']:
    assert shutdown.index(call) < shutdown.index('shaders.clear()'), call
assert 'shaders.erase' not in source and source.count('shaders.clear()') == 1
assert 'render_pass_cache.erase' not in source and 'layout_cache.erase' not in source
assert '!ab_off("pipememo")' in source and '"/gfx-pipe-memo"' in source and 'pipe_memo_valid=false;if(m)' in source
print('PASS: %d actual State fields, memo key slices, clear/evict/shutdown invalidation, opt-in/A-B source wiring, no code in comments, '
      'per-submission window origins and the viewport flip, multi-viewport gates, render-condition pending check and guards, counter types, '
      'report paths and zero counter, and restart mask; not a native or GPU test' % len(expected))
