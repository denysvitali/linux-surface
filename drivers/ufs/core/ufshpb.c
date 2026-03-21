// SPDX-License-Identifier: GPL-2.0-or-later
/*
 * UFS Host Performance Booster (HPB) - Core Implementation (Stub)
 *
 * HPB is a JEDEC UFS 3.1 feature (HPB version 2.0) that caches LBA-to-PPN
 * mappings in host memory.  By supplying the Physical Page Number directly
 * in the CDB of an HPB READ command (opcode 0xF8) the device can skip its
 * internal L2P table lookup, improving random read latency by 2-3x.
 *
 * Current status: scaffolding / stub only.
 * All public entry points exist and are wired into the build, but the
 * actual HPB READ command injection and region-management logic is marked
 * with TODO comments and returns immediately.
 *
 * Implementation plan: see
 *   spx-drivers/drivers/UFS_HPB_IMPLEMENTATION_PLAN.md
 *
 * Reverse-engineering source: Windows storufs.sys (Surface Pro X, ARM64).
 * Key findings used here:
 *   - HPBFeatureToggle gate (mapped to CONFIG_SCSI_UFS_HPB / UFSHCD_CAP_HPB_EN)
 *   - UfsHPBMappingUpdateEnqueue(region, subregion, status) -> map_req workqueue
 *   - UfsHPBReadUpdateSrb(lba, ppn) -> ufshpb_prep_fn() intercept point
 *   - "PPN entry == 0" null-PPN guard -> ufshpb_ppn_valid()
 *   - "range invalidated by write" -> ufshpb_invalidate_range()
 *   - "region contains deactivation request" -> ufshpb_rsp_upiu()
 *
 * References:
 *   - JEDEC JESD220F: UFS 3.1 specification
 *   - JEDEC JESD223D: UFSHCI 3.0 specification
 *   - include/ufs/ufshpb.h (data structures and prototypes)
 *   - include/ufs/ufs.h (descriptor offsets, flag/attr IDNs)
 *   - drivers/ufs/core/ufshcd.c (ufshcd_read_desc_param, query helpers)
 *   - spx-drivers/drivers/STORUFS_RE_ANALYSIS.md
 *
 * Copyright (C) 2026 linux-surface contributors
 */

#include <linux/blkdev.h>
#include <linux/device.h>
#include <linux/errno.h>
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/slab.h>
#include <linux/spinlock.h>
#include <linux/workqueue.h>
#include <scsi/scsi_cmnd.h>
#include <ufs/ufs.h>
#include <ufs/ufshcd.h>
#include <ufs/ufshpb.h>

#include "ufshcd-priv.h"

/* ========================================================================
 * Module metadata
 * ======================================================================== */

MODULE_AUTHOR("linux-surface contributors");
MODULE_DESCRIPTION("UFS Host Performance Booster (HPB) driver");
MODULE_LICENSE("GPL v2");

/* ========================================================================
 * Internal helpers - forward declarations
 * ======================================================================== */

static void ufshpb_map_work_fn(struct work_struct *work);
static void ufshpb_free_regions(struct ufshpb_lu *hpb);
static int  ufshpb_alloc_regions(struct ufshpb_lu *hpb);

/* ========================================================================
 * Capability detection
 *
 * Reads HPB-related fields from the UFS Device Descriptor and Geometry
 * Descriptor to determine whether HPB is supported and at what geometry.
 *
 * Descriptor offsets (defined in include/ufs/ufs.h):
 *   DEVICE_DESC_PARAM_HPB_VER         (0x40, 2 bytes) - HPB version BCD
 *   DEVICE_DESC_PARAM_HPB_CONTROL     (0x42, 1 byte)  - HPB control flags
 *   DEVICE_DESC_PARAM_EXT_UFS_FEATURE_SUP (0x4F, 4 bytes) - feature bitmask
 *     Bit 7 = UFS_DEV_HPB_SUPPORT
 *   GEOMETRY_DESC_PARAM_HPB_REGION_SIZE    (0x48, 1 byte) - region size exp
 *   GEOMETRY_DESC_PARAM_HPB_SUBREGION_SIZE (0x4A, 1 byte) - subregion size exp
 *   GEOMETRY_DESC_PARAM_HPB_MAX_ACTIVE_REGS (0x4B, 2 bytes) - max active
 * ======================================================================== */

