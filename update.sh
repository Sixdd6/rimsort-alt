#!/bin/bash

# ========================================================================
# RimSort Update Script for macOS and Linux
# This script safely updates RimSort by replacing the current installation
# with files from a temporary directory.
# Usage: update.sh <temp_update_path> [log_path] [install_dir]
# ========================================================================

set -euo pipefail # Exit on error, undefined variables, and pipe failures

# Dry-run mode
DRY_RUN=false
if [ "${1:-}" = "--dry-run" ]; then
	DRY_RUN=true
	echo "DRY RUN MODE: No actual changes will be made"
	shift
fi

# Required temp update path (first argument)
if [ -z "${1:-}" ]; then
	echo "ERROR: Temp update path is required as first argument"
	exit 1
fi
TEMP_UPDATE_PATH="$1"

# Optional logging to file (second argument)
if [ -n "${2:-}" ]; then
	LOG_PATH="$2"
	exec > >(tee -a "$LOG_PATH") 2>&1
fi

# Function to verify SHA256 checksum
verify_checksum() {
	local file_path="$1"
	local checksum_file="$2"

	if [ ! -f "$checksum_file" ]; then
		log_warning "Checksum file not found: $checksum_file"
		return 0
	fi

	# Try sha256sum first, then shasum as fallback
	local checksum_cmd=""
	if command -v sha256sum >/dev/null 2>&1; then
		checksum_cmd="sha256sum"
	elif command -v shasum >/dev/null 2>&1; then
		checksum_cmd="shasum -a 256"
	else
		log_warning "Neither sha256sum nor shasum available, skipping checksum verification"
		return 0
	fi

	log_info "Verifying SHA256 checksum for $file_path"
	if $DRY_RUN; then
		log_info "DRY RUN: Would verify checksum"
		return 0
	fi

	local expected_checksum
	expected_checksum=$(cat "$checksum_file" | tr -d '\n\r')
	local actual_checksum
	actual_checksum=$($checksum_cmd "$file_path" | awk '{print $1}')

	if [ "$actual_checksum" != "$expected_checksum" ]; then
		log_error "Checksum verification failed for $file_path"
		log_error "Expected: $expected_checksum"
		log_error "Actual: $actual_checksum"
		return 1
	fi

	log_success "Checksum verification passed"
	return 0
}

# Trap errors: put the previous version back if it was already moved aside
trap 'log_error "Update failed. Exiting."; restore_previous_version; exit 1' ERR

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions with timestamps
log_info() {
	echo -e "${BLUE}[$(date '+%Y-%m-%d %H:%M:%S') INFO]${NC} $1"
}

log_success() {
	echo -e "${GREEN}[$(date '+%Y-%m-%d %H:%M:%S') SUCCESS]${NC} $1"
}

log_warning() {
	echo -e "${YELLOW}[$(date '+%Y-%m-%d %H:%M:%S') WARNING]${NC} $1"
}

log_error() {
	echo -e "${RED}[$(date '+%Y-%m-%d %H:%M:%S') ERROR]${NC} $1"
}

# Function to kill RimSort process safely
kill_rimsort() {
	log_info "Stopping RimSort process..."

	if [ "$OS" = "Darwin" ]; then
		if killall -q RimSort 2>/dev/null; then
			log_success "RimSort process stopped"
		else
			log_warning "RimSort process not found or could not be killed"
		fi
	else
		if killall -q "$EXECUTABLE_NAME" 2>/dev/null; then
			log_success "$EXECUTABLE_NAME process stopped"
		else
			log_warning "$EXECUTABLE_NAME process not found or could not be killed"
		fi
	fi

	# Wait for process to fully terminate
	sleep 2
}

# Function to set permissions
set_permissions() {
	local target_dir="$1"

	log_info "Setting executable permissions..."

	if [ "$OS" = "Darwin" ]; then
		chmod +x "$target_dir/Contents/MacOS/RimSort" 2>/dev/null || log_warning "Could not set permissions for RimSort"
		chmod +x "$target_dir/Contents/MacOS/todds/todds" 2>/dev/null || log_warning "Could not set permissions for todds"
		chmod +x "$target_dir/Contents/MacOS/QtWebEngineProcess" 2>/dev/null || log_warning "Could not set permissions for QtWebEngineProcess"
	else
		chmod +x "$target_dir/$EXECUTABLE_NAME" 2>/dev/null || log_warning "Could not set permissions for $EXECUTABLE_NAME"
		chmod +x "$target_dir/todds/todds" 2>/dev/null || log_warning "Could not set permissions for todds"
		chmod +x "$target_dir/QtWebEngineProcess" 2>/dev/null || log_warning "Could not set permissions for QtWebEngineProcess"
	fi
}

