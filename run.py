#!/usr/bin/env python3
"""
期权合约选择器启动脚本
Option Contract Selector Launcher
"""

import subprocess
import sys
import os

def main():
    """启动Streamlit应用"""
    try:
        # 获取当前脚本所在目录
        current_dir = os.path.dirname(os.path.abspath(__file__))
        app_file = os.path.join(current_dir, "Option_Contract_Selector.py")
        
        # 检查应用文件是否存在
        if not os.path.exists(app_file):
            print(f"错误：找不到应用文件 {app_file}")
            sys.exit(1)
        
        print("🚀 启动期权合约选择器...")
        print(f"📁 应用路径: {app_file}")
        print("🌐 应用将在浏览器中自动打开")
        print("⏹️  按 Ctrl+C 停止应用\n")
        
        # 启动Streamlit应用
        subprocess.run([
            sys.executable, "-m", "streamlit", "run", app_file,
            "--server.address", "localhost",
            "--server.port", "8501",
            "--browser.gatherUsageStats", "false"
        ])
        
    except KeyboardInterrupt:
        print("\n👋 应用已停止")
    except Exception as e:
        print(f"❌ 启动失败: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
