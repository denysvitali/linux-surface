#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise actual Iris1 PM and Linux bulk helpers with offline fault injection."""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import resource
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
PREIMAGE = Path('/var/tmp/spx-video-power-preimage-20261003')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def block(source, marker):
    start = source.index(marker)
    at = source.index('{', start)
    depth, end = 1, at + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    if source[end:end + 1] == ';':
        end += 1
    return source[start:end]


PREAMBLE = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
typedef uint32_t u32;
#define __must_check
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define VIDC_RESETS_NUM_MAX 2
#define POWER_ON 1
#define POWER_OFF 0
#define VIDC_CORE_ID_DEFAULT 0
#define IS_ENABLED(x) (x)
#define IS_ERR(p) ((uintptr_t)(p) > (uintptr_t)-4096)
#define PTR_ERR(p) ((int)(intptr_t)(p))
'''

SCAFFOLD = r'''
struct device { unsigned id; int refs; bool hw; };
struct clk { unsigned id; unsigned prepared, enabled; unsigned long rate; };
struct clk_bulk_data { const char *id; struct clk *clk; };
struct reset_control { unsigned id; bool asserted; };
struct reset_control_bulk_data { const char *id; struct reset_control *rstc; };
struct dev_pm_opp { unsigned dummy; };
struct venus_resources { enum hfi_version hfi_version; enum vpu_version vpu_version;
    unsigned vcodec_clks_num, vcodec_pmdomains_num, resets_num; const char **vcodec_pmdomains; };
struct pd_list { struct device *pd_devs[3]; };
struct venus_core { struct device *dev; const struct venus_resources *res;
    struct clk *clks[3], *vcodec_clks[2], *vcodec0_clks[2], *vcodec1_clks[2];
    struct reset_control *resets[2]; struct pd_list *pmdomains; };
struct venus_inst { bool core_acquired; struct { u32 core_id; } clk_data; };
struct venus_pm_ops { int (*core_get)(struct venus_core *);
    int (*core_power)(struct venus_core *, int);
    int (*coreid_power)(struct venus_inst *, int);
    int (*load_scale)(struct venus_inst *); };
enum op { FIND, PUT_OPP, RATE, CLK_RATE, PD_ON, PD_OFF, HW_ON, HW_OFF,
    RST_ASSERT, RST_DEASSERT, SLEEP, PREPARE, ENABLE, DISABLE, UNPREPARE };
struct event { int op, id; unsigned long value; };
static struct event trace[256];
static unsigned used, warnings, property_calls, cases;
static int fail_op=-1, fail_id=-1, property_error;
static unsigned long vote;
static struct device owner={.id=3}, domains[3];
static struct clk clocks[7];
static struct reset_control resets[2];
static struct dev_pm_opp opp;
static const char *domain_names[]={"venus","vcodec0","vcodec1"};
static struct venus_resources res={.hfi_version=HFI_VERSION_4XX,
    .vpu_version=VPU_VERSION_IRIS1,.vcodec_clks_num=2,
    .vcodec_pmdomains_num=3,.resets_num=2,.vcodec_pmdomains=domain_names};
