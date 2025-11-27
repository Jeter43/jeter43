# quant_system/core/trading_config.py
# 完整的 TradingConfig 及相关配置类实现（自包含、带验证与序列化支持）
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, Optional, List
from enum import Enum
import datetime

# ------------------------------------------------------------------
# 兼容导入：如果项目其它地方已经定义了这些类型，优先导入使用
# 若导入失败，则使用本地定义（避免因循环引用或缺失导致异常）
# ------------------------------------------------------------------
try:
    # 示例（项目内如果存在这些模块会被使用）
    # from quant_system.core.enums import TradingEnvironment  # 示例路径
    TradingEnvironment  # type: ignore
    _HAVE_EXTERNAL_ENV = True
except Exception:
    _HAVE_EXTERNAL_ENV = False

if not _HAVE_EXTERNAL_ENV:
    class TradingEnvironment(Enum):
        """交易环境：模拟 / 实盘"""
        SIMULATE = "simulate"
        REAL = "real"

# 导入统一异常类
try:
    from quant_system.core.exceptions import ConfigValidationError
except ImportError:
    # 如果导入失败，定义简化版本（向后兼容）
    class ConfigValidationError(Exception):
        def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
            super().__init__(message)
            self.details = details or {}


# ------------------------------------------------------------------
# 新增：分级仓位配置类
# ------------------------------------------------------------------
@dataclass
class PositionScalingLevelConfig:
    """
    分级仓位配置 - 单个级别配置
    """
    level: int  # 级别: 1=初始, 2=第一次加仓, 3=第二次加仓
    max_ratio: float  # 该级别最大仓位比例
    profit_threshold: Optional[float] = None  # 升级所需的盈利阈值 (L1->L2, L2->L3)
    add_ratio: Optional[float] = None  # 加仓比例 (L1->L2, L2->L3)
    stop_loss_ratio: float = 0.08  # 该级别止损比例
    trailing_stop_ratio: float = 0.03  # 移动止损比例

    def validate(self) -> None:
        errors = []
        if self.level not in [1, 2, 3]:
            errors.append(f"level 必须在 1-3 之间: {self.level}")
        if not (0 < self.max_ratio <= 1):
            errors.append(f"max_ratio 必须在 0-1 之间: {self.max_ratio}")
        if self.profit_threshold is not None and not (0 < self.profit_threshold <= 0.5):
            errors.append(f"profit_threshold 必须在 0-0.5 之间: {self.profit_threshold}")
        if self.add_ratio is not None and not (0 < self.add_ratio <= 0.5):
            errors.append(f"add_ratio 必须在 0-0.5 之间: {self.add_ratio}")
        if not (0 < self.stop_loss_ratio <= 0.5):
            errors.append(f"stop_loss_ratio 必须在 0-0.5 之间: {self.stop_loss_ratio}")
        if not (0 < self.trailing_stop_ratio <= 0.5):
            errors.append(f"trailing_stop_ratio 必须在 0-0.5 之间: {self.trailing_stop_ratio}")
        if errors:
            raise ConfigValidationError(f"PositionScalingLevelConfig L{self.level} 验证失败", {"errors": errors})


