Using BLE connectivity from smartwatch (and other compatible devices) to stream physiological signals through the [LSL](https://labstreaminglayer.org/) network protocol.

![Quick test with mio alpha 2](mio_rox.png)


Works with any BLE monitoring device implementing standard HR characteristics. Tested with devices from various brands:  Polar, Mio, PulseOn, ... Note that depending on the device the sampling rate and accuracy will vary, and not all devices send IBI informations.

There are two versions of the script. One more robust and more thoroughly tested, but working only on Linuy systems: `hr_stream.py` (depends on  [bluepy](https://github.com/IanHarvey/bluepy)). The second one is more "green" but is functional on all three major desktop systems (Windows, Linux, Mac) thanks to [bleak](https://github.com/hbldh/bleak): `hr_stream_multi.py`.

Check and install dependecies (and the their tested versions) with `pip install -r requirements.txt`.


# Changelog

## v0.1.0 (2022-10-22)

Formal release for first public version.

## previously

- 2020-09-27: API change: stop sending value when disconnected, unless "keep-sending" option is set
- 2020-09-18: refactoring, merging both -- breaking change!
- 2020-07-17: new version fetched from echo codebase
- 2018-05-16: last version from conphyture project

## multi branch

Test for multi-platform script, using bleak.

# TODO

- configure separately name/type for LSL
- multi: no "keep sending" option at the moment
 
# Dev

Note: the repository is using git subrepo to handle some dependencies (e.g. GattDevice) -- see https://github.com/ingydotnet/git-subrepo
