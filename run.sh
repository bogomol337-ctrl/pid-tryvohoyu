#!/bin/bash
cd ~/tryvoha
source venv/bin/activate
export TG_API_ID=31281651
export TG_API_HASH=b4ed8c5d5551563be361dcaf53c7cc0e
python scraper.py
