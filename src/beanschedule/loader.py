"""YAML schedule file loader and validator."""

import logging
import os
from pathlib import Path
from typing import List, Optional, Tuple

import yaml

from .schema import GlobalConfig, Schedule, ScheduleFile

logger = logging.getLogger(__name__)


def find_schedules_location() -> Optional[Tuple[str, Path]]:
    """
    Locate schedules configuration (directory or file).

    Search order (highest to lowest priority):
    1. BEANSCHEDULE_DIR environment variable → directory mode
    2. BEANSCHEDULE_FILE environment variable → file mode
    3. schedules/ directory in current directory → directory mode
    4. schedules.yaml in current directory → file mode (backward compat)
    5. schedules/ in parent of importers/config.py → directory mode
    6. schedules.yaml in parent of importers/config.py → file mode (backward compat)

    Returns:
        Tuple of ("dir", Path) or ("file", Path), or None if not found
    """
    # Check BEANSCHEDULE_DIR env var (new directory mode)
    if env_dir := os.getenv("BEANSCHEDULE_DIR"):
        path = Path(env_dir)
        if path.is_dir():
            return ("dir", path)
        logger.warning(f"BEANSCHEDULE_DIR points to non-existent directory: {env_dir}")

    # Check BEANSCHEDULE_FILE env var (existing file mode)
    if env_file := os.getenv("BEANSCHEDULE_FILE"):
        path = Path(env_file)
        if path.is_file():
            return ("file", path)
        logger.warning(f"BEANSCHEDULE_FILE points to non-existent file: {env_file}")

    # Check current directory for schedules/ (directory mode)
    cwd_dir = Path.cwd() / "schedules"
    if cwd_dir.is_dir():
        return ("dir", cwd_dir)

    # Check current directory for schedules.yaml (file mode, backward compat)
    cwd_file = Path.cwd() / "schedules.yaml"
    if cwd_file.is_file():
        return ("file", cwd_file)

    # Check config.py parent directory (typical location)
    try:
        config_dir = Path(__file__).parent.parent.parent

        # Check for schedules/ directory
        config_schedules_dir = config_dir / "schedules"
        if config_schedules_dir.is_dir():
            return ("dir", config_schedules_dir)

        # Check for schedules.yaml file (backward compat)
        config_schedules_file = config_dir / "schedules.yaml"
        if config_schedules_file.is_file():
            return ("file", config_schedules_file)
    except Exception as e:
        logger.debug(f"Error checking config parent directory: {e}")

    return None


def find_schedules_file() -> Optional[Path]:
    """
    Locate schedules.yaml file.

    DEPRECATED: Use find_schedules_location() instead for directory support.
    Maintained for backward compatibility.

    Search order:
    1. BEANSCHEDULE_FILE environment variable
    2. schedules.yaml in current directory
    3. schedules.yaml in parent of importers/config.py

    Returns:
        Path to schedules.yaml or None if not found
    """
    location = find_schedules_location()
    if location is None:
        return None

    mode, path = location
    if mode == "file":
        return path
    # Directory mode found, but caller expects file
    # Return None to indicate file not found
    return None


def load_schedule_from_file(filepath: Path) -> Optional[Schedule]:
    """
    Load a single schedule from an individual YAML file.

    Args:
        filepath: Path to individual schedule YAML file

    Returns:
        Schedule object or None if file is invalid

    Note:
        Errors are logged but not raised - allows directory loading to continue
    """
    try:
        with open(filepath) as f:
            data = yaml.safe_load(f)

        if data is None:
            logger.warning(f"Empty schedule file: {filepath}")
            return None

        # Validate and parse with Pydantic
        schedule = Schedule(**data)

        # Validate filename matches schedule ID
        expected_filename = f"{schedule.id}.yaml"
        if filepath.name != expected_filename:
            logger.error(
                f"Failed to load schedule from '{filepath}':\n"
                f"  Schedule ID '{schedule.id}' does not match filename.\n"
                f"  Expected: '{expected_filename}'\n"
                f"  Found: '{filepath.name}'\n"
                f"  Fix: Rename file to '{expected_filename}' or change 'id' field to '{filepath.stem}'",
            )
            return None

        return schedule

    except yaml.YAMLError as e:
        logger.error(f"YAML parsing error in '{filepath}': {e}")
        return None
    except Exception as e:
        logger.error(f"Failed to load schedule from '{filepath}': {e}")
        return None


