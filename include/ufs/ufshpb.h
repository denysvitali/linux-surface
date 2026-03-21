/* SPDX-License-Identifier: GPL-2.0-or-later */
/*
 * UFS Host Performance Booster (HPB) - Kernel Header
 *
 * HPB is a JEDEC UFS 3.1 feature (HPB version 2.0) that caches logical
 * block address (LBA) to physical page number (PPN) mappings in host
 * memory, bypassing the device's internal L2P translation for frequently
 * accessed data.  This yields 2-3x random read IOPS improvement on
 * supported UFS 3.1 devices.
 *
 * Architecture (from JEDEC JESD220F / UFS 3.1 HPB 2.0 spec):
 *
 *  +------------------+       +------------------+
 *  |   Host Memory    |       |   UFS Device     |
 *  |                  |       |                  |
 *  |  HPB Region 0    |<----->|  HPB Region 0    |
 *  |   Subregion 0    |       |   (L2P Table)    |
 *  |   Subregion 1    |       |                  |
 *  |       ...        |       +------------------+
 *  |  HPB Region N    |
 *  +------------------+
 *
 *  HPB READ (opcode 0xF8): host supplies PPN in CDB, device skips L2P lookup.
 *  HPB WRITE BUFFER: device sends updated PPN mappings to host.
 *  Regions are activated/deactivated by the device via UPIU response fields.
 *
 * Reverse-engineering notes (storufs.sys, Windows ARM64 for Surface Pro X):
 *  - Region/subregion tracking: UfsHPBMappingUpdateEnqueue(region, subregion)
 *  - PPN update path: UfsHPBReadUpdateSrb(lba, ppn)
 *  - Write invalidation: "Failed to HPB read, range invalidated by write"
 *  - Feature toggle: HPBFeatureToggle registry key -> RtlQueryFeatureConfiguration
 *  - Null PPN guard: "PPN entry == 0" check before issuing HPB READ
 *  - Deactivation path: "HPB read for LBA %x, PPN %x (region %d) contains
 *    deactivation request"
 *
 * References:
 *  - JEDEC JESD220F: Universal Flash Storage (UFS), version 3.1
 *  - JEDEC JESD223D: UFS Host Controller Interface (UFSHCI) 3.0
 *  - storufs.sys RE analysis: spx-drivers/drivers/STORUFS_RE_ANALYSIS.md
 *  - Existing UFS kernel definitions: include/ufs/ufs.h
 *
 * Copyright (C) 2026 linux-surface contributors
 * SPDX-License-Identifier: GPL-2.0-or-later
 */

#ifndef _UFSHPB_H
#define _UFSHPB_H

#include <linux/list.h>
#include <linux/mutex.h>
#include <linux/spinlock.h>
#include <linux/types.h>
#include <linux/workqueue.h>

/* Forward declarations */
struct ufs_hba;
struct scsi_cmnd;

/* ========================================================================
 * HPB UPIU Command Opcodes
 * JEDEC JESD220F Section 11 - HPB Commands
 * ======================================================================== */

/*
 * HPB READ opcode (replaces standard READ(10) / READ(16) for HPB-eligible I/O).
 * The host places a 4-byte PPN field at CDB bytes [6..9] (for HPB READ(10))
 * or at CDB bytes [10..13] (for HPB READ(16)).
 * If the device detects a mapping mismatch it responds with a UPIU that
 * carries a region-deactivation or mapping-update hint.
 */
#define HPB_READ_OPCODE			0xF8

/*
 * HPB WRITE BUFFER sub-command codes (used in Query WRITE_BUFFER UPIUs
 * that the device sends to push updated PPN tables to the host).
 */
#define HPB_WRITE_BUFFER_SUBCODE	0x01

/* ========================================================================
 * HPB Version
 * ======================================================================== */

/*
 * The only HPB version supported by JEDEC UFS 3.1.
 * Stored in DEVICE_DESC_PARAM_HPB_VER (2 bytes, big-endian BCD).
 * 0x0200 = HPB version 2.0.
 */
#define HPB_VERSION_2_0			0x0200

/*
 * Minimum UFS spec version that mandates HPB 2.0 support.
 * UFS_DEV_HPB_SUPPORT_VERSION is defined in include/ufs/ufs.h as 0x310
 * (UFS spec version 3.1.0).
 */

