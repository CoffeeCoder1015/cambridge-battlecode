#!/bin/bash

MAPS=("dna" "corridors" "hooks" "arena" "galaxy")

echo "Starting 5 map instances..."

for MAP in "${MAPS[@]}"
do
    cambc run srcv2 srcv2 maps/$MAP.map26 --watch &
done
wait