def load_schedules_from_directory(dirpath: Path) -> Optional[ScheduleFile]:
    """
    Load all schedules from a directory structure.

    Directory structure:
        schedules/
        ├── _config.yaml           # Global config (optional)
        ├── schedule-id-1.yaml     # Individual schedule files
        ├── schedule-id-2.yaml
        └── ...

    Args:
        dirpath: Path to schedules directory

    Returns:
        ScheduleFile object with all loaded schedules
    """
    logger.info(f"Loading schedules from directory: {dirpath}")

    # Load global config
    config_path = dirpath / "_config.yaml"
    config = GlobalConfig()  # Default config

    if config_path.is_file():
        try:
            with open(config_path) as f:
                config_data = yaml.safe_load(f)

            if config_data is not None:
                config = GlobalConfig(**config_data)
                logger.debug(f"Loaded global config from: {config_path}")
        except Exception as e:
            logger.warning(f"Failed to load config from '{config_path}', using defaults: {e}")

    # Load all schedule files
    schedules = []
    schedule_files = sorted(dirpath.glob("*.yaml"))

    for schedule_path in schedule_files:
        # Skip config file
        if schedule_path.name == "_config.yaml":
            continue

        # Skip hidden files
        if schedule_path.name.startswith("."):
            continue

        schedule = load_schedule_from_file(schedule_path)
        if schedule is not None:
            schedules.append(schedule)

    # Check for duplicate IDs
    seen_ids = {}
    for schedule in schedules:
        if schedule.id in seen_ids:
            logger.error(
                f"Duplicate schedule ID '{schedule.id}' found in multiple files:\n"
                f"  First: {seen_ids[schedule.id]}\n"
                f"  Duplicate: {dirpath / f'{schedule.id}.yaml'}\n"
                f"  The duplicate will be ignored.",
            )
        else:
            seen_ids[schedule.id] = dirpath / f"{schedule.id}.yaml"

    # Remove duplicates (keep first occurrence)
    unique_schedules = []
    seen_ids_set = set()
    for schedule in schedules:
        if schedule.id not in seen_ids_set:
            unique_schedules.append(schedule)
            seen_ids_set.add(schedule.id)

    schedule_file = ScheduleFile(schedules=unique_schedules, config=config)

    logger.info(
        f"Loaded {len(schedule_file.schedules)} schedules "
        f"({sum(1 for s in schedule_file.schedules if s.enabled)} enabled) "
        f"from directory: {dirpath}",
    )

    return schedule_file


def load_schedules_file(filepath: Optional[Path] = None) -> Optional[ScheduleFile]:
    """
    Load and validate schedules (supports both directory and file formats).

    Supports two formats:
    1. Directory mode: schedules/ directory with individual YAML files
    2. File mode: single schedules.yaml file (legacy/backward compat)

    Args:
        filepath: Optional explicit path to schedules file.
                  If provided, loads as single file (legacy mode).
                  If None, uses find_schedules_location() to auto-discover.

    Returns:
        ScheduleFile object or None if not found or invalid

    Raises:
        yaml.YAMLError: If YAML parsing fails (file mode only)
        pydantic.ValidationError: If schema validation fails (file mode only)
    """
    # If explicit filepath provided, use legacy single-file loading
    if filepath is not None:
        logger.info(f"Loading schedules from: {filepath}")

        try:
            with open(filepath) as f:
                data = yaml.safe_load(f)

            if data is None:
                logger.warning(f"Empty schedules file: {filepath}")
                return ScheduleFile(schedules=[], config=GlobalConfig())

            # Handle case where schedules key is None (all commented out)
            if data.get("schedules") is None:
                data["schedules"] = []

            # Validate and parse with Pydantic
            schedule_file = ScheduleFile(**data)
            logger.info(
                f"Loaded {len(schedule_file.schedules)} schedules "
                f"({sum(1 for s in schedule_file.schedules if s.enabled)} enabled)",
            )

            return schedule_file

        except yaml.YAMLError as e:
            logger.error(f"YAML parsing error in {filepath}: {e}")
            raise
        except Exception as e:
            logger.error(f"Error loading schedules from {filepath}: {e}")
            raise

    # Auto-discover using new location finder
    location = find_schedules_location()

    if location is None:
        logger.info("No schedules file or directory found, schedule matching disabled")
        return None

    mode, path = location

    if mode == "dir":
        return load_schedules_from_directory(path)
    # mode == "file"
    logger.info(f"Loading schedules from: {path}")

    try:
        with open(path) as f:
            data = yaml.safe_load(f)

        if data is None:
            logger.warning(f"Empty schedules file: {path}")
            return ScheduleFile(schedules=[], config=GlobalConfig())

        # Handle case where schedules key is None (all commented out)
        if data.get("schedules") is None:
            data["schedules"] = []

        # Validate and parse with Pydantic
        schedule_file = ScheduleFile(**data)
        logger.info(
            f"Loaded {len(schedule_file.schedules)} schedules "
            f"({sum(1 for s in schedule_file.schedules if s.enabled)} enabled)",
        )

        return schedule_file

    except yaml.YAMLError as e:
        logger.error(f"YAML parsing error in {path}: {e}")
        raise
    except Exception as e:
        logger.error(f"Error loading schedules from {path}: {e}")
        raise


def get_enabled_schedules(schedule_file: Optional[ScheduleFile]) -> List[Schedule]:
    """
    Get list of enabled schedules.

    Args:
        schedule_file: ScheduleFile object or None

    Returns:
        List of enabled Schedule objects
    """
    if schedule_file is None:
        return []

    return [s for s in schedule_file.schedules if s.enabled]