# Where the current install is parked during the swap, and the staged copy
# of the new one. Both live next to the install target.
OLD_VERSION_DIR=""
STAGING_DIR=""
INSTALL_TARGET=""

# Function to put the previous version back after a failed swap
restore_previous_version() {
	if [ -n "$STAGING_DIR" ] && [ -d "$STAGING_DIR" ]; then
		rm -rf "$STAGING_DIR" 2>/dev/null || true
	fi
	if [ -z "$OLD_VERSION_DIR" ] || [ ! -d "$OLD_VERSION_DIR" ]; then
		return 0
	fi
	if [ -e "$INSTALL_TARGET" ]; then
		log_error "Previous version kept at: $OLD_VERSION_DIR"
		return 0
	fi
	if mv "$OLD_VERSION_DIR" "$INSTALL_TARGET"; then
		log_info "Previous version restored to: $INSTALL_TARGET"
	else
		log_error "Could not restore the previous version from: $OLD_VERSION_DIR"
	fi
}

# Function to install the update without a window where nothing runnable exists.
# The new files are staged next to the target and swapped in with two renames,
# so the previous version is intact until the copy has fully succeeded and can
# be put back if the swap fails. When the parent directory is not writable the
# files are synced in place instead, which cannot be rolled back.
install_update() {
	local target="$1"
	local parent
	parent="$(dirname "$target")"
	INSTALL_TARGET="$target"

	if $DRY_RUN; then
		log_info "DRY RUN: Would install $UPDATE_SOURCE_FOLDER over $target"
		rsync "${RSYNC_OPTS[@]}" --delete "$UPDATE_SOURCE_FOLDER/" "$target/"
		return 0
	fi

	if [ ! -w "$parent" ]; then
		log_warning "$parent is not writable; updating $target in place without rollback"
		if ! rsync "${RSYNC_OPTS[@]}" --delete "$UPDATE_SOURCE_FOLDER/" "$target/"; then
			log_error "Failed to sync update files to $target"
			return 1
		fi
		log_success "Update files synced"
		return 0
	fi

	STAGING_DIR="$target.new"
	OLD_VERSION_DIR="$target.old"
	rm -rf "$STAGING_DIR" "$OLD_VERSION_DIR"

	log_info "Staging new files in: $STAGING_DIR"
	if ! rsync "${RSYNC_OPTS[@]}" "$UPDATE_SOURCE_FOLDER/" "$STAGING_DIR/"; then
		log_error "Failed to copy update files to $STAGING_DIR"
		rm -rf "$STAGING_DIR"
		STAGING_DIR=""
		return 1
	fi

	log_info "Swapping in the new version"
	if [ -e "$target" ]; then
		mv "$target" "$OLD_VERSION_DIR"
	fi
	if ! mv "$STAGING_DIR" "$target"; then
		log_error "Failed to move the staged files to $target"
		restore_previous_version
		return 1
	fi
	STAGING_DIR=""
	log_success "New version installed"
}

# Function to drop the parked previous version once the new one is in place
remove_previous_version() {
	if [ -z "$OLD_VERSION_DIR" ] || [ ! -d "$OLD_VERSION_DIR" ]; then
		return 0
	fi
	log_info "Removing previous version: $OLD_VERSION_DIR"
	if rm -rf "$OLD_VERSION_DIR" 2>/dev/null; then
		log_success "Previous version removed"
	else
		log_warning "Could not remove previous version: $OLD_VERSION_DIR"
	fi
}

# Function to launch application
launch_app() {
	local app_path="$1"

	log_info "Launching updated RimSort..."

	if [ "$OS" = "Darwin" ]; then
		open "$app_path" &
	else
		# Check if running as root - GUI apps cannot run as root
		if [ "$EUID" -eq 0 ]; then
			log_warning "Cannot launch GUI application as root. Please launch RimSort manually as a regular user."
			read -r -p "Press any key to continue..."
			return
		fi
		cd "$(dirname "$app_path")"
		nohup ./"$(basename "$app_path")" >/dev/null 2>&1 &
	fi

	sleep 2

	# Verify the application started
	if [ "$OS" = "Darwin" ]; then
		if pgrep -f "RimSort" >/dev/null; then
			log_success "RimSort started successfully!"
		else
			log_warning "RimSort may not have started successfully"
		fi
	else
		if pgrep -f "$EXECUTABLE_NAME" >/dev/null; then
			log_success "RimSort started successfully!"
		else
			log_warning "$EXECUTABLE_NAME may not have started successfully"
		fi
	fi
}

