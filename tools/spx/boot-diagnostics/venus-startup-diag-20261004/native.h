/* SPDX-License-Identifier: GPL-2.0-only */
/* Mock leaves for extracted, unmodified kernel C bodies. No hardware access. */
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint32_t u32;
typedef uint64_t dma_addr_t;
typedef uint64_t phys_addr_t;
#define __iomem
#define BIT(n) (1U << (n))
#define GENMASK(h,l) ((~0U << (l)) & (~0U >> (31-(h))))
#define IS_ENABLED(x) (x)
#define CONFIG_QCOM_MDT_LOADER 1
#define EPROBE_DEFER 517
#define SZ_4K 4096U
#define SZ_1M 1048576U
#define ALIGN(x,a) (((x)+(a)-1)&~((a)-1))
#define READ_ONCE(x) (x)
#define module_param_named(name,value,type,mode) _Static_assert(mode == 0400, "read-only parameter")
#define MODULE_PARM_DESC(name,description)
typedef struct { _Atomic int value; } atomic_t;
#define ATOMIC_INIT(x) {x}
static int atomic_read(const atomic_t *v) { return atomic_load(&v->value); }
static int atomic_inc_return(atomic_t *v) { return atomic_fetch_add(&v->value,1)+1; }
#include "linux-hfi_venus_io.h"
/* SOURCE_DEFINITIONS */
struct device { void *of_node; };
struct venus_resources {
    enum vpu_version vpu_version;
    enum hfi_version hfi_version;
    const char *fwname;
    u32 cp_start,cp_size,cp_nonpixel_start,cp_nonpixel_size;
};
struct venus_core {
    struct device *dev;
    const struct venus_resources *res;
    void *cpu_cs_base,*wrapper_base,*wrapper_tz_base;
    bool use_tz;
    struct { size_t mem_size,mapped_mem_size; phys_addr_t mem_phys; } fw;
};
struct venus_hfi_device { struct venus_core *core; struct mem_desc ifaceq_table,sfr; };
struct event { unsigned kind; uint64_t a,b,c,d; };
struct log_entry { unsigned kind; uint64_t v[6]; };
struct capture {
    struct event trace[512]; unsigned len,sleeps,errors,debugs;
    struct log_entry logs[64]; unsigned nlogs;
    int result; uint64_t mem_phys,mem_size;
};
static struct capture got;
static u32 cpu[0x300/4],wrapper[0x4000/4],tz_wrapper[0x4000/4];
static unsigned polls,ready_after;
static u32 ctrl_result;
static bool available;
static int load_error,boot_error,protect_error,remote_error,property_error;
static void event(unsigned kind,uint64_t a,uint64_t b,uint64_t c,uint64_t d) {
    assert(got.len<512); got.trace[got.len++]=(struct event){kind,a,b,c,d};
}
static u32 offset(const void *addr) {
    uintptr_t a=(uintptr_t)addr,c=(uintptr_t)cpu,w=(uintptr_t)wrapper,t=(uintptr_t)tz_wrapper;
    assert(!(a&3));
    if(a>=c && a<c+sizeof(cpu)) return 0xd2000+(u32)(a-c);
    if(a>=w && a<w+sizeof(wrapper)) return 0xe0000+(u32)(a-w);
    assert(a>=t && a<t+sizeof(tz_wrapper)); return 0xf0000+(u32)(a-t);
}
static u32 readl(const void *addr) {
    u32 off=offset(addr),value;memcpy(&value,addr,4);
    if(off==0xd204c) value=(++polls>=ready_after)?ctrl_result:0;
    event(0,off,value,0,0);return value;
}
static void writel(u32 value,void *addr) { event(1,offset(addr),value,0,0);memcpy(addr,&value,4); }
static void usleep_range(unsigned low,unsigned high) {
    assert(low==500 && high==1000);got.sleeps++;
}
static void dev_err(struct device *dev,const char *format,...) { (void)dev;(void)format;got.errors++; }
static void dev_dbg(struct device *dev,const char *format,...) { (void)dev;(void)format;got.debugs++; }
static void dev_info(struct device *dev,const char *format,...) {
    (void)dev;assert(got.nlogs<64);struct log_entry *l=&got.logs[got.nlogs++];
    va_list ap;va_start(ap,format);
    if(!strcmp(format,"SPX Venus startup poll ret=%d count=%u status=%#x mask=%#x hw=%#x\n")) {
        l->kind=1;l->v[0]=(uint64_t)(int64_t)va_arg(ap,int);
        for(unsigned i=1;i<5;i++) l->v[i]=va_arg(ap,unsigned);
    } else if(!strcmp(format,"SPX Venus startup buffers queue=%pad queue_size=%u uc_size=%u sfr=%pad sfr_size=%u tz=%u\n")) {
        l->kind=2;l->v[0]=*va_arg(ap,dma_addr_t *);l->v[1]=va_arg(ap,unsigned);
        l->v[2]=va_arg(ap,unsigned);l->v[3]=*va_arg(ap,dma_addr_t *);
        l->v[4]=va_arg(ap,unsigned);l->v[5]=va_arg(ap,unsigned);
    } else if(!strcmp(format,"SPX Venus startup remote-state resume=%u ret=%d\n")) {
        l->kind=3;l->v[0]=va_arg(ap,unsigned);l->v[1]=(uint64_t)(int64_t)va_arg(ap,int);
    } else {
        assert(!strcmp(format,"SPX Venus startup auth-reset pas=%u ret=%d\n"));
        l->kind=4;l->v[0]=va_arg(ap,unsigned);l->v[1]=(uint64_t)(int64_t)va_arg(ap,int);
    }
    va_end(ap);
}
static void venus_set_registers(struct venus_hfi_device *hdev) { (void)hdev;event(2,0,0,0,0); }
static bool qcom_pas_is_available(void) { event(3,available,0,0,0);return available; }
static int of_property_read_string_index(void *node,const char *prop,unsigned index,const char **value) {
    (void)node;assert(!strcmp(prop,"firmware-name") && !index);event(4,0,0,0,0);
    *value="board-fw";return property_error;
}
static int venus_load_fw(struct venus_core *core,const char *path,phys_addr_t *phys,size_t *size) {
    assert(!strcmp(path,property_error?core->res->fwname:"board-fw"));event(5,load_error,0,0,0);
    *phys=0x8d300000;*size=0x500000;return load_error;
}
static int qcom_pas_auth_and_reset(unsigned id) { assert(id==9);event(6,id,boot_error,0,0);return boot_error; }
static int venus_boot_no_tz(struct venus_core *core,phys_addr_t phys,size_t size) {
    (void)core;assert(phys==0x8d300000 && size==0x500000);event(7,phys,size,boot_error,0);return boot_error;
}
static int qcom_scm_mem_protect_video_var(u32 a,u32 b,u32 c,u32 d) { event(8,a,b,c,d);return protect_error; }
static int qcom_pas_shutdown(unsigned id) { assert(id==9);event(9,id,0,0,0);return 0; }
static int qcom_pas_set_remote_state(bool resume,unsigned id) {
    assert(id==0);event(10,resume,id,remote_error,0);return remote_error;
}
static void venus_reset_cpu(struct venus_core *core) { event(11,core->fw.mapped_mem_size,0,0,0); }
#define VDBGL ""
/* SOURCE_BODIES */
