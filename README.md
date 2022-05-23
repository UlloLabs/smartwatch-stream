Using BLE connectivity from smartwatch (and other compatible devices) to stream physiological signals to computer.

Requires [bluepy](https://github.com/IanHarvey/bluepy) and [LSL](https://github.com/sccn/labstreaminglayer), install (the right versions) with `pip install -r requirements.txt`.


![Quick test with mio alpha 2](mio_rox.png)

# Changelog

- 2018-05-16: last version from conphyture project
- 2020-7-17: new version fetched from echo codebase
- 2020-9-18: refactoring, merging both -- breaking change!
- 2020-9-27: API change: stop sending value when disconnected, unless "keep-sending" option is set

## multi branch

Test for multi-platform script, using bleak.

# TODO

- configure separately name/type for LSL
- multi: no "keep sending" option at the moment
 
# Dev

Note: the repository is using git subrepo to handle some dependencies (e.g. GattDevice) -- see https://github.com/ingydotnet/git-subrepo
