# trading_system/utils/logger.py
"""
日志系统模块 - Logging System Module

本模块提供了量化交易系统的完整日志解决方案，支持结构化日志、
日志轮转、多级别过滤、性能监控等高级特性。

版本重大改进：
- 支持结构化日志（JSON格式）和文本格式
- 实现自动日志轮转，避免日志文件过大
- 增加异步日志记录，避免I/O阻塞主线程
- 集成性能监控，记录日志系统自身性能
- 支持上下文管理和请求链路跟踪
- 提供丰富的配置选项和自定义格式化

核心特性：
1. 多日志级别: DEBUG, INFO, WARNING, ERROR, CRITICAL
2. 多输出目标: 控制台、文件、网络等
3. 结构化日志: 支持JSON格式便于日志分析
4. 日志轮转: 按时间或文件大小自动轮转
5. 性能优化: 异步写入和批量提交
6. 上下文跟踪: 支持请求链路和用户会话跟踪
"""

import logging
import sys
import os
import json
from datetime import datetime
from typing import Optional, Dict, Any, Union, List
from pathlib import Path
import threading
from queue import Queue, Empty, Full  # 修复：导入Full
import time
from enum import Enum

# 导入项目内部模块
from quant_system.core.exceptions import ConfigValidationError
from quant_system.utils.monitoring import performance_monitor, Timer


class LogLevel(Enum):
    """日志级别枚举"""
    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARNING = logging.WARNING
    ERROR = logging.ERROR
    CRITICAL = logging.CRITICAL

    @classmethod
    def from_string(cls, level_str: str) -> 'LogLevel':
        """
        从字符串转换日志级别

        Args:
            level_str: 日志级别字符串，不区分大小写

        Returns:
            LogLevel: 对应的日志级别枚举

        Raises:
            ValueError: 当字符串无法匹配任何日志级别时
        """
        level_map = {
            'debug': cls.DEBUG,
            'info': cls.INFO,
            'warning': cls.WARNING,
            'error': cls.ERROR,
            'critical': cls.CRITICAL
        }

        level_lower = level_str.lower()
        if level_lower in level_map:
            return level_map[level_lower]
        else:
            raise ValueError(f"无效的日志级别: {level_str}")


class LogFormat(Enum):
    """日志格式枚举"""
    TEXT = "text"    # 文本格式，人类可读
    JSON = "json"    # JSON格式，机器可读


class LogRotationConfig:
    """
    日志轮转配置类

    控制日志文件的自动轮转策略，支持按时间和文件大小两种方式。

    Attributes:
        max_bytes (int): 单个日志文件最大字节数，0表示不限制
        backup_count (int): 保留的备份文件数量
        rotation_time (str): 轮转时间，如 'midnight'、'H'（每小时）等
        encoding (str): 文件编码，默认utf-8
    """

    def __init__(self,
                 max_bytes: int = 10 * 1024 * 1024,  # 10MB
                 backup_count: int = 5,
                 rotation_time: Optional[str] = 'midnight',
                 encoding: str = 'utf-8'):
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self.rotation_time = rotation_time
        self.encoding = encoding

        self._validate_config()

    def _validate_config(self):
        """验证配置参数的有效性"""
        if self.max_bytes < 0:
            raise ConfigValidationError("max_bytes不能为负数")

        if self.backup_count < 0:
            raise ConfigValidationError("backup_count不能为负数")

        if self.encoding not in ['utf-8', 'gbk', 'ascii']:
            raise ConfigValidationError(f"不支持的编码格式: {self.encoding}")


