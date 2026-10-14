#!/usr/bin/env python3
"""Bounded SensorProxy probe; stdout is one controlled JSON object, no raw data."""
import json
import os
import math
import sys
import time

NAME = "net.hadess.SensorProxy"
PATH = "/net/hadess/SensorProxy"
PROPS = "org.freedesktop.DBus.Properties"


def main():
    compass_mode = sys.argv[1:] == ["--compass"]
    sensor_path = PATH + "/Compass" if compass_mode else PATH
    sensor_interface = NAME + ".Compass" if compass_mode else NAME
    capability_name = "HasCompass" if compass_mode else "HasAccelerometer"
    value_name = "CompassHeading" if compass_mode else "AccelerometerOrientation"
    claim_name = "ClaimCompass" if compass_mode else "ClaimAccelerometer"
    release_name = "ReleaseCompass" if compass_mode else "ReleaseAccelerometer"
    result = dict(status="error", reason="helper_error", has_compass=None,
                  orientation_before=None, orientation_after=None, signal=False,
                  claimed=False, released=False, window_complete=False,
                  compass_signal_count=0, compass_min=None, compass_max=None)
    try:
        from gi.repository import Gio, GLib
    except (ImportError, ValueError):
        result.update(status="blocked", reason="unavailable")
        print(json.dumps(result), flush=True)
        return

    loop = GLib.MainLoop()
    connection = None
    subscription = 0
    owner = None
    claim_attempted = False
    claim_time = None
    observation_end = None
    observed_defined = False
    cancellable = Gio.Cancellable()
    generation = 0
    finished = False
    cleaning = False
    deadline = time.monotonic() + 9.5

    class Abort(Exception):
        pass

    def call(destination, path, interface, method, parameters, timeout=800):
        return (destination, path, interface, method, parameters, timeout)

    def prop(path, interface, name):
        return call(owner, path, PROPS, "Get", GLib.Variant("(ss)", (interface, name)))

    def defined(value):
        return value not in ("", "undefined")

    def signal(conn, sender, path, interface, name, parameters, data):
        nonlocal observed_defined
        iface, changed, invalidated = parameters.unpack()
        # The subscription precedes the claim; exclude signals seen before it.
        if cleaning or claim_time is None or iface != sensor_interface or (
                observation_end is not None and time.monotonic() > observation_end):
            return
        if compass_mode:
            if value_name in changed:
                value = changed.get(value_name)
                if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value < 360:
                    result["signal"] = True
                    result["compass_signal_count"] += 1
                    result["compass_min"] = value if result["compass_min"] is None else min(result["compass_min"], value)
                    result["compass_max"] = value if result["compass_max"] is None else max(result["compass_max"], value)
            return
        if "AccelerometerOrientation" in changed or "AccelerometerTilt" in changed:
            result["signal"] = True
        value = changed.get(value_name)
        if isinstance(value, str) and defined(value):
            observed_defined = True
            result["orientation_after"] = value

    def routine():
        nonlocal owner, subscription, claim_attempted, claim_time, observed_defined, cleaning, observation_end
        try:
            owned = yield call("org.freedesktop.DBus", "/org/freedesktop/DBus",
                               "org.freedesktop.DBus", "NameHasOwner",
                               GLib.Variant("(s)", (NAME,)))
            if not owned[0]:
                result.update(status="blocked", reason="no_service")
                return
            # Pin the existing owner: service replacement cannot supply evidence.
            owner = (yield call("org.freedesktop.DBus", "/org/freedesktop/DBus",
                                "org.freedesktop.DBus", "GetNameOwner",
                                GLib.Variant("(s)", (NAME,))))[0]
            try:
                compass = (yield prop(PATH + "/Compass", NAME + ".Compass", "HasCompass"))[0]
                if isinstance(compass, bool):
                    result["has_compass"] = compass
            except GLib.Error:
                pass  # Missing compass property must not fail motion.
            has_accel = (yield prop(sensor_path, sensor_interface, capability_name))[0]
            if compass_mode and isinstance(has_accel, bool):
                result["has_compass"] = has_accel
            if has_accel is False:
                result.update(status="blocked", reason="no_compass" if compass_mode else "no_accelerometer")
                return
            if has_accel is not True:
                raise ValueError("Invalid capability type")
            before = (yield prop(sensor_path, sensor_interface, value_name))[0]
            if compass_mode:
                if isinstance(before, bool) or not isinstance(before, (int, float)):
                    raise ValueError("Invalid heading type")
                result["compass_before"] = before
            elif not isinstance(before, str):
                raise ValueError("Invalid orientation type")
            result["orientation_before"] = before
            subscription = connection.signal_subscribe(
                owner, PROPS, "PropertiesChanged", sensor_path, sensor_interface,
                Gio.DBusSignalFlags.NONE, signal, None)
            claim_attempted = True  # Also release after a lost/refused reply.
            if not compass_mode:
                claim_time = time.monotonic()
            try:
                yield call(owner, sensor_path, sensor_interface, claim_name, None)
            except GLib.Error as error:
                # Only a remote refusal is a prerequisite; transport faults are errors.
                if Gio.DBusError.is_remote_error(error):
                    remote = Gio.DBusError.get_remote_error(error) or ""
                    result.update(status="blocked", reason="access_denied" if remote.endswith("AccessDenied") else "claim_refused")
                    return
                raise
            if compass_mode:
                claim_time = time.monotonic()
            result["claimed"] = True
            window_end = time.monotonic() + 6.0
            observation_end = window_end
            after = (yield prop(sensor_path, sensor_interface, value_name))[0]
            if compass_mode:
                if isinstance(after, bool) or not isinstance(after, (int, float)):
                    raise ValueError("Invalid heading type")
                result["compass_after"] = after
            elif not isinstance(after, str):
                raise ValueError("Invalid orientation type")
            result["orientation_after"] = after
            observed_defined = observed_defined or defined(after)
            if not result["signal"] and not (not defined(before) and observed_defined):
                yield max(1, int((window_end - time.monotonic()) * 1000) + 1)
                after = (yield prop(sensor_path, sensor_interface, value_name))[0]
                if compass_mode:
                    if isinstance(after, bool) or not isinstance(after, (int, float)):
                        raise ValueError("Invalid heading type")
                    result["compass_after"] = after
                elif not isinstance(after, str):
                    raise ValueError("Invalid orientation type")
                result["orientation_after"] = after
                observed_defined = observed_defined or defined(after)
                result["window_complete"] = True
            if compass_mode:
                fresh = result["signal"]
                unchanged_or_invalid = (not math.isfinite(after) or not math.isfinite(before) or after == before)
                if fresh:
                    result.update(status="pass", reason="signal")
                elif unchanged_or_invalid:
                    result.update(status="fail", reason="no_heading")
                else:
                    result.update(status="error", reason="helper_error")
            elif result["signal"]:
                result.update(status="pass", reason="signal")
            elif not defined(before) and observed_defined:
                result.update(status="pass", reason="transition")
            elif not observed_defined:
                result.update(status="fail", reason="undefined")
            else:
                result.update(status="blocked", reason="stationary")
        except Abort:
            result.update(status="error", reason="timeout")
        except Exception:
            result.update(status="error", reason="helper_error")
        finally:
            cleaning = True
            if claim_attempted:
                try:
                    yield call(owner, sensor_path, sensor_interface, release_name, None, 1000)
                    result["released"] = True
                except Exception:
                    result.update(status="error", reason="release_error")
            if subscription:
                connection.signal_unsubscribe(subscription)

    task = routine()

    def close():
        nonlocal finished
        finished = True
        if connection is None:
            loop.quit()
            return

        def closed(conn, reply):
            try:
                conn.close_finish(reply)
            except Exception:
                result.update(status="error", reason="close_error")
            loop.quit()
        try:
            connection.close(None, closed)
        except Exception:
            result.update(status="error", reason="close_error")
            loop.quit()

    def advance(value=None, error=None):
        nonlocal generation
        generation += 1
        ticket = generation
        try:
            request = task.throw(error) if error else task.send(value)
        except StopIteration:
            close()
            return
        except Exception:
            result.update(status="error", reason="helper_error")
            close()
            return
        if isinstance(request, int):
            def wake():
                if ticket == generation:
                    advance()
                return GLib.SOURCE_REMOVE
            GLib.timeout_add(request, wake)
            return
        destination, path, interface, method, params, timeout = request

        def replied(conn, reply):
            if ticket != generation:
                return
            try:
                value = conn.call_finish(reply).unpack()
            except Exception as error:
                advance(error=error)
            else:
                advance(value=value)
        try:
            connection.call(destination, path, interface, method, params, None,
                            Gio.DBusCallFlags.NO_AUTO_START, timeout,
                            None if method == release_name else cancellable,
                            replied)
        except Exception as error:
            advance(error=error)

    def connected(source, reply):
        nonlocal connection
        try:
            connection = Gio.DBusConnection.new_for_address_finish(reply)
            connection.set_exit_on_close(False)
            if finished:
                close()
            else:
                advance()
        except Exception:
            result.update(status="blocked", reason="bus_unavailable")
            close()

    def work_timeout():
        if not finished and not cleaning:
            cancellable.cancel()
            if connection is not None:
                advance(error=Abort())  # Enters the generator's finally release.
            else:
                result.update(status="error", reason="timeout")
                close()
        return GLib.SOURCE_REMOVE

    def hard_timeout():
        # Work has already been cancelled and release attempted by 9.5 s.
        result.update(status="error", reason="timeout")
        for key in ("compass_before", "compass_after", "compass_min", "compass_max"):
            if isinstance(result.get(key), float) and not math.isfinite(result[key]):
                result[key] = None
        print(json.dumps(result, allow_nan=False), flush=True)
        os._exit(0)

    GLib.timeout_add(11500, hard_timeout)
    GLib.timeout_add(max(1, int((deadline - time.monotonic()) * 1000)), work_timeout)
    try:
        address = Gio.dbus_address_get_for_bus_sync(Gio.BusType.SYSTEM, None)
        Gio.DBusConnection.new_for_address(
            address, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT |
            Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
            None, cancellable, connected)
        loop.run()
    except Exception:
        result.update(status="blocked", reason="bus_unavailable")
    for key in ("compass_before", "compass_after", "compass_min", "compass_max"):
        if isinstance(result.get(key), float) and not math.isfinite(result[key]):
            result[key] = None
    print(json.dumps(result, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
