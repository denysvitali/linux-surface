/* SPDX-License-Identifier: GPL-2.0-only */
static struct venus_resources resources(unsigned kind) {
    struct venus_resources r={.fwname="fallback-fw",.cp_start=1,.cp_nonpixel_start=3,.cp_nonpixel_size=4};
    switch(kind) {
    case 0:r.vpu_version=VPU_VERSION_AR50;r.hfi_version=HFI_VERSION_1XX;break;
    case 1:r.vpu_version=VPU_VERSION_AR50;r.hfi_version=HFI_VERSION_3XX;break;
    case 2:r.vpu_version=VPU_VERSION_AR50;r.hfi_version=HFI_VERSION_4XX;break;
    case 3:r.vpu_version=VPU_VERSION_IRIS1;r.hfi_version=HFI_VERSION_4XX;break;
#if !CONFIG_VIDEO_QCOM_IRIS
    case 4:r.vpu_version=VPU_VERSION_IRIS2;r.hfi_version=HFI_VERSION_6XX;break;
    case 5:r.vpu_version=VPU_VERSION_IRIS2_1;r.hfi_version=HFI_VERSION_6XX;break;
#endif
    case 6:r.vpu_version=VPU_VERSION_AR50_LITE;r.hfi_version=HFI_VERSION_4XX;break;
    default:assert(0);
    }return r;
}
static void reset(bool enabled,bool budget) {
    memset(cpu,0,sizeof(cpu));memset(wrapper,0,sizeof(wrapper));memset(tz_wrapper,0,sizeof(tz_wrapper));
    memset(&got,0,sizeof(got));polls=0;
    wrapper[0x10/4]=0x1f6;wrapper[0/4]=0x30210001;
    spx_hfi_startup_diag=enabled;if(budget) atomic_store(&spx_hfi_startup_diag_lines.value,0);
}
static void equal(struct capture a,struct capture b,bool extra) {
    /* The sole added read is after the last poll, possibly before normal hwversion. */
    if(extra) {
        unsigned i=0;for(;i<a.len;i++) if(a.trace[i].kind==0 && a.trace[i].a==0xe0000) break;
        assert(i<a.len);memmove(&a.trace[i],&a.trace[i+1],(a.len-i-1)*sizeof(a.trace[0]));a.len--;
    }
    assert(a.result==b.result && a.mem_phys==b.mem_phys && a.mem_size==b.mem_size);
    assert(a.len==b.len && a.sleeps==b.sleeps && a.errors==b.errors && a.debugs==b.debugs);
    assert(!memcmp(a.trace,b.trace,a.len*sizeof(a.trace[0])));
}
static struct capture hfi_case(unsigned kind,bool run,bool before,bool enabled,unsigned after,u32 value,bool sfr) {
    struct venus_resources res=resources(kind);struct device dev={0};
    struct venus_core core={.dev=&dev,.res=&res,.cpu_cs_base=cpu,.wrapper_base=wrapper,.wrapper_tz_base=tz_wrapper,.use_tz=true};
    struct venus_hfi_device hdev={.core=&core,.ifaceq_table={.da=0xabcdef00,.size=2461696},.sfr={.da=sfr?0x12345600:0,.size=4096}};
    reset(enabled,true);ready_after=after;ctrl_result=value;
    got.result=run?(before?before_venus_run(&hdev):venus_run(&hdev)):
                   (before?before_venus_boot_core(&hdev):venus_boot_core(&hdev));
    return got;
}
static void check_hfi(void) {
    const u32 values[]={0,1,2,4,5,6,0xfe,0xffffffff};unsigned cases=0;
    for(unsigned kind=0;kind<7;kind++) for(unsigned run=0;run<2;run++)
    for(unsigned sfr=0;sfr<2;sfr++) for(unsigned after=1;after<=101;after++) for(unsigned v=0;v<8;v++) {
#if CONFIG_VIDEO_QCOM_IRIS
        if(kind==4 || kind==5) continue;
#endif
        struct capture b=hfi_case(kind,run,true,false,after,values[v],sfr);
        struct capture off=hfi_case(kind,run,false,false,after,values[v],sfr);equal(off,b,false);assert(!off.nlogs);
        struct capture on=hfi_case(kind,run,false,true,after,values[v],sfr);equal(on,b,kind==3);
        if(kind!=3) assert(!on.nlogs);
        else {
            assert(on.nlogs==1+run);
            struct log_entry l=on.logs[run];assert(l.kind==1);
            assert((int64_t)l.v[0]==on.result && l.v[2]==((after<=100)?values[v]:0));
            unsigned count=(!values[v] || after>100)?100:((values[v]&0xfe)==4)?after-1:after;
            assert(l.v[1]==count && l.v[3]==0x1e2 && l.v[4]==0x30210001);
            if(run) {
                l=on.logs[0];assert(l.kind==2 && l.v[0]==0xabcdef00 && l.v[1]==2461696);
                assert(l.v[2]==3145728 && l.v[3]==(sfr?0x12345600U:0) && l.v[4]==4096 && l.v[5]==1);
            }
        }cases++;
    }
    printf("\"hfi_comparisons\":%u,",cases*2);
}
static struct capture fw_case(unsigned kind,bool state,bool before,bool enabled,bool use_tz,unsigned scenario,bool resume) {
    struct venus_resources res=resources(kind);struct device dev={0};res.cp_size=scenario==7?2:0;
    struct venus_core core={.dev=&dev,.res=&res,.wrapper_base=wrapper,.wrapper_tz_base=tz_wrapper,.use_tz=use_tz,.fw={.mapped_mem_size=0x500000}};
    reset(enabled,true);available=scenario!=6;property_error=scenario==8?-EINVAL:0;
    load_error=scenario==1?-ENOENT:scenario==2?-EIO:scenario==3?-EPROBE_DEFER:0;
    boot_error=scenario==4?-EACCES:scenario==5?-ETIMEDOUT:0;protect_error=scenario==7?-EINVAL:0;
    const int remote[]={0,-EINVAL,-EIO,-EPROBE_DEFER,-ETIMEDOUT,-EACCES,1,42,-ERANGE};remote_error=remote[scenario];
    got.result=state?(before?before_venus_set_hw_state(&core,resume):venus_set_hw_state(&core,resume)):
                     (before?before_venus_boot(&core):venus_boot(&core));
    got.mem_phys=core.fw.mem_phys;got.mem_size=core.fw.mem_size;return got;
}
static void check_fw(void) {
    unsigned cases=0;
    for(unsigned kind=0;kind<7;kind++) for(unsigned state=0;state<2;state++)
    for(unsigned tz=0;tz<2;tz++) for(unsigned resume=0;resume<2;resume++) for(unsigned s=0;s<9;s++) {
#if CONFIG_VIDEO_QCOM_IRIS
        if(kind==4 || kind==5) continue;
#endif
        struct capture b=fw_case(kind,state,true,false,tz,s,resume);
        struct capture off=fw_case(kind,state,false,false,tz,s,resume);equal(off,b,false);assert(!off.nlogs);
        struct capture on=fw_case(kind,state,false,true,tz,s,resume);equal(on,b,false);
        bool logs=kind==3 && tz && (state || (s!=1 && s!=2 && s!=3 && s!=6));assert(on.nlogs==logs);
        if(logs) {
            struct log_entry l=on.logs[0];assert(l.kind==(state?3U:4U) && l.v[0]==(state?resume:9U));
            assert((int64_t)l.v[1]==(state?remote_error:boot_error));
            if(state && resume && remote_error==-EINVAL) assert(on.result==0 && (int64_t)l.v[1]==-EINVAL);
        }cases++;
    }printf("\"firmware_comparisons\":%u,",cases*2);
}
static void *worker(void *arg) {
    struct venus_core *core=arg;
    for(unsigned i=0;i<1000;i++) if(venus_hfi_startup_diag(core)) atomic_fetch_add((_Atomic unsigned *)core->dev->of_node,1);
    return NULL;
}
static void check_budget(void) {
    struct venus_resources res=resources(3);struct device dev={0};
    struct venus_core core={.dev=&dev,.res=&res,.cpu_cs_base=cpu,.wrapper_base=wrapper,.wrapper_tz_base=tz_wrapper,.use_tz=true};
    struct venus_hfi_device hdev={.core=&core,.ifaceq_table={.da=0x12340000,.size=2461696},.sfr={.da=0x56780000,.size=4096}};
    reset(true,true);available=true;load_error=boot_error=protect_error=remote_error=property_error=0;
    unsigned total=0;
    for(unsigned i=0;i<12;i++) {
        reset(true,false);ready_after=1;ctrl_result=1;
        assert(!venus_boot(&core));assert(!venus_set_hw_state(&core,true));assert(!venus_run(&hdev));
        total+=got.nlogs;assert(got.nlogs==(i<8?4U:0U));
        unsigned reads=0;for(unsigned j=0;j<got.len;j++) if(got.trace[j].kind==0 && got.trace[j].a==0xe0000) reads++;
        assert(reads==(i<8?2U:1U));
        if(i<8) assert(got.logs[0].kind==4 && got.logs[1].kind==3 && got.logs[2].kind==2 && got.logs[3].kind==1);
    }assert(total==32);
    _Atomic unsigned accepted=0;dev.of_node=&accepted;pthread_t threads[16];
    reset(true,true);
    for(unsigned i=0;i<16;i++) assert(!pthread_create(&threads[i],NULL,worker,&core));
    for(unsigned i=0;i<16;i++) assert(!pthread_join(threads[i],NULL));
    assert(atomic_load(&accepted)==32);
    reset(false,true);for(unsigned i=0;i<100;i++) assert(!venus_hfi_startup_diag(&core));
    assert(!atomic_read(&spx_hfi_startup_diag_lines));
    spx_hfi_startup_diag=true;res=resources(2);
    for(unsigned i=0;i<100;i++) assert(!venus_hfi_startup_diag(&core));
    assert(!atomic_read(&spx_hfi_startup_diag_lines));
    puts("\"shared_log_limit\":32,\"concurrent_calls\":16000,\"concurrent_accepted\":32}");
}
int main(void) {
    assert(!spx_hfi_startup_diag && !atomic_read(&spx_hfi_startup_diag_lines));
    assert(QUEUE_SIZE==2457792 && ALIGNED_QUEUE_SIZE==2461696 && SHARED_QSIZE==3145728);
    printf("{\"config_iris\":%u,",CONFIG_VIDEO_QCOM_IRIS);check_hfi();check_fw();check_budget();return 0;
}
