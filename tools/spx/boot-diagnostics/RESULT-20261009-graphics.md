boxes closed: 3 of 47; IDs closed since the last report: none.

# GTK window corruption: working OpenGL workaround

Boot `1dd03623-3859-434e-af24-69426f77e99f`, kernel
`7.3.0-rc2-spx-mainline-20261004bg+` (FH); GTK 4.22.4, Mesa 26.2.1,
GNOME/Mutter 50.4. No reboot, kernel change or MSM module reload.

**Observed:** the user's photo shows repeated strips and broken glyphs in
Text Editor while Console and the desktop remain clear. Text Editor PID 3364
has no `GSK_RENDERER` and loads `libvulkan_freedreno.so`; Console and GNOME
inherit `GSK_RENDERER=opengl`. That setting existed only in
`/etc/environment.d/99-gtk-renderer.conf`, which the `runuser` launch omitted.
The kernel journal contains no GPU reset or IOMMU fault; the GPU fault
counter is zero. Bounded GTK runs confirm GskVulkanRenderer versus
GskGLRenderer/OpenGL ES 3.2 on `/dev/dri/renderD128`.

**Changed:** extended the existing `GSK_RENDERER=opengl` setting to
`/etc/environment` for PAM launches. A fresh `sudo runuser` environment now
contains it. The user confirmed that the new OpenGL Text Editor window is
clear in response to the text/control/resize check. Original editor session
and saved drafts were backed up privately before restarting; draft contents
were checked across restart. The restored editor uses GskGLRenderer.

**Meaning:** the GTK Vulkan path is the failing path; hardware-accelerated
OpenGL is a visually verified workaround. This does not locate or fix the
underlying GTK/Turnip Vulkan defect. Existing D02 evidence covers GL/GLES,
not Vulkan. D01 still needs its full brightness/blank/wake acceptance.

**Next:** continue the pending hands-on session. Investigate Vulkan only if
the user requests that path; do not repeat successful OpenGL tests. Private
diagnostic logs and draft backups are in `/tmp/spx-gtk-graphics-20261009/`;
no draft contents are in this report. Shell denied screen capture, so no
automated screenshot or visual acceptance was claimed.