static struct pd_list pds;
static struct venus_core core={.dev=&owner,.res=&res,.pmdomains=&pds};
static int event(int op,int id,unsigned long value) {
    assert(used<ARRAY_SIZE(trace)); trace[used++]=(struct event){op,id,value};
    return fail_op==op && fail_id==id ? -EIO : 0;
}
static struct dev_pm_opp *dev_pm_opp_find_freq_ceil(struct device *d,unsigned long *f) {
    assert(d==&owner && !*f); if(event(FIND,3,0))return (void *)(intptr_t)-ENOENT;
    *f=200000000; return &opp;
}
static void dev_pm_opp_put(struct dev_pm_opp *o) { assert(o==&opp);event(PUT_OPP,3,0); }
static int dev_pm_opp_set_rate(struct device *d,unsigned long f) {
    assert(d==&owner);int ret=event(RATE,f?1:0,f);
    if(!ret) { vote=f;clocks[4].rate=f; } return ret;
}
static int clk_set_rate(struct clk *c,unsigned long f) {
    if(!c)return 0;
    assert(c->id==5 || c->id==6);int ret=event(CLK_RATE,c->id,f);
    if(!ret)c->rate=f;return ret;
}
static int pm_runtime_resume_and_get(struct device *d) {
    assert(d->id<3 && !d->refs && vote);
    int ret=event(PD_ON,d->id,0);if(!ret)d->refs++;return ret;
}
static int pm_runtime_put_sync(struct device *d) {
    assert(d->refs==1 && !d->hw);
    for(unsigned i=0;i<7;i++)assert(!clocks[i].enabled && !clocks[i].prepared);
    event(PD_OFF,d->id,0);d->refs--;return 0;
}
static int dev_pm_genpd_set_hwmode(struct device *d,bool hw) {
    int ret=event(hw?HW_ON:HW_OFF,d->id,0);
    if(!d->id)return -EOPNOTSUPP;
    if(ret)return ret;
    assert(d->refs==1);d->hw=hw;return 0;
}
static int reset_control_assert(struct reset_control *r) {
    for(unsigned i=0;i<3;i++)assert(domains[i].refs && !domains[i].hw);
    for(unsigned i=0;i<7;i++)assert(!clocks[i].prepared);
    int ret=event(RST_ASSERT,r->id,0);if(!ret)r->asserted=true;return ret;
}
static int reset_control_deassert(struct reset_control *r) {
    int ret=event(RST_DEASSERT,r->id,0);if(!ret)r->asserted=false;return ret;
}
static void usleep_range(unsigned low,unsigned high) {
    assert(low==150 && high==250 && resets[0].asserted && resets[1].asserted);
    event(SLEEP,0,0);
}
static int clk_prepare(struct clk *c) {
    assert(c && !c->prepared && !c->enabled && !resets[0].asserted && !resets[1].asserted);
    for(unsigned i=0;i<3;i++)assert(domains[i].refs && !domains[i].hw);
    int ret=event(PREPARE,c->id,0);if(!ret)c->prepared++;return ret;
}
static void clk_unprepare(struct clk *c) {
    assert(c->prepared==1 && !c->enabled);event(UNPREPARE,c->id,0);c->prepared--;
}
static int clk_enable(struct clk *c) {
    assert(c->prepared==1 && !c->enabled);
    int ret=event(ENABLE,c->id,0);if(!ret)c->enabled++;return ret;
}
static void clk_disable(struct clk *c) {
    assert(c->enabled==1);event(DISABLE,c->id,0);c->enabled--;
}
#define pr_err(...) ((void)0)
#define dev_warn(...) (warnings++)
static int decide_core(struct venus_inst *i) {
    property_calls++;if(property_error)return property_error;i->clk_data.core_id=1;return 0;
}
static int core_get_v4(struct venus_core *c) { (void)c;return 0; }
static int load_scale_v4(struct venus_inst *i) { (void)i;return 0; }
static const struct venus_pm_ops pm_ops_v1={0},pm_ops_v3={0},pm_ops_v4={0};
'''

CHECKS = r'''
static void init(void) {
    memset(domains,0,sizeof(domains));memset(clocks,0,sizeof(clocks));memset(resets,0,sizeof(resets));
    used=warnings=property_calls=0;fail_op=fail_id=-1;vote=0;property_error=0;
    for(unsigned i=0;i<3;i++) {domains[i].id=i;pds.pd_devs[i]=&domains[i];}
    for(unsigned i=0;i<7;i++)clocks[i].id=i;
    resets[0].id=0;resets[1].id=1;core.resets[0]=&resets[0];core.resets[1]=&resets[1];
    core.clks[2]=&clocks[0];core.vcodec0_clks[1]=&clocks[1];core.vcodec1_clks[1]=&clocks[2];
    core.clks[1]=&clocks[3];core.clks[0]=&clocks[4];
    core.vcodec0_clks[0]=&clocks[5];core.vcodec1_clks[0]=&clocks[6];
}
static void clean(void) {
    assert(!vote);for(unsigned i=0;i<3;i++)assert(!domains[i].refs && !domains[i].hw);
    for(unsigned i=0;i<7;i++)assert(!clocks[i].enabled && !clocks[i].prepared);
}
static void expected(unsigned *at,int op,int id,unsigned long value) {
    assert(*at<used);struct event e=trace[(*at)++];assert(e.op==op && e.id==id && e.value==value);
}
static void on_trace(void) {
    unsigned at=0;expected(&at,FIND,3,0);expected(&at,PUT_OPP,3,0);expected(&at,RATE,1,200000000);
    expected(&at,CLK_RATE,5,200000000);expected(&at,CLK_RATE,6,200000000);
    for(unsigned i=0;i<3;i++)expected(&at,PD_ON,i,0);
    expected(&at,RST_ASSERT,0,0);expected(&at,RST_ASSERT,1,0);expected(&at,SLEEP,0,0);
    expected(&at,RST_DEASSERT,1,0);expected(&at,RST_DEASSERT,0,0);
    for(unsigned i=0;i<7;i++)expected(&at,PREPARE,i,0);
    for(unsigned i=0;i<7;i++)expected(&at,ENABLE,i,0);
    for(unsigned i=0;i<3;i++)expected(&at,HW_ON,i,0);
    assert(at==used && domains[1].hw && domains[2].hw && vote==200000000);
}
static void off_trace(void) {
    unsigned at=0;for(unsigned i=0;i<3;i++)expected(&at,HW_OFF,i,0);
    for(int i=6;i>=0;i--)expected(&at,DISABLE,i,0);
    for(int i=6;i>=0;i--)expected(&at,UNPREPARE,i,0);
    for(int i=2;i>=0;i--)expected(&at,PD_OFF,i,0);
    expected(&at,RATE,0,0);assert(at==used);clean();
}
int main(void) {
    for(unsigned cycle=0;cycle<64;cycle++) {
        init();assert(core_power_iris1(&core,POWER_ON)==0);on_trace();used=0;
        assert(core_power_iris1(&core,POWER_OFF)==0);off_trace();cases++;
    }
    const int faults[][2]={{FIND,3},{RATE,1},{CLK_RATE,5},{CLK_RATE,6},
        {PD_ON,0},{PD_ON,1},{PD_ON,2},{RST_ASSERT,0},{RST_ASSERT,1},
        {RST_DEASSERT,0},{RST_DEASSERT,1},{PREPARE,0},{PREPARE,1},
        {PREPARE,2},{PREPARE,3},{PREPARE,4},{PREPARE,5},{PREPARE,6},
        {ENABLE,0},{ENABLE,1},{ENABLE,2},{ENABLE,3},{ENABLE,4},{ENABLE,5},
        {ENABLE,6},{HW_ON,1},{HW_ON,2}};
    for(unsigned i=0;i<ARRAY_SIZE(faults);i++) {
        init();fail_op=faults[i][0];fail_id=faults[i][1];
        assert(core_power_iris1(&core,POWER_ON)==(fail_op==FIND?-ENOENT:-EIO));clean();
        fail_op=fail_id=-1;used=0;
        assert(core_power_iris1(&core,POWER_ON)==0);on_trace();used=0;
        assert(core_power_iris1(&core,POWER_OFF)==0);off_trace();cases++;
    }
    for(unsigned id=1;id<3;id++) {
        init();assert(!core_power_iris1(&core,POWER_ON));used=0;fail_op=HW_OFF;fail_id=id;
        assert(core_power_iris1(&core,POWER_OFF)==-EIO && vote==200000000);
        assert(domains[1].hw && domains[2].hw);
        for(unsigned i=0;i<7;i++)assert(clocks[i].enabled && clocks[i].prepared);
        fail_op=fail_id=-1;used=0;assert(!core_power_iris1(&core,POWER_OFF));off_trace();cases++;
    }
    init();assert(!core_power_iris1(&core,POWER_ON));fail_op=RATE;fail_id=0;
    assert(!core_power_iris1(&core,POWER_OFF) && warnings==1 && vote==200000000);
    fail_op=fail_id=-1;assert(!dev_pm_opp_set_rate(&owner,0));clean();cases++;
    const unsigned last_vpu =
#if (!IS_ENABLED(CONFIG_VIDEO_QCOM_IRIS))
        VPU_VERSION_IRIS2_1;
#else
        VPU_VERSION_IRIS1;
#endif
    for(unsigned v=0;v<=last_vpu;v++) {
        for(unsigned h=0;h<=HFI_VERSION_6XX;h++) {
            struct venus_resources r={.vpu_version=v,.hfi_version=h};
            struct venus_core c={.res=&r};const struct venus_pm_ops *want;
            if(v==VPU_VERSION_IRIS1)want=&pm_ops_iris1;
            else if(h==HFI_VERSION_3XX)want=&pm_ops_v3;
            else if(h==HFI_VERSION_4XX || h==HFI_VERSION_6XX)want=&pm_ops_v4;
            else want=&pm_ops_v1;
            assert(venus_pm_get(&c)==want);cases++;
        }
    }
    init();struct venus_inst inst={0};
    property_error=-EIO;assert(coreid_power_iris1(&inst,POWER_ON)==-EIO && !inst.core_acquired);cases++;
    property_error=0;assert(!coreid_power_iris1(&inst,POWER_ON) && inst.core_acquired && inst.clk_data.core_id==1);cases++;
    assert(!coreid_power_iris1(&inst,POWER_ON) && property_calls==2);cases++;
    assert(!coreid_power_iris1(&inst,POWER_OFF) && !inst.core_acquired && !inst.clk_data.core_id);clean();cases++;
    printf("{\"checks\":%u,\"power_cycles\":64,\"startup_failure_points\":27,\"off_failure_points\":3}\n",cases);
    return 0;
}
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('output', type=Path)
    args = p.parse_args()
    out = args.output
    out.mkdir(mode=0o700)
    paths = {
        'pm_helpers.c': REPO / 'drivers/media/platform/qcom/venus/pm_helpers.c',
        'pm_helpers.h': REPO / 'drivers/media/platform/qcom/venus/pm_helpers.h',
        'core.c': REPO / 'drivers/media/platform/qcom/venus/core.c',
        'core.h': REPO / 'drivers/media/platform/qcom/venus/core.h',
        'hfi_helper.h': REPO / 'drivers/media/platform/qcom/venus/hfi_helper.h',
        'clk-bulk.c': REPO / 'drivers/clk/clk-bulk.c',
        'clk.h': REPO / 'include/linux/clk.h',
        'reset-core.c': REPO / 'drivers/reset/core.c',
    }
    for name, path in paths.items():
        shutil.copyfile(path, out / name)
    before = (PREIMAGE / 'pm_helpers.c').read_text()
    after = (out / 'pm_helpers.c').read_text()
    cut = before.index('const struct venus_pm_ops *venus_pm_get(')
    assert after[:cut] == before[:cut]
    old_selector = block(before, 'const struct venus_pm_ops *venus_pm_get(')
    new_selector = block(after, 'const struct venus_pm_ops *venus_pm_get(')
    old_switch = old_selector[old_selector.index('\tswitch (version)'):]
    assert new_selector[new_selector.index('\tswitch (core->res->hfi_version)'):] == \
        old_switch.replace('switch (version)', 'switch (core->res->hfi_version)')
    patch = []
    for name in ('pm_helpers.c', 'pm_helpers.h', 'core.c'):
        old = (PREIMAGE / name).read_text()
        new = (out / name).read_text()
        shutil.copyfile(PREIMAGE / name, out / ('before-' + name))
        if name == 'core.c':
            assert new == old.replace('venus_pm_get(core->res->hfi_version)', 'venus_pm_get(core)')
        if name == 'pm_helpers.h':
            assert new == old.replace('venus_pm_get(enum hfi_version version)', 'venus_pm_get(struct venus_core *core)')
        patch.extend(difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True),
                     fromfile='a/drivers/media/platform/qcom/venus/' + name,
                     tofile='b/drivers/media/platform/qcom/venus/' + name))
    (out / 'power.patch').write_text(''.join(patch))
    definitions = block((out / 'core.h').read_text(), 'enum vpu_version {')
    definitions += '\n' + block((out / 'hfi_helper.h').read_text(), 'enum hfi_version {')
    definitions += '\n#define IS_IRIS1(core) ((core)->res->vpu_version == VPU_VERSION_IRIS1)\n'
    bodies = []
    extracted = []
    selections = [
        ('clk-bulk.c', ('void clk_bulk_unprepare(', 'int __must_check clk_bulk_prepare(',
                        'void clk_bulk_disable(', 'int __must_check clk_bulk_enable(')),
        ('clk.h', ('static inline int __must_check\nclk_bulk_prepare_enable(',
                   'static inline void clk_bulk_disable_unprepare(')),
        ('reset-core.c', ('int reset_control_bulk_assert(', 'int reset_control_bulk_deassert(')),
        ('pm_helpers.c', ('static int core_clks_set_rate(', 'static int vcodec_domains_enable(',
                          'static void vcodec_domains_disable(', 'static int vcodec_domains_set_hw(',
                          'static int iris1_clks_power(', 'static int iris1_resets_reset(',
                          'static int core_power_iris1(', 'static int coreid_power_iris1(',
                          'static const struct venus_pm_ops pm_ops_iris1 =',
                          'const struct venus_pm_ops *venus_pm_get('))]
    for name, markers in selections:
        text = (out / name).read_text()
        for marker in markers:
            body = block(text, marker)
            bodies.append(body)
            extracted.append(dict(file=name, marker=marker, sha256=hashlib.sha256(body.encode()).hexdigest()))
    body = '\n\n'.join(bodies)
    source = PREAMBLE + definitions + SCAFFOLD + body + CHECKS
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    results = []

    def run(name, text, config, negative=False):
        cfile = out / (name + '.c')
        cfile.write_text(text)
        cmd = ['gcc', '-std=gnu11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
               '-Wno-sign-compare', '-Wno-misleading-indentation',
               '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
               '-DCONFIG_VIDEO_QCOM_IRIS=' + str(config), str(cfile), '-o', str(out / name)]
        compiled = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        (out / (name + '.compile.stdout')).write_text(compiled.stdout)
        (out / (name + '.compile.stderr')).write_text(compiled.stderr)
        assert compiled.returncode == 0, compiled.stderr
        actual = subprocess.run([str(out / name)], capture_output=True, text=True, timeout=30)
        (out / (name + '.stdout')).write_text(actual.stdout)
        (out / (name + '.stderr')).write_text(actual.stderr)
        assert (actual.returncode != 0 and 'Assertion' in actual.stderr) if negative else \
            actual.returncode == 0 and not actual.stderr, (name, actual.stderr)
        results.append(dict(name=name, command=cmd, exit_code=actual.returncode,
                            checks=None if negative else json.loads(actual.stdout)))

    run('iris-disabled', source, 0)
    run('iris-enabled', source, 1)
    bad_order = body.replace('{ .clk = core->clks[2] }', '{ .clk = ORDER_SWAP }', 1)
    bad_order = bad_order.replace('{ .clk = core->vcodec0_clks[1] }', '{ .clk = core->clks[2] }', 1)
    bad_order = bad_order.replace('{ .clk = ORDER_SWAP }', '{ .clk = core->vcodec0_clks[1] }', 1)
    assert bad_order != body
    run('negative-clock-order', source.replace(body, bad_order), 0, True)
    bad_unwind = body.replace('err_domains:\n\tvcodec_domains_disable(core);', 'err_domains:\n\t;')
    assert bad_unwind != body
    run('negative-domain-unwind', source.replace(body, bad_unwind), 0, True)
    bad_reset = body.replace('reset_control_bulk_assert(core->res->resets_num, resets)',
                             'reset_control_bulk_assert(1, resets)', 1)
    assert bad_reset != body
    run('negative-paired-reset', source.replace(body, bad_reset), 0, True)
    shutil.copyfile(Path(__file__), out / 'verify_power.py')
    result = dict(actual_extractions=extracted, unchanged_generation_selection=True,
                  existing_pm_bodies_unchanged=True, runs=results,
                  actual_clock_bulk_helpers=True, actual_reset_bulk_helpers=True,
                  asan_ubsan=True, hardware_operations=0,
                  limits=['Leaf clock/reset/genpd/OPP APIs are synthetic and do not establish hardware behavior.',
                          'The existing decide_core algorithm is stubbed; this covers session ownership/error handling.',
                          'Failed runtime domain puts and failed rollback leaf operations are not emulated.'])
    (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    manifest = ''.join(f'{sha(p)}  {p.name}\n' for p in sorted(out.iterdir()) if p.is_file())
    (out / 'SHA256SUMS').write_text(manifest)
    print(json.dumps(dict(files=len(manifest.splitlines()), manifest_sha256=sha(out / 'SHA256SUMS'),
                         runs=[dict(name=r['name'], checks=r['checks']) for r in results]), indent=2))


if __name__ == '__main__':
    main()
