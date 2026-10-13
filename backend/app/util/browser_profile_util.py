import os
import subprocess
from pathlib import Path
from typing import List


def list_browser_profile_process_id(profile_dir: Path) -> List[int]:
    if os.name != "nt":
        return []
    profile_path = str(profile_dir).replace("'", "''")
    command = (
        f"$profile='{profile_path}'; "
        "Get-CimInstance Win32_Process | "
        "Where-Object { "
        "($_.Name -eq 'msedge.exe' -or $_.Name -eq 'chrome.exe' -or $_.Name -eq 'chromium.exe') "
        "-and $_.CommandLine -like \"*$profile*\" "
        "} | Select-Object -ExpandProperty ProcessId"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    process_id_list = []
    for line in result.stdout.splitlines():
        clean_line = line.strip()
        if clean_line.isdigit():
            process_id_list.append(int(clean_line))
    return process_id_list


def stop_process_id_list(process_id_list: List[int]) -> None:
    if not process_id_list:
        return
    id_text = ",".join(str(process_id) for process_id in process_id_list)
    command = f"$ids=@({id_text}); Stop-Process -Id $ids -Force"
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
