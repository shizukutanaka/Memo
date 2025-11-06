#!/usr/bin/env python3
"""Platform compatibility utilities for Windows/macOS/Linux."""

import os
import sys
import platform
from pathlib import Path
from typing import Optional, Dict, Any, List
import subprocess
import shutil
import logging

logger = logging.getLogger(__name__)


class PlatformInfo:
    """Detect and provide platform information."""

    @staticmethod
    def get_system() -> str:
        """Get operating system name."""
        return platform.system()

    @staticmethod
    def is_windows() -> bool:
        """Check if running on Windows."""
        return PlatformInfo.get_system() == "Windows"

    @staticmethod
    def is_macos() -> bool:
        """Check if running on macOS."""
        return PlatformInfo.get_system() == "Darwin"

    @staticmethod
    def is_linux() -> bool:
        """Check if running on Linux."""
        return PlatformInfo.get_system() == "Linux"

    @staticmethod
    def get_platform_name() -> str:
        """Get platform name."""
        if PlatformInfo.is_windows():
            return "windows"
        elif PlatformInfo.is_macos():
            return "macos"
        else:
            return "linux"

    @staticmethod
    def get_python_version() -> str:
        """Get Python version."""
        return platform.python_version()

    @staticmethod
    def get_architecture() -> str:
        """Get system architecture."""
        return platform.machine()

    @staticmethod
    def get_info() -> Dict[str, str]:
        """Get comprehensive platform information."""
        return {
            "system": PlatformInfo.get_system(),
            "platform": PlatformInfo.get_platform_name(),
            "python_version": PlatformInfo.get_python_version(),
            "architecture": PlatformInfo.get_architecture(),
            "processor": platform.processor() or "unknown"
        }


class PathUtils:
    """Platform-aware path utilities."""

    @staticmethod
    def get_home_dir() -> Path:
        """Get user home directory."""
        return Path.home()

    @staticmethod
    def get_config_dir() -> Path:
        """
        Get platform-specific config directory.

        Returns:
            Path to config directory
        """
        if PlatformInfo.is_windows():
            # Windows: %APPDATA%/memo
            appdata = os.getenv("APPDATA")
            if appdata:
                return Path(appdata) / "memo"
            return Path.home() / "AppData" / "Roaming" / "memo"

        elif PlatformInfo.is_macos():
            # macOS: ~/Library/Application Support/memo
            return Path.home() / "Library" / "Application Support" / "memo"

        else:
            # Linux: ~/.config/memo (XDG standard)
            config_home = os.getenv("XDG_CONFIG_HOME")
            if config_home:
                return Path(config_home) / "memo"
            return Path.home() / ".config" / "memo"

    @staticmethod
    def get_data_dir() -> Path:
        """
        Get platform-specific data directory.

        Returns:
            Path to data directory
        """
        if PlatformInfo.is_windows():
            # Windows: %APPDATA%/memo/data
            return PathUtils.get_config_dir() / "data"

        elif PlatformInfo.is_macos():
            # macOS: ~/Library/Application Support/memo/data
            return PathUtils.get_config_dir() / "data"

        else:
            # Linux: ~/.local/share/memo (XDG standard)
            data_home = os.getenv("XDG_DATA_HOME")
            if data_home:
                return Path(data_home) / "memo"
            return Path.home() / ".local" / "share" / "memo"

    @staticmethod
    def get_cache_dir() -> Path:
        """
        Get platform-specific cache directory.

        Returns:
            Path to cache directory
        """
        if PlatformInfo.is_windows():
            # Windows: %TEMP%/memo
            temp = os.getenv("TEMP")
            if temp:
                return Path(temp) / "memo"
            return Path(os.path.expandvars("%TEMP%")) / "memo"

        elif PlatformInfo.is_macos():
            # macOS: ~/Library/Caches/memo
            return Path.home() / "Library" / "Caches" / "memo"

        else:
            # Linux: ~/.cache/memo (XDG standard)
            cache_home = os.getenv("XDG_CACHE_HOME")
            if cache_home:
                return Path(cache_home) / "memo"
            return Path.home() / ".cache" / "memo"

    @staticmethod
    def get_logs_dir() -> Path:
        """Get platform-specific logs directory."""
        if PlatformInfo.is_windows():
            return PathUtils.get_config_dir() / "logs"
        elif PlatformInfo.is_macos():
            return Path.home() / "Library" / "Logs" / "memo"
        else:
            return PathUtils.get_config_dir() / "logs"

    @staticmethod
    def normalize_path(path: str) -> Path:
        """
        Normalize path for current platform.

        Args:
            path: Path string

        Returns:
            Normalized Path object
        """
        return Path(path).expanduser().resolve()


class ShellUtils:
    """Platform-aware shell utilities."""

    @staticmethod
    def open_file(file_path: Path) -> bool:
        """
        Open file with default application.

        Args:
            file_path: Path to file

        Returns:
            True if successful
        """
        try:
            if PlatformInfo.is_windows():
                os.startfile(file_path)
            elif PlatformInfo.is_macos():
                subprocess.run(["open", str(file_path)], check=True)
            else:  # Linux
                subprocess.run(["xdg-open", str(file_path)], check=True)

            return True

        except Exception as e:
            logger.error(f"Failed to open file: {e}")
            return False

    @staticmethod
    def open_directory(dir_path: Path) -> bool:
        """
        Open directory with file manager.

        Args:
            dir_path: Path to directory

        Returns:
            True if successful
        """
        try:
            if PlatformInfo.is_windows():
                os.startfile(dir_path)
            elif PlatformInfo.is_macos():
                subprocess.run(["open", str(dir_path)], check=True)
            else:  # Linux
                subprocess.run(["xdg-open", str(dir_path)], check=True)

            return True

        except Exception as e:
            logger.error(f"Failed to open directory: {e}")
            return False

    @staticmethod
    def get_shell_command() -> str:
        """
        Get appropriate shell command for platform.

        Returns:
            Shell command
        """
        if PlatformInfo.is_windows():
            return "cmd.exe"
        else:
            return os.getenv("SHELL", "/bin/bash")

    @staticmethod
    def execute_command(command: str, shell: bool = True) -> int:
        """
        Execute shell command.

        Args:
            command: Command to execute
            shell: Whether to use shell

        Returns:
            Return code
        """
        try:
            result = subprocess.run(command, shell=shell, capture_output=True)
            return result.returncode

        except Exception as e:
            logger.error(f"Command execution failed: {e}")
            return -1


