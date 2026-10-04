/* SPDX-License-Identifier: GPL-2.0-only */
/* Mock DMA leaves for verbatim driver bodies; no hardware operations. */
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint8_t u8;
typedef uint32_t u32;
typedef uint64_t dma_addr_t;
#define __counted_by(x)
#define CONFIG_VIDEO_QCOM_IRIS CONFIG_IRIS
#define IS_ENABLED(x) (x)
#define SZ_4K 4096U
#define SZ_1M 1048576U
#define ALIGN(x,a) (((x)+(a)-1)&~((a)-1))
#define READ_ONCE(x) (x)
#define GFP_KERNEL 0
#define DMA_ATTR_WRITE_COMBINE 4
#define module_param_named(name,value,type,mode) _Static_assert(mode == 0400, "read-only parameter")
#define MODULE_PARM_DESC(name,description)
struct mutex { unsigned locked; };
struct completion { unsigned unused; };
struct device_node { const char *compatible; };
struct device { const struct device_node *of_node; };
/* SOURCE_DEFINITIONS */
struct venus_resources { enum vpu_version vpu_version; };
struct venus_core {
    struct device *dev;
    const struct venus_resources *res;
    void *priv;
};
/* SOURCE_HDEV */
struct allocation { void *ptr; u32 size; dma_addr_t da; unsigned long attrs; bool live; };
struct event { unsigned kind; uint64_t size,da,attrs; };
struct trace { struct event events[32]; unsigned len,attempts,frees,null_frees,barriers; };
static struct allocation allocations[2];
static struct trace trace;
static unsigned fail_at;
static dma_addr_t next_base;
static __attribute__((unused)) int of_device_is_compatible(const struct device_node *node, const char *value)
{ return node && node->compatible && !strcmp(node->compatible,value); }
static void mutex_lock(struct mutex *m) { assert(!m->locked); m->locked=1; }
static void mutex_unlock(struct mutex *m) { assert(m->locked); m->locked=0; }
static void wmb(void) { trace.barriers++; }
static void record(unsigned kind,uint64_t size,uint64_t da,uint64_t attrs) {
    assert(trace.len<32);trace.events[trace.len++]=(struct event){kind,size,da,attrs};
}
static void *dma_alloc_attrs(struct device *dev,u32 size,dma_addr_t *da,int flags,unsigned long attrs) {
    assert(dev && flags==GFP_KERNEL && attrs==DMA_ATTR_WRITE_COMBINE);
    unsigned n=++trace.attempts;
    assert(n<=2);record(0,size,n==1?next_base:next_base-4096,attrs);
    if(n==fail_at) return NULL;
    void *ptr=malloc(size);assert(ptr);memset(ptr,0xa5,size);
    *da=n==1?next_base:next_base-4096;
    allocations[n-1]=(struct allocation){ptr,size,*da,attrs,true};
    return ptr;
}
static void dma_free_attrs(struct device *dev,u32 size,void *ptr,dma_addr_t da,unsigned long attrs) {
    assert(dev);record(1,size,da,attrs);
    if(!ptr) { trace.null_frees++;return; }
    unsigned n;
    for(n=0;n<2;n++) if(allocations[n].ptr==ptr) break;
    assert(n<2 && allocations[n].live);
    assert(allocations[n].size==size && allocations[n].da==da && allocations[n].attrs==attrs);
    allocations[n].live=false;trace.frees++;free(ptr);
}
/* SOURCE_FUNCTIONS */
