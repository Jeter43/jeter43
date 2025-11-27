"""
批次风控服务模块
专门处理仓位批次级别的风险控制和止损逻辑
"""

from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
import logging
from dataclasses import dataclass
from enum import Enum

from quant_system.utils.logger import get_logger
from quant_system.domain.entities.portfolio import Portfolio
from quant_system.domain.entities.position_batch import PositionBatch, PositionBatchStatus


class BatchRiskAction(Enum):
    """批次风控动作枚举"""
    STOP_LOSS = "stop_loss"  # 止损
    TRAILING_STOP = "trailing_stop"  # 移动止损
    VOLATILITY_STOP = "volatility_stop"  # 波动率止损
    TIME_STOP = "time_stop"  # 时间止损
    PROFIT_TAKING = "profit_taking"  # 止盈


@dataclass
class BatchRiskAssessment:
    """批次风险评估数据类"""
    batch_id: str
    symbol: str
    level: int
    current_price: float
    profit_ratio: float
    risk_score: float  # 风险分数 0-100
    recommended_action: Optional[BatchRiskAction]
    stop_loss_price: float
    trailing_stop_price: float
    urgency: str  # LOW, MEDIUM, HIGH, CRITICAL
    reason: str
    timestamp: datetime


@dataclass
class BatchRiskExecution:
    """批次风控执行结果"""
    batch_id: str
    symbol: str
    action: BatchRiskAction
    quantity: int
    price: float
    executed: bool
    reason: str
    timestamp: datetime


