#!/bin/bash

# Comprehensive clean script for Debian packaging artifacts

set -e

echo "=== Debian Package Clean Script ==="
echo ""

# Function to safely remove files/directories with sudo fallback
safe_remove() {
    local target="$1"
    local description="$2"
    
    if [ -e "$target" ] || [ -d "$target" ]; then
        echo "Removing $description..."
        if rm -rf "$target" 2>/dev/null; then
            echo "  Removed: $target"
        elif sudo rm -rf "$target" 2>/dev/null; then
            echo "  Removed (with sudo): $target"
        else
            echo "  Failed to remove: $target"
        fi
    else
        echo "  Not found: $target"
    fi
}

echo "Starting comprehensive clean..."
echo ""

# Clean debian build artifacts
echo "Cleaning debian build artifacts:"
safe_remove "debian/surfscape/" "debian package staging directory"
safe_remove "debian/.debhelper/" "debhelper cache directory"
safe_remove "debian/debhelper-build-stamp" "debhelper build stamp"
safe_remove "debian/files" "debian files list"

# Clean debian log and temporary files
echo ""
echo "Cleaning debian temporary files:"
find debian/ -name "*.substvars" -type f 2>/dev/null | while read -r file; do
    safe_remove "$file" "substvars file"
done

find debian/ -name "*.debhelper.log" -type f 2>/dev/null | while read -r file; do
    safe_remove "$file" "debhelper log file"
done

find debian/ -name "*.debhelper" -type d 2>/dev/null | while read -r dir; do
    safe_remove "$dir" "debhelper directory"
done

safe_remove "debian/tmp" "debian temporary directory"

# Clean parent directory package artifacts
echo ""
echo "Cleaning package files from parent directory:"
safe_remove "../surfscape_*.deb" "debian package files"
safe_remove "../surfscape_*.changes" "changes files"
safe_remove "../surfscape_*.dsc" "source description files"
safe_remove "../surfscape_*.tar.*" "source tar files"
safe_remove "../surfscape_*.build*" "build files"
safe_remove "../surfscape_*.buildinfo" "build info files"

# Use find for pattern-based cleanup in parent directory
echo ""
echo "Searching for remaining package artifacts:"
cd ..
for pattern in "surfscape_*"; do
    find . -maxdepth 1 -name "$pattern" -type f 2>/dev/null | while read -r file; do
        safe_remove "$file" "package artifact"
    done
done
cd - >/dev/null

# Clean Python artifacts
echo ""
echo "Cleaning Python build artifacts:"
safe_remove "build/" "Python build directory"
safe_remove "build-venv/" "Python venv build directory"
safe_remove "dist/" "Python dist directory"
safe_remove ".pybuild/" "pybuild directory"

# Clean egg-info directories
find . -name "*.egg-info" -type d 2>/dev/null | while read -r dir; do
    safe_remove "$dir" "Python egg-info directory"
done

# Clean Python cache files
echo ""
echo "Cleaning Python cache files:"
echo "Removing .pyc files..."
find . -name "*.pyc" -type f -delete 2>/dev/null && echo "  Removed .pyc files" || echo "  No .pyc files found"

echo "Removing __pycache__ directories..."
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null && echo "  Removed __pycache__ directories" || echo "  No __pycache__ directories found"

# Clean editor and system temporary files
echo ""
echo "Cleaning editor and system temporary files:"
safe_remove ".*.swp" "vim swap files"
safe_remove ".*.swo" "vim backup files"
safe_remove "*~" "editor backup files"
safe_remove ".DS_Store" "macOS system files"
safe_remove "Thumbs.db" "Windows thumbnail cache"

# Clean any residual locks or temporary files
echo ""
echo "Cleaning locks and temporary files:"
find . -name "*.lock" -type f 2>/dev/null | while read -r file; do
    safe_remove "$file" "lock file"
done

find . -name ".tmp*" -type f 2>/dev/null | while read -r file; do
    safe_remove "$file" "temporary file"
done

echo ""
echo "Clean complete!"
echo ""
echo "Summary of cleaned items:"
echo "  - Debian build artifacts and staging directories"
echo "  - Package files (.deb, .changes, .dsc, .tar.*)"
echo "  - Python build artifacts (build/, dist/, *.egg-info/)"
echo "  - Python cache files (.pyc, __pycache__/)"
echo "  - Editor temporary files"
echo "  - System temporary files"
echo ""
echo "The project is now clean and ready for a fresh build."
echo "Run './build-deb.sh' to build the Debian package."
