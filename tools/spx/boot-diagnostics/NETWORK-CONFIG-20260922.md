# SPX IPv6 MARK configuration follow-up — 2026-09-22

## 2026-10-05 implementation

BX boot `85aa4bf6-2169-41d5-9d62-ed797b570132` repeats this exact failure on
`7.3.0-rc2-spx-mainline-20261004bg+`: the read-only rule check exits2 and
Tailscale reports the MARK router error. Commit `0bc334d2aded` applies the
single option below to the functional fragment. Incremental Image/modules
build passes with the fixed release; only `IP6_NF_IPTABLES: n -> m` changes
effectively in Kconfig. The affected configured modules are xt_mark/xt_connmark.
Legacy tables stay disabled. **BY runtime verification passes**, boot
`f23d0acb-8e26-49af-b888-5769a13b7a04`, same fixed release: normal Tailscale
startup installs the IPv6 rule, all three intended chains are present, Health
is empty, and three ICMPv6 packets through tailscale0 to a configured peer
return without loss. [Actual BY result](RESULT-20261005by.md).

BX's firewall held xt_mark in use, so its active modules/rules/backend were
preserved and BY was installed from recovery. The backend remains nf_tables;
no live host rule or policy was changed manually for a passing test.
Use current fixed-build/trial rules; historical manifests/distinct-release
instructions below are superseded by AGENTS.md.

## Original investigation

Trial F's Tailscale router configuration fails because its kernel omits the
IPv6 MARK target. The smallest proposed configuration correction is
`CONFIG_IP6_NF_IPTABLES=m`, followed by rebuilding and deploying the matching
kernel/module set in a separate trial. This review changes only this document.
No configuration, kernel source, loaded module, firewall rule or service was
changed, and the proposed correction has not been built or tested.

Keep this separate from G's proposed QRTR rollback. First collect G's result;
then hold the selected QRTR baseline, audio stage, DTB, services and other
configuration fixed for a later network trial.

## Evidence and scope

F is boot `9ed25de5-fecb-499d-8ef6-c4f4ca29d08c`, release
`7.3.0-rc2-spx-mainline-20260922f+`. Its journal records:

| Monotonic seconds | Tailscaled observation |
| --- | --- |
| 30.029119 | Selects iptables mode, reporting IPv6 filtering and NAT available. |
| 87.630667 | Router configuration fails when adding `-i tailscale0 -j MARK --set-mark 0x40000/0xff0000` to `v6/filter/ts-forward`. |
| 87.630667 | `ip6tables v1.8.13 (nf_tables)` reports `Extension MARK revision 0 not supported, missing kernel module?`, followed by a bad-value/range error. |
| 87.657730 | Router health reports that same failure. |
| 87.658379 | Tailscaled nevertheless transitions from Starting to Running. |

The hexadecimal mark and mask fit in 32 bits. The misleading range message
does not establish an invalid rule value. The relevant kernel implementation
registers MARK revision 2; an unsupported-extension diagnostic mentioning
revision 0 is not a reason to force an older target revision.

Read-only inspection confirms that `/usr/bin/ip6tables` resolves to
`xtables-nft-multi` and that `xt_mark`, `nft_compat` and `nf_tables` are loaded.
Being loaded does not establish IPv6 target registration. Likewise, Running
does not establish that Tailscale installed its complete router rules.

F's archived embedded configuration is:

```
/var/lib/spx-boot-diagnostics/attempts/20260922f/build/config-extracted
SHA-256: 8458a3281a9f56e6befa17a2b04ff463f28cb777577d5b5792d71702c42411b8
```

| Relevant option | F | Sibling known-good 6.18 `.config` |
| --- | --- | --- |
| `CONFIG_IP6_NF_IPTABLES` | unset | `m` |
| `CONFIG_IP6_NF_IPTABLES_LEGACY` | unset | `m` |
| `CONFIG_NETFILTER_XT_MARK` | `m` | `m` |
| `CONFIG_NETFILTER_XT_CONNMARK` | `m` | `m` |
| `CONFIG_NFT_COMPAT` | `m` | `m` |
| `CONFIG_NF_TABLES_IPV6` | `y` | `y` |

The sibling config is a comparison point, not an artifact identity check of
the installed recovery kernel. F's config comes from its archived build.

This failure concerns IPv6 firewall setup. It does **not** establish the cause
of Happy's startup TCP delay on its IPv4 path, the modem's 40-second fatal
errors, or delayed Wi-Fi availability. Those observations need separate
evidence and experiments.

## Source explanation and minimum change

