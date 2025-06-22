#!/bin/bash

# Clean script for Surfscape project
# Removes all build artifacts and temporary files

echo "Cleaning Surfscape build artifacts..."

# Remove build directories
rm -rf build/
rm -rf dist/
rm -rf __pycache__/
rm -rf venv/

# Remove Python cache files
find . -name "*.pyc" -delete
find . -name "*.pyo" -delete
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null

# Remove PyInstaller files
rm -f *.spec.bak

echo "Clean complete!"