/**
 * ufshpb_read_geometry - Read HPB geometry from device descriptors
 * @hba: Host controller.
 * @hpb: HPB LU context to fill in.
 *
 * Reads the Device Descriptor and Geometry Descriptor to populate the
 * HPB geometry fields: region_count, subregion_count, max_active_regions,
 * region_block_size, and subregion_block_size.
 *
 * Returns 0 on success, negative errno on descriptor read failure.
 *
 * TODO: implement - currently returns -ENOSYS.
 */
static int ufshpb_read_geometry(struct ufs_hba *hba, struct ufshpb_lu *hpb)
{
	/*
	 * TODO: Read HPB geometry descriptors.
	 *
	 * Step 1: Read wHPBVersion from Device Descriptor
	 *   u8 ver_buf[2];
	 *   ret = ufshcd_read_desc_param(hba, QUERY_DESC_IDN_DEVICE, 0,
	 *       DEVICE_DESC_PARAM_HPB_VER, ver_buf, sizeof(ver_buf));
	 *   hpb->hpb_ver = get_unaligned_be16(ver_buf);
	 *
	 * Step 2: Read dExtendedUFSFeaturesSupport (bit 7 = HPB supported)
	 *   u8 feat_buf[4];
	 *   ret = ufshcd_read_desc_param(hba, QUERY_DESC_IDN_DEVICE, 0,
	 *       DEVICE_DESC_PARAM_EXT_UFS_FEATURE_SUP, feat_buf, sizeof(feat_buf));
	 *   if (!(get_unaligned_be32(feat_buf) & UFS_DEV_HPB_SUPPORT))
	 *       return -EOPNOTSUPP;
	 *
	 * Step 3: Read HPB geometry from Geometry Descriptor
	 *   bHPBRegionSize (0x48): region_size = 512KiB << bHPBRegionSize
	 *   bHPBNumberLU  (0x49): total HPB LUs
	 *   bHPBSubRegionSize (0x4A): subregion_size = 512KiB << bHPBSubRegionSize
	 *   wHPBMaxActiveRegs (0x4B, 2 bytes): max simultaneously active regions
	 *
	 * Step 4: Read per-LU HPB parameters from Unit Descriptor
	 *   wLUMaxHPBSingleCMD (0x23): max HPB commands outstanding
	 *   wHPBPinnedRegionStartOffset (0x25): start of pinned region range
	 *   wNumHPBPinnedRegions (0x27): number of pinned regions
	 */
	dev_dbg(hba->dev, "ufshpb: geometry read not yet implemented for LUN %d\n",
		hpb->lun);
	return -ENOSYS;
}

/**
 * ufshpb_check_device_support - Verify device reports HPB capability
 * @hba: Host controller.
 * @lun: LUN to check.
 *
 * Reads DEVICE_DESC_PARAM_EXT_UFS_FEATURE_SUP and checks UFS_DEV_HPB_SUPPORT.
 *
 * Returns true if the device declares HPB support, false otherwise.
 *
 * TODO: implement - currently returns false.
 */
static bool ufshpb_check_device_support(struct ufs_hba *hba, int lun)
{
	/*
	 * TODO: Read dExtendedUFSFeaturesSupport from Device Descriptor and
	 * check bit 7 (UFS_DEV_HPB_SUPPORT).
	 *
	 * Also check that wHPBVersion >= HPB_VERSION_2_0 (0x0200).
	 *
	 * From storufs.sys: the driver queries UFSSpecMajorVersion and
	 * checks the HPBFeatureToggle registry key before enabling HPB.
	 *
	 * Linux equivalent: if (!(hba->caps & UFSHCD_CAP_HPB_EN)) return false;
	 */
	(void)hba; (void)lun;
	return false;
}

