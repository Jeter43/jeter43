# run_trading_system.py
#!/usr/bin/env python3
"""
交易系统启动脚本
放在项目根目录下运行
"""

import sys
import os

# 添加项目根目录到Python路径
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

from quant_system.main import main

if __name__ == "__main__":
    main()