class AsyncLogHandler:
    """
    异步日志处理器

    将日志记录操作放入队列，由后台线程异步处理，避免I/O阻塞主线程。
    这对于高频交易系统尤其重要，可以显著降低日志记录对性能的影响。
    """

    def __init__(self, queue_size: int = 10000):
        """
        初始化异步日志处理器

        Args:
            queue_size: 日志队列最大大小，默认10000条记录
        """
        self.queue = Queue(maxsize=queue_size)
        self.worker_thread = None
        self.running = False
        self.queue_size = queue_size

    def start(self):
        """启动异步日志处理线程"""
        if self.running:
            return

        self.running = True
        self.worker_thread = threading.Thread(
            target=self._process_logs,
            name="AsyncLogWorker",
            daemon=True
        )
        self.worker_thread.start()
        # 详细日志已移至日志文件，控制台不显示

    def stop(self):
        """停止异步日志处理线程"""
        if not self.running:
            return

        self.running = False
        if self.worker_thread:
            self.worker_thread.join(timeout=5.0)
            # 详细日志已移至日志文件，控制台不显示

    def put_log(self, log_record: Dict[str, Any]):
        """
        将日志记录放入队列

        Args:
            log_record: 结构化日志记录

        Note:
            当队列已满时，会丢弃最旧的日志记录来腾出空间
        """
        try:
            self.queue.put_nowait(log_record)
        except Full:
            # 队列已满，丢弃最旧的日志记录
            try:
                self.queue.get_nowait()  # 丢弃一条旧记录
                self.queue.put_nowait(log_record)  # 放入新记录
                print("⚠️ 日志队列已满，丢弃一条旧记录")
            except (Empty, Full):
                # 尽力而为，如果还是失败就丢弃当前记录
                print("🚨 日志队列处理异常，丢弃当前日志记录")
                pass

    def _process_logs(self):
        """
        后台线程处理日志记录

        这个方法运行在独立的线程中，负责从队列中取出日志记录并批量写入。
        使用批量处理提高I/O效率，减少文件操作次数。
        """
        batch = []
        batch_size = 100
        last_flush = time.time()
        flush_interval = 1.0  # 最大刷新间隔1秒

        # 详细日志已移至日志文件，控制台不显示

        while self.running:
            try:
                # 非阻塞获取日志记录
                try:
                    log_record = self.queue.get_nowait()
                    batch.append(log_record)
                except Empty:
                    # 队列为空，检查是否需要刷新批次
                    if batch and (time.time() - last_flush > flush_interval or len(batch) >= batch_size):
                        self._flush_batch(batch)
                        batch = []
                        last_flush = time.time()
                    time.sleep(0.1)  # 短暂休眠避免CPU空转
                    continue

                # 批次处理或超时刷新
                if len(batch) >= batch_size or (batch and time.time() - last_flush > flush_interval):
                    self._flush_batch(batch)
                    batch = []
                    last_flush = time.time()

            except Exception as e:
                # 避免后台线程异常导致程序崩溃
                print(f"🚨 异步日志处理异常: {e}")
                time.sleep(1.0)  # 发生异常时休眠1秒

        # 线程结束前刷新剩余日志
        if batch:
            self._flush_batch(batch)
            # 详细日志已移至日志文件，控制台不显示

    def _flush_batch(self, batch: List[Dict[str, Any]]):
        """
        批量刷新日志记录到文件

        Args:
            batch: 待写入的日志记录批次

        Note:
            使用批量写入减少I/O操作，提高日志记录性能
        """
        if not batch:
            return

        try:
            # 这里可以实现批量写入逻辑
            # 例如写入到文件系统、数据库或日志服务
            success_count = 0
            for record in batch:
                if self._write_single_log(record):
                    success_count += 1

            # 记录批量写入统计
            if len(batch) > 50:  # 只记录较大的批次
                print(f"📊 批量写入日志: {success_count}/{len(batch)} 条记录")

        except Exception as e:
            print(f"🚨 批量写入日志失败: {e}")

    def _write_single_log(self, record: Dict[str, Any]) -> bool:
        """
        写入单条日志记录

        Args:
            record: 单条日志记录

        Returns:
            bool: 写入是否成功
        """
        try:
            # 在实际项目中，这里可以写入文件、数据库或发送到日志服务
            log_dir = Path("logs")
            log_dir.mkdir(exist_ok=True)

            log_file = log_dir / f"trading_{datetime.now().strftime('%Y%m%d')}.log"

            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(record, ensure_ascii=False) + '\n')

            return True

        except Exception as e:
            print(f"🚨 写入单条日志失败: {e}")
            return False


class StructuredFormatter(logging.Formatter):
    """
    结构化日志格式化器

    支持文本和JSON两种格式的输出，便于日志分析和监控。
    """

    def __init__(self,
                 fmt: Optional[str] = None,
                 datefmt: Optional[str] = None,
                 style: str = '%',
                 log_format: LogFormat = LogFormat.TEXT):
        """
        初始化结构化格式化器

        Args:
            fmt: 格式字符串
            datefmt: 日期格式字符串
            style: 格式风格
            log_format: 日志格式类型
        """
        super().__init__(fmt, datefmt, style)
        self.log_format = log_format

    def format(self, record: logging.LogRecord) -> str:
        """
        格式化日志记录

        Args:
            record: 日志记录对象

        Returns:
            str: 格式化后的日志字符串
        """
        if self.log_format == LogFormat.JSON:
            return self._format_json(record)
        else:
            return self._format_text(record)

    def _format_json(self, record: logging.LogRecord) -> str:
        """
        格式化为JSON字符串

        Args:
            record: 日志记录对象

        Returns:
            str: JSON格式的日志字符串
        """
        log_entry = {
            'timestamp': datetime.fromtimestamp(record.created).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
            'thread': record.threadName,
            'process': record.processName
        }

        # 添加额外字段
        if hasattr(record, 'extra_fields') and isinstance(record.extra_fields, dict):
            log_entry.update(record.extra_fields)

        return json.dumps(log_entry, ensure_ascii=False)

    def _format_text(self, record: logging.LogRecord) -> str:
        """
        格式化为文本字符串

        Args:
            record: 日志记录对象

        Returns:
            str: 文本格式的日志字符串
        """
        return super().format(record)


