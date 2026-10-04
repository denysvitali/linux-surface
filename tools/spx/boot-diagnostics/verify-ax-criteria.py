#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Check unchanged AR baseline and reject camera/identity/idle failures offline."""
import ast
import copy
import json
from pathlib import Path

from ax_camera_core import CCI, SENSOR, PROVIDER, RAILS, LED, assess, decode, trial_findings, complete_trial_findings

SRC = Path(__file__).resolve().parent


def expression(tree, name):
    return next(n.value for n in ast.walk(tree) if isinstance(n, ast.Assign) and
                any(isinstance(t, ast.Name) and t.id == name for t in n.targets))


def main():
    old = ast.parse((SRC / 'ar-finalize.py').read_text())
    new = ast.parse((SRC / 'ax-baseline.py').read_text())
    same = ('passed', 'native_path_passed', 'touch_diag_passed', 'healthy', 'power_path_passed',
            'pin_state_passed', 'pin2_diagnostic', 'topology_preserved', 'declared_names',
            'firmware_identity_match', 'identity_diag_passed', 'right_init')
    for name in same:
        assert ast.dump(expression(old, name)) == ast.dump(expression(new, name)), name
    exp = expression(new, 'passed')
    scope = {n.id: True for n in ast.walk(exp) if isinstance(n, ast.Name) and n.id != 'len'}
    scope.update(right_init=1, slim_devices=['a', 'b'], no_cards=False, force_start=0,
                 force_done=0, force_slaves=0, attached=1, wsa_mode='Y', wsa_init=1,
                 wsa_init_fail=0, wsa_status_fail=0, wsa_write_overflows=0,
                 wsa_read_underflows=0, taint='0')
    judge = compile(ast.Expression(exp), 'AX-baseline', 'eval')
    assert eval(judge, {}, scope)
    negatives = ({'cmd_diag_passed': False}, {'native_path_passed': False}, {'right_init': 0},
                 {'topology_preserved': False}, {'pin_state_passed': False}, {'touch': False},
                 {'taint': '1'}, {'graph': False}, {'wifi': False})
    for patch in negatives:
        assert not eval(judge, {}, scope | patch), patch
    trial = compile(ast.Expression(expression(new, 'passed_trial')), 'AX-trial', 'eval')
    for baseline in (True, False):
        for camera in (True, False):
            assert eval(trial, {}, {'passed': baseline, 'camera_findings': {
                'camera_trial_passed': camera}}) == (baseline and camera)
    records = json.loads(Path('/var/lib/spx-boot-diagnostics/attempts/20261002ap/camera-pmic-metadata-20261003/result.json').read_text())['reads']
    reference = decode(records)
    identity = {'boot_id': 'incoming-AX', 'release': 'reused-AR', 'taint': '0', 'cmdline': 'AX-command'}
    control = {'identity_before': dict(identity), 'identity_after': dict(identity),
               'cci': [{'of_node': CCI, 'driver': 'i2c-qcom-cci', 'assigned_clock_rate_hz': 37500000,
                        'power': {'runtime_status': 'suspended'}}],
               'sensors': [{'name': '8-0010', 'of_node': SENSOR, 'driver': 'ov13858',
                            'adapter_of_node': CCI + '/i2c-bus@0', 'power': {'runtime_status': 'suspended'}}],
               'providers': {name: {'name': name, 'state': 'disabled', 'num_users': '0',
                                   'provider_driver': 'qcom-spmi-regulator', 'provider_of_node': PROVIDER,
                                   **{key: str(voltage) for key in ('microvolts', 'min_microvolts', 'max_microvolts')}}
                             for name, voltage in RAILS.items()},
               'pmic_reads': records, 'camera_error_lines': [],
               'privacy_leds': [{'name': 'spx:rear:privacy', 'of_node': LED,
                   'provider_driver': 'leds-gpio', 'brightness': '0', 'max_brightness': '1',
                   'trigger_selected': 'none', 'phandle': 123, 'sensor_led_phandle': 123,
                   'sensor_led_names': ['privacy'], 'gpio_provider': '/soc@0/pinctrl@3100000',
                   'gpio_pin': 11, 'gpio_flags': 0}],
               'privacy_gpio_line': ' gpio11  : out low func0 2mA pull down',
               'front_privacy_pinmux_line': 'pin 25 (GPIO_25): UNCLAIMED'}
    assert assess(control, reference)['control_passed']
    mutations = []

    def case(fn):
        r = copy.deepcopy(control)
        fn(r)
        mutations.append(r)

    case(lambda r: r['identity_after'].update(boot_id='different'))
    case(lambda r: r['identity_before'].update(taint='1'))
    case(lambda r: r.update(failure='collector failed'))
    case(lambda r: r.update(cci=[]))
    case(lambda r: r['cci'].append(copy.deepcopy(r['cci'][0])))
    case(lambda r: r['cci'][0].update(driver=None))
    case(lambda r: r['cci'][0].update(assigned_clock_rate_hz=19200000))
    case(lambda r: r['cci'][0]['power'].update(runtime_status='active'))
    case(lambda r: r.update(sensors=[]))
    case(lambda r: r['sensors'].append(copy.deepcopy(r['sensors'][0])))
    case(lambda r: r['sensors'][0].update(driver=None))
    case(lambda r: r['sensors'][0].update(adapter_of_node='/other-controller'))
    case(lambda r: r['sensors'][0].update(name='8-0011'))
    case(lambda r: r['sensors'][0]['power'].update(runtime_status='active'))
    case(lambda r: r['providers']['spx-camera-dovdd'].update(num_users='1', state='enabled'))
    case(lambda r: r['providers']['spx-camera-avdd'].update(microvolts='2800000'))
    case(lambda r: r['providers']['spx-camera-dvdd'].update(provider_driver='reg-fixed-voltage'))
    case(lambda r: r['providers'].pop('spx-camera-dvdd'))
    case(lambda r: r['pmic_reads'].pop())
    case(lambda r: r['pmic_reads'][0].update(raw='4001: XX\n'))
    case(lambda r: r['camera_error_lines'].append('ov13858 failed to disable supplies'))
    inherited_cases = len(mutations)
    case(lambda r: r.update(privacy_leds=[]))
    case(lambda r: r['privacy_leds'].append(copy.deepcopy(r['privacy_leds'][0])))
    for key, value in [('of_node', '/wrong-led'), ('provider_driver', 'other'),
                       ('brightness', '1'), ('max_brightness', '255'),
                       ('trigger_selected', 'heartbeat'), ('sensor_led_phandle', 124),
                       ('phandle', None), ('sensor_led_names', ['activity']),
                       ('gpio_provider', '/different-gpio'), ('gpio_pin', 25), ('gpio_flags', 1)]:
        case(lambda r, k=key, v=value: r['privacy_leds'][0].update({k: v}))
    for line in (' gpio11 : in low func0 2mA pull down', ' gpio11 : out high func0 2mA pull down',
                 ' gpio11 : out low func1 2mA pull down'):
        case(lambda r, line=line: r.update(privacy_gpio_line=line))
    case(lambda r: r.update(front_privacy_pinmux_line='pin 25 (GPIO_25): CLAIMED'))
    case(lambda r: r['camera_error_lines'].append('camera-privacy-leds failed to probe'))
    privacy_cases = len(mutations) - inherited_cases
    assert inherited_cases == 21 and privacy_cases == 18
    for index, r in enumerate(mutations):
        assert not assess(r, reference)['control_passed'], index
    control |= assess(control, reference)
    providers = {k: copy.deepcopy(control[k]) for k in ('identity_before', 'identity_after', 'providers', 'pmic_reads')}
    providers['provider_registration_verified'] = True
    assert trial_findings(control, providers, reference, identity)['camera_trial_passed']
    assert not trial_findings(control, providers, reference, identity | {'boot_id': 'outgoing-AR'})['camera_trial_passed']
    for r in mutations:
        r |= assess(r, reference)
        assert not trial_findings(r, providers, reference, identity)['camera_trial_passed']
    initial = control | {'collection_phase': 'initial', 'uptime_seconds': 120.5}
    final = control | {'collection_phase': 'final', 'uptime_seconds': 621.0}
    assert complete_trial_findings(initial, final, providers, reference, identity)['camera_trial_passed']
    for r in mutations:
        r |= {'collection_phase': 'final', 'uptime_seconds': 621.0}
        assert not complete_trial_findings(initial, r, providers, reference, identity)['camera_trial_passed']
    timing_cases = ((initial | {'uptime_seconds': 119.9}, final),
                    (initial, final | {'uptime_seconds': 599.9}),
                    (initial, final | {'uptime_seconds': 900.0}),
                    (initial | {'uptime_seconds': 700.0}, final),
                    (initial | {'collection_phase': 'final'}, final),
                    (initial, final | {'collection_phase': 'initial'}))
    for first, last in timing_cases:
        assert not complete_trial_findings(first, last, providers, reference, identity)['camera_trial_passed']
    print(json.dumps({'strict_scope_expressions_unchanged': len(same), 'baseline_positive_cases': 1,
        'baseline_negative_cases': len(negatives), 'camera_positive_cases': 1,
        'camera_negative_cases': len(mutations), 'privacy_negative_cases': privacy_cases, 'trial_truth_table_cases': 4,
        'trial_identity_negative_cases': 1, 'camera_final_positive_cases': 1,
        'camera_final_negative_cases': len(mutations), 'camera_phase_timing_negative_cases': len(timing_cases),
        'hardware_actions': []}))


if __name__ == '__main__':
    main()
