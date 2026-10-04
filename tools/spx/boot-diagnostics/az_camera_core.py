#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Pure policy for AZ normal rear probe and sampled idle cleanup; no hardware access."""
import re

CCI = '/soc@0/cci@ac4a000'
SENSOR = CCI + '/i2c-bus@0/camera@10'
PROVIDER = '/soc@0/spmi@c440000/pmic@1/regulators'
RAILS = {'spx-camera-dvdd': 1200000, 'spx-camera-dovdd': 1800000,
         'spx-camera-avdd': 2856000}
LED = '/camera-privacy-leds/led-0'


def privacy_checks(report):
    leds = report.get('privacy_leds', [])
    return {
        'rear_privacy_provider_bound_idle': bool(len(leds) == 1 and
            leds[0].get('name') == 'spx:rear:privacy' and
            leds[0].get('of_node', '').endswith(LED) and
            leds[0].get('provider_driver') == 'leds-gpio' and
            leds[0].get('brightness') == '0' and leds[0].get('max_brightness') == '1' and
            leds[0].get('trigger_selected') == 'none'),
        'rear_privacy_dt_relation_exact': bool(len(leds) == 1 and
            leds[0].get('sensor_led_phandle') == leds[0].get('phandle') and
            isinstance(leds[0].get('phandle'), int) and leds[0]['phandle'] > 0 and
            leds[0].get('sensor_led_names') == ['privacy'] and
            leds[0].get('gpio_provider') == '/soc@0/pinctrl@3100000' and
            leds[0].get('gpio_pin') == 11 and leds[0].get('gpio_flags') == 0),
        'rear_privacy_gpio_output_low': bool(re.fullmatch(
            r'\s*gpio11\s*:\s*out\s+low\s+func0\s+.*',
            report.get('privacy_gpio_line', ''))),
        'front_privacy_gpio_unclaimed': report.get('front_privacy_pinmux_line') ==
            'pin 25 (GPIO_25): UNCLAIMED',
    }


def decode(records):
    values = {}
    for record in records:
        match = re.fullmatch(r'([0-9a-f]{4}): ([0-9a-f]{2})\n', record['raw'])
        if not match or int(match[1], 16) != record['address']:
            return None
        address = int(match[1], 16)
        if address in values or record['file_offset'] != address * 9:
            return None
        values[address] = int(match[2], 16)
    return values


def assess(report, reference):
    before, after = report.get('identity_before'), report.get('identity_after')
    checks = {'identity_stable_untainted': bool(before and before == after and before.get('taint') == '0'),
              'collection_complete': not report.get('failure')}
    cci, sensors = report.get('cci', []), report.get('sensors', [])
    checks['cci_normal_driver_bound_idle'] = bool(len(cci) == 1 and
        cci[0].get('of_node', '').endswith(CCI) and cci[0].get('driver') == 'i2c-qcom-cci' and
        cci[0].get('power', {}).get('runtime_status') == 'suspended' and
        cci[0].get('assigned_clock_rate_hz') == 37500000)
    checks['rear_normal_probe_completed'] = bool(len(sensors) == 1 and
        sensors[0].get('of_node', '').endswith(SENSOR) and sensors[0].get('driver') == 'ov13858' and
        sensors[0].get('name', '').endswith('-0010') and
        sensors[0].get('adapter_of_node', '').endswith(CCI + '/i2c-bus@0'))
    checks['rear_runtime_idle'] = bool(len(sensors) == 1 and
        sensors[0].get('power', {}).get('runtime_status') == 'suspended')
    providers = report.get('providers', {})
    checks['three_real_providers_idle'] = bool(set(providers) == set(RAILS) and all(
        fields.get('name') == name and fields.get('state') == 'disabled' and fields.get('num_users') == '0' and
        fields.get('provider_driver') == 'qcom-spmi-regulator' and fields.get('provider_of_node', '').endswith(PROVIDER) and
        all(fields.get(key) == str(RAILS[name]) for key in ('microvolts', 'min_microvolts', 'max_microvolts'))
        for name, fields in providers.items()))
    now = decode(report.get('pmic_reads', []))
    checks['sampled_pmic_controls_exact_reference'] = bool(now is not None and len(now) == 21 and now == reference)
    checks['no_camera_error_lines'] = not report.get('camera_error_lines', [])
    checks.update(privacy_checks(report))
    return {'checks': checks, 'control_passed': all(checks.values()),
            'failure_reasons': [name for name, passed in checks.items() if not passed]}


def trial_findings(control, providers, reference, expected_identity):
    findings = assess(control, reference)
    assert findings['control_passed'] == control['control_passed']
    assert findings['checks'] == control['checks']
    provider_checks = assess(providers, reference)['checks']
    provider_idle = bool(provider_checks['identity_stable_untainted'] and
        provider_checks['collection_complete'] and provider_checks['three_real_providers_idle'] and
        provider_checks['sampled_pmic_controls_exact_reference'])
    assert providers['provider_registration_verified'] == provider_idle
    control_identity = control['identity_before'] == control['identity_after'] == expected_identity
    provider_identity = providers['identity_before'] == providers['identity_after'] == expected_identity
    return {'camera_control_passed': findings['control_passed'] and control_identity,
            'camera_provider_idle_passed': provider_idle and provider_identity,
            'camera_trial_passed': bool(findings['control_passed'] and provider_idle and
                                      control_identity and provider_identity)}


def complete_trial_findings(initial, final, providers, reference, expected_identity):
    first = trial_findings(initial, providers, reference, expected_identity)
    last = trial_findings(final, providers, reference, expected_identity)
    ordered = (initial.get('collection_phase') == 'initial' and
               final.get('collection_phase') == 'final' and
               120 <= initial.get('uptime_seconds', -1) < final.get('uptime_seconds', -1) and
               600 <= final.get('uptime_seconds', -1) < 900)
    initial_passed = first['camera_control_passed']
    final_passed = last['camera_control_passed']
    return {'camera_control_initial_passed': initial_passed,
            'camera_control_final_passed': final_passed,
            'camera_observations_ordered': bool(ordered),
            'camera_control_passed': bool(initial_passed and final_passed and ordered),
            'camera_provider_idle_passed': first['camera_provider_idle_passed'] and last['camera_provider_idle_passed'],
            'camera_trial_passed': bool(first['camera_trial_passed'] and last['camera_trial_passed'] and ordered)}
