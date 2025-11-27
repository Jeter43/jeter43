# setup_environment.py
import subprocess
import sys

def install_requirements():
    """安装项目依赖"""
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
        print("✅ 依赖包安装完成")
    except subprocess.CalledProcessError:
        print("❌ 依赖包安装失败")

if __name__ == "__main__":
    install_requirements()