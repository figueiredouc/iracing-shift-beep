# iRacing Shift Beep

Plays a short beep in your headphones when the engine RPM crosses the upshift point in iRacing.

Why: in some cars (and some camera / FOV setups) the shift lights are hard or impossible to see. An audio cue lets you shift on time without looking for the lights.

The upshift point comes from iRacing's own shift light data, and you can override it per car and per gear with a small JSON file.

## Requirements

- Windows (the script reads iRacing's shared memory, so it must run on the same PC as the sim).
- Python 3.x from [python.org](https://www.python.org/downloads/). During install, tick "Add python.exe to PATH" (the `py` launcher is installed by default).
- The `pyirsdk` package:

  ```
  py -m pip install pyirsdk
  ```

## Install

1. Download this repository (Code > Download ZIP, then extract) or `git clone` it.
2. Double-click `run.bat`.

The console window shows `waiting for iRacing...` until you join a session, then prints the car and a live status line. Close the window or press Ctrl+C to stop.

## Usage and flags

Run from a command prompt in the project folder:

```
py -3 shift_beep.py [flags]
```

Flags can also be appended to `run.bat` (e.g. `run.bat --freq 1500`) or added to the `py -3` line inside it.

| Flag | Default | Description |
|------|---------|-------------|
| `--test` | | Beep 3 times and exit. Use it to check sound and pick a frequency. |
| `--freq HZ` | `1000` | Beep frequency in Hz (37-32767). |
| `--ms MS` | `120` | Beep duration in milliseconds. |
| `--config PATH` | `shift_points.json` next to the script | Per-car / per-gear shift RPM file. |

## How the shift threshold is chosen

For the current car, the first value that is available and greater than 0 wins:

1. `PlayerCarSLShiftRPM` (live telemetry: the RPM where iRacing's shift lights say "shift").
2. `DriverInfo.DriverCarSLShiftRPM` (session info).
3. 97% of the car's redline (`DriverCarRedLine`).

Then the config file is applied for the current gear:

1. A per-gear value for this car (`"gears": {"3": 7400}`), if present.
2. Otherwise the car's `"default"`, if present.
3. Otherwise the iRacing value above.

The status line shows the threshold for the current gear and where it came from, e.g.:

```
gear= 3 rpm= 6820 thr= 7400 (config gear 3 ) armed=True  track=True
```

Possible sources: `iracing`, `config default`, `config gear N`.

## Tuning per car / per gear (`shift_points.json`)

When the script connects or the car changes, it prints the car name exactly as it must appear in the file, and whether an override was found:

```
config: no override for car name "Mazda MX-5 Cup" (add this exact name to shift_points.json)
```

Add that name under `"cars"`:

```json
{
  "cars": {
    "Mazda MX-5 Cup": {
      "default": 7200,
      "gears": { "1": 7000, "2": 7150 }
    },
    "Porsche 911 GT3 Cup (992)": {
      "gears": { "5": 8300 }
    }
  }
}
```

(The car names and numbers above are only examples; use the name your console prints and your own RPMs.)

- `"default"` (optional): RPM used for every gear not listed in `"gears"`.
- `"gears"` (optional): RPM per gear. Gear numbers are strings: `"1"`, `"2"`, ...
- A car with no entry uses the iRacing-derived threshold.
- Keys starting with `_` are ignored everywhere (e.g. `"_example"`, `"_notes"`), so you can keep notes or disabled entries in the file.
- The file is optional. If it does not exist, there are no overrides.

**Hot reload:** the script checks the file about once per second. Save it while driving and you will see `config reloaded`. If the file has a JSON mistake, the script prints the error with line and column and keeps using the previous config, so a typo never stops it mid-race. Invalid entries (e.g. a negative RPM or gear `"0"`) print a warning and are ignored; the rest of the file still applies.

## When it beeps

- Once each time the RPM rises across the threshold (not continuously while above it).
- Only in forward gears below top gear: never in neutral, reverse, or the top gear.
- Only while the car is on track (not in the garage).
- It re-arms after a gear change, or when RPM drops 300 below the threshold.

## Editing with an AI assistant

The config is plain JSON designed so you can paste it into an AI assistant such as Claude (or let one edit the file directly) and ask things like "set the MX-5 to 7100 in 2nd and 7300 in 3rd". Rules to give the assistant:

- Top level: `{"cars": { ... }}`. Car names are keys and must match the name the script prints exactly (case, spaces, punctuation).
- Each car is an object with optional `"default"` (number > 0) and optional `"gears"` (object mapping gear number as a string, `"1"` and up, to an RPM number > 0).
- Per-gear value beats `"default"`; a car not in the file uses iRacing's own shift point.
- Keys starting with `_` are ignored; anything else unknown produces a warning.
- Plain JSON only: double quotes, no comments, no trailing commas.

## Troubleshooting

- **No sound:** the beep plays on the Windows default output device. If your headset is not the default device, set it as default in Windows sound settings. Run `py -3 shift_beep.py --test` to check.
- **Stuck on `waiting for iRacing...`:** the sim must be running and you must be in a session (practice, race, test drive). The menus/UI alone are not enough.
- **Never beeps but status line updates:** check `track=True` (you must be in the car on track) and that you are not in top gear. Compare `rpm` with `thr`; if the threshold is too high for that car, set an override in `shift_points.json`.
- **Running from WSL / a `\\wsl$` path:** it must run with Windows Python (`python.exe` / `py`), not Linux Python, because it needs `winsound` and iRacing's shared memory. Windows Python can run the script from a WSL path, but `run.bat` and file watching are more reliable if the folder lives on a Windows drive.
- **`ModuleNotFoundError: No module named 'irsdk'`:** run `py -m pip install pyirsdk` with the same Python that runs the script.

## License

MIT, see [LICENSE](LICENSE).
