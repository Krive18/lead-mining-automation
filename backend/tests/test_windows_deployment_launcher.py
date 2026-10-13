import os
import shutil
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


WORKSPACE_DIR = Path(__file__).resolve().parents[2]


class WindowsDeploymentLauncherTest(unittest.TestCase):
    def build_test_package(self, target_dir: Path) -> None:
        target_dir.mkdir(parents=True)
        (target_dir / "deployment" / "windows").mkdir(parents=True)
        (target_dir / "backend").mkdir()
        (target_dir / "frontend").mkdir()

        shutil.copy2(WORKSPACE_DIR / "setup_environment.bat", target_dir / "setup_environment.bat")
        shutil.copy2(WORKSPACE_DIR / "一键配置环境.bat", target_dir / "一键配置环境.bat")
        shutil.copy2(
            WORKSPACE_DIR / "deployment" / "windows" / "setup_env.ps1",
            target_dir / "deployment" / "windows" / "setup_env.ps1",
        )
        (target_dir / "backend" / "requirements.txt").write_text("", encoding="utf-8")
        (target_dir / "backend" / ".env.example").write_text("", encoding="utf-8")
        (target_dir / "frontend" / "package.json").write_text("{}", encoding="utf-8")

    def run_launcher(self, launcher: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", str(launcher), "-PreflightOnly"],
            cwd=launcher.parent,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    def test_setup_reuses_system_edge_without_running_playwright_edge_installer(self):
        setup_script = (
            WORKSPACE_DIR / "deployment" / "windows" / "setup_env.ps1"
        ).read_text(encoding="utf-8")

        self.assertIn("-m playwright install chromium", setup_script)
        self.assertNotIn("-m playwright install msedge", setup_script)
        self.assertIn("Find-SystemEdgeExecutable", setup_script)

    @unittest.skipUnless(os.name == "nt", "Windows launcher test")
    def test_ascii_launcher_runs_from_unicode_path_with_spaces_and_parentheses(self):
        with TemporaryDirectory() as tmp_dir:
            package_dir = Path(tmp_dir) / "Automation AI 部署 (1)"
            self.build_test_package(package_dir)

            result = self.run_launcher(package_dir / "setup_environment.bat")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Preflight passed", result.stdout)

    @unittest.skipUnless(os.name == "nt", "Windows launcher test")
    def test_chinese_launcher_delegates_to_ascii_launcher(self):
        with TemporaryDirectory() as tmp_dir:
            package_dir = Path(tmp_dir) / "Automation AI 部署 (1)"
            self.build_test_package(package_dir)

            result = self.run_launcher(package_dir / "一键配置环境.bat")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Preflight passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