/* ========================================================================
 * Region / Subregion allocation
 * ======================================================================== */

/**
 * ufshpb_init_subregion - Initialize a subregion descriptor in place
 * @sr:           Subregion to initialize (already allocated in region array).
 * @subregion_id: Subregion index within the region.
 *
 * Initialises the spinlock and fields of a pre-allocated subregion.
 * The PPN table is NOT allocated here; it is allocated on first activation.
 *
 * TODO: implement PPN table lazy allocation in ufshpb_activate_region().
 */
static void ufshpb_init_subregion(struct ufshpb_subregion *sr,
				  u8 subregion_id)
{
	sr->subregion_id = subregion_id;
	sr->state        = HPB_REGION_INACTIVE;
	sr->dirty        = false;
	sr->ppn_table    = NULL;
	spin_lock_init(&sr->lock);
}

/**
 * ufshpb_cleanup_subregion - Free a subregion's PPN table resources
 * @sr: Subregion to clean up.
 *
 * Frees the PPN table if allocated.  The subregion struct itself lives
 * in the parent region's kcalloc'd array and is freed with it.
 */
static void ufshpb_cleanup_subregion(struct ufshpb_subregion *sr)
{
	if (sr->ppn_table) {
		kfree(sr->ppn_table->ppn);
		kfree(sr->ppn_table);
		sr->ppn_table = NULL;
	}
}

/**
 * ufshpb_alloc_regions - Allocate the full region/subregion table
 * @hpb: HPB LU context (geometry fields must be populated first).
 *
 * Allocates hpb->region_count struct ufshpb_region objects, each containing
 * hpb->subregion_count struct ufshpb_subregion objects.
 *
 * Returns 0 on success, -ENOMEM on allocation failure.
 */
static int ufshpb_alloc_regions(struct ufshpb_lu *hpb)
{
	u16 i, j;

	hpb->regions = kcalloc(hpb->region_count, sizeof(*hpb->regions),
			       GFP_KERNEL);
	if (!hpb->regions)
		return -ENOMEM;

	for (i = 0; i < hpb->region_count; i++) {
		struct ufshpb_region *r = &hpb->regions[i];

		r->region_id      = i;
		r->state          = HPB_REGION_INACTIVE;
		r->subregion_count = hpb->subregion_count;
		spin_lock_init(&r->lock);
		INIT_LIST_HEAD(&r->lru_node);

		r->subregions = kcalloc(hpb->subregion_count,
					sizeof(*r->subregions), GFP_KERNEL);
		if (!r->subregions)
			goto err_free;

		for (j = 0; j < hpb->subregion_count; j++)
			ufshpb_init_subregion(&r->subregions[j], j);
	}
	return 0;

err_free:
	/* ufshpb_free_regions() handles partial allocation */
	ufshpb_free_regions(hpb);
	return -ENOMEM;
}

/**
 * ufshpb_free_regions - Free all region and subregion memory
 * @hpb: HPB LU context.
 */
static void ufshpb_free_regions(struct ufshpb_lu *hpb)
{
	u16 i, j;

	if (!hpb->regions)
		return;

	for (i = 0; i < hpb->region_count; i++) {
		struct ufshpb_region *r = &hpb->regions[i];

		if (!r->subregions)
			continue;

		for (j = 0; j < r->subregion_count; j++)
			ufshpb_cleanup_subregion(&r->subregions[j]);

		kfree(r->subregions);
		r->subregions = NULL;
	}

	kfree(hpb->regions);
	hpb->regions = NULL;
}

