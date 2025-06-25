# Surfscape Web Browser Makefile
# Professional build system for cross-platform development
# 
# Author: André Machado
# License: GPL v3

# ============================================================================
# Configuration Variables
# ============================================================================

# Project information
PROJECT_NAME := surfscape
VERSION := $(shell grep -E '^__version__' $(PROJECT_NAME).py 2>/dev/null | cut -d'"' -f2 || echo "1.0.0")
DESCRIPTION := Your Own Way to Navigate the Web with Freedom

# Python configuration
PYTHON := $(shell command -v python3 2>/dev/null || command -v python 2>/dev/null)
PIP := $(shell command -v pip3 2>/dev/null || command -v pip 2>/dev/null)
VENV_DIR := venv
VENV_PYTHON := $(VENV_DIR)/bin/python
VENV_PIP := $(VENV_DIR)/bin/pip

# Build directories
BUILD_DIR := build
DIST_DIR := dist
CACHE_DIRS := __pycache__ .pytest_cache .coverage

# Platform detection
UNAME_S := $(shell uname -s 2>/dev/null || echo "Windows")
ifeq ($(UNAME_S),Linux)
    PLATFORM := linux
    EXECUTABLE := $(DIST_DIR)/$(PROJECT_NAME)
    VENV_ACTIVATE := $(VENV_DIR)/bin/activate
endif
ifeq ($(UNAME_S),Darwin)
    PLATFORM := macos
    EXECUTABLE := $(DIST_DIR)/$(PROJECT_NAME)
    VENV_ACTIVATE := $(VENV_DIR)/bin/activate
endif
ifeq ($(UNAME_S),Windows)
    PLATFORM := windows
    EXECUTABLE := $(DIST_DIR)/$(PROJECT_NAME).exe
    VENV_ACTIVATE := $(VENV_DIR)/Scripts/activate
endif