@dataclass
class PositionScalingConfig:
    """
    分级仓位管理配置
    """
    enabled: bool = True  # 是否启用分级仓位管理
    levels: List[PositionScalingLevelConfig] = field(default_factory=list)

    def __post_init__(self):
        # 如果levels为空，设置默认配置
        if not self.levels:
            self.levels = [
                PositionScalingLevelConfig(
                    level=1,
                    max_ratio=0.10,
                    stop_loss_ratio=0.08,
                    trailing_stop_ratio=0.05
                ),
                PositionScalingLevelConfig(
                    level=2,
                    max_ratio=0.20,  # L1 + L2 = 20%
                    profit_threshold=0.08,
                    add_ratio=0.10,
                    stop_loss_ratio=0.04,
                    trailing_stop_ratio=0.04
                ),
                PositionScalingLevelConfig(
                    level=3,
                    max_ratio=0.25,  # L1 + L2 + L3 = 25%
                    profit_threshold=0.08,
                    add_ratio=0.05,
                    stop_loss_ratio=0.03,
                    trailing_stop_ratio=0.03
                )
            ]

    def get_level_config(self, level: int) -> Optional[PositionScalingLevelConfig]:
        """获取指定级别的配置"""
        for config in self.levels:
            if config.level == level:
                return config
        return None

    def validate(self) -> None:
        errors = []

        # 验证每个级别配置
        for level_config in self.levels:
            try:
                level_config.validate()
            except ConfigValidationError as e:
                errors.extend([f"L{level_config.level}: {err}" for err in e.details.get("errors", [])])

        # 验证级别连续性
        levels = [config.level for config in self.levels]
        if sorted(levels) != [1, 2, 3]:
            errors.append("必须包含完整的级别配置: L1, L2, L3")

        # 验证比例连续性
        level1 = self.get_level_config(1)
        level2 = self.get_level_config(2)
        level3 = self.get_level_config(3)

        if level1 and level2 and level2.max_ratio <= level1.max_ratio:
            errors.append("L2 max_ratio 必须大于 L1 max_ratio")
        if level2 and level3 and level3.max_ratio <= level2.max_ratio:
            errors.append("L3 max_ratio 必须大于 L2 max_ratio")

        if errors:
            raise ConfigValidationError("PositionScalingConfig 验证失败", {"errors": errors})


# ------------------------------------------------------------------
# 子配置类：BacktestConfig / RiskConfig / PositionConfig / BrokerConfig
# ------------------------------------------------------------------
@dataclass
class BacktestConfig:
    """
    回测相关配置
    """
    commission_rate: float = 0.0003  # 交易手续费率（按成交额）
    slippage: float = 0.001  # 滑点（按比例）
    initial_capital: float = 100000.0  # 回测初始资金（默认 100000）
    start_date: Optional[str] = None  # 回测开始日期 "YYYY-MM-DD"（可为 None）
    end_date: Optional[str] = None  # 回测结束日期 "YYYY-MM-DD"（可为 None）
    allow_universe_change: bool = True  # 是否允许标的池在回测期间变更

    def validate(self) -> None:
        errors = []
        if self.commission_rate < 0:
            errors.append("commission_rate 不能为负数")
        if self.slippage < 0:
            errors.append("slippage 不能为负数")
        if self.initial_capital is not None and self.initial_capital <= 0:
            errors.append("initial_capital 必须大于 0")
        if errors:
            raise ConfigValidationError("BacktestConfig 验证失败", {"errors": errors})


@dataclass
class RiskConfig:
    """
    风控相关配置
    """
    stop_loss_pct: float = 0.2  # 单笔止损百分比（0-1）
    max_drawdown_pct: float = 0.3  # 最大回撤比例（0-1）
    enable_auto_close: bool = True  # 是否启用自动强平/止损执行
    check_interval_seconds: int = 60  # 风控检查间隔（秒）

    def validate(self) -> None:
        errors = []
        if not (0 <= self.stop_loss_pct <= 1):
            errors.append("stop_loss_pct 必须在 0 到 1 之间")
        if not (0 <= self.max_drawdown_pct <= 1):
            errors.append("max_drawdown_pct 必须在 0 到 1 之间")
        if self.check_interval_seconds <= 0:
            errors.append("check_interval_seconds 必须大于 0")
        if errors:
            raise ConfigValidationError("RiskConfig 验证失败", {"errors": errors})


@dataclass
class PositionConfig:
    """
    仓位管理配置 - 增强版本，支持分级仓位
    """
    max_stocks: int = 3  # 最多持仓数量（默认3只）
    initial_position_ratio: float = 0.1  # 单笔初始仓位占用初始资金比例（0-1）
    max_position_weight: float = 0.2  # 单仓最大权重（相对于组合净值，0-1）

    # 新增：分级仓位配置
    scaling_config: PositionScalingConfig = field(default_factory=PositionScalingConfig)

    def validate(self) -> None:
        errors = []
        if self.max_stocks <= 0:
            errors.append("max_stocks 必须大于 0")
        if not (0 < self.initial_position_ratio <= 1):
            errors.append("initial_position_ratio 必须在 0 到 1 之间")
        if not (0 < self.max_position_weight <= 1):
            errors.append("max_position_weight 必须在 0 到 1 之间")

        # 验证分级仓位配置
        try:
            self.scaling_config.validate()
        except ConfigValidationError as e:
            errors.extend([f"scaling_config: {err}" for err in e.details.get("errors", [])])

        if errors:
            raise ConfigValidationError("PositionConfig 验证失败", {"errors": errors})


