"""
launcher.py — точка входа для скомпилированного и исходного приложения.
Запускает Streamlit, открывает браузер, ждёт завершения.
"""
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path


def _app_root() -> Path:
    if getattr(sys, "frozen", False):
        meipass = Path(sys._MEIPASS)
        if (meipass / "app.py").exists():
            return meipass
        exe_dir = Path(sys.executable).parent
        if (exe_dir / "app.py").exists():
            return exe_dir
        if (exe_dir.parent / "Resources" / "app.py").exists():
            return exe_dir.parent / "Resources"
        return exe_dir
    return Path(__file__).parent


def _find_free_port(start=8501):
    import socket
    for port in range(start, start + 100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return start


def _wait_for_server(url: str, timeout: float = 30.0) -> bool:
    import urllib.request
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            resp = urllib.request.urlopen(url, timeout=3)
            if resp.status == 200:
                return True
        except Exception:
            time.sleep(0.5)
    return False


def _open_browser_after_delay(url: str, delay: float = 3.0):
    time.sleep(delay)
    webbrowser.open(url)


def main():
    root = _app_root()
    os.chdir(root)

    port = _find_free_port()
    url = f"http://localhost:{port}"
    app_path = root / "app.py"

    print(f"🏪 Retail Location Analyzer")
    print(f"   Порт: {port}")
    print()

    if not app_path.exists():
        print(f"❌ Не найден app.py в {root}")
        print(f"   Содержимое: {list(root.iterdir())}")
        input("Нажмите Enter для выхода...")
        return 1

    # Установка зависимостей (только при запуске из исходников)
    if not getattr(sys, "frozen", False):
        deps_flag = root / ".deps_installed"
        if not deps_flag.exists():
            print("📦 Устанавливаю зависимости...")
            import subprocess
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "-q", "-r", "requirements.txt"]
            )
            deps_flag.touch()
            print("✅ Готово")
            print()

    print("🚀 Запуск сервера...")

    os.environ["STREAMLIT_SERVER_PORT"] = str(port)
    os.environ["STREAMLIT_SERVER_HEADLESS"] = "true"
    os.environ["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    os.environ["STREAMLIT_SERVER_FILE_WATCHER_TYPE"] = "none"
    os.environ["STREAMLIT_GLOBAL_DEVELOPMENT_MODE"] = "false"

    # Запускаем поток, который откроет браузер после старта сервера
    threading.Thread(target=_open_browser_after_delay, args=(url,), daemon=True).start()

    if getattr(sys, "frozen", False):
        # Скомпилированная версия: streamlit.run в том же процессе
        from streamlit.web import cli as stcli
        sys.argv = [
            "streamlit", "run", str(app_path),
            "--server.port", str(port),
            "--server.headless", "true",
            "--browser.gatherUsageStats", "false",
            "--server.fileWatcherType", "none",
            "--global.developmentMode", "false",
        ]
        from streamlit.web import cli as stcli
        stcli.main()
    else:
        import subprocess
        proc = subprocess.Popen(
            [sys.executable, "-m", "streamlit", "run", str(app_path),
             "--server.port", str(port),
             "--server.headless", "true",
             "--browser.gatherUsageStats", "false",
             "--server.fileWatcherType", "none",
             "--global.developmentMode", "false"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        for line in proc.stdout:
            print(line.decode("utf-8", errors="replace"), end="")
        proc.wait()

    return 0


if __name__ == "__main__":
    sys.exit(main())
