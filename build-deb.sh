#!/bin/bash

# Build script for creating Debian package for Surfscape (Static Build)

set -e

# Function to perform comprehensive clean
clean_debian() {
    echo "Performing comprehensive Debian clean..."
    
    # Clean debian build artifacts
    echo "- Removing debian build artifacts..."
    sudo rm -rf debian/surfscape/ 2>/dev/null || rm -rf debian/surfscape/
    sudo rm -rf debian/.debhelper/ 2>/dev/null || rm -rf debian/.debhelper/
    sudo rm -f debian/debhelper-build-stamp 2>/dev/null || rm -f debian/debhelper-build-stamp
    sudo rm -f debian/files 2>/dev/null || rm -f debian/files
    sudo rm -f debian/*.substvars 2>/dev/null || rm -f debian/*.substvars
    sudo rm -f debian/*.debhelper.log 2>/dev/null || rm -f debian/*.debhelper.log
    
    # Clean parent directory artifacts
    echo "- Removing package files from parent directory..."
    sudo rm -f ../surfscape_*.deb 2>/dev/null || rm -f ../surfscape_*.deb
    sudo rm -f ../surfscape_*.changes 2>/dev/null || rm -f ../surfscape_*.changes
    sudo rm -f ../surfscape_*.dsc 2>/dev/null || rm -f ../surfscape_*.dsc
    sudo rm -f ../surfscape_*.tar.* 2>/dev/null || rm -f ../surfscape_*.tar.*
    sudo rm -f ../surfscape_*.build* 2>/dev/null || rm -f ../surfscape_*.build*
    sudo rm -f ../surfscape_*.buildinfo 2>/dev/null || rm -f ../surfscape_*.buildinfo
    
    # Clean Python artifacts
    echo "- Removing Python build artifacts..."
    sudo rm -rf build/ 2>/dev/null || rm -rf build/
    sudo rm -rf dist/ 2>/dev/null || rm -rf dist/
    sudo rm -rf *.egg-info/ 2>/dev/null || rm -rf *.egg-info/
    sudo rm -rf .pybuild/ 2>/dev/null || rm -rf .pybuild/
    
    # Clean Python cache files
    echo "- Removing Python cache files..."
    find . -name "*.pyc" -delete 2>/dev/null || true
    find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
    
    echo "Clean complete!"
}

# Check for clean flag
if [ "$1" = "clean" ]; then
    clean_debian
    exit 0
fi

echo "Building Debian package for Surfscape (Static Build)..."

# Check if we're in the right directory
if [ ! -f "surfscape.py" ]; then
    echo "Error: surfscape.py not found. Please run this script from the project root."
    exit 1
fi

# Check for required tools
command -v debuild >/dev/null 2>&1 || { echo "Error: debuild not found. Install devscripts package." >&2; exit 1; }
command -v dh >/dev/null 2>&1 || { echo "Error: debhelper not found. Install debhelper package." >&2; exit 1; }

# Clean previous builds
clean_debian

# Update changelog with current date
echo "Updating changelog..."
sed -i "s/Mon, 21 Jul 2025 12:00:00 +0000/$(date -R)/" debian/changelog

# Build the package
echo "Building static package..."
debuild -us -uc -b

echo "Build complete!"
echo "Package files created:"
ls -la ../surfscape_*.deb || echo "No .deb files found"

# Install instructions
echo ""
echo "To install the package:"
echo "sudo dpkg -i ../surfscape_*.deb"
echo "sudo apt-get install -f  # Fix any dependency issues"
echo ""
echo "To remove the package:"
echo "sudo apt-get remove surfscape"
echo ""
echo "This static build includes all dependencies - no additional Python packages needed!"
echo ""
echo "To clean build artifacts:"
echo "./build-deb.sh clean"
