#!/usr/bin/env bash
# Re-download the OpenStreetMap source data into tools/data/ (Overpass API). Only needed to
# refresh boundaries; build.py works from the committed copies.
set -euo pipefail
cd "$(dirname "$0")/data"
API=https://overpass-api.de/api/interpreter
COUNCILS='^(City of Brisbane|City of Moreton Bay|Redland City|Ipswich City|Logan City)$'
BB='-29.2,151.4,-25.6,154.4'   # coastline: wide enough for the zoomed-out view
RB='-28.2,152.2,-26.6,153.65'  # rivers

fetch() {  # fetch <out.json> <query>; the public server is often busy, so back off and retry
  for i in 1 2 3 4 5; do
    curl -s -m 320 -A 'brismap-builder/1.0' --data-urlencode "data=$2" "$API" -o "$1.tmp"
    if python3 -c "import json,sys;json.load(open(sys.argv[1]))" "$1.tmp" 2>/dev/null; then mv "$1.tmp" "$1"; echo "$1 ok"; return; fi
    echo "$1: busy, retry $i"; sleep $((i * 20))
  done
  echo "$1: failed" >&2; exit 1
}
# all councils around the five too, so split localities can name the other council
fetch councils.json   "[out:json][timeout:300];relation[\"boundary\"=\"administrative\"][\"admin_level\"=\"6\"]($RB);out geom;"
fetch localities.json "[out:json][timeout:300];area[\"boundary\"=\"administrative\"][\"admin_level\"=\"6\"][\"name\"~\"$COUNCILS\"]->.c;relation(area.c)[\"boundary\"=\"administrative\"][\"admin_level\"=\"9\"];out geom;"
fetch coastline.json  "[out:json][timeout:300];way[\"natural\"=\"coastline\"]($BB);out geom;"
fetch rivers.json     "[out:json][timeout:300];(way[\"natural\"=\"water\"][\"water\"=\"river\"]($RB);relation[\"natural\"=\"water\"][\"water\"=\"river\"]($RB);way[\"waterway\"=\"riverbank\"]($RB);relation[\"waterway\"=\"riverbank\"]($RB););out geom;"