@dataclass
class BrokerConfig:
    """
    券商连接与凭证配置（简化版）
    """
    broker_name: str = "futu"
    host: str = "127.0.0.1"
    port: int = 11111
    api_key: Optional[str] = None
    simulate: bool = True

    def validate(self) -> None:
        errors = []
        if not isinstance(self.port, int) or self.port <= 0:
            errors.append("port 必须是正整数")
        if errors:
            raise ConfigValidationError("BrokerConfig 验证失败", {"errors": errors})


# ------------------------------------------------------------------
# 主配置类：TradingConfig
# ------------------------------------------------------------------
@dataclass
class TradingConfig:
    """
    主交易配置类（包含子配置与常用全局参数）
    说明：此类尽量自包含、带默认值与验证方法，可通过 from_dict/from_config 合并外部配置。
    """
    # 运行/安全
    trading_password: str = ""
    environment: TradingEnvironment = TradingEnvironment.SIMULATE

    # 子配置
    risk_config: RiskConfig = field(default_factory=RiskConfig)
    position_config: PositionConfig = field(default_factory=PositionConfig)
    broker_config: BrokerConfig = field(default_factory=BrokerConfig)
    backtest_config: BacktestConfig = field(default_factory=BacktestConfig)

    # 交易全局参数
    commission_rate: float = 0.0003
    slippage: float = 0.001
    trade_execution_delay: int = 1000  # ms

    # 常被直接引用的便捷字段（显式声明，避免静态分析未解析）
    max_stocks: int = 10
    initial_position_ratio: float = 0.1

    # 兼容旧配置的扩展字段（自由扩展）
    extra: Dict[str, Any] = field(default_factory=dict)

    # ---------- 初始化后处理 ----------
    def __post_init__(self):
        # 如果外部注入为 dict，转换为 dataclass 实例
        if isinstance(self.risk_config, dict):
            self.risk_config = RiskConfig(**self.risk_config)
        if isinstance(self.position_config, dict):
            self.position_config = PositionConfig(**self.position_config)
        if isinstance(self.broker_config, dict):
            self.broker_config = BrokerConfig(**self.broker_config)
        if isinstance(self.backtest_config, dict):
            self.backtest_config = BacktestConfig(**self.backtest_config)

        # 处理分级仓位配置的dict转换
        if (hasattr(self.position_config, 'scaling_config') and
                isinstance(self.position_config.scaling_config, dict)):
            scaling_dict = self.position_config.scaling_config
            levels_data = scaling_dict.get('levels', [])
            levels = []
            for level_data in levels_data:
                if isinstance(level_data, dict):
                    levels.append(PositionScalingLevelConfig(**level_data))
                else:
                    levels.append(level_data)
            self.position_config.scaling_config = PositionScalingConfig(
                enabled=scaling_dict.get('enabled', True),
                levels=levels
            )

        # 将常见字段同步（优先使用子配置的值）
        # 若子配置给出了更具体的值，覆盖顶层字段
        try:
            # 从 position_config 同步
            self.max_stocks = int(getattr(self.position_config, "max_stocks", self.max_stocks))
            self.initial_position_ratio = float(
                getattr(self.position_config, "initial_position_ratio", self.initial_position_ratio))
            # 从 backtest_config 同步 commission/slippage（如果没有显式设置）
            if getattr(self.backtest_config, "commission_rate", None) is not None:
                self.commission_rate = float(self.backtest_config.commission_rate)
            if getattr(self.backtest_config, "slippage", None) is not None:
                self.slippage = float(self.backtest_config.slippage)
        except Exception:
            # 容错：若子配置类型不对，交由 validate 抛出错误
            pass

        # 验证配置有效性
        self._validate_config()

    # ---------- 验证 ----------
    def _validate_config(self) -> None:
        errors = []

        if self.environment == TradingEnvironment.REAL and not self.trading_password:
            errors.append("实盘环境必须提供 trading_password")

        if self.commission_rate < 0:
            errors.append("commission_rate 不能为负数")

        if self.slippage < 0:
            errors.append("slippage 不能为负数")

        if self.trade_execution_delay < 0:
            errors.append("trade_execution_delay 不能为负数")

        # 子配置校验
        try:
            self.position_config.validate()
        except ConfigValidationError as e:
            errors.extend(e.details.get("errors", []))

        try:
            self.risk_config.validate()
        except ConfigValidationError as e:
            errors.extend(e.details.get("errors", []))

        try:
            self.broker_config.validate()
        except ConfigValidationError as e:
            errors.extend(e.details.get("errors", []))

        try:
            self.backtest_config.validate()
        except ConfigValidationError as e:
            errors.extend(e.details.get("errors", []))

        if errors:
            raise ConfigValidationError("TradingConfig 验证失败", {"errors": errors, "config": self.to_dict()})

    # ---------- 便捷方法：分级仓位配置访问 ----------
    @property
    def position_scaling_enabled(self) -> bool:
        """是否启用分级仓位管理"""
        return (hasattr(self.position_config, 'scaling_config') and
                getattr(self.position_config.scaling_config, 'enabled', False))

    def get_scaling_level_config(self, level: int) -> Optional[PositionScalingLevelConfig]:
        """获取分级仓位级别配置"""
        if (hasattr(self.position_config, 'scaling_config') and
                hasattr(self.position_config.scaling_config, 'get_level_config')):
            return self.position_config.scaling_config.get_level_config(level)
        return None

    # ---------- 序列化 / 反序列化 ----------
    def to_dict(self) -> Dict[str, Any]:
        """
        转为字典（适用于保存配置）
        注意：会把 Enum 转为其 value
        """
        d = asdict(self)
        # Enum -> value
        if isinstance(self.environment, Enum):
            d["environment"] = self.environment.value
        # 子配置对象保持字典形式
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TradingConfig":
        """
        从字典恢复 TradingConfig（会自动处理子配置 dict -> dataclass）
        """
        # 解析 environment：允许传字符串或枚举
        env = data.get("environment", None)
        if isinstance(env, str):
            try:
                env_val = TradingEnvironment(env)
            except Exception:
                # 尝试大小写容错
                env_val = TradingEnvironment(env.lower())
        elif isinstance(env, TradingEnvironment):
            env_val = env
        else:
            env_val = TradingEnvironment.SIMULATE

        # 提取子配置 dict（如果存在）
        rc = data.get("risk_config", None)
        pc = data.get("position_config", None)
        bc = data.get("broker_config", None)
        btc = data.get("backtest_config", None)

        # 其余字段按需读取
        kwargs = {
            "trading_password": data.get("trading_password", ""),
            "environment": env_val,
            "risk_config": rc if rc is not None else RiskConfig(),
            "position_config": pc if pc is not None else PositionConfig(),
            "broker_config": bc if bc is not None else BrokerConfig(),
            "backtest_config": btc if btc is not None else BacktestConfig(),
            "commission_rate": data.get("commission_rate", 0.0003),
            "slippage": data.get("slippage", 0.001),
            "trade_execution_delay": data.get("trade_execution_delay", 1000),
            "max_stocks": data.get("max_stocks", data.get("position_config", {}).get("max_stocks", 10)),
            "initial_position_ratio": data.get("initial_position_ratio",
                                               data.get("position_config", {}).get("initial_position_ratio", 0.1)),
            "extra": data.get("extra", {})
        }

        # 构建实例（__post_init__ 会进一步校验）
        return cls(**kwargs)

    def merge_from_dict(self, data: Dict[str, Any]) -> None:
        """
        将外部 dict 合并到当前配置实例（就地修改）。
        优先级：传入值覆盖现有值。合并后会重新验证配置。
        """
        # 简单字段
        for key in ("trading_password", "commission_rate", "slippage", "trade_execution_delay", "max_stocks",
                    "initial_position_ratio"):
            if key in data:
                setattr(self, key, data[key])

        # environment
        if "environment" in data:
            env = data["environment"]
            if isinstance(env, str):
                try:
                    self.environment = TradingEnvironment(env)
                except Exception:
                    self.environment = TradingEnvironment(env.lower())
            elif isinstance(env, TradingEnvironment):
                self.environment = env

        # 子配置合并（如果为 dict 则更新）
        if "risk_config" in data:
            rc = data["risk_config"]
            if isinstance(rc, dict):
                for k, v in rc.items():
                    setattr(self.risk_config, k, v)
            elif isinstance(rc, RiskConfig):
                self.risk_config = rc

        if "position_config" in data:
            pc = data["position_config"]
            if isinstance(pc, dict):
                for k, v in pc.items():
                    setattr(self.position_config, k, v)
            elif isinstance(pc, PositionConfig):
                self.position_config = pc

            # 特殊处理分级仓位配置
            if "scaling_config" in pc:
                scaling_data = pc["scaling_config"]
                if isinstance(scaling_data, dict):
                    if hasattr(self.position_config, 'scaling_config'):
                        # 更新现有配置
                        if "enabled" in scaling_data:
                            self.position_config.scaling_config.enabled = scaling_data["enabled"]
                        if "levels" in scaling_data:
                            # 重新构建levels
                            levels = []
                            for level_data in scaling_data["levels"]:
                                if isinstance(level_data, dict):
                                    levels.append(PositionScalingLevelConfig(**level_data))
                                else:
                                    levels.append(level_data)
                            self.position_config.scaling_config.levels = levels

        if "broker_config" in data:
            bc = data["broker_config"]
            if isinstance(bc, dict):
                for k, v in bc.items():
                    setattr(self.broker_config, k, v)
            elif isinstance(bc, BrokerConfig):
                self.broker_config = bc

        if "backtest_config" in data:
            btc = data["backtest_config"]
            if isinstance(btc, dict):
                for k, v in btc.items():
                    setattr(self.backtest_config, k, v)
            elif isinstance(btc, BacktestConfig):
                self.backtest_config = btc

        # extra
        if "extra" in data and isinstance(data["extra"], dict):
            self.extra.update(data["extra"])

        # 重新同步与校验
        self.__post_init__()