/* ========================================================================
 * Region Activation / Deactivation (stub)
 * ======================================================================== */

/**
 * ufshpb_activate_region - Activate an HPB region (allocate PPN table)
 * @hpb:       HPB LU context.
 * @region_id: Region to activate.
 *
 * Transitions the region from INACTIVE to ACTIVATING, allocates PPN tables
 * for all subregions, then transitions to ACTIVE.
 *
 * If max_active_regions is already reached, the LRU region is evicted first.
 *
 * From storufs.sys: "Activated region %d, subregion %d - regions active:%d"
 *
 * TODO: implement PPN table allocation, LRU eviction, and the
 *   HPB WRITE BUFFER command to fetch initial PPN data from the device.
 *
 * Returns 0 on success, negative errno on failure.
 */
static int ufshpb_activate_region(struct ufshpb_lu *hpb, u8 region_id)
{
	struct ufshpb_region *r;

	if (region_id >= hpb->region_count)
		return -EINVAL;

	r = &hpb->regions[region_id];

	spin_lock(&r->lock);

	if (r->state == HPB_REGION_ACTIVE) {
		spin_unlock(&r->lock);
		return 0; /* already active */
	}

	/*
	 * TODO:
	 * 1. If active_region_count >= max_active_regions, evict LRU region.
	 * 2. Transition r->state = HPB_REGION_ACTIVATING.
	 * 3. Allocate PPN table for each subregion:
	 *      sr->ppn_table = kzalloc(sizeof(*sr->ppn_table), GFP_ATOMIC);
	 *      sr->ppn_table->ppn = kcalloc(hpb->subregion_block_size,
	 *                                   UFSHPB_PPN_SIZE, GFP_ATOMIC);
	 * 4. Issue HPB WRITE BUFFER query to device to fetch initial PPNs.
	 * 5. On success: r->state = HPB_REGION_ACTIVE; hpb->active_region_count++
	 * 6. Add to hpb->lru_list tail.
	 * 7. r->activation_count++
	 */
	spin_unlock(&r->lock);

	dev_dbg(hpb->hba->dev,
		"ufshpb: activate_region LUN %d region %u - NOT YET IMPLEMENTED\n",
		hpb->lun, region_id);
	return -ENOSYS;
}

/**
 * ufshpb_deactivate_region - Deactivate an HPB region (free PPN table)
 * @hpb:       HPB LU context.
 * @region_id: Region to deactivate.
 *
 * From storufs.sys: "Region %d deactivated, %d active regions"
 *                   "Inactive region queued for deactivation - region: 0x%x"
 *
 * TODO: implement - quiesce in-flight HPB READs, free PPN tables,
 *   remove from LRU list, decrement active_region_count.
 */
static void ufshpb_deactivate_region(struct ufshpb_lu *hpb, u8 region_id)
{
	if (region_id >= hpb->region_count)
		return;

	/*
	 * TODO:
	 * 1. Set r->state = HPB_REGION_DEACTIVATING (under lock).
	 * 2. Wait for in-flight HPB READs to complete (ref-count drain).
	 * 3. Free PPN tables for all subregions.
	 * 4. Remove from lru_list.
	 * 5. r->state = HPB_REGION_INACTIVE; hpb->active_region_count--
	 */
	dev_dbg(hpb->hba->dev,
		"ufshpb: deactivate_region LUN %d region %u - NOT YET IMPLEMENTED\n",
		hpb->lun, region_id);
}

/* ========================================================================
 * Mapping-Update Work Queue
 *
 * The device piggybacks region-activation hints, deactivation hints, and
 * fresh PPN data onto UPIU responses.  ufshpb_rsp_upiu() is called from
 * the completion interrupt; it enqueues map_req items and schedules this
 * work function to process them in process context.
 * ======================================================================== */

