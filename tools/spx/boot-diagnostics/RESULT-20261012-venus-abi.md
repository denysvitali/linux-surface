boxes closed: 3 of 47; newly closed: none.

Venus fault analysis — offline, 2026-10-12

Conclusion
Mixing the installed decoder/encoder with the candidate core is ABI-unsafe.
ELF evidence predicts BOTH recorded symptoms, in order: uninitialized decoder
work at close, then NULL m2m context dereference at 0x20. This is a strong,
specific hypothesis, not proof that these exact binaries were loaded on boot
2530c4ce. Do not retry a reload based on this report alone.

Evidence and offsets (decimal, relative to struct venus_inst)
Installed tree: /lib/modules/7.3.0-rc2-spx-mainline-20261004bg+/kernel/drivers/media/platform/qcom/venus/
Candidate output: /var/tmp/spx-mainline-trial-20261004bg/work-build/drivers/media/platform/qcom/venus/
Native sudo -n objdump -dr --disassemble=<function> inspected regular ELF files.
Installed venus-dec.ko vdec_open allocates 3280 bytes; sets session_type=2
at 2888; stores m2m_dev=2792, m2m_ctx=2800; fh=680. Installed venus-enc.ko
venc_open also allocates 3280, sets type=1 at 2888, and stores dev/context
at 2792/2800. Installed core helper tests type at 2888, initializes work
at 152 and its func at 176. Installed vdec_close derives inst from fh-680,
then passes inst+152 to cancel_work_sync (0x2a8 - 0x210 = 0x98).
Installed core close reads context at 2800, device at 2792.
Surviving candidate helpers.o tests type at 2896; initializes work at 160,
func at 184. Candidate core.o close reads context at 2808, device at 2800,
fh at 688 and ctrl handler at 200 rather than 192. Candidate source inserts
u32 session_id at 48 before clock_data, shifting later aligned fields by 8.
Thus this is a demonstrated ABI difference, not merely an old timestamp.

Conditional reconstruction of the fault
1. core probe creates platform children via of_platform_populate; decoder/
encoder OF aliases in installed .modinfo permit userspace autoload. Installed
60-persistent-v4l.rules invokes v4l_id for video4linux events. The saved journal
names v4l_id as the faulting process. Automatic open/QUERYCAP/close is therefore
consistent with the trigger; the full syscall sequence is not retained.
2. vdec_open calls venus_helper_init_instance BEFORE controls/m2m/session
creation. With an old decoder and new core, helper reads zero at 2896 instead
of type=2 at 2888 and returns without initializing work. No STREAMON is needed.
3. hfi_session_create initializes state/completion/ops and registers the
instance on the core list. It does NOT initialize delayed work or run a
firmware session-init. Candidate bounded session IDs are allocated here;
hfi_session_destroy only removes the list node/decrements the count under
core->lock. Its lifetime cleanup occurs after m2m release in common close.
4. vdec_close calls vdec_pm_get, then cancel_work_sync(inst+152).
kernel/workqueue.c:4409 is exactly WARN_ON(!work->func). Under the mixed ABI,
work remains zero, explaining that warning without blaming firmware.
5. cancel returns; venus_close_common synchronizes IRQ then reads the new
context slot at 2808, where the old module has an initially zero mutex field.
It calls v4l2_m2m_ctx_release(NULL). Installed v4l2-mem2mem.ko calls cancel_job,
whose instruction at 0x1340 is ldr x20,[x19,#32] with x19=context: NULL+32=0x20.
This matches the recorded NULL address exactly. There is no retained PC to
confirm that this was the actual faulting instruction. Encoder close also
misreads the context, but does not cancel decoder delayed work.
Matched current source initializes decoder work in open before success and
unconditionally cancels it on close. No clear matched-ABI initialization bug
was found in this auto-open/close path. Adding a NULL work guard would hide
one symptom and leave the ABI corruption intact.

Smallest fix proposal (NOT executed)
Operational: keep all three Venus modules from ONE matching build. A core-only
insmod is insufficient: child autoload and v4l_id can race before explicit
candidate dec/enc insertion. For a future authorized coordinator trial, first
recover/rebuild valid outputs, then arrange that ordinary autoload resolves
matching candidate dec/enc (and core), or temporarily suppress only Venus
child autoload while loading the three absolute paths. Do not suppress all
udev processing or change unrelated media drivers. Restore normal policy
when the coherent stack is ready. No experiment until the repository/output
corruption is addressed. Do not blanket-blacklist or reload now.
Optional smallest code alternative, only if core-only replacement is required:
move session_id to the END of venus_inst rather than inserting it before
clock_data. Then prove all shared old field offsets unchanged and ensure old
allocations have sufficient capacity. This is not an established supported
ABI: old callers allocate 3280, so appending still cannot safely assume room.
Prefer coherent rebuilt modules; no speculative guard or lifetime rewrite.

Exact proof gaps / limits
- All THREE final work-build .ko files and hfi.o/vdec.o/venc.o are now zero
bytes. Fresh linked core/dec/enc ELF cannot be re-inspected. The earlier
matching-ABI statement in the result describes files before corruption;
surviving helpers.o/core.o prove candidate layout only, not final loaded ELF.
- The fault journal lists venus_dec/venus_enc (no O) and venus_core(O), and
records core-only insmod. Installed dec/enc have intree=Y and old offsets;
this supports installed autoload but does not prove its exact path. No loaded
module build IDs/checksums, dec/enc load commands or fault registers survive.
- Full WARNING stack and NULL fault PC/LR are absent. Another caller of
__flush_work or another NULL+0x20 site cannot be excluded.
- HFI read_ret=-61/version failure is separate startup evidence; no direct
link to this host ABI fault is proven. Bounded SID firmware behavior and
useful decoding remain unvalidated. Reset/panic mechanism remains unproven.

Scope
Read AGENTS/TODO/checklist/latest progress/result/reset report and regular
source/ELF/rule files only. No live device, /proc, /sys, logs, builds, module
operations, reboot or Git edits. No assumptions promoted to acceptance.
No constants changed. Only this requested report was written.