# ------------------------------------------------------------------
# 文件自测：演示如何使用（仅在直接运行此文件时执行）
# ------------------------------------------------------------------
if __name__ == "__main__":
    # 简单示例：从 dict 加载并验证
    sample = {
        "environment": "simulate",
        "commission_rate": 0.0005,
        "position_config": {
            "max_stocks": 5,
            "initial_position_ratio": 0.08,
            "scaling_config": {
                "enabled": True,
                "levels": [
                    {"level": 1, "max_ratio": 0.10, "stop_loss_ratio": 0.08},
                    {"level": 2, "max_ratio": 0.18, "profit_threshold": 0.08, "add_ratio": 0.08,
                     "stop_loss_ratio": 0.04},
                    {"level": 3, "max_ratio": 0.22, "profit_threshold": 0.08, "add_ratio": 0.04,
                     "stop_loss_ratio": 0.03}
                ]
            }
        },
        "backtest_config": {"commission_rate": 0.0005, "slippage": 0.0008}
    }

    cfg = TradingConfig.from_dict(sample)
    print("配置加载成功:")
    print("分级仓位启用:", cfg.position_scaling_enabled)
    print("L1配置:", cfg.get_scaling_level_config(1))
    print("L2配置:", cfg.get_scaling_level_config(2))

    # 合并修改示例
    cfg.merge_from_dict({"max_stocks": 8, "risk_config": {"stop_loss_pct": 0.15}})
    print("合并后配置验证通过")