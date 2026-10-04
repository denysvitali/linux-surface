/* SPDX-License-Identifier: GPL-2.0-only */
/* Actual function bodies are inserted by verify_diag.py; leaves are mocked. */
#include <assert.h>
#include <errno.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdatomic.h>

typedef unsigned int u32;
typedef unsigned long long u64;
typedef u64 dma_addr_t;
typedef u64 phys_addr_t;
typedef unsigned int __le32;
typedef u64 __le64;
typedef unsigned int gfp_t;
typedef struct { atomic_int value; } atomic_t;
#define ATOMIC_INIT(x) { ATOMIC_VAR_INIT(x) }
#define READ_ONCE(x) (x)
#define unlikely(x) __builtin_expect(!!(x), 0)
#define _AC(x,t) x##t
#define GFP_ATOMIC 1
#define GFP_KERNEL 2
#define ARRAY_SIZE(x) (sizeof(x) / sizeof((x)[0]))
#define min_t(t,a,b) ((t)(a) < (t)(b) ? (t)(a) : (t)(b))
#define cpu_to_le32(x) (x)
#define cpu_to_le64(x) (x)
#define module_param_named(name,value,type,mode) _Static_assert((mode) == 0400, "Readonly parameter required")

static bool atomic_add_unless(atomic_t *counter, int add, int unless)
{
	int old = atomic_load(&counter->value);
	while (old != unless) {
		if (atomic_compare_exchange_weak(&counter->value, &old, old + add))
			return true;
	}
	return false;
}

struct device { unsigned int dummy; };
struct qcom_tzmem_pool { unsigned int dummy; };
struct arm_smccc_res { unsigned long a0, a1, a2, a3; };
/* @DEFINITIONS */

/* @GLOBALS */
static bool use_before;
static int clock_rc, bandwidth_rc, do_rc;
static struct arm_smccc_res raw_result;
static enum qcom_scm_convention convention;

struct observation {
	unsigned int count;
	unsigned int events[8];
	unsigned long smc[8];
	bool atomic;
};
static struct observation observed;
enum { CLOCK_ON = 1, BANDWIDTH_ON, SMC, BANDWIDTH_OFF, CLOCK_OFF };

struct log_record {
	char format[512];
	int ret, valid, convention;
	u32 pas;
	u64 service, address, size;
	unsigned long id, arginfo, args[3], raw[4];
};
static struct log_record logs[64];
static unsigned int log_count, checks;

static void dev_info(struct device *dev, const char *format, ...)
{
	assert(dev && log_count < ARRAY_SIZE(logs));
	struct log_record *record = &logs[log_count++];
	assert(strlen(format) < sizeof(record->format));
	strcpy(record->format, format);
	va_list args;
	va_start(args, format);
	if (strstr(format, "init-image begin")) {
		record->pas = va_arg(args, u32);
		record->address = *va_arg(args, dma_addr_t *);
	} else if (strstr(format, "mem-setup begin")) {
		record->pas = va_arg(args, u32);
		record->address = *va_arg(args, phys_addr_t *);
		record->size = *va_arg(args, phys_addr_t *);
	} else if (strstr(format, "transport")) {
		record->ret = va_arg(args, int);
		record->valid = va_arg(args, int);
		record->service = va_arg(args, u64);
	} else if (strstr(format, "clock") || strstr(format, "bandwidth")) {
		record->ret = va_arg(args, int);
	} else if (strstr(format, "smc begin")) {
		record->id = va_arg(args, unsigned long);
		record->convention = va_arg(args, int);
		record->arginfo = va_arg(args, unsigned long);
		for (unsigned int i = 0; i < 3; i++)
			record->args[i] = va_arg(args, unsigned long);
	} else {
		assert(strstr(format, "smc done"));
		record->id = va_arg(args, unsigned long);
		if (strstr(format, "raw_valid=0")) {
			record->ret = va_arg(args, int);
		} else {
			assert(strstr(format, "raw_valid=1"));
			record->valid = 1;
			for (unsigned int i = 0; i < 4; i++)
				record->raw[i] = va_arg(args, unsigned long);
		}
	}
	va_end(args);
}

static void event(unsigned int value)
{
	assert(observed.count < ARRAY_SIZE(observed.events));
	observed.events[observed.count++] = value;
}
static int qcom_scm_clk_enable(void) { event(CLOCK_ON); return clock_rc; }
static int qcom_scm_bw_enable(void) { event(BANDWIDTH_ON); return bandwidth_rc; }
static void qcom_scm_bw_disable(void) { event(BANDWIDTH_OFF); }
static void qcom_scm_clk_disable(void) { event(CLOCK_OFF); }

