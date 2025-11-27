# quant_system/core/logger.py
import logging
import logging.handlers
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


class LoggerConfig:
    """日志配置类"""

    def __init__(self):
        self.log_level = logging.INFO
        self.log_to_console = True
        self.log_to_file = True
        self.log_dir = "logs"
        self.max_file_size = 10 * 1024 * 1024  # 10MB
        self.backup_count = 5
        self.log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        self.date_format = '%Y-%m-%d %H:%M:%S'


def setup_logger(name: str = "quant_system",
                 level: Optional[int] = None,
                 config: Optional[LoggerConfig] = None) -> logging.Logger:
    """
    设置并返回配置好的logger

    Args:
        name: logger名称
        level: 日志级别
        config: 日志配置

    Returns:
        logging.Logger: 配置好的logger实例
    """
    if config is None:
        config = LoggerConfig()

    if level is None:
        level = config.log_level

    # 创建logger
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # 避免重复添加handler
    if logger.handlers:
        return logger

    # 创建formatter
    formatter = logging.Formatter(config.log_format, config.date_format)

    # 控制台handler
    if config.log_to_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    # 文件handler
    if config.log_to_file:
        # 确保日志目录存在
        log_path = Path(config.log_dir)
        log_path.mkdir(exist_ok=True)

        # 日志文件名
        log_file = log_path / f"quant_system_{datetime.now().strftime('%Y%m%d')}.log"

        # 使用RotatingFileHandler实现日志轮转
        file_handler = logging.handlers.RotatingFileHandler(
            filename=log_file,
            maxBytes=config.max_file_size,
            backupCount=config.backup_count,
            encoding='utf-8'
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def get_logger(name: str = "quant_system") -> logging.Logger:
    """
    获取logger实例的快捷函数

    Args:
        name: logger名称

    Returns:
        logging.Logger: logger实例
    """
    return setup_logger(name)


# 预配置的logger实例
logger = get_logger()


class ColoredFormatter(logging.Formatter):
    """彩色日志格式化器"""

    COLORS = {
        'DEBUG': '\033[36m',  # 青色
        'INFO': '\033[32m',  # 绿色
        'WARNING': '\033[33m',  # 黄色
        'ERROR': '\033[31m',  # 红色
        'CRITICAL': '\033[35m',  # 紫色
        'RESET': '\033[0m'  # 重置
    }

    def format(self, record):
        # 保存原始级别名称
        original_levelname = record.levelname

        # 添加颜色
        if original_levelname in self.COLORS:
            colored_levelname = f"{self.COLORS[original_levelname]}{original_levelname}{self.COLORS['RESET']}"
            record.levelname = colored_levelname

        # 调用父类格式化
        result = super().format(record)

        # 恢复原始级别名称
        record.levelname = original_levelname

        return result


def setup_colored_logger(name: str = "quant_system") -> logging.Logger:
    """
    设置彩色日志logger

    Args:
        name: logger名称

    Returns:
        logging.Logger: 配置彩色输出的logger
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    # 避免重复添加handler
    if any(isinstance(handler, logging.StreamHandler) for handler in logger.handlers):
        return logger

    # 创建彩色formatter
    formatter = ColoredFormatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 控制台handler（彩色输出）
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


# 函数别名，便于使用
def info(msg: str, *args, **kwargs):
    """info级别日志"""
    logger.info(msg, *args, **kwargs)


def debug(msg: str, *args, **kwargs):
    """debug级别日志"""
    logger.debug(msg, *args, **kwargs)


def warning(msg: str, *args, **kwargs):
    """warning级别日志"""
    logger.warning(msg, *args, **kwargs)


def error(msg: str, *args, **kwargs):
    """error级别日志"""
    logger.error(msg, *args, **kwargs)


def critical(msg: str, *args, **kwargs):
    """critical级别日志"""
    logger.critical(msg, *args, **kwargs)


def exception(msg: str, *args, **kwargs):
    """exception级别日志（包含堆栈跟踪）"""
    logger.exception(msg, *args, **kwargs)


# 模块级别的logger实例
colored_logger = setup_colored_logger()

if __name__ == "__main__":
    # 测试日志功能
    logger.debug("这是一条debug日志")
    logger.info("这是一条info日志")
    logger.warning("这是一条warning日志")
    logger.error("这是一条error日志")

    # 测试彩色日志
    colored_logger.info("这是一条彩色info日志")
    colored_logger.warning("这是一条彩色warning日志")
    colored_logger.error("这是一条彩色error日志")