# Main script starts here
echo "========================================================================
"
echo "RimSort Update Script"
echo "========================================================================
"

# Detect the operating system
OS=$(uname)
log_info "Operating system: $OS"
log_info "Current working directory: $(pwd)"
log_info "User: $(whoami)"
log_info "TMPDIR: ${TMPDIR:-not set}"

# Set variables based on OS
if [ "$OS" = "Darwin" ]; then
	# macOS detected
	EXECUTABLE_NAME="RimSort.app"
	SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"            # .../RimSort.app/Contents/MacOS
	APP_BUNDLE_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")" # .../RimSort.app
	INSTALL_PARENT_DIR="$(dirname "$APP_BUNDLE_DIR")"      # Parent of .app (e.g. /Applications)
	INSTALL_DIR="$APP_BUNDLE_DIR"                          # For common messaging
	UPDATE_SOURCE_FOLDER="$TEMP_UPDATE_PATH"

	log_info "macOS detected"
	log_info "App bundle: $APP_BUNDLE_DIR"
	log_info "Install parent: $INSTALL_PARENT_DIR"
	log_info "Update source: $UPDATE_SOURCE_FOLDER"
else
	# Assume Linux if not macOS
	EXECUTABLE_NAME="RimSort"
	SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
	INSTALL_DIR="${3:-$SCRIPT_DIR}"
	UPDATE_SOURCE_FOLDER="$TEMP_UPDATE_PATH"

	log_info "Linux detected"
	log_info "Installation directory: $INSTALL_DIR"
	log_info "Update source: $UPDATE_SOURCE_FOLDER"
fi

# Kill running processes
kill_rimsort

# ======================================================================
# AppImage self-update mode
# When $APPIMAGE is set, we are running inside an AppImage.  The update
# source ($TEMP_UPDATE_PATH) is a single .AppImage file, not a directory.
# We replace the running AppImage atomically via rename.
# ======================================================================
if [ -n "${APPIMAGE:-}" ]; then
	NEW_APPIMAGE="$TEMP_UPDATE_PATH"
	BACKUP_PATH="${APPIMAGE}.bak"

	# Override the generic ERR trap with an AppImage-specific recovery hint
	trap 'log_error "AppImage update failed. If your AppImage is missing, restore from: $BACKUP_PATH"; exit 1' ERR

	log_info "AppImage update mode"
	log_info "Current AppImage: $APPIMAGE"
	log_info "New AppImage: $NEW_APPIMAGE"

	# Validate new AppImage file exists
	if [ ! -f "$NEW_APPIMAGE" ]; then
		log_error "New AppImage file not found: $NEW_APPIMAGE"
		exit 1
	fi

	# Validate write permission to AppImage directory
	APPIMAGE_DIR="$(dirname "$APPIMAGE")"
	if [ ! -w "$APPIMAGE_DIR" ]; then
		log_error "No write permission to AppImage directory: $APPIMAGE_DIR"
		log_error "Move RimSort to a user-writable location or update manually."
		exit 1
	fi

	# Rename current AppImage to .bak (serves as backup)
	log_info "Backing up current AppImage to: $BACKUP_PATH"
	if $DRY_RUN; then
		log_info "DRY RUN: Would rename $APPIMAGE -> $BACKUP_PATH"
	else
		mv "$APPIMAGE" "$BACKUP_PATH"
	fi

	# Move new AppImage into place
	log_info "Installing new AppImage to: $APPIMAGE"
	if $DRY_RUN; then
		log_info "DRY RUN: Would move $NEW_APPIMAGE -> $APPIMAGE"
	else
		mv "$NEW_APPIMAGE" "$APPIMAGE"
		chmod +x "$APPIMAGE"
	fi

	log_success "AppImage replaced successfully"

	# Launch new AppImage
	log_info "Launching updated AppImage..."
	if [ "$(id -u)" -eq 0 ]; then
		log_warning "Cannot launch GUI application as root. Please launch RimSort manually as a regular user."
		read -r -p "Press any key to continue..."
	elif ! $DRY_RUN; then
		nohup "$APPIMAGE" >/dev/null 2>&1 &
		sleep 2
		if pgrep -xf "$APPIMAGE" >/dev/null; then
			log_success "RimSort started successfully!"
		else
			log_warning "RimSort may not have started successfully"
		fi
	fi

	log_success "AppImage update completed successfully!"
	echo "========================================================================"
	trap - ERR
	exit 0