/* ========================================================================
 * HPB Region/Subregion Limits
 * These are implementation limits, not spec maximums.
 * ======================================================================== */

/*
 * Maximum number of HPB regions this driver will track.
 * The device reports its actual count in GEOMETRY_DESC_PARAM_HPB_MAX_ACTIVE_REGS.
 * Typical values: 16-256.
 */
#define UFSHPB_MAX_REGIONS		256

/*
 * Maximum number of subregions within a single HPB region.
 * Each subregion has its own PPN table page.
 */
#define UFSHPB_MAX_SUBREGIONS		256

/*
 * Absolute maximum simultaneously active HPB regions.
 * This driver clamps to the device's reported limit.
 */
#define UFSHPB_MAX_ACTIVE_REGIONS	128

/*
 * Size of one PPN entry in bytes (64-bit physical page number).
 * JEDEC specifies 4-byte PPNs for HPB 1.0 and 8-byte for HPB 2.0.
 */
#define UFSHPB_PPN_SIZE			8   /* bytes, HPB 2.0 */

/* ========================================================================
 * HPB Region State Machine
 *
 * Lifecycle (RE finding from storufs.sys):
 *
 *   INACTIVE --> ACTIVATING --> ACTIVE --> DEACTIVATING --> INACTIVE
 *                    |                          ^
 *                    |      device response     |
 *                    +--------ACTIVE HINT ------+
 *
 * Log strings observed:
 *   "Activated region %d, subregion %d - regions active:%d"
 *   "Region %d deactivated, %d active regions"
 *   "Inactive region queued for deactivation - region: 0x%x, status: 0x%x"
 * ======================================================================== */

/**
 * enum ufshpb_region_state - per-region HPB state
 * @HPB_REGION_INACTIVE:    Region is not cached; PPN table may be freed.
 * @HPB_REGION_ACTIVATING:  Region activation requested; fetching PPN table.
 * @HPB_REGION_ACTIVE:      PPN table resident in host memory; HPB READs allowed.
 * @HPB_REGION_DEACTIVATING: Deactivation in progress; quiescing in-flight HPB READs.
 */
enum ufshpb_region_state {
	HPB_REGION_INACTIVE	= 0,
	HPB_REGION_ACTIVATING	= 1,
	HPB_REGION_ACTIVE	= 2,
	HPB_REGION_DEACTIVATING	= 3,
};

/* ========================================================================
 * HPB PPN (Physical Page Number) Table
 *
 * Each subregion owns one PPN table: an array of 8-byte PPNs, one per
 * 4 KiB logical block covered by the subregion.
 * A zero PPN means "not yet mapped" (guard from storufs.sys).
 * ======================================================================== */

/**
 * struct ufshpb_ppn_table - in-memory PPN table for one subregion
 * @ppn:      Array of 8-byte PPNs, one per logical block in the subregion.
 *            Entries are written by the device via HPB WRITE BUFFER responses.
 * @num_ppns: Number of valid entries (= subregion_blocks).
 *
 * Allocated as a single kmalloc'd buffer; accessed under the parent
 * subregion's @lock.
 */
struct ufshpb_ppn_table {
	__le64		*ppn;
	u32		 num_ppns;
};

/* ========================================================================
 * Subregion
 * ======================================================================== */

/**
 * struct ufshpb_subregion - one HPB subregion within a region
 * @subregion_id: Index within the parent region (0-based).
 * @state:        Current state (uses ufshpb_region_state enum values).
 * @dirty:        PPN table needs refresh from device.
 * @ppn_table:    PPN mapping table, NULL when subregion is inactive.
 * @lock:         Protects @state, @dirty, and @ppn_table contents.
 * @hit_count:    Number of HPB READ cache hits for this subregion.
 * @miss_count:   Number of PPN-zero misses (uninitialized entries).
 * @inval_count:  Times this subregion was invalidated by a write.
 */
struct ufshpb_subregion {
	u8			 subregion_id;
	u8			 state;		/* enum ufshpb_region_state */
	bool			 dirty;

	struct ufshpb_ppn_table	*ppn_table;
	spinlock_t		 lock;

	/* Statistics */
	u64			 hit_count;
	u64			 miss_count;
	u64			 inval_count;
};

/* ========================================================================
 * Region
 * ======================================================================== */