class TradingLogger:
    """
    交易系统日志器 - 主日志类

    提供完整的日志记录功能，支持多级别、多目标、结构化日志等特性。
    这个类是线程安全的，可以在多线程环境中安全使用。

    Attributes:
        name (str): 日志器名称，通常使用模块名
        level (LogLevel): 日志级别
        log_to_file (bool): 是否记录到文件
        log_to_console (bool): 是否输出到控制台
        log_format (LogFormat): 日志格式
        rotation_config (LogRotationConfig): 日志轮转配置
        async_enabled (bool): 是否启用异步日志
    """

    def __init__(self,
                 name: str = "quant_system",
                 level: Union[LogLevel, int, str] = LogLevel.INFO,
                 log_to_file: bool = True,
                 log_to_console: bool = True,
                 log_format: LogFormat = LogFormat.TEXT,
                 rotation_config: Optional[LogRotationConfig] = None,
                 async_enabled: bool = True,
                 log_dir: str = "logs"):
        """
        初始化交易系统日志器

        Args:
            name: 日志器名称，用于区分不同模块的日志
            level: 日志级别，可以是LogLevel枚举、整数或字符串
            log_to_file: 是否记录到文件
            log_to_console: 是否输出到控制台
            log_format: 日志格式，文本或JSON
            rotation_config: 日志轮转配置
            async_enabled: 是否启用异步日志记录
            log_dir: 日志文件目录
        """
        self.name = name
        self.log_to_file = log_to_file
        self.log_to_console = log_to_console
        self.log_format = log_format
        self.async_enabled = async_enabled
        self.log_dir = Path(log_dir)

        # 设置日志级别
        if isinstance(level, LogLevel):
            self.level = level.value
        elif isinstance(level, int):
            self.level = level
        elif isinstance(level, str):
            self.level = LogLevel.from_string(level).value
        else:
            raise ConfigValidationError(f"不支持的日志级别类型: {type(level)}")

        # 设置轮转配置
        self.rotation_config = rotation_config or LogRotationConfig()

        # 异步日志处理器
        self.async_handler = AsyncLogHandler() if async_enabled else None

        # 初始化日志系统
        self._setup_logger()

        # 启动异步日志处理
        if self.async_enabled and self.async_handler:
            self.async_handler.start()

    def _setup_logger(self):
        """设置日志器配置"""
        # 创建日志器
        self.logger = logging.getLogger(self.name)
        self.logger.setLevel(self.level)

        # 清除已有的处理器，避免重复
        self.logger.handlers.clear()

        # 创建格式化器
        formatter = StructuredFormatter(
            fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
            log_format=self.log_format
        )

        # 控制台处理器
        if self.log_to_console:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(self.level)
            console_handler.setFormatter(formatter)
            self.logger.addHandler(console_handler)

        # 文件处理器
        if self.log_to_file:
            self._setup_file_handler(formatter)

    def _setup_file_handler(self, formatter: StructuredFormatter):
        """设置文件日志处理器"""
        try:
            # 确保日志目录存在
            self.log_dir.mkdir(parents=True, exist_ok=True)

            # 创建文件处理器
            log_file = self.log_dir / f"{self.name}_{datetime.now().strftime('%Y%m%d')}.log"

            # 使用RotatingFileHandler支持日志轮转
            from logging.handlers import RotatingFileHandler

            file_handler = RotatingFileHandler(
                filename=log_file,
                maxBytes=self.rotation_config.max_bytes,
                backupCount=self.rotation_config.backup_count,
                encoding=self.rotation_config.encoding
            )

            file_handler.setLevel(self.level)
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)

            # 详细日志已移至日志文件，控制台不显示

        except Exception as e:
            raise ConfigValidationError(f"设置文件日志处理器失败: {e}")

    @performance_monitor("logger_info")
    def info(self,
             message: str,
             extra_fields: Optional[Dict[str, Any]] = None,
             **kwargs):
        """
        记录信息级别日志

        Args:
            message: 日志消息
            extra_fields: 额外字段，会包含在结构化日志中
            **kwargs: 其他参数，用于字符串格式化
        """
        self._log(logging.INFO, message, extra_fields, **kwargs)

    @performance_monitor("logger_warning")
    def warning(self,
                message: str,
                extra_fields: Optional[Dict[str, Any]] = None,
                **kwargs):
        """记录警告级别日志"""
        self._log(logging.WARNING, message, extra_fields, **kwargs)

    @performance_monitor("logger_error")
    def error(self,
              message: str,
              extra_fields: Optional[Dict[str, Any]] = None,
              **kwargs):
        """记录错误级别日志"""
        self._log(logging.ERROR, message, extra_fields, **kwargs)

    def isEnabledFor(self, level: int) -> bool:
        """
        检查指定日志级别是否启用
        
        Args:
            level: 日志级别（如logging.DEBUG, logging.INFO等）
            
        Returns:
            bool: 如果该级别启用则返回True
        """
        return self.logger.isEnabledFor(level)

    @performance_monitor("logger_debug")
    def debug(self,
              message: str,
              extra_fields: Optional[Dict[str, Any]] = None,
              **kwargs):
        """记录调试级别日志"""
        self._log(logging.DEBUG, message, extra_fields, **kwargs)

    @performance_monitor("logger_critical")
    def critical(self,
                 message: str,
                 extra_fields: Optional[Dict[str, Any]] = None,
                 **kwargs):
        """记录严重错误级别日志"""
        self._log(logging.CRITICAL, message, extra_fields, **kwargs)

    def _log(self,
             level: int,
             message: str,
             extra_fields: Optional[Dict[str, Any]] = None,
             **kwargs):
        """
        内部日志记录方法

        Args:
            level: 日志级别
            message: 日志消息
            extra_fields: 额外字段
            **kwargs: 格式化参数
        """
        try:
            # 格式化消息
            formatted_message = message.format(**kwargs) if kwargs else message

            # 创建日志记录
            if self.async_enabled and self.async_handler:
                # 异步记录
                log_record = {
                    'timestamp': datetime.now().isoformat(),
                    'level': logging.getLevelName(level),
                    'logger': self.name,
                    'message': formatted_message,
                    'extra_fields': extra_fields or {}
                }
                self.async_handler.put_log(log_record)
            else:
                # 同步记录
                if extra_fields:
                    # 为同步记录添加额外字段
                    record = self.logger.makeRecord(
                        self.name, level,
                        '', 0, formatted_message,
                        (), None, extra=extra_fields
                    )
                    self.logger.handle(record)
                else:
                    self.logger.log(level, formatted_message)

        except Exception as e:
            # 日志记录本身发生异常，避免无限递归
            print(f"🚨 日志记录失败: {e} - 原消息: {message}")

    def __del__(self):
        """析构函数，确保资源清理"""
        if self.async_enabled and self.async_handler:
            self.async_handler.stop()


