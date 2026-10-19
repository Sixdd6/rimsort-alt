"""Windows update launch arguments: the install folder must be explicit.

update.bat is run from a copy in app storage and, when elevated, cmd changes
directory first, so the script cannot derive the install folder from %CD%.
"""

from pathlib import Path

from app.utils.app_info import AppInfo
from app.utils.update_utils import ScriptConfig


def _config() -> ScriptConfig:
    return ScriptConfig("update.bat", "Windows")


def test_unelevated_windows_args_pass_the_install_folder() -> None:
    script = AppInfo().app_storage_folder / "update.bat"
    args = _config().get_args(script, Path("C:/tmp/upd"), Path("C:/tmp/log.txt"))

    assert args == [
        "cmd",
        "/k",
        str(script),
        str(Path("C:/tmp/upd")),
        str(Path("C:/tmp/log.txt")),
        str(AppInfo().application_folder),
    ]


def test_elevated_windows_args_change_to_the_install_folder_not_the_script_folder() -> (
    None
):
    script = AppInfo().app_storage_folder / "update.bat"
    command = _config().get_args(
        script, Path("C:/tmp/upd"), Path("C:/tmp/log.txt"), needs_elevation=True
    )

    assert isinstance(command, str)
    install_dir = str(AppInfo().application_folder)
    assert f'cd /d "{install_dir}" && "{script}"' in command
    assert command.count(f'"{install_dir}"') == 2  # cd target and script argument
    assert f'cd /d "{script.parent}"' not in command
