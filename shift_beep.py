"""iRacing shift beep.

Beeps once (winsound, default output device) when RPM crosses the car's
upshift threshold taken from iRacing's own shift light data, optionally
overridden per car / per gear by shift_points.json (hot reloaded).
Must run with Windows Python (needs iRacing shared memory): py -3 shift_beep.py
Flags: --freq HZ, --ms MS, --config PATH, --test (beep 3x and exit).
"""
import argparse
import json
import os
import sys
import threading
import time
import winsound

import irsdk

TICK = 1 / 60
STATUS_EVERY = 0.5
REARM_DROP = 300
CONFIG_CHECK_EVERY = 1.0
DEFAULT_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'shift_points.json')


def num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def positive_rpm(v):
    """Return v as float if it is a number > 0 (bools rejected), else None."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not v > 0:
        return None
    return float(v)


def parse_config(text):
    """Parse shift_points.json text -> ({car: {'default': rpm|None, 'gears': {int: rpm}}}, warnings).

    Raises ValueError with a readable message if the file as a whole is unusable.
    Keys starting with '_' are ignored at every level. Bad entries -> warning, skipped.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError('invalid JSON at line %d column %d: %s' % (e.lineno, e.colno, e.msg))
    if not isinstance(data, dict):
        raise ValueError('top level must be a JSON object like {"cars": {...}}')
    cars_in = data.get('cars', {})
    if not isinstance(cars_in, dict):
        raise ValueError('"cars" must be a JSON object keyed by car name')
    warnings = ['unknown top-level key %r ignored' % k for k in data if k != 'cars' and not k.startswith('_')]
    cars = {}
    for car, entry in cars_in.items():
        if car.startswith('_'):
            continue
        if not isinstance(entry, dict):
            warnings.append('car %r: entry must be an object, ignored' % car)
            continue
        cfg = {'default': None, 'gears': {}}
        for k, v in entry.items():
            if k.startswith('_'):
                continue
            if k == 'default':
                cfg['default'] = positive_rpm(v)
                if cfg['default'] is None:
                    warnings.append('car %r: "default" must be a number > 0, got %r, ignored' % (car, v))
            elif k == 'gears':
                if not isinstance(v, dict):
                    warnings.append('car %r: "gears" must be an object like {"1": 7000}, ignored' % car)
                    continue
                for g, rpm in v.items():
                    if g.startswith('_'):
                        continue
                    if not (g.isdecimal() and int(g) > 0):
                        warnings.append('car %r: gear %r must be a positive integer like "1", ignored' % (car, g))
                    elif positive_rpm(rpm) is None:
                        warnings.append('car %r gear %s: RPM must be a number > 0, got %r, ignored' % (car, g, rpm))
                    else:
                        cfg['gears'][int(g)] = positive_rpm(rpm)
            else:
                warnings.append('car %r: unknown key %r ignored' % (car, k))
        cars[car] = cfg
    return cars, warnings


def load_config(path):
    """Load config file -> (cars, warnings). Missing file -> ({}, []). Raises ValueError on bad file."""
    try:
        with open(path, encoding='utf-8-sig') as f:
            text = f.read()
    except FileNotFoundError:
        return {}, []
    except OSError as e:
        raise ValueError('cannot read file: %s' % e)
    return parse_config(text)


def override_for(cars, car, gear):
    """Return (rpm, source) from config for this car/gear, or None to use iRacing's value."""
    cfg = cars.get(car)
    if not cfg:
        return None
    if gear in cfg['gears']:
        return cfg['gears'][gear], 'config gear %d' % gear
    if cfg['default'] is not None:
        return cfg['default'], 'config default'
    return None


def file_stamp(path):
    try:
        st = os.stat(path)
        return st.st_mtime_ns, st.st_size
    except OSError:
        return None


class Config:
    """Holds the current overrides and reloads them when the file changes."""

    def __init__(self, path):
        self.path = path
        self.cars = {}
        self.stamp = None
        self.last_check = 0.0
        self.load(initial=True)

    def load(self, initial=False):
        self.stamp = file_stamp(self.path)
        try:
            cars, warnings = load_config(self.path)
        except ValueError as e:
            print('\nCONFIG ERROR in %s: %s -> keeping previous config' % (self.path, e), flush=True)
            return False
        for w in warnings:
            print('\nconfig warning: %s' % w, flush=True)
        self.cars = cars
        if initial:
            if self.stamp is None:
                print('config: %s not found, no overrides' % self.path, flush=True)
            else:
                print('config: %s (%d car(s))' % (self.path, len(cars)), flush=True)
        else:
            print('\nconfig reloaded (%d car(s))' % len(cars), flush=True)
        return True

    def poll(self):
        """Reload if the file changed; return True if new config was applied."""
        now = time.monotonic()
        if now - self.last_check < CONFIG_CHECK_EVERY:
            return False
        self.last_check = now
        if file_stamp(self.path) == self.stamp:
            return False
        return self.load()


