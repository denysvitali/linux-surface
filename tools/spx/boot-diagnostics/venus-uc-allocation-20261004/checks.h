/* SPDX-License-Identifier: GPL-2.0-only */
struct view { dma_addr_t da; u32 size; unsigned long attrs; };
struct result {
    int rc;
    struct view queue,sfr;
    struct hfi_queue_table_header table;
    struct hfi_queue_header headers[3];
    dma_addr_t queue_da[3];
    u32 queue_size[3],sfr_size;
    struct trace trace;
};
static struct view view(struct mem_desc *p) { return (struct view){p->da,p->size,p->attrs}; }
static void queue_checks(struct venus_hfi_device *h) {
    struct hfi_queue_table_header *t=h->ifaceq_table.kva;
    assert(t->version==0 && t->size==192 && t->qhdr0_offset==24 && t->qhdr_size==56);
    assert(t->num_q==3 && t->num_active_q==3);
    for(unsigned n=0;n<3;n++) {
        struct iface_queue *q=&h->queues[n];struct hfi_queue_header *p=q->qhdr;
        assert(q->qmem.da==h->ifaceq_table.da+192+n*819200U && q->qmem.size==819200U);
        assert((char *)q->qmem.kva==(char *)h->ifaceq_table.kva+192+n*819200U);
        assert((char *)p==(char *)h->ifaceq_table.kva+24+n*56);
        assert(p->start_addr==q->qmem.da && p->type==(0x01010000U|n) && p->q_size==204800U);
        assert(p->status==1 && p->rx_req==(n==2?0U:1U) && !p->tx_req);
        assert(p->rx_wm==1 && p->tx_wm==1 && !p->read_idx && !p->write_idx);
    }
}
static struct result one(bool old,bool gate,int gen,int compat,unsigned fail,dma_addr_t base) {
    memset(allocations,0,sizeof(allocations));memset(&trace,0,sizeof(trace));fail_at=fail;next_base=base;
    struct device_node node={compat==0?"qcom,sc8180x-venus":compat==1?"qcom,sc7180-venus":NULL};
    struct device dev={compat==2?NULL:&node};struct venus_resources res={gen};
    struct venus_hfi_device h={0};struct venus_core core={&dev,&res,&h};h.core=&core;
    spx_uc_shared_alloc=gate;
    bool shared=!old && gate && gen==VPU_VERSION_IRIS1 && compat==0;
    struct result r={0};
    r.rc=old?before_venus_interface_queues_init(&h):venus_interface_queues_init(&h);
    assert(r.rc==(fail==1?-ENOMEM:0));
    assert(trace.attempts==(fail==1||shared?1U:2U));
    assert(trace.events[0].size==(shared?3145728U:2461696U));
    if(!r.rc) {
        assert(h.ifaceq_table.size==2461696U);queue_checks(&h);
        bool has_sfr=shared||fail!=2;
        assert((h.sfr.kva!=NULL)==has_sfr);
        if(has_sfr) assert(((struct hfi_sfr *)h.sfr.kva)->buf_size==4096U);
        if(shared) {
            assert(h.shared_uc.kva==h.ifaceq_table.kva && h.shared_uc.size==3145728U);
            assert(h.shared_uc.da==base && h.sfr.da==base+2461696U && h.sfr.size==4096U);
            assert((char *)h.sfr.kva==(char *)h.shared_uc.kva+2461696U);
            assert(h.sfr.da+h.sfr.size<=base+h.shared_uc.size);
            for(unsigned i=192;i<h.shared_uc.size;i++) {
                if(i>=2461696U && i<2461700U) continue;
                assert(!((u8 *)h.shared_uc.kva)[i]);
            }
        } else assert(!h.shared_uc.kva);
        r.queue=view(&h.ifaceq_table);r.sfr=view(&h.sfr);
        memcpy(&r.table,h.ifaceq_table.kva,sizeof(r.table));
        for(unsigned n=0;n<3;n++) {
            r.headers[n]=*h.queues[n].qhdr;r.queue_da[n]=h.queues[n].qmem.da;r.queue_size[n]=h.queues[n].qmem.size;
        }
        if(has_sfr) {
            r.sfr_size=((struct hfi_sfr *)h.sfr.kva)->buf_size;
            for(unsigned n=0;n<3;n++) memset(h.queues[n].qhdr,0x55,sizeof(*h.queues[n].qhdr));
            ((struct hfi_sfr *)h.sfr.kva)->buf_size=0x55555555;
            unsigned attempts=trace.attempts;
            spx_uc_shared_alloc=!gate;
            if(old) before_venus_hfi_queues_reinit(&core);else venus_hfi_queues_reinit(&core);
            queue_checks(&h);assert(trace.attempts==attempts && !trace.frees);
            assert(((struct hfi_sfr *)h.sfr.kva)->buf_size==4096);
            for(unsigned n=0;n<3;n++) {
                struct hfi_queue_header expected=r.headers[n];
                /* Reinit preserves this firmware counter in the BF contract. */
                expected.pkt_drop_cnt=0x55555555;
                assert(!memcmp(&expected,h.queues[n].qhdr,sizeof(expected)));
            }
        }
    }
    spx_uc_shared_alloc=!gate;
    if(old) before_venus_interface_queues_release(&h);else venus_interface_queues_release(&h);
    assert(trace.frees==(fail==1?0U:shared||fail==2?1U:2U));
    assert(!h.ifaceq_table.kva && !h.sfr.kva && !h.shared_uc.kva && !h.lock.locked);
    struct iface_queue empty[3]={0};assert(!memcmp(h.queues,empty,sizeof(empty)));
    for(unsigned n=0;n<2;n++) assert(!allocations[n].live);
    unsigned freed=trace.frees;
    if(old) before_venus_interface_queues_release(&h);else venus_interface_queues_release(&h);
    assert(trace.frees==freed);r.trace=trace;
    return r;
}
int main(void) {
    assert(!spx_uc_shared_alloc);
    unsigned comparisons=0,shared_cases=0;
    dma_addr_t bases[]={0x01000000,0x25801000,0x80000000,0xbfc00000};
    unsigned generations=CONFIG_IRIS?3U:5U;
    for(unsigned gate=0;gate<2;gate++) for(unsigned gen=0;gen<generations;gen++)
    for(unsigned compat=0;compat<4;compat++) for(unsigned fail=0;fail<3;fail++)
    for(unsigned n=0;n<4;n++) {
        struct result old=one(true,gate,gen,compat,fail,bases[n]);
        struct result current=one(false,gate,gen,compat,fail,bases[n]);
        if(gate && gen==VPU_VERSION_IRIS1 && compat==0) shared_cases++;
        else {
            assert(old.rc==current.rc && old.sfr_size==current.sfr_size);
            assert(old.queue.da==current.queue.da && old.queue.size==current.queue.size && old.queue.attrs==current.queue.attrs);
            assert(old.sfr.da==current.sfr.da && old.sfr.size==current.sfr.size && old.sfr.attrs==current.sfr.attrs);
            assert(!memcmp(&old.table,&current.table,sizeof(old.table)));
            assert(!memcmp(old.headers,current.headers,sizeof(old.headers)));
            assert(!memcmp(old.queue_da,current.queue_da,sizeof(old.queue_da)));
            assert(!memcmp(old.queue_size,current.queue_size,sizeof(old.queue_size)));
            assert(old.trace.len==current.trace.len && old.trace.attempts==current.trace.attempts);
            assert(old.trace.frees==current.trace.frees && old.trace.null_frees==current.trace.null_frees && old.trace.barriers==current.trace.barriers);
            for(unsigned i=0;i<old.trace.len;i++) {
                assert(old.trace.events[i].kind==current.trace.events[i].kind);
                assert(old.trace.events[i].size==current.trace.events[i].size);
                assert(old.trace.events[i].da==current.trace.events[i].da);
                assert(old.trace.events[i].attrs==current.trace.events[i].attrs);
            }
            comparisons++;
        }
    }
    printf("{\"unchanged_path_comparisons\":%u,\"shared_cases\":%u,\"config_iris\":%u}\n",
           comparisons,shared_cases,CONFIG_IRIS);
}