/**
 * struct ufshpb_region - one HPB region
 * @region_id:      Index in the device's HPB region space (0-based).
 * @state:          Region-level state (enum ufshpb_region_state).
 * @subregion_count: Number of subregions in this region.
 * @subregions:     Array of @subregion_count subregion descriptors.
 * @lru_node:       Node in ufshpb_dev.lru_list (protected by hpb->lock).
 * @lock:           Protects @state and LRU membership.
 * @total_hits:     Aggregate cache hits across all subregions.
 * @total_misses:   Aggregate cache misses across all subregions.
 * @activation_count: Number of times this region was activated.
 */
struct ufshpb_region {
	u8			 region_id;
	u8			 state;		/* enum ufshpb_region_state */
	u16			 subregion_count;

	struct ufshpb_subregion	*subregions;	/* array [subregion_count] */

	struct list_head	 lru_node;
	spinlock_t		 lock;

	/* Statistics */
	u64			 total_hits;
	u64			 total_misses;
	u64			 activation_count;
};

/* ========================================================================
 * HPB Device Context
 *
 * One instance per UFS logical unit that supports HPB.
 * Embedded in (or pointed to from) the per-LU data hung off ufs_hba.
 * ======================================================================== */

/**
 * struct ufshpb_lu - HPB state for one UFS logical unit
 * @hba:                  Back-pointer to the host controller.
 * @lun:                  SCSI LUN index this HPB context belongs to.
 *
 * Geometry (read from device descriptors during probe):
 * @hpb_ver:              HPB version reported by device (e.g. 0x0200).
 * @region_count:         Total HPB regions on this LU.
 * @subregion_count:      Subregions per region.
 * @max_active_regions:   Max simultaneously active regions (device limit).
 * @region_block_size:    Logical blocks covered by one region.
 * @subregion_block_size: Logical blocks covered by one subregion.
 *
 * Runtime state:
 * @regions:              Array of @region_count region descriptors (NULL if
 *                        HPB is disabled or not yet initialised).
 * @active_region_count:  Number of currently active regions.
 * @lru_list:             LRU list of active regions for eviction.
 * @lock:                 Protects @active_region_count and @lru_list.
 *
 * Async work:
 * @map_req_list:         Pending mapping-update requests from device.
 * @map_req_lock:         Protects @map_req_list.
 * @map_work:             Worker that processes @map_req_list.
 *
 * Statistics:
 * @stat_hpb_reads:       Total HPB READ commands issued.
 * @stat_hpb_hits:        HPB READ hits (valid PPN found).
 * @stat_hpb_misses:      HPB READ misses (PPN zero or region inactive).
 * @stat_write_invals:    Write-triggered cache invalidations.
 * @stat_region_activ:    Total region activations.
 * @stat_region_deactiv:  Total region deactivations.
 */
struct ufshpb_lu {
	struct ufs_hba		*hba;
	int			 lun;

	/* ---- Geometry from device descriptors ---- */
	u16			 hpb_ver;
	u16			 region_count;
	u16			 subregion_count;
	u16			 max_active_regions;
	u32			 region_block_size;   /* blocks per region */
	u32			 subregion_block_size; /* blocks per subregion */

	/* ---- Runtime region table ---- */
	struct ufshpb_region	*regions;	/* array [region_count] */
	u16			 active_region_count;
	struct list_head	 lru_list;	/* active regions, LRU order */
	spinlock_t		 lock;

	/* ---- Async mapping-update work ---- */
	struct list_head	 map_req_list;
	spinlock_t		 map_req_lock;
	struct work_struct	 map_work;

	/* ---- Statistics ---- */
	u64			 stat_hpb_reads;
	u64			 stat_hpb_hits;
	u64			 stat_hpb_misses;
	u64			 stat_write_invals;
	u64			 stat_region_activ;
	u64			 stat_region_deactiv;
};

/* ========================================================================
 * Mapping-Update Request
 *
 * Queued when the device asks the host to update/activate/deactivate a
 * region.  Posted from interrupt context onto ufshpb_lu.map_req_list and
 * processed by ufshpb_map_work().
 *
 * From storufs.sys:
 *   "UfsHPBMappingUpdateEnqueue - region: %d, subregion: %d, status %x"
 * ======================================================================== */

