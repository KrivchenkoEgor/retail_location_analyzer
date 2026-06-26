"""
build_mac.py — сборка .app для macOS через PyInstaller.
Запуск: python build_mac.py
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
DIST = ROOT / "dist"

APP_NAME = "RetailLocationAnalyzer"

# Очистка
for p in [ROOT / "build", DIST]:
    if p.exists():
        shutil.rmtree(p)

# Исключаем неиспользуемые тяжёлые пакеты, чтобы .app не весил 4+ ГБ
EXCLUDES = [
    "tensorflow", "torch", "torchvision", "jax", "jaxlib",
    "boto3", "botocore", "s3fs", "gcsfs", "fsspec",
    "scipy", "scikit-learn", "sklearn",
    "matplotlib", "PIL",
    "cv2", "opencv-python",
    "transformers", "datasets",
    "numba", "llvmlite", "lightgbm", "xgboost",
    "psycopg2", "sqlalchemy", "alembic",
    "pyspark", "dask",
    "sympy", "statsmodels",
    "h5py", "grpcio",
    "lightning", "pytorch_lightning",
    "mxnet", "keras",
    "IPython", "jupyter",
    "notebook", "nbformat",
    "google_auth", "google.api", "google.cloud", "google.oauth2",
    "google.auth", "google.type", "google.rpc", "google.longrunning",
    "google.logging", "google.monitoring", "google.iam", "google.api_core",
    "kubernetes", "docker",
    "snowflake", "snowflake_connector",
    "Flask", "Django", "fastapi",
    "uvicorn", "gunicorn",
    "celery", "redis",
    "pytest", "nose",
    "sphinx", "docutils",
]

cmd = [
    sys.executable, "-m", "PyInstaller",
    "--onedir",
    "--name", APP_NAME,
    "--distpath", str(DIST),
    "--add-data", f"{ROOT / 'app.py'}{os.pathsep}.",
    "--add-data", f"{ROOT / 'config.py'}{os.pathsep}.",
    "--add-data", f"{ROOT / 'core'}{os.pathsep}core",
    "--add-data", f"{ROOT / 'exporters'}{os.pathsep}exporters",
    "--add-data", f"{ROOT / 'requirements.txt'}{os.pathsep}.",
    "--collect-all", "streamlit",
    "--collect-data", "streamlit",
    "--hidden-import", "pandas",
    "--hidden-import", "openpyxl",
    "--hidden-import", "plotly",
    "--hidden-import", "requests",
    "--hidden-import", "tornado",
    "--hidden-import", "google.protobuf",
    "--collect-all", "protobuf",
    "--collect-all", "google",
    "--windowed",
]

for mod in EXCLUDES:
    cmd.extend(["--exclude-module", mod])

cmd.append(str(ROOT / "launcher.py"))

print("🔨 Сборка macOS .app (минимизированная)...")
print(f"   Команда: python -m PyInstaller ...")
print(f"   Исключено модулей: {len(EXCLUDES)}")
print()

result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)

# Показываем только ключевые строки
for line in result.stdout.splitlines():
    if any(s in line for s in ["INFO: Building", "INFO: Build complete", "WARNING", "ERROR",
                                "completed successfully", "EXE target"]):
        print(f"  {line.strip()}")
if result.stderr:
    for line in result.stderr.splitlines():
        if any(s in line for s in ["Error", "error", "WARNING", "FAILED"]):
            print(f"  ! {line.strip()}")

if result.returncode == 0:
    app_path = DIST / f"{APP_NAME}.app"
    size_mb = sum(f.stat().st_size for f in app_path.rglob("*") if f.is_file()) / 1024 / 1024
    print()
    print(f"  ✅ {app_path}")
    print(f"     Размер: {size_mb:.0f} MB")
    print()

    # DMG (устаревший формат, оставлен для совместимости)
    dmg_path = DIST / f"{APP_NAME}.dmg"
    print("  📦 DMG (deprecated)...")
    subprocess.run([
        "hdiutil", "create", "-volname", APP_NAME,
        "-srcfolder", str(app_path),
        "-ov", "-format", "UDZO",
        str(dmg_path),
    ], capture_output=True)
    if dmg_path.exists():
        print(f"     {dmg_path}")

    # .pkg — правильный установщик macOS (в /Applications)
    pkg_path = DIST / f"{APP_NAME}.pkg"
    print(f"  📦 PKG...")
    subprocess.run([
        "pkgbuild",
        "--root", str(app_path),
        "--install-location", f"/Applications/{APP_NAME}.app",
        "--identifier", "com.retailanalyzer.app",
        "--version", "1.0",
        str(pkg_path),
    ], capture_output=True)
    if pkg_path.exists():
        print(f"     {pkg_path}")
else:
    print(f"\n  ❌ Ошибка сборки (код {result.returncode})")
    print("  === STDOUT ===")
    print(result.stdout[-2000:])
    print("  === STDERR ===")
    print(result.stderr[-2000:])
    sys.exit(1)