class BatchRiskService:
    """
    批次风控服务

    专门处理仓位批次级别的风险控制，提供独立的止损、移动止损、
    波动率止损等功能。与整体风控策略协同工作，实现精细化的风险管理。
    """

    def __init__(self, broker=None, config=None):
        """
        初始化批次风控服务

        Args:
            broker: 券商接口
            config: 配置管理器
        """
        self.broker = broker
        self.config = config
        self.logger = get_logger(__name__)

        # 风控配置
        self.risk_config = self._load_risk_config()

        # 状态跟踪
        self.last_check_time: Optional[datetime] = None
        self.risk_assessments: Dict[str, BatchRiskAssessment] = {}
        self.execution_history: List[BatchRiskExecution] = []

        # 缓存
        self._atr_cache: Dict[str, float] = {}
        self._trend_cache: Dict[str, Dict[str, float]] = {}

        self.logger.info("批次风控服务初始化完成")

    def _load_risk_config(self) -> Dict[str, Any]:
        """
        加载风控配置

        Returns:
            Dict[str, Any]: 风控配置
        """
        default_config = {
            'enabled': True,
            'check_interval_minutes': 15,
            'batch_level_config': {
                1: {
                    'stop_loss_ratio': 0.08,
                    'trailing_stop_ratio': 0.05,
                    'volatility_multiplier': 2.0,
                    'max_holding_days': 60,
                    'profit_taking_ratio': 0.20
                },
                2: {
                    'stop_loss_ratio': 0.04,
                    'trailing_stop_ratio': 0.04,
                    'volatility_multiplier': 1.5,
                    'max_holding_days': 45,
                    'profit_taking_ratio': 0.15
                },
                3: {
                    'stop_loss_ratio': 0.03,
                    'trailing_stop_ratio': 0.03,
                    'volatility_multiplier': 1.2,
                    'max_holding_days': 30,
                    'profit_taking_ratio': 0.12
                }
            },
            'execution_settings': {
                'auto_execute_stop_loss': True,
                'auto_execute_trailing_stop': True,
                'require_confirmation_above': 0.10,  # 盈利10%以上需要确认
                'max_batch_actions_per_check': 3
            }
        }

        try:
            if self.config and hasattr(self.config.trading, 'position_scaling_enabled'):
                if self.config.trading.position_scaling_enabled:
                    config = {'enabled': True}
                    level_config = {}

                    for level in [1, 2, 3]:
                        scaling_config = self.config.get_scaling_level_config(level)
                        if scaling_config:
                            level_config[level] = {
                                'stop_loss_ratio': getattr(scaling_config, 'stop_loss_ratio',
                                                           default_config['batch_level_config'][level][
                                                               'stop_loss_ratio']),
                                'trailing_stop_ratio': getattr(scaling_config, 'trailing_stop_ratio',
                                                               default_config['batch_level_config'][level][
                                                                   'trailing_stop_ratio']),
                                'volatility_multiplier': getattr(scaling_config, 'volatility_multiplier',
                                                                 default_config['batch_level_config'][level][
                                                                     'volatility_multiplier']),
                                'max_holding_days': getattr(scaling_config, 'max_holding_days',
                                                            default_config['batch_level_config'][level][
                                                                'max_holding_days']),
                                'profit_taking_ratio': getattr(scaling_config, 'profit_taking_ratio',
                                                               default_config['batch_level_config'][level][
                                                                   'profit_taking_ratio'])
                            }

                    config['batch_level_config'] = level_config
                    config['execution_settings'] = default_config['execution_settings']
                    return config

        except Exception as e:
            self.logger.warning(f"加载批次风控配置失败，使用默认配置: {e}")

        return default_config

    def check_batch_risks(self, portfolio: Portfolio, market_data: Dict[str, Any]) -> List[BatchRiskAssessment]:
        """
        检查批次风险

        Args:
            portfolio: 投资组合
            market_data: 市场数据

        Returns:
            List[BatchRiskAssessment]: 风险评估列表
        """
        if not self.risk_config['enabled']:
            return []

        assessments = []

        try:
            # 获取所有活跃批次
            active_batches = self._get_all_active_batches(portfolio)

            for batch in active_batches:
                if batch.symbol not in market_data:
                    continue

                current_data = market_data[batch.symbol]
                current_price = current_data.get('last_price', 0)

                if current_price <= 0:
                    continue

                # 评估批次风险
                assessment = self._assess_batch_risk(batch, current_price, current_data)

                if assessment:
                    assessments.append(assessment)
                    self.risk_assessments[batch.batch_id] = assessment

            self.last_check_time = datetime.now()

            # 记录检查结果
            critical_risks = [a for a in assessments if a.urgency in ['HIGH', 'CRITICAL']]
            if critical_risks:
                self.logger.warning(f"发现 {len(critical_risks)} 个高风险批次")
            else:
                self.logger.info(f"批次风险检查完成: {len(assessments)} 个批次评估")

        except Exception as e:
            self.logger.error(f"检查批次风险异常: {e}")

        return assessments

    def execute_batch_actions(self, portfolio: Portfolio, assessments: List[BatchRiskAssessment]) -> List[
        BatchRiskExecution]:
        """
        执行批次风控动作

        Args:
            portfolio: 投资组合
            assessments: 风险评估列表

        Returns:
            List[BatchRiskExecution]: 执行结果列表
        """
        executions = []

        if not self.risk_config['enabled']:
            return executions

        try:
            # 按紧急程度排序
            sorted_assessments = sorted(
                assessments,
                key=lambda x: {'LOW': 0, 'MEDIUM': 1, 'HIGH': 2, 'CRITICAL': 3}[x.urgency],
                reverse=True
            )

            # 限制每次检查的最大执行数量
            max_actions = self.risk_config['execution_settings']['max_batch_actions_per_check']
            assessments_to_execute = sorted_assessments[:max_actions]

            for assessment in assessments_to_execute:
                execution = self._execute_single_batch_action(portfolio, assessment)
                if execution:
                    executions.append(execution)
                    self.execution_history.append(execution)

            if executions:
                self.logger.info(f"执行 {len(executions)} 个批次风控动作")

        except Exception as e:
            self.logger.error(f"执行批次动作异常: {e}")

        return executions

    def _get_all_active_batches(self, portfolio: Portfolio) -> List[PositionBatch]:
        """
        获取所有活跃批次

        Args:
            portfolio: 投资组合

        Returns:
            List[PositionBatch]: 活跃批次列表
        """
        active_batches = []

        try:
            for symbol in portfolio.positions.keys():
                symbol_batches = self._get_active_batches_for_symbol(portfolio, symbol)
                active_batches.extend(symbol_batches)

        except Exception as e:
            self.logger.error(f"获取活跃批次异常: {e}")

        return active_batches

    def _get_active_batches_for_symbol(self, portfolio: Portfolio, symbol: str) -> List[PositionBatch]:
        """
        获取指定股票的活跃批次

        Args:
            portfolio: 投资组合
            symbol: 股票代码

        Returns:
            List[PositionBatch]: 活跃批次列表
        """
        try:
            if hasattr(portfolio, 'get_active_batches'):
                return portfolio.get_active_batches(symbol)
            elif hasattr(portfolio, 'batch_manager'):
                return portfolio.batch_manager.get_active_batches_by_symbol(symbol)
            else:
                return []
        except Exception as e:
            self.logger.error(f"获取股票批次异常 {symbol}: {e}")
            return []

    def _assess_batch_risk(self, batch: PositionBatch, current_price: float, market_data: Dict[str, Any]) -> Optional[
        BatchRiskAssessment]:
        """
        评估单个批次风险

        Args:
            batch: 仓位批次
            current_price: 当前价格
            market_data: 市场数据

        Returns:
            Optional[BatchRiskAssessment]: 风险评估
        """
        try:
            # 更新批次价格
            batch.update_price(current_price)

            # 获取批次级别配置
            level_config = self.risk_config['batch_level_config'].get(batch.level, {})

            # 计算盈亏比例
            profit_ratio = (current_price - batch.entry_price) / batch.entry_price

            # 检查各种风险条件
            risk_checks = self._perform_risk_checks(batch, current_price, market_data, level_config, profit_ratio)

            # 计算风险分数
            risk_score = self._calculate_risk_score(risk_checks, profit_ratio, batch.level)

            # 确定推荐动作和紧急程度
            recommended_action, urgency = self._determine_action_and_urgency(risk_checks, risk_score, profit_ratio)

            # 计算止损价格
            stop_loss_price = self._calculate_stop_loss_price(batch, level_config)
            trailing_stop_price = self._calculate_trailing_stop_price(batch, level_config)

            # 生成理由
            reason = self._generate_risk_reason(risk_checks, profit_ratio, recommended_action)

            assessment = BatchRiskAssessment(
                batch_id=batch.batch_id,
                symbol=batch.symbol,
                level=batch.level,
                current_price=current_price,
                profit_ratio=profit_ratio,
                risk_score=risk_score,
                recommended_action=recommended_action,
                stop_loss_price=stop_loss_price,
                trailing_stop_price=trailing_stop_price,
                urgency=urgency,
                reason=reason,
                timestamp=datetime.now()
            )

            return assessment

        except Exception as e:
            self.logger.error(f"评估批次风险异常 {getattr(batch, 'batch_id', 'unknown')}: {e}")
            return None

    def _perform_risk_checks(self, batch: PositionBatch, current_price: float,
                             market_data: Dict[str, Any], level_config: Dict[str, Any],
                             profit_ratio: float) -> Dict[str, Any]:
        """
        执行风险检查

        Args:
            batch: 仓位批次
            current_price: 当前价格
            market_data: 市场数据
            level_config: 级别配置
            profit_ratio: 盈亏比例

        Returns:
            Dict[str, Any]: 风险检查结果
        """
        checks = {
            'stop_loss_triggered': False,
            'trailing_stop_triggered': False,
            'volatility_stop_triggered': False,
            'time_stop_triggered': False,
            'profit_taking_triggered': False,
            'stop_loss_reason': '',
            'trailing_stop_reason': '',
            'volatility_stop_reason': '',
            'time_stop_reason': '',
            'profit_taking_reason': ''
        }

        try:
            # 1. 止损检查
            stop_loss_ratio = level_config.get('stop_loss_ratio', 0.08)
            if profit_ratio <= -stop_loss_ratio:
                checks['stop_loss_triggered'] = True
                checks['stop_loss_reason'] = f'亏损{abs(profit_ratio):.1%}超过止损阈值{stop_loss_ratio:.1%}'

            # 2. 移动止损检查
            trailing_stop_ratio = level_config.get('trailing_stop_ratio', 0.05)
            batch.update_trailing_stop(trailing_stop_ratio)
            if hasattr(batch, 'trailing_stop_price') and current_price <= batch.trailing_stop_price:
                checks['trailing_stop_triggered'] = True
                checks['trailing_stop_reason'] = f'触发移动止损，回撤{trailing_stop_ratio:.1%}'

            # 3. 波动率止损检查
            volatility_check = self._check_volatility_stop(batch, current_price, market_data, level_config)
            if volatility_check['triggered']:
                checks['volatility_stop_triggered'] = True
                checks['volatility_stop_reason'] = volatility_check['reason']

            # 4. 时间止损检查
            time_check = self._check_time_stop(batch, level_config)
            if time_check['triggered']:
                checks['time_stop_triggered'] = True
                checks['time_stop_reason'] = time_check['reason']

            # 5. 止盈检查
            profit_taking_ratio = level_config.get('profit_taking_ratio', 0.20)
            if profit_ratio >= profit_taking_ratio:
                checks['profit_taking_triggered'] = True
                checks['profit_taking_reason'] = f'盈利{profit_ratio:.1%}达到止盈阈值{profit_taking_ratio:.1%}'

        except Exception as e:
            self.logger.error(f"执行风险检查异常 {batch.batch_id}: {e}")

        return checks

    def _check_volatility_stop(self, batch: PositionBatch, current_price: float,
                               market_data: Dict[str, Any], level_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        检查波动率止损

        Args:
            batch: 仓位批次
            current_price: 当前价格
            market_data: 市场数据
            level_config: 级别配置

        Returns:
            Dict[str, Any]: 检查结果
        """
        try:
            symbol = batch.symbol
            multiplier = level_config.get('volatility_multiplier', 2.0)

            # 获取ATR
            atr = self._get_atr_value(symbol)
            if atr > 0:
                atr_stop_price = batch.entry_price - (atr * multiplier)

                if current_price <= atr_stop_price:
                    return {
                        'triggered': True,
                        'reason': f'波动率止损触发，ATR倍数: {multiplier}'
                    }

            return {'triggered': False, 'reason': ''}

        except Exception as e:
            self.logger.error(f"检查波动率止损异常 {batch.batch_id}: {e}")
            return {'triggered': False, 'reason': ''}

    def _check_time_stop(self, batch: PositionBatch, level_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        检查时间止损

        Args:
            batch: 仓位批次
            level_config: 级别配置

        Returns:
            Dict[str, Any]: 检查结果
        """
        try:
            max_holding_days = level_config.get('max_holding_days', 60)
            holding_days = (datetime.now() - batch.entry_time).days

            if holding_days >= max_holding_days:
                return {
                    'triggered': True,
                    'reason': f'持仓{holding_days}天超过时间限制{max_holding_days}天'
                }

            return {'triggered': False, 'reason': ''}

        except Exception as e:
            self.logger.error(f"检查时间止损异常 {batch.batch_id}: {e}")
            return {'triggered': False, 'reason': ''}

    def _get_atr_value(self, symbol: str) -> float:
        """
        获取ATR值

        Args:
            symbol: 股票代码

        Returns:
            float: ATR值
        """
        try:
            # 检查缓存
            if symbol in self._atr_cache:
                cached_time, atr_value = self._atr_cache[symbol]
                if (datetime.now() - cached_time).total_seconds() < 3600:  # 1小时缓存
                    return atr_value

            # 重新计算ATR
            if self.broker:
                from quant_system.utils.indicators import calculate_atr

                hist_data = self.broker.get_history_kline(symbol, ktype="K_DAY", max_count=20)
                if hist_data is not None and len(hist_data) >= 14:
                    highs = hist_data['high'].values
                    lows = hist_data['low'].values
                    closes = hist_data['close'].values

                    atr_value = calculate_atr(highs, lows, closes)
                    self._atr_cache[symbol] = (datetime.now(), atr_value)
                    return atr_value

            return 0.0

        except Exception as e:
            self.logger.error(f"获取ATR异常 {symbol}: {e}")
            return 0.0

    def _calculate_risk_score(self, risk_checks: Dict[str, Any], profit_ratio: float, level: int) -> float:
        """
        计算风险分数

        Args:
            risk_checks: 风险检查结果
            profit_ratio: 盈亏比例
            level: 批次级别

        Returns:
            float: 风险分数 0-100
        """
        score = 0

        # 止损触发权重
        if risk_checks['stop_loss_triggered']:
            score += 40
        if risk_checks['trailing_stop_triggered']:
            score += 30
        if risk_checks['volatility_stop_triggered']:
            score += 25
        if risk_checks['time_stop_triggered']:
            score += 20
        if risk_checks['profit_taking_triggered']:
            score += 15

        # 亏损程度加成
        if profit_ratio < -0.10:
            score += 20
        elif profit_ratio < -0.05:
            score += 10

        # 级别风险调整（高级别风险更敏感）
        level_weights = {1: 1.0, 2: 1.2, 3: 1.5}
        weight = level_weights.get(level, 1.0)
        score = score * weight

        return min(score, 100)

    def _determine_action_and_urgency(self, risk_checks: Dict[str, Any], risk_score: float, profit_ratio: float) -> \
    Tuple[Optional[BatchRiskAction], str]:
        """
        确定推荐动作和紧急程度

        Args:
            risk_checks: 风险检查结果
            risk_score: 风险分数
            profit_ratio: 盈亏比例

        Returns:
            Tuple: (推荐动作, 紧急程度)
        """
        # 优先级：止损 > 移动止损 > 波动率止损 > 时间止损 > 止盈
        if risk_checks['stop_loss_triggered']:
            return BatchRiskAction.STOP_LOSS, 'CRITICAL'
        elif risk_checks['trailing_stop_triggered']:
            return BatchRiskAction.TRAILING_STOP, 'HIGH'
        elif risk_checks['volatility_stop_triggered']:
            return BatchRiskAction.VOLATILITY_STOP, 'HIGH'
        elif risk_checks['time_stop_triggered']:
            return BatchRiskAction.TIME_STOP, 'MEDIUM'
        elif risk_checks['profit_taking_triggered']:
            return BatchRiskAction.PROFIT_TAKING, 'MEDIUM'

        # 基于风险分数的动作
        if risk_score >= 70:
            return BatchRiskAction.STOP_LOSS, 'HIGH'
        elif risk_score >= 50:
            return BatchRiskAction.TRAILING_STOP, 'MEDIUM'
        elif risk_score >= 30:
            return BatchRiskAction.VOLATILITY_STOP, 'LOW'

        return None, 'LOW'

    def _calculate_stop_loss_price(self, batch: PositionBatch, level_config: Dict[str, Any]) -> float:
        """
        计算止损价格

        Args:
            batch: 仓位批次
            level_config: 级别配置

        Returns:
            float: 止损价格
        """
        stop_loss_ratio = level_config.get('stop_loss_ratio', 0.08)
        return batch.entry_price * (1 - stop_loss_ratio)

    def _calculate_trailing_stop_price(self, batch: PositionBatch, level_config: Dict[str, Any]) -> float:
        """
        计算移动止损价格

        Args:
            batch: 仓位批次
            level_config: 级别配置

        Returns:
            float: 移动止损价格
        """
        trailing_stop_ratio = level_config.get('trailing_stop_ratio', 0.05)
        if hasattr(batch, 'highest_price') and batch.highest_price > 0:
            return batch.highest_price * (1 - trailing_stop_ratio)
        else:
            return self._calculate_stop_loss_price(batch, level_config)

    def _generate_risk_reason(self, risk_checks: Dict[str, Any], profit_ratio: float,
                              action: Optional[BatchRiskAction]) -> str:
        """
        生成风险理由

        Args:
            risk_checks: 风险检查结果
            profit_ratio: 盈亏比例
            action: 推荐动作

        Returns:
            str: 风险理由
        """
        if not action:
            return f"风险可控，当前盈亏{profit_ratio:.1%}"

        reasons = []
        if risk_checks['stop_loss_triggered']:
            reasons.append(risk_checks['stop_loss_reason'])
        if risk_checks['trailing_stop_triggered']:
            reasons.append(risk_checks['trailing_stop_reason'])
        if risk_checks['volatility_stop_triggered']:
            reasons.append(risk_checks['volatility_stop_reason'])
        if risk_checks['time_stop_triggered']:
            reasons.append(risk_checks['time_stop_reason'])
        if risk_checks['profit_taking_triggered']:
            reasons.append(risk_checks['profit_taking_reason'])

        return " | ".join(reasons) if reasons else f"{action.value}, 盈亏{profit_ratio:.1%}"

    def _execute_single_batch_action(self, portfolio: Portfolio, assessment: BatchRiskAssessment) -> Optional[
        BatchRiskExecution]:
        """
        执行单个批次动作

        Args:
            portfolio: 投资组合
            assessment: 风险评估

        Returns:
            Optional[BatchRiskExecution]: 执行结果
        """
        try:
            # 获取批次信息
            batch = self._get_batch_by_id(portfolio, assessment.batch_id)
            if not batch:
                self.logger.error(f"找不到批次: {assessment.batch_id}")
                return None

            # 检查是否需要确认（高盈利情况下）
            require_confirmation = (assessment.profit_ratio >
                                    self.risk_config['execution_settings']['require_confirmation_above'])

            if require_confirmation:
                self.logger.info(f"需要确认的高盈利批次: {batch.symbol} 盈利{assessment.profit_ratio:.1%}")
                # 在实际系统中，这里可以添加确认逻辑
                # 现在我们先跳过执行
                return None

            # 执行平仓
            execution_result = self._close_batch_position(batch, assessment)

            return execution_result

        except Exception as e:
            self.logger.error(f"执行批次动作异常 {assessment.batch_id}: {e}")
            return None

    def _get_batch_by_id(self, portfolio: Portfolio, batch_id: str) -> Optional[PositionBatch]:
        """
        根据ID获取批次

        Args:
            portfolio: 投资组合
            batch_id: 批次ID

        Returns:
            Optional[PositionBatch]: 批次对象
        """
        try:
            # 遍历所有股票查找批次
            for symbol in portfolio.positions.keys():
                batches = self._get_active_batches_for_symbol(portfolio, symbol)
                for batch in batches:
                    if batch.batch_id == batch_id:
                        return batch
            return None
        except Exception as e:
            self.logger.error(f"根据ID获取批次异常 {batch_id}: {e}")
            return None

    def _close_batch_position(self, batch: PositionBatch, assessment: BatchRiskAssessment) -> BatchRiskExecution:
        """
        平仓批次头寸

        Args:
            batch: 仓位批次
            assessment: 风险评估

        Returns:
            BatchRiskExecution: 执行结果
        """
        try:
            # 在模拟环境中只记录不执行
            if (self.config and hasattr(self.config.trading, 'environment') and
                    self.config.trading.environment.value == 'simulate'):
                self.logger.info(
                    f"[模拟] 平仓批次 {batch.symbol} L{batch.level}: {assessment.recommended_action.value}")

                # 更新批次状态
                batch.close_position(
                    exit_price=assessment.current_price,
                    reason=assessment.reason,
                    exit_time=datetime.now()
                )

                return BatchRiskExecution(
                    batch_id=batch.batch_id,
                    symbol=batch.symbol,
                    action=assessment.recommended_action,
                    quantity=batch.quantity,
                    price=assessment.current_price,
                    executed=True,
                    reason=assessment.reason,
                    timestamp=datetime.now()
                )

            # 实盘环境执行平仓
            # 这里可以添加实际的平仓逻辑
            # 现在我们先模拟执行

            self.logger.warning(f"[实盘] 应执行批次平仓: {batch.symbol} {assessment.recommended_action.value}")

            return BatchRiskExecution(
                batch_id=batch.batch_id,
                symbol=batch.symbol,
                action=assessment.recommended_action,
                quantity=batch.quantity,
                price=assessment.current_price,
                executed=False,  # 标记为未执行，需要手动处理
                reason=assessment.reason,
                timestamp=datetime.now()
            )

        except Exception as e:
            self.logger.error(f"平仓批次异常 {batch.batch_id}: {e}")
            return BatchRiskExecution(
                batch_id=batch.batch_id,
                symbol=batch.symbol,
                action=assessment.recommended_action,
                quantity=batch.quantity,
                price=assessment.current_price,
                executed=False,
                reason=f"执行失败: {e}",
                timestamp=datetime.now()
            )

    def get_risk_report(self) -> Dict[str, Any]:
        """
        获取风控报告

        Returns:
            Dict[str, Any]: 风控报告
        """
        critical_assessments = [a for a in self.risk_assessments.values() if a.urgency in ['HIGH', 'CRITICAL']]
        recent_executions = [e for e in self.execution_history
                             if (datetime.now() - e.timestamp).total_seconds() < 3600]  # 1小时内

        return {
            'service': 'batch_risk',
            'enabled': self.risk_config['enabled'],
            'last_check_time': self.last_check_time,
            'active_assessments': len(self.risk_assessments),
            'critical_risks': len(critical_assessments),
            'recent_executions': len(recent_executions),
            'total_executions': len(self.execution_history),
            'config': {
                'check_interval': self.risk_config.get('check_interval_minutes'),
                'auto_execute': self.risk_config['execution_settings']['auto_execute_stop_loss']
            }
        }


# 导出类
__all__ = ['BatchRiskService', 'BatchRiskAssessment', 'BatchRiskExecution', 'BatchRiskAction']