[xt_mark.c:42](../../../net/netfilter/xt_mark.c#L42) registers the IPv4 MARK
target unconditionally. Its IPv6 registration at
[line 61](../../../net/netfilter/xt_mark.c#L61) is inside
`#if IS_ENABLED(CONFIG_IP6_NF_IPTABLES)`. F's unset option therefore excludes
the IPv6 target even though `xt_mark.ko` loads. Its `ip6t_MARK` module alias
is unconditional, so inspecting that alias is also insufficient evidence.

[Kconfig:759](../../../net/netfilter/Kconfig#L759) makes
`CONFIG_NETFILTER_XT_MARK` the combined MARK target and mark match option.
F already enables it. `CONFIG_NETFILTER_XT_TARGET_MARK` and
`CONFIG_NETFILTER_XT_MATCH_MARK` are compatibility selectors of that same
option, not additional implementations required for this correction.

The proposed functional config difference is:

```diff
-# CONFIG_IP6_NF_IPTABLES is not set
+CONFIG_IP6_NF_IPTABLES=m
```

[IPv6 Kconfig:80](../../../net/ipv6/netfilter/Kconfig#L80) requires INET and
IPV6 within the NETFILTER menu and selects NETFILTER_XTABLES. F already has
all four enabled, plus modules and the nftables compatibility infrastructure.
`IS_ENABLED()` accepts either `m` or `y`; `m` matches the sibling config and
is sufficient for the target registration.

In this source tree, [Makefile:7](../../../net/ipv6/netfilter/Makefile#L7)
builds `ip6_tables.ko` from the separate `IP6_NF_IPTABLES_LEGACY` option.
The latter's [help text](../../../net/ipv6/netfilter/Kconfig#L10) explicitly
excludes a requirement for iptables-nft. Do not add legacy filter, mangle or
NAT tables merely to satisfy the observed nft-backed MARK failure. Inspect
the complete `olddefconfig` diff when preparing the future build: newly
visible options must not silently broaden the intended configuration change.

## Related compatibility checks

- [xt_connmark.c:181](../../../net/netfilter/xt_connmark.c#L181) uses the same
  guard for IPv6 CONNMARK target revisions 1 and 2. F already builds this
  module, so rebuilding with the proposed option also restores those target
  registrations. No observed F CONNMARK failure is claimed.
- [xt_mark.c:73](../../../net/netfilter/xt_mark.c#L73) registers the lowercase
  `mark` match with `NFPROTO_UNSPEC`. It does not have this IPv6 target guard.
  The connmark and conntrack matches likewise register for `NFPROTO_UNSPEC`.
- [xt_MASQUERADE.c:74](../../../net/netfilter/xt_MASQUERADE.c#L74) guards its
  IPv6 target with `CONFIG_IPV6`, already enabled in F. F also enables the
  combined MASQUERADE module and NF_NAT. The unset compatibility selector
  `IP6_NF_TARGET_MASQUERADE` is not independently missing target code.
- TCPMSS and addrtype also contain `IP6_NF_IPTABLES` guards, but their modules
  are not enabled in F. There is no evidence here to add them. Preserve the
  narrow experiment and investigate any subsequent distinct rule failure.

Rebuild and stage all affected configured modules, including `xt_mark` and
`xt_connmark`, under a distinct release with the matching kernel, config and
initramfs. Adding a new `ip6_tables.ko` alone or reloading F's existing
`xt_mark.ko` cannot add code compiled out of that module. Do not unload or
replace firewall modules in the active diagnostic session.

## Proposed verification, not yet executed

1. Archive the source/config and artifacts, compare the complete config diff
   against the selected baseline, verify embedded config and staged module
   hashes, and run staged depmod. Preserve the usual one-shot boot and
   known-good recovery records. Keep G's QRTR experiment separate.
2. After the new boot, verify its exact release/config and loaded module
   provenance. Confirm the existing `ip6tables` command still uses nf_tables;
   changing its backend would confound this test.
3. Inspect normal tailscaled startup and router health. Require absence of
   the IPv6 MARK failure and successful installation of the `ts-forward`
   MARK rule. A read-only check of that exact rule is:

   ```sh
   sudo ip6tables -w -t filter -C ts-forward -i tailscale0 \
       -j MARK --set-mark 0x40000/0xff0000
   ```

   Also inspect the remaining intended Tailscale chains and any new router
   errors; passing one rule does not establish complete firewall setup.
4. If normal startup does not exercise the rule, test equivalent MARK rule
   insertion in an unconnected chain inside a disposable network namespace
   on the new kernel. That avoids modifying the host's active rules, although
   module autoload is still global. No packet generation is needed. Record
   the command, return status and resulting rule before deleting the namespace.
5. Preserve kernel and tailscaled logs plus the rule checks and compare the
   retained baseline's graphics, Wi-Fi, ADSP and input observations. Actual
   IPv6 tunnel traffic, subnet routing and exit-node operation need their own
   suitable peers and routes; do not infer those from successful rule insertion.

No runtime verification above has been performed by this review.