static int __scm_smc_do(struct device *dev, struct arm_smccc_args *args,
			struct arm_smccc_res *result, bool atomic)
{
	(void)dev;
	event(SMC);
	memcpy(observed.smc, args->args, sizeof(observed.smc));
	observed.atomic = atomic;
	/* Failure leaves data invalid, with a sentinel to catch faulty logging. */
	*result = do_rc ? (struct arm_smccc_res) {0xfeed, 0xdead, 0xbeef, 0xcafe} : raw_result;
	return do_rc;
}
static struct qcom_tzmem_pool *qcom_scm_get_tzmem_pool(void) { return NULL; }
static void *qcom_tzmem_alloc(struct qcom_tzmem_pool *pool, size_t n, gfp_t flags)
{
	(void)pool; (void)n; (void)flags;
	assert(!"Unexpected extended-argument allocation");
	return NULL;
}
static unsigned long qcom_tzmem_to_phys(void *pointer)
{
	(void)pointer;
	assert(!"Unexpected physical-address conversion");
	return 0;
}
static void mock_cleanup(void *address) { assert(!*(void **)address); }
#define __free(x) __attribute__((cleanup(mock_cleanup)))
#define trace_scm_smc_done(...) ((void)0)

static int qcom_scm_call(struct device *, const struct qcom_scm_desc *, struct qcom_scm_res *);
/* @BODIES */

static int qcom_scm_call(struct device *dev, const struct qcom_scm_desc *desc,
			struct qcom_scm_res *result)
{
	if (use_before)
		return before_smc_call(dev, desc, convention, result, false);
	return __scm_smc_call(dev, desc, convention, result, false);
}

static void reset(bool budget)
{
	memset(&observed, 0, sizeof(observed));
	memset(logs, 0, sizeof(logs));
	log_count = 0;
	if (budget) {
		atomic_store(&spx_pas_image_diag_count.value, 0);
		atomic_store(&spx_pas_mem_diag_count.value, 0);
		atomic_store(&spx_pas_smc_diag_count.value, 0);
	}
}

static int invoke(bool image, u32 pas)
{
	struct device dev = {0};
	struct qcom_scm_res res = { .result = {0xdead, 0xbeef, 0xcafe} };
	if (image) {
		if (use_before)
			return before_image(&dev, pas, 0x12345000, &res);
		return __qcom_scm_pas_init_image(&dev, pas, 0x12345000, &res);
	}
	if (use_before)
		return before_memory(&dev, pas, 0xfe500000, 0x500000);
	return __qcom_scm_pas_mem_setup(&dev, pas, 0xfe500000, 0x500000);
}

static void validate_logs(bool image, bool enabled, int transport)
{
	if (!enabled) { assert(!log_count); return; }
	assert(log_count == (clock_rc || bandwidth_rc ? 2 : 4));
	assert(logs[0].pas == 9);
	assert(logs[0].address == (image ? 0x12345000ULL : 0xfe500000ULL));
	if (!image) assert(logs[0].size == 0x500000);
	if (clock_rc || bandwidth_rc) {
		assert(strstr(logs[1].format, clock_rc ? "clock" : "bandwidth"));
		assert(logs[1].ret == (clock_rc ? clock_rc : bandwidth_rc));
		return;
	}
	assert(strstr(logs[1].format, "smc begin"));
	assert(logs[1].id == (convention == SMC_CONVENTION_ARM_64 ? 0x42000200UL : 0x02000200UL) +
			    (image ? QCOM_SCM_PIL_PAS_INIT_IMAGE : QCOM_SCM_PIL_PAS_MEM_SETUP));
	assert(logs[1].convention == (int)convention);
	assert(logs[1].args[0] == 9);
	assert(logs[1].arginfo == (image ? QCOM_SCM_ARGS(2, QCOM_SCM_VAL, QCOM_SCM_RW) : QCOM_SCM_ARGS(3)));
	assert(logs[2].valid == !do_rc);
	if (do_rc) {
		assert(logs[2].ret == do_rc);
		for (unsigned int i = 0; i < 4; i++) assert(!logs[2].raw[i]);
	} else {
		assert(!memcmp(logs[2].raw, &raw_result, sizeof(raw_result)));
	}
	assert(strstr(logs[3].format, "transport"));
	assert(logs[3].ret == transport && logs[3].valid == !transport);
	assert(logs[3].service == (transport ? 0 : raw_result.a1));
}