class FileSystemUtils:
    """Platform-aware file system utilities."""

    @staticmethod
    def set_file_permissions(file_path: Path, mode: int) -> bool:
        """
        Set file permissions (Unix-like systems only).

        Args:
            file_path: Path to file
            mode: Permission mode (e.g., 0o600)

        Returns:
            True if successful
        """
        if PlatformInfo.is_windows():
            # Windows doesn't support Unix permissions
            return True

        try:
            os.chmod(file_path, mode)
            return True

        except Exception as e:
            logger.error(f"Failed to set permissions: {e}")
            return False

    @staticmethod
    def get_file_size(file_path: Path) -> int:
        """
        Get file size in bytes.

        Args:
            file_path: Path to file

        Returns:
            File size in bytes
        """
        try:
            return file_path.stat().st_size
        except Exception as e:
            logger.error(f"Failed to get file size: {e}")
            return 0

    @staticmethod
    def is_symlink_supported() -> bool:
        """Check if symlinks are supported."""
        return not PlatformInfo.is_windows() or sys.version_info >= (3, 8)

    @staticmethod
    def create_symlink(source: Path, target: Path) -> bool:
        """
        Create symlink (if supported).

        Args:
            source: Source path
            target: Target path

        Returns:
            True if successful
        """
        if not FileSystemUtils.is_symlink_supported():
            logger.warning("Symlinks not supported on this platform")
            return False

        try:
            target.symlink_to(source)
            return True

        except Exception as e:
            logger.error(f"Failed to create symlink: {e}")
            return False


class EnvironmentUtils:
    """Platform-aware environment utilities."""

    @staticmethod
    def get_env_var(name: str, default: Optional[str] = None) -> Optional[str]:
        """
        Get environment variable.

        Args:
            name: Variable name
            default: Default value

        Returns:
            Variable value
        """
        return os.getenv(name, default)

    @staticmethod
    def set_env_var(name: str, value: str) -> bool:
        """
        Set environment variable (current session only).

        Args:
            name: Variable name
            value: Variable value

        Returns:
            True if successful
        """
        try:
            os.environ[name] = value
            return True
        except Exception as e:
            logger.error(f"Failed to set environment variable: {e}")
            return False

    @staticmethod
    def get_path_separator() -> str:
        """Get path separator for platform."""
        return os.pathsep

    @staticmethod
    def get_line_separator() -> str:
        """Get line separator for platform."""
        return os.linesep

    @staticmethod
    def find_executable(name: str) -> Optional[Path]:
        """
        Find executable in PATH.

        Args:
            name: Executable name

        Returns:
            Path to executable or None
        """
        found = shutil.which(name)
        return Path(found) if found else None


class TerminalUtils:
    """Terminal and console utilities."""

    @staticmethod
    def is_tty() -> bool:
        """Check if output is to a terminal."""
        return sys.stdout.isatty()

    @staticmethod
    def get_terminal_width() -> int:
        """Get terminal width in characters."""
        try:
            return shutil.get_terminal_size().columns
        except Exception:
            return 80

    @staticmethod
    def get_terminal_height() -> int:
        """Get terminal height in characters."""
        try:
            return shutil.get_terminal_size().lines
        except Exception:
            return 24

    @staticmethod
    def clear_screen() -> None:
        """Clear terminal screen."""
        command = "cls" if PlatformInfo.is_windows() else "clear"
        os.system(command)

    @staticmethod
    def supports_colors() -> bool:
        """Check if terminal supports colors."""
        if PlatformInfo.is_windows():
            # Windows 10+ supports ANSI colors
            return sys.version_info >= (3, 6)

        return TerminalUtils.is_tty()


if __name__ == "__main__":
    # Display platform information
    print("=== Platform Information ===")
    info = PlatformInfo.get_info()
    for key, value in info.items():
        print(f"{key}: {value}")

    # Display directory paths
    print("\n=== Directory Paths ===")
    print(f"Home: {PathUtils.get_home_dir()}")
    print(f"Config: {PathUtils.get_config_dir()}")
    print(f"Data: {PathUtils.get_data_dir()}")
    print(f"Cache: {PathUtils.get_cache_dir()}")
    print(f"Logs: {PathUtils.get_logs_dir()}")

    # Display terminal information
    print("\n=== Terminal Information ===")
    print(f"Is TTY: {TerminalUtils.is_tty()}")
    print(f"Width: {TerminalUtils.get_terminal_width()}")
    print(f"Height: {TerminalUtils.get_terminal_height()}")
    print(f"Supports colors: {TerminalUtils.supports_colors()}")

    # Display environment
    print("\n=== Environment ===")
    print(f"Path separator: {EnvironmentUtils.get_path_separator()}")
    print(f"Line separator: {repr(EnvironmentUtils.get_line_separator())}")
    print(f"Python: {EnvironmentUtils.find_executable('python')}")
