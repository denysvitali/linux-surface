# FastRPC SDSP teardown: quiesced clients first

This WIP enables a controlled teardown only after the SensorsPD host and other
FastRPC clients have closed. It does not drain guessed DSP response references
or establish crash/restart safety.

Ownership states:

- Before sharing, the pool gets a heap-allocated `IORES_DESC_RESERVED` resource
  lease. `insert_resource()` can nest it beneath a containing System RAM resource;
  a plain `request_mem_region()` would conflict with busy System RAM. A reserved
  overlap check under the FastRPC heap mutex rejects an old lease, including one
  left by a previous module instance. Resource/name allocations are independent
  of module text and survive an SCM restoration failure.
- Successful sharing records SCM's returned owner mask. Removal disconnects
  RPCs, deregisters misc devices, reports users/pending contexts, depopulates
  context banks, and drops only the driver's channel reference.
- Users, RPC contexts and exported DMA buffers retain their lifetime references.
  Users pin module text beyond file close; exported DMA buffers retain the user.
  A private response workqueue drains before module exit returns. Missing DSP
  response references remain held, deliberately blocking unload and reprobe.
- Final channel release occurs after user/context DMA cleanup. It frees channel
  heap buffers, restores the whole pool to HLOS, removes the lease, releases the
  CMA association and retained device. Users also retain their context-bank device through map cleanup.
  Buffer/device references keep delayed DMA free valid; mask storage belongs to the device rather than the channel.
- Failed restoration retains the resource lease, channel/device and CMA
  association until reboot. Reprobe cannot assume the pool is HLOS-owned. This
  deliberately leaks bounded state instead of erasing ownership evidence.

Probe lifetime initialization and context-bank creation precede misc publication.
SCM availability/allocation checks and the SDSP ownership fence precede
reserved-memory attachment. A same-device retry cannot detach an old channel's
CMA association on its failure path. All later
probe failures run the same channel cleanup, including partial population and
partial misc registration.

Coordinator validation after booting the patched module:

1. Verify normal SensorsPD and sensor samples first. Stop proxy/clients and the
   retained host; do not repeatedly reattach the old host.
2. Remove only after client closure. Require `channel remove users=0 pending=0`
   and `SDSP heap restored to HLOS owners=0x8; final context drained`.
3. If pending contexts remain, removal/unload is blocked by retained references;
   do not force unload. If SCM restoration fails, require the ownership resource
   to remain in `/proc/iomem`; do not retry sharing that range.
4. Reload and require a new assignment log with owners `0x28` before samples.
   Missing-response drains, concurrent restart and repeated SensorsPD attach
   remain separate work.

Incremental build (coordinator only):

```sh
make -C /home/dvitali/Documents/git/linux-surface-next \
  O=/var/tmp/spx-mainline-trial-20261004bg/work-build \
  ARCH=arm64 LOCALVERSION=+ -j4 drivers/misc/fastrpc.ko
```

Do not unload the old live module to install this fix. Stage only the rebuilt
module into the fixed trial release, preserve the separate known-good release,
and boot the new code before exercising removal.