/**
 * ufshpb_map_work_fn - Process queued mapping-update requests
 * @work: Embedded work_struct from struct ufshpb_lu.
 *
 * Dequeues all pending ufshpb_map_req entries and dispatches them to
 * ufshpb_activate_region() / ufshpb_deactivate_region() / PPN table update.
 *
 * TODO: implement the UPDATE path (copy ppn_buf into the subregion's
 * PPN table and mark the subregion dirty=false).
 */
static void ufshpb_map_work_fn(struct work_struct *work)
{
	struct ufshpb_lu *hpb =
		container_of(work, struct ufshpb_lu, map_work);
	struct ufshpb_map_req *req, *tmp;
	LIST_HEAD(local_list);

	spin_lock(&hpb->map_req_lock);
	list_splice_init(&hpb->map_req_list, &local_list);
	spin_unlock(&hpb->map_req_lock);

	list_for_each_entry_safe(req, tmp, &local_list, list) {
		list_del(&req->list);

		switch (req->type) {
		case UFSHPB_MAP_REQ_ACTIVATE:
			ufshpb_activate_region(hpb, req->region_id);
			break;
		case UFSHPB_MAP_REQ_DEACTIVATE:
			ufshpb_deactivate_region(hpb, req->region_id);
			break;
		case UFSHPB_MAP_REQ_UPDATE:
			/*
			 * TODO: copy req->ppn_buf into the subregion PPN table.
			 *
			 * sr = hpb->regions[req->region_id]
			 *          .subregions[req->subregion_id];
			 * spin_lock(&sr->lock);
			 * memcpy(sr->ppn_table->ppn, req->ppn_buf,
			 *        req->ppn_count * UFSHPB_PPN_SIZE);
			 * sr->dirty = false;
			 * spin_unlock(&sr->lock);
			 */
			dev_dbg(hpb->hba->dev,
				"ufshpb: map_work UPDATE region %u sr %u - TODO\n",
				req->region_id, req->subregion_id);
			kfree(req->ppn_buf);
			break;
		}

		kfree(req);
	}
}

/* ========================================================================
 * Public API - Init / Exit
 * ======================================================================== */

/**
 * ufshpb_init - Initialise HPB for a UFS logical unit
 * @hba: Host controller.
 * @lun: SCSI LUN index.
 *
 * Called from ufshcd_add_lus() (or equivalent probe path) after the device
 * has responded to the initial device descriptor query.
 *
 * Steps:
 *  1. Check device support via ufshpb_check_device_support().
 *  2. Read geometry via ufshpb_read_geometry().
 *  3. Allocate struct ufshpb_lu and region table.
 *  4. Initialise the mapping-update workqueue.
 *  5. Send QUERY SET_FLAG (QUERY_FLAG_IDN_HPB_EN) to enable HPB on device.
 *
 * On success, the ufshpb_lu pointer is stored in hba->lpriv[lun] or a
 * similar per-LU slot (exact attachment point is a TODO).
 *
 * Returns 0 on success, -EOPNOTSUPP if the device does not support HPB,
 * negative errno on other errors.
 *
 * TODO: wire up hba->lpriv (or equivalent) for per-LU HPB storage.
 */
