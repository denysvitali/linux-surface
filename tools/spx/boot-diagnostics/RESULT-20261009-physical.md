boxes closed: 3 of 47; IDs closed since the last report: none.

# Hands-on session, 2026-10-09

Mainline boot `1dd03623-3859-434e-af24-69426f77e99f`, kernel
`7.3.0-rc2-spx-mainline-20261004bg+`, attempt FH (`20261009fh`).
Existing candidate Image/modules and FG camera DTB; known-good stays the
persistent default. No sound, camera/microphone capture or battery tests.

| Step | Box | User observation | Captured evidence | Verdict |
|---|---|---|---|---|
| Typing, Shift, Backspace | I04 | Works | Keyboard event categories delivered to libinput | Observed; full acceptance remains open |
| Pointer, left/right click, two-finger scroll | I05 | Works | Touchpad motion/button/swipe categories; no scroll category in recorder | User confirms; lifecycle, other gestures and palm rejection remain open |
| Cover detach/reattach, repeat typing/touchpad | I04, I05 | Everything works as expected | Devices removed at uptime 874.5–874.7s, returned at 884.4–884.5s; fresh input followed | Hotplug observed; full acceptance remains open |
| Ctrl+A, Alt+Tab, fitted Caps/Fn indicators, backlight and brightness/volume/mute shortcuts | I04 | Works | Keyboard/consumer events; indicators and effects confirmed visually | These controls observed; resume remains open |
| Three-finger desktop gestures | I05 | 3 fingers works | Fresh touchpad swipe events, including uptime 1941.9s | Observed; palm rejection and resume remain open |
| Pen in desktop and input debug window | I03 | Desktop seems to work; debug trace location wrong, about 0.5 fps | Pen tip/axis/proximity/button categories are recorded | Debug GUI closed; pressure/tilt and full pen acceptance remain open |
| FI pen position and GUI redraw | I03 | Somewhat faster; GUI trail displaced, desktop cursor follows the pen | Real pen axis/proximity/tip/button categories; GUI reports 23ms processing lag and overdue timers | Desktop position observed; relative diagnostic trail does not validate mapping; pressure/tilt and lifecycle remain open |
| FI pen pressure | I03 | Pressure bar works | Physical light/firm action requested; real tablet tip/axis delivery recorded | Pressure response observed; full I03 remains open |

Input evidence: `/var/lib/spx-boot-diagnostics/functional/20261009fh/physical/`.
Only event categories were retained; no keycodes, typed text or coordinates.
Initial recorder overlap makes exact initial event counts unsuitable for
scoring; event delivery and the user's observation establish this typing step.

Remaining I04: unexercised media actions and resume. I05 still needs palm
rejection and resume; the other physical steps await the user's actions.

Session paused for the GTK fix, then FH returned automatically after its
bounded window. Known-good boot `2590efe3-cc73-4dd0-be35-143e67f9fa18`, kernel
`6.18.3-1-surface+`, verifies the return. Input recorder is stopped.

Pen diagnostic follow-up: the installed libinput 1.31.3 GUI links GTK4.
Its versioned source transforms the absolute marker to the window dimensions,
but deliberately starts the relative-motion trail at the window centre;
that trail is not a pen-position drawing. The saved PAM renderer setting now
reaches this GUI: a five-second known-good launch selected `GskGLRenderer`,
GPU OpenGL ES 3.2; log: `physical/debug-gui-renderer.log`. No input recorded or
synthetic events sent. This establishes the current launch setting, not the
cause of the earlier 0.5 fps or smoothness on mainline. Next: a physical retest
using the absolute marker, followed by fitted pen capabilities and resume.

FI continuation: mainline boot `29923cc8-d3dd-4fd6-8400-e73cfbe6b5ca`, same
kernel release; IPTSD active with zero restarts. User observes that the desktop
cursor follows the pen, the GUI is somewhat faster, and the pressure bar
works. Tilt and accessory identification requested next. Category-only input recording and GUI log in
`functional/20261009fi/physical/`. No camera/audio or battery test.

FI stopping point: pressure and desktop position observed. Tilt/model reply,
fitted buttons/eraser, palm rejection and resume pending; own GUI and category
recorders stopped. Mainline remains on its bounded automatic-return window.