/**
 * enum ufshpb_map_req_type - type of mapping-update request
 * @UFSHPB_MAP_REQ_ACTIVATE:   Device requests region activation.
 * @UFSHPB_MAP_REQ_DEACTIVATE: Device requests region deactivation.
 * @UFSHPB_MAP_REQ_UPDATE:     Device provides fresh PPN data for a subregion.
 */
enum ufshpb_map_req_type {
	UFSHPB_MAP_REQ_ACTIVATE	  = 0,
	UFSHPB_MAP_REQ_DEACTIVATE = 1,
	UFSHPB_MAP_REQ_UPDATE	  = 2,
};

/**
 * struct ufshpb_map_req - pending mapping-update request
 * @list:         Node in ufshpb_lu.map_req_list.
 * @type:         Kind of update (activate / deactivate / update).
 * @region_id:    Target region.
 * @subregion_id: Target subregion (only meaningful for UPDATE).
 * @ppn_buf:      Buffer containing new PPN entries (UPDATE only, kfreed after use).
 * @ppn_count:    Number of valid PPN entries in @ppn_buf.
 */
struct ufshpb_map_req {
	struct list_head	 list;
	enum ufshpb_map_req_type type;
	u8			 region_id;
	u8			 subregion_id;

	__le64			*ppn_buf;	/* NULL for activate/deactivate */
	u32			 ppn_count;
};

/* ========================================================================
 * HPB CDB Helpers
 *
 * HPB READ (10) CDB layout (JEDEC JESD220F Table 11-3):
 *   Byte  0: opcode (0xF8)
 *   Byte  1: RDPROTECT | DPO | FUA | RARC (same as READ(10))
 *   Byte 2-5: LBA (32-bit, big-endian)
 *   Byte 6-9: PPN (32 low-order bits; upper 32 bits in EHS for HPB 2.0 64-bit mode)
 *   Byte 10-11: Transfer length
 *   Byte 15: Control
 *
 * For HPB 2.0 the full 64-bit PPN is delivered in the Extra Header Segment
 * (EHS), 8 bytes starting at offset EHS_OFFSET_IN_RESPONSE (32).
 * ======================================================================== */

/**
 * ufshpb_set_hpb_read_cdb - Fill in an HPB READ(10) CDB
 * @cdb:   16-byte CDB buffer (already zeroed by caller).
 * @lba:   Starting logical block address.
 * @ppn:   64-bit physical page number from HPB cache.
 * @len:   Transfer length in logical blocks.
 *
 * Callers must ensure @ppn != 0 (see ufshpb_ppn_valid()) before calling.
 *
 * TODO: implement when ufshpb.c is fleshed out.
 */
static inline void ufshpb_set_hpb_read_cdb(u8 *cdb, u64 lba, u64 ppn, u16 len)
{
	/*
	 * TODO: Build the HPB READ(10) CDB.
	 *
	 * cdb[0]    = HPB_READ_OPCODE;           // 0xF8
	 * cdb[2..5] = cpu_to_be32(lba);
	 * cdb[6..9] = cpu_to_be32(lower_32_bits(ppn));
	 * cdb[10]   = (len >> 8) & 0xff;
	 * cdb[11]   = len & 0xff;
	 * // Upper 32 bits of PPN go into EHS (HPB 2.0, 64-bit mode)
	 */
	(void)cdb; (void)lba; (void)ppn; (void)len;
}

/**
 * ufshpb_ppn_valid - Check whether a PPN table entry is valid
 * @ppn: The PPN value (little-endian, as stored in ufshpb_ppn_table.ppn[]).
 *
 * A zero PPN means the entry has not yet been populated by the device.
 * From storufs.sys: "PPN entry == 0" is an explicit error path.
 *
 * Returns: true if the PPN is non-zero and may be used in an HPB READ.
 */
static inline bool ufshpb_ppn_valid(__le64 ppn)
{
	return ppn != 0;
}

/* ========================================================================
 * HPB Capability Flag (for ufshcd_caps in ufshcd.h)
 *
 * NOTE: This bit is not yet wired into enum ufshcd_caps.  It is defined
 * here so that ufshpb.c and any host driver can reference a single
 * canonical name while the patch set evolves.
 *
 * Suggested placement: after UFSHCD_CAP_WB_WITH_CLK_SCALING (1 << 12).
 * ======================================================================== */