int ufshpb_init(struct ufs_hba *hba, int lun)
{
	struct ufshpb_lu *hpb;
	int ret;

	if (!ufshpb_check_device_support(hba, lun)) {
		dev_dbg(hba->dev,
			"ufshpb: LUN %d does not support HPB, skipping\n", lun);
		return -EOPNOTSUPP;
	}

	hpb = kzalloc(sizeof(*hpb), GFP_KERNEL);
	if (!hpb)
		return -ENOMEM;

	hpb->hba = hba;
	hpb->lun = lun;
	spin_lock_init(&hpb->lock);
	spin_lock_init(&hpb->map_req_lock);
	INIT_LIST_HEAD(&hpb->lru_list);
	INIT_LIST_HEAD(&hpb->map_req_list);
	INIT_WORK(&hpb->map_work, ufshpb_map_work_fn);

	ret = ufshpb_read_geometry(hba, hpb);
	if (ret) {
		dev_err(hba->dev,
			"ufshpb: LUN %d geometry read failed (%d)\n", lun, ret);
		goto err_free_hpb;
	}

	ret = ufshpb_alloc_regions(hpb);
	if (ret) {
		dev_err(hba->dev,
			"ufshpb: LUN %d region allocation failed (%d)\n",
			lun, ret);
		goto err_free_hpb;
	}

	/*
	 * TODO: send QUERY SET_FLAG QUERY_FLAG_IDN_HPB_EN to the device so
	 * it starts sending PPN mapping data in UPIU responses.
	 *
	 *   ret = ufshcd_query_flag(hba, UPIU_QUERY_OPCODE_SET_FLAG,
	 *                           QUERY_FLAG_IDN_HPB_EN, lun, NULL);
	 *
	 * TODO: store hpb in a per-LU slot on hba (e.g. hba->lpriv[lun]).
	 *   Currently there is no per-LU HPB pointer in struct ufs_hba.
	 *   Possible approach: piggyback on scsi_device->hostdata via
	 *   sdev_priv(), or add a new hpb[] array to struct ufs_hba.
	 */

	dev_info(hba->dev,
		 "ufshpb: LUN %d HPB scaffolding initialised (stub, not functional)\n",
		 lun);

	/*
	 * Return -ENOSYS here because the stub is not yet wired up end-to-end.
	 * Remove this error return once ufshpb_prep_fn() and ufshpb_rsp_upiu()
	 * are implemented and the per-LU storage slot exists.
	 */
	ret = -ENOSYS;

err_free_hpb:
	ufshpb_free_regions(hpb);
	kfree(hpb);
	return ret;
}
EXPORT_SYMBOL_GPL(ufshpb_init);

/**
 * ufshpb_exit - Tear down HPB for a UFS logical unit
 * @hba: Host controller.
 * @lun: SCSI LUN index.
 *
 * Cancels any pending map_work, drains the map_req_list, frees all
 * region/subregion/PPN table memory, and NULLs the per-LU pointer.
 *
 * TODO: retrieve hpb from the per-LU storage slot (see ufshpb_init TODO).
 */
void ufshpb_exit(struct ufs_hba *hba, int lun)
{
	/*
	 * TODO:
	 * struct ufshpb_lu *hpb = ufshpb_get_lu(hba, lun);
	 * if (!hpb) return;
	 *
	 * cancel_work_sync(&hpb->map_work);
	 *
	 * spin_lock(&hpb->map_req_lock);
	 * // drain and free map_req_list
	 * spin_unlock(&hpb->map_req_lock);
	 *
	 * ufshpb_free_regions(hpb);
	 * kfree(hpb);
	 * // clear per-LU slot
	 */
	dev_dbg(hba->dev, "ufshpb: exit LUN %d (stub)\n", lun);
}
EXPORT_SYMBOL_GPL(ufshpb_exit);

/* ========================================================================
 * Public API - get_lu
 * ======================================================================== */

/**
 * ufshpb_get_lu - Return the HPB context for a LUN
 * @hba: Host controller.
 * @lun: SCSI LUN index.
 *
 * Returns the ufshpb_lu pointer, or NULL if HPB is not active for this LUN.
 *
 * TODO: implement once the per-LU storage slot is defined.
 */
struct ufshpb_lu *ufshpb_get_lu(struct ufs_hba *hba, int lun)
{
	/* TODO: return hba->hpb_lu[lun] or equivalent */
	(void)hba; (void)lun;
	return NULL;
}
EXPORT_SYMBOL_GPL(ufshpb_get_lu);

/* ========================================================================
 * Public API - prep_fn (SCSI command intercept)
 * ======================================================================== */