# Colors for output (if terminal supports them)
RED := \033[0;31m
GREEN := \033[0;32m
YELLOW := \033[1;33m
BLUE := \033[0;34m
CYAN := \033[0;36m
BOLD := \033[1m
NC := \033[0m

# ============================================================================
# Helper Functions
# ============================================================================

define print_header
	@echo "$(CYAN)========================================$(NC)"
	@echo "$(BOLD)  $(1)$(NC)"
	@echo "$(CYAN)========================================$(NC)"
endef

define print_status
	@echo "$(BLUE)[INFO]$(NC) $(1)"
endef

define print_success
	@echo "$(GREEN)[SUCCESS]$(NC) $(1)"
endef

define print_warning
	@echo "$(YELLOW)[WARNING]$(NC) $(1)"
endef

define print_error
	@echo "$(RED)[ERROR]$(NC) $(1)"
endef

# ============================================================================
# Main Targets
# ============================================================================

.PHONY: all help build clean install deps check test run package info

# Default target
all: build

# Help target - shows available commands
help:
	$(call print_header,Surfscape Build System)
	@echo "Available targets:"
	@echo ""
	@echo "  $(BOLD)Build Targets:$(NC)"
	@echo "    build      - Build the executable (default)"
	@echo "    package    - Create distribution package"
	@echo ""
	@echo "  $(BOLD)Development Targets:$(NC)"
	@echo "    deps       - Install Python dependencies"
	@echo "    venv       - Create virtual environment"
	@echo "    install    - Install in development mode"
	@echo "    run        - Run from source"
	@echo ""
	@echo "  $(BOLD)Quality Assurance:$(NC)"
	@echo "    check      - Run code quality checks"
	@echo "    test       - Run test suite"
	@echo ""
	@echo "  $(BOLD)Maintenance Targets:$(NC)"
	@echo "    clean      - Clean build artifacts"
	@echo "    clean-all  - Clean everything including venv"
	@echo "    info       - Show project information"
	@echo ""
	@echo "  $(BOLD)Platform:$(NC) $(PLATFORM)"
	@echo "  $(BOLD)Python:$(NC) $(PYTHON)"

# Build the executable
build: deps clean-build
	$(call print_header,Building $(PROJECT_NAME))
	@echo "$(BLUE)[INFO]$(NC) Building executable with PyInstaller..."
	@if [ -f "$(VENV_ACTIVATE)" ]; then \
		. $(VENV_ACTIVATE) && pyinstaller --clean $(PROJECT_NAME).spec; \
	else \
		pyinstaller --clean $(PROJECT_NAME).spec; \
	fi
	@if [ -f "$(EXECUTABLE)" ]; then \
		echo "$(GREEN)[SUCCESS]$(NC) Build completed successfully!"; \
		echo "$(BLUE)[INFO]$(NC) Executable: $(EXECUTABLE)"; \
		echo "$(BLUE)[INFO]$(NC) Size: $$(du -h $(EXECUTABLE) | cut -f1)"; \
		chmod +x $(EXECUTABLE) 2>/dev/null || true; \
		echo "$(GREEN)[SUCCESS]$(NC) BUILD COMPLETE!"; \
	else \
		echo "$(RED)[ERROR]$(NC) Build failed!"; \
		exit 1; \
	fi

# Create virtual environment
venv:
	@echo "$(BLUE)[INFO]$(NC) Creating virtual environment..."
	@if [ ! -d "$(VENV_DIR)" ]; then \
		$(PYTHON) -m venv $(VENV_DIR); \
		echo "$(GREEN)[SUCCESS]$(NC) Virtual environment created at $(VENV_DIR)"; \
	else \
		echo "$(YELLOW)[WARNING]$(NC) Virtual environment already exists"; \
	fi

# Install dependencies
deps: venv
	@echo "$(BLUE)[INFO]$(NC) Installing dependencies..."
	@if [ -f "$(VENV_ACTIVATE)" ]; then \
		. $(VENV_ACTIVATE) && \
		$(VENV_PIP) install --upgrade pip --break-system-packages && \
		$(VENV_PIP) install -r requirements.txt --break-system-packages; \
	else \
		$(PIP) install --upgrade pip --break-system-packages && \
		$(PIP) install -r requirements.txt --break-system-packages 2>/dev/null || \
		$(PIP) install -r requirements.txt --break-system-packages; \
	fi
	@echo "$(GREEN)[SUCCESS]$(NC) Dependencies installed successfully"

# Install in development mode
install: deps
	@echo "$(BLUE)[INFO]$(NC) Installing $(PROJECT_NAME) in development mode..."
	@if [ -f "$(VENV_ACTIVATE)" ]; then \
		. $(VENV_ACTIVATE) && \
		$(VENV_PIP) install -e .; \
	else \
		$(PIP) install -e .; \
	fi

# Run from source
run: deps
	@echo "$(BLUE)[INFO]$(NC) Running $(PROJECT_NAME) from source..."
	@if [ -f "$(VENV_ACTIVATE)" ]; then \
		. $(VENV_ACTIVATE) && $(VENV_PYTHON) $(PROJECT_NAME).py; \
	else \
		$(PYTHON) $(PROJECT_NAME).py; \
	fi

# Run code quality checks
check:
	@echo "$(BLUE)[INFO]$(NC) Running code quality checks..."
	@if command -v flake8 >/dev/null 2>&1; then \
		echo "$(BLUE)[INFO]$(NC) Running flake8..."; \
		flake8 $(PROJECT_NAME).py || true; \
	fi
	@if command -v pylint >/dev/null 2>&1; then \
		echo "$(BLUE)[INFO]$(NC) Running pylint..."; \
		pylint $(PROJECT_NAME).py || true; \
	fi
	@if command -v black >/dev/null 2>&1; then \
		echo "$(BLUE)[INFO]$(NC) Checking code formatting with black..."; \
		black --check $(PROJECT_NAME).py || true; \
	fi

# Run tests
test:
	@echo "$(BLUE)[INFO]$(NC) Running test suite..."
	@if [ -d "tests" ]; then \
		if command -v pytest >/dev/null 2>&1; then \
			pytest tests/; \
		else \
			$(PYTHON) -m unittest discover tests/; \
		fi; \
	else \
		echo "$(YELLOW)[WARNING]$(NC) No tests directory found"; \
	fi

# Create distribution package
package: build
	$(call print_header,Creating Distribution Package)
	@mkdir -p $(DIST_DIR)/package
	@cp $(EXECUTABLE) $(DIST_DIR)/package/
	@cp README.md $(DIST_DIR)/package/ 2>/dev/null || true
	@cp LICENSE $(DIST_DIR)/package/ 2>/dev/null || true
	@if [ -d "screenshots" ]; then cp -r screenshots $(DIST_DIR)/package/; fi
	$(call print_success,"Package created in $(DIST_DIR)/package/")

# Show project information
info:
	$(call print_header,Project Information)
	@echo "$(BOLD)Name:$(NC) $(PROJECT_NAME)"
	@echo "$(BOLD)Version:$(NC) $(VERSION)"
	@echo "$(BOLD)Description:$(NC) $(DESCRIPTION)"
	@echo "$(BOLD)Platform:$(NC) $(PLATFORM)"
	@echo "$(BOLD)Python:$(NC) $(shell $(PYTHON) --version 2>&1)"
	@echo "$(BOLD)Virtual Environment:$(NC) $(if $(wildcard $(VENV_DIR)),✓ Active,✗ Not found)"
	@echo "$(BOLD)Executable:$(NC) $(EXECUTABLE)"
	@echo "$(BOLD)Build Status:$(NC) $(if $(wildcard $(EXECUTABLE)),✓ Built,✗ Not built)"

# ============================================================================
# Cleanup Targets
# ============================================================================

# Clean build artifacts only
clean-build:
	$(call print_status,"Cleaning build artifacts...")
	@rm -rf $(BUILD_DIR)/ $(DIST_DIR)/
	@find . -name "*.pyc" -delete 2>/dev/null || true
	@find . -name "*.pyo" -delete 2>/dev/null || true
	@find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	@rm -f *.spec.bak 2>/dev/null || true

# Clean everything except virtual environment
clean: clean-build
	$(call print_status,"Cleaning temporary files...")
	@rm -rf $(CACHE_DIRS) 2>/dev/null || true
	@find . -name "*.egg-info" -type d -exec rm -rf {} + 2>/dev/null || true
	$(call print_success,"Clean completed")

# Clean everything including virtual environment
clean-all: clean
	$(call print_status,"Removing virtual environment...")
	@rm -rf $(VENV_DIR)/
	$(call print_success,"Full cleanup completed")

# ============================================================================
# Development Utilities
# ============================================================================

# Format code with black
format:
	@if command -v black >/dev/null 2>&1; then \
		echo "$(BLUE)[INFO]$(NC) Formatting code with black..."; \
		black $(PROJECT_NAME).py; \
	else \
		echo "$(YELLOW)[WARNING]$(NC) black not installed. Install with: pip install black"; \
	fi

# Update dependencies
update-deps:
	$(call print_status,"Updating dependencies...")
	@if [ -f "$(VENV_ACTIVATE)" ]; then \
		. $(VENV_ACTIVATE) && \
		$(VENV_PIP) list --outdated && \
		$(VENV_PIP) install --upgrade -r requirements.txt; \
	else \
		$(PIP) list --outdated && \
		$(PIP) install --upgrade -r requirements.txt; \
	fi

# Generate requirements.txt from current environment
freeze:
	@if [ -f "$(VENV_ACTIVATE)" ]; then \
		. $(VENV_ACTIVATE) && $(VENV_PIP) freeze > requirements.txt; \
	else \
		$(PIP) freeze > requirements.txt; \
	fi
	$(call print_success,"Requirements frozen to requirements.txt")

# ============================================================================
# CI/CD Targets
# ============================================================================

# Target for continuous integration
ci: deps check test build

# Target for release preparation
release: clean-all ci package
	$(call print_success,"Release package ready in $(DIST_DIR)/package/")

# Debug build with verbose output
debug: clean-build
	$(call print_header,Debug Build)
	@if [ -f "$(VENV_ACTIVATE)" ]; then \
		. $(VENV_ACTIVATE) && \
		pyinstaller --clean --debug=all --console $(PROJECT_NAME).spec; \
	else \
		pyinstaller --clean --debug=all --console $(PROJECT_NAME).spec; \
	fi

.PHONY: venv format update-deps freeze ci release debug clean-build