fi

# Check if update source exists
if [ ! -d "$UPDATE_SOURCE_FOLDER" ]; then
	log_error "Update source folder does not exist: $UPDATE_SOURCE_FOLDER"
	exit 1
fi

log_info "Update source folder exists: $UPDATE_SOURCE_FOLDER"

# Adjust source folder if it contains a RimSort subdirectory (unwrapped structure)
if [ -d "$UPDATE_SOURCE_FOLDER/RimSort" ]; then
	UPDATE_SOURCE_FOLDER="$UPDATE_SOURCE_FOLDER/RimSort"
	log_info "Adjusted update source to subdirectory: $UPDATE_SOURCE_FOLDER"
fi

# On macOS, adjust source if it contains a RimSort.app bundle so rsync copies the
# bundle contents rather than nesting RimSort.app inside the target .app directory.
if [ "$OS" = "Darwin" ] && [ -d "$UPDATE_SOURCE_FOLDER/RimSort.app" ]; then
	UPDATE_SOURCE_FOLDER="$UPDATE_SOURCE_FOLDER/RimSort.app"
	log_info "Adjusted update source to .app bundle: $UPDATE_SOURCE_FOLDER"
fi

# Verify checksum if available
checksum_file="$UPDATE_SOURCE_FOLDER/checksum.sha256"
if [ -f "$checksum_file" ]; then
	# Find the main file to verify (assuming it's the executable or app bundle)
	if [ "$OS" = "Darwin" ]; then
		main_file="$UPDATE_SOURCE_FOLDER/RimSort.app"
	else
		main_file="$UPDATE_SOURCE_FOLDER/RimSort"
	fi
	if [ -e "$main_file" ]; then
		verify_checksum "$main_file" "$checksum_file" || exit 1
	else
		log_warning "Main file not found for checksum verification"
	fi
fi

# Display update confirmation
echo
echo "========================================================================
"
echo "RimSort Update Ready"
echo "========================================================================
"
echo "Source: $UPDATE_SOURCE_FOLDER"
echo "Target: $INSTALL_DIR"
echo
echo "Starting update..."
echo "========================================================================
"
echo

# Perform the update
log_info "Performing update..."
log_info "Source: $UPDATE_SOURCE_FOLDER"
log_info "Target: $INSTALL_DIR"

RSYNC_OPTS=(-av)
if $DRY_RUN; then
	RSYNC_OPTS+=(--dry-run)
fi

if [ "$OS" = "Darwin" ]; then
	# macOS update process
	log_info "Starting macOS update process"
	# Safety guard: never operate on root or /Applications itself
	if [ -z "$APP_BUNDLE_DIR" ] || [ "$APP_BUNDLE_DIR" = "/" ] || [ "$INSTALL_PARENT_DIR" = "/" ]; then
		log_error "Unsafe install paths detected. Aborting update."
		exit 1
	fi

	TARGET_BUNDLE="$INSTALL_PARENT_DIR/$EXECUTABLE_NAME"
	mkdir -p "$INSTALL_PARENT_DIR"
	install_update "$TARGET_BUNDLE" || exit 1

	# Set permissions on the newly installed app bundle
	set_permissions "$TARGET_BUNDLE"
	launch_app "$TARGET_BUNDLE"

else
	# Linux update process
	log_info "Starting Linux update process"

	install_update "$INSTALL_DIR" || exit 1

	set_permissions "$INSTALL_DIR"
	launch_app "$INSTALL_DIR/$EXECUTABLE_NAME"
fi

remove_previous_version

# Clean up temporary files
log_info "Cleaning up temporary files..."
log_info "Removing: $UPDATE_SOURCE_FOLDER"
if rm -rf "$UPDATE_SOURCE_FOLDER" 2>/dev/null; then
	log_success "Temporary files cleaned up"
else
	log_warning "Could not remove temporary folder: $UPDATE_SOURCE_FOLDER"
fi

log_success "RimSort update completed successfully!"
echo "========================================================================
"

# Clear trap on successful exit
trap - ERR

exit 0