def beep_async(freq, ms):
    threading.Thread(target=winsound.Beep, args=(freq, ms), daemon=True).start()


def car_info(ir):
    di = ir['DriverInfo'] or {}
    idx = di.get('DriverCarIdx')
    name = next((d.get('CarScreenName') for d in di.get('Drivers', []) if d.get('CarIdx') == idx), '?')
    return {
        'car': name,
        'redline': num(di.get('DriverCarRedLine')),
        'si_shift': num(di.get('DriverCarSLShiftRPM')),
        'gears': int(num(di.get('DriverCarGearNumForward'))),
        'tm_first': num(ir['PlayerCarSLFirstRPM']),
        'tm_shift': num(ir['PlayerCarSLShiftRPM']),
        'tm_last': num(ir['PlayerCarSLLastRPM']),
        'tm_blink': num(ir['PlayerCarSLBlinkRPM']),
    }


def threshold(info):
    if info['tm_shift'] > 0:
        return info['tm_shift'], 'PlayerCarSLShiftRPM'
    if info['si_shift'] > 0:
        return info['si_shift'], 'DriverCarSLShiftRPM'
    return info['redline'] * 0.97, 'DriverCarRedLine*0.97'


def run(args):
    config = Config(args.config)
    ir = irsdk.IRSDK()
    connected = waiting_printed = False
    last_key = None
    armed, last_gear, last_rpm = True, None, 0.0
    last_status = 0.0
    try:
        while True:
            if config.poll():
                last_key = None
            if connected and not (ir.is_initialized and ir.is_connected):
                connected, last_key = False, None
                ir.shutdown()
                print('\ndisconnected from iRacing')
            if not connected:
                if ir.startup() and ir.is_initialized and ir.is_connected:
                    connected, waiting_printed = True, False
                    print('connected to iRacing')
                else:
                    if not waiting_printed:
                        print('waiting for iRacing...', flush=True)
                        waiting_printed = True
                    time.sleep(1)
                    continue

            ir.freeze_var_buffer_latest()
            info = car_info(ir)
            base_thr, base_src = threshold(info)
            key = (info['car'], base_thr, info['gears'])
            if key != last_key:
                last_key = key
                print('\ncar=%r redline=%.0f gears=%d SLFirst=%.0f SLShift=%.0f SLLast=%.0f SLBlink=%.0f '
                      'DriverCarSLShiftRPM=%.0f -> threshold=%.0f (%s)' % (
                          info['car'], info['redline'], info['gears'], info['tm_first'], info['tm_shift'],
                          info['tm_last'], info['tm_blink'], info['si_shift'], base_thr, base_src), flush=True)
                cfg = config.cars.get(info['car'])
                if cfg is None:
                    print('config: no override for car name "%s" (add this exact name to %s)' % (
                        info['car'], os.path.basename(config.path)), flush=True)
                else:
                    gears = ', '.join('%d=%.0f' % g for g in sorted(cfg['gears'].items())) or 'none'
                    dflt = '%.0f' % cfg['default'] if cfg['default'] is not None else 'none'
                    print('config: override found for "%s": default=%s gears: %s' % (
                        info['car'], dflt, gears), flush=True)

            rpm = num(ir['RPM'])
            gear = int(num(ir['Gear']))
            on_track = bool(ir['IsOnTrack'])
            ov = override_for(config.cars, info['car'], gear)
            thr, src = ov if ov else (base_thr, 'iracing')

            if gear != last_gear or rpm < thr - REARM_DROP:
                armed = True
            if (armed and thr > 0 and on_track and 1 <= gear < info['gears']
                    and last_rpm < thr <= rpm):
                beep_async(args.freq, args.ms)
                armed = False
            last_gear, last_rpm = gear, rpm

            now = time.monotonic()
            if now - last_status >= STATUS_EVERY:
                last_status = now
                sys.stdout.write('\rgear=%2d rpm=%5.0f thr=%5.0f (%-14s) armed=%-5s track=%-5s' % (
                    gear, rpm, thr, src, armed, on_track))
                sys.stdout.flush()
            time.sleep(TICK)
    except KeyboardInterrupt:
        print('\nbye')
    finally:
        ir.shutdown()


def main():
    p = argparse.ArgumentParser(description='Beep on upshift point in iRacing.')
    p.add_argument('--freq', type=int, default=1000, help='beep frequency in Hz (37-32767)')
    p.add_argument('--ms', type=int, default=120, help='beep duration in ms')
    p.add_argument('--config', default=DEFAULT_CONFIG,
                   help='per-car/per-gear shift RPM file (default: shift_points.json next to this script)')
    p.add_argument('--test', action='store_true', help='beep 3 times and exit')
    args = p.parse_args()
    if args.test:
        for _ in range(3):
            winsound.Beep(args.freq, args.ms)
            time.sleep(0.2)
        print('test done')
        return
    run(args)


if __name__ == '__main__':
    main()
