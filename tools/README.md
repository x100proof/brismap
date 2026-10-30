# Map data tools

`build.py` regenerates the map data (`const D=` in `../brismap.html`) from OpenStreetMap data
in `data/`, and writes it into the page in place. There's no other build step; deploy as usual.

```bash
cd tools
uv venv --seed && uv pip install -r requirements.txt
.venv/bin/python build.py      # ~20 s
./fetch.sh                     # optional: refresh data/ from Overpass first
```

## Data (`data/`)

| File | What |
|---|---|
| `localities.json` | Gazetted localities (OSM `admin_level=9`, imported from PSMA/Geoscape) touching the five councils |
| `councils.json` | The five local government areas (`admin_level=6`) |
| `coastline.json` | OSM `natural=coastline` ways, turned into land polygons by `build.py` |
| `rivers.json` | OSM river-area polygons |
| `extras.json` | Hand-placed bits: Brisbane River label path, POIs, water label positions |

OSM data © OpenStreetMap contributors, ODbL.

## How the build works

- **Projection:** equirectangular, `x = 1331.969·lon − 203577.98`, `y = −1499.866·lat − 40496.37`
  (x/y ratio = cos 27.4°). Everything in `extras.json` is in these coordinates.
- **Council membership:** a locality belongs to a council if ≥3 % of its area (or of its land) is
  in it, so a few belong to two (Chuwar: Brisbane/Ipswich; Moreton Bay: Brisbane/Redland). Each
  locality is clipped to the five councils; the card notes the share shown when it is partial.
  Names repeated across councils get a suffix, e.g. `Cedar Creek (Logan)`.
- **Shapes** are simplified together as a coverage, so shared borders stay shared.
- **Land** comes from the coastline (land is left of each way); locality parts over water are
  faded with an SVG mask.
- **Labels** are fitted inside each locality's largest land piece using the page's own label
  font metrics (MapSC, read from `brismap.html`), trying several angles and line breaks.
- **Colours:** greedy 16-colour palette; neighbours never share, neighbours-of-neighbours rarely.