static void compare_cases(void)
{
	for (unsigned int mode = 0; mode < 2; mode++)
	for (unsigned int enabled = 0; enabled < 2; enabled++)
	for (unsigned int image = 0; image < 2; image++)
	for (unsigned int error = 0; error < 10; error++) {
		convention = mode ? SMC_CONVENTION_ARM_64 : SMC_CONVENTION_ARM_32;
		clock_rc = error == 1 ? -EINVAL : 0;
		bandwidth_rc = error == 2 ? -EINVAL : 0;
		do_rc = error == 3 ? -ETIMEDOUT : 0;
		raw_result = (struct arm_smccc_res) {0, 0, 0x55, 0xaa};
		if (error >= 4 && error <= 7)
			raw_result.a0 = (unsigned long[]){-2UL, -3UL, -1UL, -12UL}[error - 4];
		if (error == 8) raw_result.a1 = (unsigned long)-EINVAL;
		if (error == 9) raw_result.a1 = 7;
		int transport = do_rc ? do_rc : raw_result.a0 ? qcom_scm_remap_error(raw_result.a0) : 0;
		int expected = clock_rc ? clock_rc : bandwidth_rc ? bandwidth_rc :
			       transport ? transport : image ? 0 : (int)raw_result.a1;
		reset(true); spx_pas_diag = enabled; use_before = true;
		int old = invoke(image, 9);
		struct observation original = observed;
		assert(!log_count && old == expected);
		reset(true); use_before = false;
		int actual = invoke(image, 9);
		assert(actual == expected && !memcmp(&observed, &original, sizeof(original)));
		validate_logs(image, enabled, transport);
		if (!enabled) {
			assert(!atomic_load(&spx_pas_image_diag_count.value));
			assert(!atomic_load(&spx_pas_mem_diag_count.value));
			assert(!atomic_load(&spx_pas_smc_diag_count.value));
		}
		checks++;
	}
}

static void scopes_and_budgets(void)
{
	struct device dev = {0};
	struct qcom_scm_res res;
	spx_pas_diag = true; use_before = false;
	clock_rc = bandwidth_rc = do_rc = 0;
	raw_result = (struct arm_smccc_res) {0};
	for (unsigned int kind = 0; kind < 10; kind++) {
		reset(true);
		struct qcom_scm_desc desc = { .owner = ARM_SMCCC_OWNER_SIP,
			.svc = QCOM_SCM_SVC_PIL, .cmd = QCOM_SCM_PIL_PAS_MEM_SETUP,
			.arginfo = QCOM_SCM_ARGS(3), .args = {9, 0xfe500000, 0x500000} };
		if (kind < 4) desc.args[0] = (unsigned int[]){0, 4, 8, 10}[kind];
		if (kind == 4) desc.owner = 0;
		if (kind == 5) desc.svc = 1;
		if (kind == 6) desc.cmd = 5;
		if (kind == 7) desc.cmd = 6;
		assert(!__scm_smc_call(kind == 9 ? NULL : &dev, &desc,
				    SMC_CONVENTION_ARM_64, &res, kind == 8));
		assert(!log_count && !atomic_load(&spx_pas_smc_diag_count.value));
		checks++;
	}
	reset(true); convention = SMC_CONVENTION_ARM_64;
	for (unsigned int i = 0; i < 32; i++) {
		memset(&observed, 0, sizeof(observed));
		assert(!invoke(i < 4, 9));
		assert(observed.count == 5);
	}
	assert(log_count == 32);
	assert(atomic_load(&spx_pas_image_diag_count.value) == 4);
	assert(atomic_load(&spx_pas_mem_diag_count.value) == 4);
	assert(atomic_load(&spx_pas_smc_diag_count.value) == 8);
	for (unsigned int i = 0; i < 16; i++) {
		assert(!atomic_add_unless(&spx_pas_mem_diag_count, 1, 4));
		assert(atomic_load(&spx_pas_mem_diag_count.value) == 4);
	}
	checks++;
}

int main(void)
{
	assert(!spx_pas_diag);
	compare_cases();
	scopes_and_budgets();
	printf("{\"checks\":%u,\"before_after_cases\":80,\"scope_cases\":10,\"maximum_lines\":32}\n", checks);
	return 0;
}