/**
 * ufshpb_prep_fn - Optionally rewrite a READ as an HPB READ
 * @hba: Host controller.
 * @cmd: SCSI command being prepared for submission.
 *
 * Called from ufshcd_queuecommand() just before the UPIU is built.
 * If the command is a READ(10) or READ(16) targeting an LBA whose region
 * and subregion are active and whose PPN table entry is non-zero, this
 * function rewrites the CDB to HPB READ (opcode 0xF8) and embeds the PPN.
 *
 * From storufs.sys: UfsHPBReadUpdateSrb(lba, ppn)
 *   "UfsHPBReadUpdateSrb (0x%llx) - LBA: 0x%llx, PPN: 0x%llx"
 *   "Failed to HPB read, PPN entry == 0 - LBA: 0x%llx"
 *   "HPB read for LBA %x, PPN %x (region %d) contains deactivation request"
 *
 * Returns 0 if the command was not modified (standard I/O path).
 * Returns 1 if the CDB was rewritten to HPB READ.
 *
 * TODO: implement the lookup and CDB rewrite logic.
 */
int ufshpb_prep_fn(struct ufs_hba *hba, struct scsi_cmnd *cmd)
{
	/*
	 * TODO:
	 *
	 * 1. Check opcode: only intercept READ(10) = 0x28 or READ(16) = 0x88.
	 *    u8 opcode = cmd->cmnd[0];
	 *    if (opcode != READ_10 && opcode != READ_16) return 0;
	 *
	 * 2. Get LUN: int lun = cmd->device->lun;
	 *    struct ufshpb_lu *hpb = ufshpb_get_lu(hba, lun);
	 *    if (!hpb) return 0;
	 *
	 * 3. Extract LBA and length from CDB.
	 *    u64 lba = (opcode == READ_10) ? get_unaligned_be32(&cmd->cmnd[2])
	 *                                  : get_unaligned_be64(&cmd->cmnd[2]);
	 *
	 * 4. Compute region_id and subregion_id:
	 *    u8 region_id = lba / (hpb->region_block_size);
	 *    u8 sub_id    = (lba % hpb->region_block_size) / hpb->subregion_block_size;
	 *    u32 ppn_idx  = lba % hpb->subregion_block_size;
	 *
	 * 5. Look up PPN (under subregion spinlock):
	 *    struct ufshpb_region *r = &hpb->regions[region_id];
	 *    if (r->state != HPB_REGION_ACTIVE) return 0;
	 *    struct ufshpb_subregion *sr = r->subregions[sub_id];
	 *    spin_lock(&sr->lock);
	 *    __le64 ppn = sr->ppn_table->ppn[ppn_idx];
	 *    spin_unlock(&sr->lock);
	 *
	 * 6. Null-PPN guard (storufs.sys finding):
	 *    if (!ufshpb_ppn_valid(ppn)) { hpb->stat_hpb_misses++; return 0; }
	 *
	 * 7. Rewrite CDB:
	 *    ufshpb_set_hpb_read_cdb(cmd->cmnd, lba, le64_to_cpu(ppn), len);
	 *    hpb->stat_hpb_reads++;
	 *    hpb->stat_hpb_hits++;
	 *
	 * 8. Update LRU position for the region.
	 *
	 * return 1;
	 */
	(void)hba; (void)cmd;
	return 0;
}
EXPORT_SYMBOL_GPL(ufshpb_prep_fn);

/* ========================================================================
 * Public API - rsp_upiu (completion path HPB hint processing)
 * ======================================================================== */

