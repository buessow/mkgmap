# Swiss maps for Garmin watches

This repository builds Garmin `.img` maps for Switzerland, including a topo basemap and ski touring overlays. A compatible Garmin watch must support custom maps.

## Download the latest maps

- [Swiss topo map (`swiss-topo.img`)](https://github.com/buessow/mkgmap/releases/latest/download/swiss-topo.img)
- [All Swiss maps (`swiss-topo-all.zip`)](https://github.com/buessow/mkgmap/releases/latest/download/swiss-topo-all.zip) — contains the topo map, ski network, slope overlay, and rock overlay as separate `.img` files.

You can also [browse the latest release](https://github.com/buessow/mkgmap/releases/latest) to download individual overlays. Extract the ZIP before copying any maps to the watch.

## Install on Windows

1. Connect the watch to the computer with a USB cable.
2. Open the watch in File Explorer. It may appear as a removable drive or as an MTP device.
3. Open the `GARMIN` folder on the watch. Create it if necessary.
4. Copy the downloaded `.img` file into `GARMIN`. If you downloaded the ZIP, extract it first and copy the `.img` files you want.
5. Safely eject the watch, disconnect it, and restart it.

## Install on macOS

1. Connect the watch to the Mac with a USB cable. MTP watches generally do not appear in Finder.
2. Open the watch with an MTP file transfer app such as OpenMTP.
3. Open the `GARMIN` folder on the watch. Create it if necessary.
4. Copy the `.img` file into `GARMIN`, or extract the ZIP and copy the maps you want.
5. Disconnect the watch and give it a moment to load the maps. Restart it if they do not appear.

## Enable a map on the watch

1. Start an activity that uses maps, such as Backcountry Ski.
2. Open that activity's map settings or Map Manager.
3. Find **Configure Maps** (the name varies by watch) and enable the new map layers.

If a map is missing, restart the watch and check the map list again. You can keep several custom `.img` files in `GARMIN`, but give them distinct filenames and do not overwrite a built-in map.

## Building and publishing

Run `make swisstopo` to build the Swiss topo basemap, `make skitouring` for the ski overlays, or `make publish-swiss` to publish existing `out/swiss-*` files as a tagged GitHub Release. The publishing command requires the GitHub CLI (`gh`) to be authenticated and the current commit to be pushed to GitHub.
