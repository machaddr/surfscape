#!/bin/bash

# Surfscape Build Script for Linux/Unix
# This script builds a static executable using PyInstaller

set -e  # Exit on any error

echo "========================================"
echo "  Surfscape Build Script (Linux/Unix)  "
echo "========================================"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    print_error "Python 3 is not installed or not in PATH"
    exit 1
fi

print_status "Python version: $(python3 --version)"

# Check if pip is installed
if ! command -v pip3 &> /dev/null; then
    print_error "pip3 is not installed or not in PATH"
    exit 1
fi

# Install dependencies
print_status "Installing dependencies..."
pip3 install -r requirements.txt --break-system-packages

# Clean previous builds
print_status "Cleaning previous builds..."
rm -rf build/
rm -rf dist/
rm -rf __pycache__/
find . -name "*.pyc" -delete

# Build the executable
print_status "Building executable with PyInstaller..."
pyinstaller --clean surfscape.spec

# Check if build was successful
if [ -f "dist/surfscape" ]; then
    print_success "Build completed successfully!"
    print_status "Executable location: $(pwd)/dist/surfscape"
    
    # Make executable if not already
    chmod +x dist/surfscape
    
    # Get file size
    SIZE=$(du -h dist/surfscape | cut -f1)
    print_status "Executable size: $SIZE"
    
    # Check for dynamic dependencies
    if ldd dist/surfscape &> /dev/null; then
        print_warning "Executable has dynamic dependencies. Run 'ldd dist/surfscape' to see them."
    else
        print_success "Executable appears to be statically linked!"
    fi
    
    echo ""
    echo "========================================"
    print_success "BUILD COMPLETE!"
    echo "========================================"
    echo "You can find your executable at: ./dist/surfscape"
    echo "To run: ./dist/surfscape"
    echo ""
    
else
    print_error "Build failed! Check the output above for errors."
    exit 1
fi

# Deactivate virtual environment
deactivate