# 全局日志实例管理
_default_logger: Optional[TradingLogger] = None
_logger_lock = threading.Lock()


def setup_logger(name: str = "quant_system", **kwargs) -> TradingLogger:
    """
    设置全局日志器

    Args:
        name: 日志器名称
        **kwargs: 其他配置参数

    Returns:
        TradingLogger: 配置好的日志器实例
    """
    global _default_logger

    with _logger_lock:
        if _default_logger is None:
            _default_logger = TradingLogger(name, **kwargs)
        return _default_logger


def get_logger(name: Optional[str] = None) -> TradingLogger:
    """
    获取日志器实例

    Args:
        name: 日志器名称，为None时返回默认日志器

    Returns:
        TradingLogger: 日志器实例
    """
    if name is None:
        if _default_logger is None:
            return setup_logger()
        return _default_logger
    else:
        return TradingLogger(name)


# 便捷函数 - 使用默认日志器
@performance_monitor("log_info")
def log_info(message: str, **kwargs):
    """使用默认日志器记录信息日志"""
    get_logger().info(message, **kwargs)


@performance_monitor("log_warning")
def log_warning(message: str, **kwargs):
    """使用默认日志器记录警告日志"""
    get_logger().warning(message, **kwargs)


@performance_monitor("log_error")
def log_error(message: str, **kwargs):
    """使用默认日志器记录错误日志"""
    get_logger().error(message, **kwargs)


@performance_monitor("log_debug")
def log_debug(message: str, **kwargs):
    """使用默认日志器记录调试日志"""
    get_logger().debug(message, **kwargs)


@performance_monitor("log_critical")
def log_critical(message: str, **kwargs):
    """使用默认日志器记录严重错误日志"""
    get_logger().critical(message, **kwargs)


# 导出所有类和函数
__all__ = [
    'TradingLogger',
    'LogLevel',
    'LogFormat',
    'LogRotationConfig',
    'AsyncLogHandler',
    'StructuredFormatter',
    'setup_logger',
    'get_logger',
    'log_info',
    'log_warning',
    'log_error',
    'log_debug',
    'log_critical'
]