#!/bin/bash
set -e

# Install Python deps
pip install -r requirements.txt

# Build React frontend
cd frontend
npm install
node ./node_modules/vite/bin/vite.js build
cd ..
