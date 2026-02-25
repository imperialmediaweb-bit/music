"""Set up OS-level scheduled tasks for the music pipeline.

Creates crontab entries (Linux/macOS) or Windows Task Scheduler tasks
so the pipeline runs automatically WITHOUT needing a terminal open.

This replaces the APScheduler approach which requires keeping PowerShell
or a terminal running permanently.
"""

import os
import sys
import platform
import subprocess
from pathlib import Path

from utils.logger import log


def _get_python_path() -> str:
    """Get the absolute path to the current Python interpreter."""
    return sys.executable


def _get_project_dir() -> str:
    """Get the absolute path to the project directory."""
    return str(Path(__file__).parent.parent.resolve())


def setup_crontab(schedule_slots: list[tuple[int, int, int]], remove: bool = False):
    """Set up crontab entries for the music pipeline (Linux/macOS).

    Args:
        schedule_slots: List of (hour, minute, gen_count) tuples.
        remove: If True, remove existing pipeline entries instead.
    """
    python = _get_python_path()
    project_dir = _get_project_dir()
    marker = "# music-pipeline-auto"

    # Read existing crontab
    try:
        result = subprocess.run(
            ["crontab", "-l"], capture_output=True, text=True
        )
        existing = result.stdout if result.returncode == 0 else ""
    except FileNotFoundError:
        log.error("crontab not found. Install cron: sudo apt install cron")
        return False

    # Remove old pipeline entries
    lines = [
        line for line in existing.splitlines()
        if marker not in line
    ]

    if remove:
        new_crontab = "\n".join(lines) + "\n" if lines else ""
        _write_crontab(new_crontab)
        log.info("Removed all music pipeline crontab entries")
        return True

    # Add new entries
    for hour, minute, gen_count in schedule_slots:
        cmd = f"cd {project_dir} && {python} main.py run -n 1"
        cron_line = f"{minute} {hour} * * * {cmd} >> {project_dir}/output/cron.log 2>&1 {marker}"
        lines.append(cron_line)

    new_crontab = "\n".join(lines) + "\n"
    _write_crontab(new_crontab)
    return True


def _write_crontab(content: str):
    """Write content to crontab."""
    proc = subprocess.run(
        ["crontab", "-"],
        input=content,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        log.error(f"Failed to write crontab: {proc.stderr}")
        raise RuntimeError(f"crontab write failed: {proc.stderr}")


def setup_windows_tasks(schedule_slots: list[tuple[int, int, int]], remove: bool = False):
    """Set up Windows Task Scheduler tasks for the music pipeline.

    Creates scheduled tasks that run `python main.py run` at specified times.
    Does NOT require PowerShell to stay open.

    Args:
        schedule_slots: List of (hour, minute, gen_count) tuples.
        remove: If True, remove existing pipeline tasks instead.
    """
    python = _get_python_path()
    project_dir = _get_project_dir()
    task_prefix = "MusicPipeline"

    if remove:
        # Remove all existing pipeline tasks
        for i in range(1, 9):
            task_name = f"{task_prefix}_{i}"
            try:
                subprocess.run(
                    ["schtasks", "/Delete", "/TN", task_name, "/F"],
                    capture_output=True, text=True,
                )
                log.info(f"Removed task: {task_name}")
            except Exception:
                pass
        log.info("Removed all music pipeline scheduled tasks")
        return True

    # Create tasks
    for i, (hour, minute, gen_count) in enumerate(schedule_slots, 1):
        task_name = f"{task_prefix}_{i}"
        start_time = f"{hour:02d}:{minute:02d}"

        # First remove old task with same name (if exists)
        subprocess.run(
            ["schtasks", "/Delete", "/TN", task_name, "/F"],
            capture_output=True, text=True,
        )

        # Create the scheduled task
        cmd = f'"{python}" main.py run -n 1'
        result = subprocess.run(
            [
                "schtasks", "/Create",
                "/TN", task_name,
                "/TR", f'cmd /c "cd /d {project_dir} && {cmd}"',
                "/SC", "DAILY",
                "/ST", start_time,
                "/F",  # Force overwrite
            ],
            capture_output=True, text=True,
        )

        if result.returncode == 0:
            log.info(f"Created task: {task_name} at {start_time}")
        else:
            log.error(f"Failed to create task {task_name}: {result.stderr}")
            return False

    return True


def setup_schedule(schedule_slots: list[tuple[int, int, int]], remove: bool = False) -> bool:
    """Auto-detect OS and set up scheduled tasks.

    Args:
        schedule_slots: List of (hour, minute, gen_count) tuples.
        remove: If True, remove scheduled tasks instead.

    Returns:
        True on success.
    """
    system = platform.system()

    if system == "Windows":
        log.info("Detected Windows — using Task Scheduler (schtasks)")
        success = setup_windows_tasks(schedule_slots, remove=remove)
        if success and not remove:
            log.info("")
            log.info("Windows Task Scheduler tasks created!")
            log.info("The pipeline will run automatically — no PowerShell needed.")
            log.info("")
            log.info("To verify: open Task Scheduler (taskschd.msc)")
            log.info("To remove: python main.py setup-schedule --remove")
    elif system in ("Linux", "Darwin"):
        log.info(f"Detected {system} — using crontab")
        success = setup_crontab(schedule_slots, remove=remove)
        if success and not remove:
            log.info("")
            log.info("Crontab entries created!")
            log.info("The pipeline will run automatically in the background.")
            log.info("")
            log.info("To verify: crontab -l")
            log.info("To remove: python main.py setup-schedule --remove")
    else:
        log.error(f"Unsupported OS: {system}")
        log.info("Supported: Windows, Linux, macOS")
        return False

    return success


def list_schedule() -> None:
    """List current scheduled pipeline tasks."""
    system = platform.system()

    if system == "Windows":
        result = subprocess.run(
            ["schtasks", "/Query", "/FO", "TABLE"],
            capture_output=True, text=True,
        )
        lines = [
            line for line in result.stdout.splitlines()
            if "MusicPipeline" in line
        ]
        if lines:
            log.info("Current scheduled tasks:")
            for line in lines:
                log.info(f"  {line.strip()}")
        else:
            log.info("No music pipeline tasks found in Task Scheduler")

    elif system in ("Linux", "Darwin"):
        result = subprocess.run(
            ["crontab", "-l"], capture_output=True, text=True,
        )
        lines = [
            line for line in result.stdout.splitlines()
            if "music-pipeline-auto" in line
        ]
        if lines:
            log.info("Current crontab entries:")
            for line in lines:
                log.info(f"  {line.strip()}")
        else:
            log.info("No music pipeline entries found in crontab")
    else:
        log.error(f"Unsupported OS: {system}")