/**
 * UFSHCD_CAP_HPB_EN - enable HPB if the device supports it
 *
 * When set the core driver will call ufshpb_init() during device probe
 * and will attempt to issue HPB READ commands for eligible I/Os.
 *
 * TODO: add to enum ufshcd_caps in include/ufs/ufshcd.h once the
 * implementation is complete enough to merge.
 */
#define UFSHCD_CAP_HPB_EN		BIT(13)

/* ========================================================================
 * Function Prototypes
 * Implemented in drivers/ufs/core/ufshpb.c
 * ======================================================================== */

#ifdef CONFIG_SCSI_UFS_HPB

/**
 * ufshpb_init - Initialise HPB for a newly probed UFS LU
 * @hba: Host controller.
 * @lun: SCSI LUN index.
 *
 * Reads HPB geometry descriptors from the device, allocates the region
 * table, and starts the mapping-update workqueue.
 *
 * Returns 0 on success, negative errno on failure.
 */
int ufshpb_init(struct ufs_hba *hba, int lun);

/**
 * ufshpb_exit - Tear down HPB for a LU
 * @hba: Host controller.
 * @lun: SCSI LUN index.
 *
 * Cancels pending work, frees all region/subregion/PPN table memory.
 */
void ufshpb_exit(struct ufs_hba *hba, int lun);

/**
 * ufshpb_prep_fn - Intercept SCSI READ commands for HPB acceleration
 * @hba:  Host controller.
 * @cmd:  SCSI command being prepared.
 *
 * If the command is a READ targeting an active HPB region with a valid
 * cached PPN, this function rewrites the CDB to use HPB_READ_OPCODE and
 * embeds the PPN.
 *
 * Called from ufshcd_queuecommand() just before the UPIU is built.
 *
 * Returns 0 if the command was left unmodified, 1 if converted to HPB READ.
 */
int ufshpb_prep_fn(struct ufs_hba *hba, struct scsi_cmnd *cmd);

/**
 * ufshpb_rsp_upiu - Process HPB hints in a completed UPIU response
 * @hba:  Host controller.
 * @lun:  SCSI LUN index of the completed command.
 * @rsp:  Pointer to the RESPONSE UPIU (16 + data bytes).
 * @rsp_len: Length of the response buffer.
 *
 * Inspects the UPIU response for HPB region-activation or mapping-update
 * hints and enqueues corresponding ufshpb_map_req entries.
 *
 * Called from the transfer completion path (interrupt context).
 */
void ufshpb_rsp_upiu(struct ufs_hba *hba, int lun,
		     const void *rsp, size_t rsp_len);

/**
 * ufshpb_invalidate_range - Invalidate HPB mappings covering a write
 * @hba:      Host controller.
 * @lun:      SCSI LUN index.
 * @lba:      Starting LBA of the write.
 * @lba_count: Number of blocks written.
 *
 * Marks the affected subregion PPN entries as zero so subsequent reads
 * fall back to standard (non-HPB) I/O until the device resends mapping data.
 *
 * From storufs.sys:
 *   "Failed to HPB read, range invalidated by write - LBA: 0x%llx"
 *
 * Called from the WRITE command completion path.
 */
void ufshpb_invalidate_range(struct ufs_hba *hba, int lun,
			     u64 lba, u32 lba_count);

/**
 * ufshpb_get_lu - Retrieve the HPB context for a LUN (may return NULL)
 * @hba: Host controller.
 * @lun: SCSI LUN index.
 */
struct ufshpb_lu *ufshpb_get_lu(struct ufs_hba *hba, int lun);

#else /* !CONFIG_SCSI_UFS_HPB */

static inline int ufshpb_init(struct ufs_hba *hba, int lun)
{
	return 0;
}

static inline void ufshpb_exit(struct ufs_hba *hba, int lun) {}

static inline int ufshpb_prep_fn(struct ufs_hba *hba, struct scsi_cmnd *cmd)
{
	return 0;
}

static inline void ufshpb_rsp_upiu(struct ufs_hba *hba, int lun,
				   const void *rsp, size_t rsp_len) {}

static inline void ufshpb_invalidate_range(struct ufs_hba *hba, int lun,
					   u64 lba, u32 lba_count) {}

static inline struct ufshpb_lu *ufshpb_get_lu(struct ufs_hba *hba, int lun)
{
	return NULL;
}

#endif /* CONFIG_SCSI_UFS_HPB */

#endif /* _UFSHPB_H */