/**
 * ufshpb_rsp_upiu - Process HPB activation/update hints in a UPIU response
 * @hba:     Host controller.
 * @lun:     SCSI LUN index of the completed command.
 * @rsp:     Pointer to the RESPONSE UPIU buffer.
 * @rsp_len: Total length of the UPIU buffer in bytes.
 *
 * Called from interrupt context at transfer completion time.
 * The UFS 3.1 spec allows the device to piggyback HPB mapping information
 * in the Extra Header Segment (EHS) of a RESPONSE UPIU:
 *   - Activate region X
 *   - Deactivate region Y
 *   - Provide fresh PPN data for subregion Z
 *
 * This function parses the EHS, creates ufshpb_map_req entries, appends
 * them to hpb->map_req_list, and schedules hpb->map_work.
 *
 * From storufs.sys: UfsHPBMappingUpdateEnqueue(region, subregion, status)
 *   "UfsHPBMappingUpdateEnqueue - region: %d, subregion: %d, status %x"
 *
 * TODO: parse the EHS according to JEDEC JESD220F Table 10-29 (HPB Response
 *   UPIU format) and enqueue map_req items.
 */
void ufshpb_rsp_upiu(struct ufs_hba *hba, int lun,
		     const void *rsp, size_t rsp_len)
{
	/*
	 * TODO:
	 *
	 * 1. Parse EHS starting at EHS_OFFSET_IN_RESPONSE (32 bytes into UPIU).
	 *    Check EHS type field: 0x02 = HPB Update Response.
	 *
	 * 2. For each HPB hint record in the EHS:
	 *    - Extract region_id, subregion_id, action (activate/deactivate/update).
	 *    - Allocate struct ufshpb_map_req.
	 *    - For UPDATE: copy PPN data into req->ppn_buf.
	 *    - Append to hpb->map_req_list (under map_req_lock).
	 *
	 * 3. schedule_work(&hpb->map_work);
	 *
	 * EHS format reference: JEDEC JESD220F Section 10.7.8
	 *   Byte 0-1: EHS Length
	 *   Byte 2:   EHS Type (0x02 for HPB)
	 *   Byte 3:   EHS Sub-type
	 *   Byte 4+:  HPB region/subregion hints
	 */
	(void)hba; (void)lun; (void)rsp; (void)rsp_len;
}
EXPORT_SYMBOL_GPL(ufshpb_rsp_upiu);

/* ========================================================================
 * Public API - write invalidation
 * ======================================================================== */

/**
 * ufshpb_invalidate_range - Invalidate HPB cache entries covering a write
 * @hba:       Host controller.
 * @lun:       SCSI LUN index.
 * @lba:       Starting LBA of the write operation.
 * @lba_count: Number of logical blocks written.
 *
 * Called from the WRITE command completion path.  Zeroes out PPN table
 * entries for all subregions that overlap the written range, forcing
 * subsequent reads of those LBAs to fall back to standard UFS I/O until
 * the device resends fresh PPN mapping data.
 *
 * From storufs.sys:
 *   "Failed to HPB read, range invalidated by write - LBA: 0x%llx - PPN: 0x%llx"
 *
 * TODO: implement the range-to-subregion mapping and PPN zeroing.
 */
void ufshpb_invalidate_range(struct ufs_hba *hba, int lun,
			     u64 lba, u32 lba_count)
{
	/*
	 * TODO:
	 *
	 * 1. Get hpb = ufshpb_get_lu(hba, lun). Return if NULL.
	 *
	 * 2. Compute first and last subregion affected:
	 *    u64 lba_end = lba + lba_count - 1;
	 *    u8 r_start  = lba / hpb->region_block_size;
	 *    u8 r_end    = lba_end / hpb->region_block_size;
	 *
	 * 3. For each region in [r_start..r_end]:
	 *    For each subregion overlapping [lba..lba_end]:
	 *      spin_lock(&sr->lock);
	 *      memset(sr->ppn_table->ppn + offset, 0, count * UFSHPB_PPN_SIZE);
	 *      sr->inval_count++;
	 *      spin_unlock(&sr->lock);
	 *
	 * 4. hpb->stat_write_invals++;
	 */
	(void)hba; (void)lun; (void)lba; (void)lba_count;
}
EXPORT_SYMBOL_GPL(ufshpb_invalidate_range);
