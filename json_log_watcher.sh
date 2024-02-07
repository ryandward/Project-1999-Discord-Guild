#!/bin/bash

FILE=lore_cache.json

while true
do
    inotifywait -e close_write $FILE
    clear
    jq . $FILE
done
