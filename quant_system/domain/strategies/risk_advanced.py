# quant_system/domain/strategies/risk_advanced.py
"""
高级风控策略
包含多层次风险监控和智能止损逻辑
"""

import sys
import os
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import numpy as np

# 添加项目根目录到Python路径
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from quant_system.utils.logger import get_logger
from quant_system.utils.indicators import calculate_atr, calculate_trend_strength
from .base import RiskStrategy


class AdvancedRiskStrategy(RiskStrategy):
    """高级风控策略 - 完整实现"""

    def __init__(self, broker=None, config=None):
        super().__init__("advanced_risk_management")
        self.broker = broker
        self.config = config
        self.logger = get_logger()

        # 从配置中读取分级仓位参数
        self.scaling_config = self._load_scaling_config()

        # 风控参数 - 增强版本，包含分级参数
        max_position_ratio = 0.2  # 默认20%
        if self.config and hasattr(self.config, 'trading'):
            if hasattr(self.config.trading, 'position_config'):
                max_position_ratio = getattr(self.config.trading.position_config, 'max_position_weight', 0.2)
            elif hasattr(self.config.trading, 'max_position_ratio'):
                max_position_ratio = getattr(self.config.trading, 'max_position_ratio', 0.2)

        self.risk_parameters = {
            # 个股风险参数
            'max_single_loss_ratio': 0.05,  # 单票最大亏损5%
            'trailing_stop_ratio': 0.03,  # 移动止损3%
            'volatility_stop_multiplier': 2.0,  # ATR止损倍数

            # 组合风险参数
            'max_portfolio_loss_ratio': 0.02,  # 组合最大亏损2%
            'max_drawdown_limit': 0.08,  # 最大回撤8%
            'position_concentration_limit': max_position_ratio,  # 单只股票最大持仓比例

            # 市场风险参数
            'market_decline_threshold': -0.03,  # 市场下跌阈值-3%
            'high_volatility_threshold': 0.04,  # 高波动率阈值4%

            # 时间参数
            'profit_protection_time': 7,  # 盈利保护期(天)
            'position_holding_limit': 30,  # 最大持仓天数

            # 新增：分级仓位风控参数
            'scaling_enabled': self.scaling_config.get('enabled', True),
            'batch_risk_check_interval': 300,  # 批次风控检查间隔(秒)
        }

        # 风险状态跟踪 - 增强版本
        self.risk_state = {
            'overall_risk_level': 'LOW',
            'last_market_check': None,
            'last_batch_check': None,
            'position_risks': {},
            'batch_risks': {},  # 新增：批次风险状态
            'market_alert': False
        }

    def check_risk(self, portfolio: Any, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行全面风险检查

        Args:
            portfolio: 投资组合对象
            market_data: 市场数据

        Returns:
            Dict: 风险检查结果和应对措施
        """
        risk_actions = []
        risk_scores = {}

        try:
            # 1. 个股风险检查
            individual_risks = self._check_individual_risks(portfolio, market_data)
            risk_actions.extend(individual_risks['actions'])
            risk_scores['individual'] = individual_risks['risk_score']

            # 2. 组合风险检查
            portfolio_risks = self._check_portfolio_risks(portfolio, market_data)
            risk_actions.extend(portfolio_risks['actions'])
            risk_scores['portfolio'] = portfolio_risks['risk_score']

            # 3. 市场风险检查
            market_risks = self._check_market_risks(market_data)
            risk_actions.extend(market_risks['actions'])
            risk_scores['market'] = market_risks['risk_score']

            # 4. 时间维度风险检查
            time_risks = self._check_time_risks(portfolio)
            risk_actions.extend(time_risks['actions'])
            risk_scores['time'] = time_risks['risk_score']

            # 计算总体风险等级
            overall_risk_level, total_risk_score = self._calculate_overall_risk(risk_scores, len(risk_actions))

            # 更新风险状态
            self.risk_state['overall_risk_level'] = overall_risk_level
            self.risk_state['last_market_check'] = datetime.now().isoformat()

            result = {
                'risk_level': overall_risk_level,
                'risk_score': total_risk_score,
                'actions': risk_actions,
                'risk_breakdown': risk_scores,
                'timestamp': datetime.now(),
                'strategy': self.name
            }

            # 记录风险检查结果
            if overall_risk_level in ['HIGH', 'CRITICAL']:
                self.logger.warning(f"🚨 高风险警报: {overall_risk_level}, 分数: {total_risk_score}")

            return result

        except Exception as e:
            self.logger.error(f"风险检查异常: {e}")
            return {
                'risk_level': 'UNKNOWN',
                'risk_score': 50,
                'actions': [],
                'risk_breakdown': {},
                'timestamp': datetime.now(),
                'strategy': self.name,
                'error': str(e)
            }

    def _check_individual_risks(self, portfolio: Any, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """检查个股风险 - 增强版本，支持分级仓位"""
        risk_actions = []
        risk_score = 0

        try:
            # 先检查批次级别风险（如果启用分级仓位）
            batch_risks = []
            if self.risk_parameters['scaling_enabled']:
                batch_risks = self._check_batch_risks(portfolio, market_data)
                risk_actions.extend(batch_risks)

            # 然后检查整体持仓风险
            for symbol, position in portfolio.positions.items():
                # 如果该股票已经有批次级别的止损动作，跳过整体检查
                has_batch_action = any(
                    action.get('symbol') == symbol and
                    action.get('action') in ['STOP_LOSS', 'TRAILING_STOP']
                    for action in batch_risks
                )

                if not has_batch_action:
                    position_risk = self._analyze_position_risk(position, market_data)

                    if position_risk['should_act']:
                        risk_actions.append(position_risk['action'])

                    risk_score += position_risk['risk_score']

                    # 更新个股风险状态
                    self.risk_state['position_risks'][symbol] = {
                        'risk_level': position_risk['risk_level'],
                        'last_check': datetime.now()
                    }

            # 平均个股风险分数
            position_count = len(portfolio.positions)
            if position_count > 0:
                risk_score = risk_score / position_count

            # 更新批次风险状态
            self.risk_state['last_batch_check'] = datetime.now().isoformat()
            self.risk_state['batch_risks'] = {
                'checked_batches': len(batch_risks),
                'active_actions': len([a for a in batch_risks if a.get('urgency') in ['HIGH', 'MEDIUM']])
            }

            return {
                'actions': risk_actions,
                'risk_score': risk_score,
                'checked_positions': len(portfolio.positions),
                'batch_actions': len(batch_risks)
            }

        except Exception as e:
            self.logger.error(f"个股风险检查异常: {e}")
            return {'actions': [], 'risk_score': 25, 'checked_positions': 0, 'batch_actions': 0}

    def _analyze_position_risk(self, position: Any, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """分析单个持仓的风险"""
        try:
            symbol = position.symbol
            current_data = market_data.get(symbol, {})
            current_price = current_data.get('price', 0)

            if current_price <= 0:
                return {
                    'should_act': False,
                    'action': None,
                    'risk_score': 10,
                    'risk_level': 'LOW'
                }

            # 计算盈亏比例
            profit_ratio = (current_price - position.cost_price) / position.cost_price

            risk_score = 0
            should_act = False
            action = None
            risk_level = 'LOW'

            # 1. 亏损止损检查
            if profit_ratio <= -self.risk_parameters['max_single_loss_ratio']:
                risk_score += 40
                should_act = True
                action = {
                    'symbol': symbol,
                    'action': 'STOP_LOSS',
                    'reason': f'亏损达到{abs(profit_ratio):.1%}，超过阈值',
                    'quantity': position.quantity,
                    'urgency': 'HIGH'
                }
                risk_level = 'HIGH'

            # 2. 移动止损检查 (针对盈利头寸)
            elif profit_ratio > 0:
                trailing_stop_price = self._calculate_trailing_stop_price(position, current_price)
                if current_price <= trailing_stop_price:
                    risk_score += 30
                    should_act = True
                    action = {
                        'symbol': symbol,
                        'action': 'TRAILING_STOP',
                        'reason': f'触发移动止损，保护盈利{profit_ratio:.1%}',
                        'quantity': position.quantity,
                        'urgency': 'MEDIUM'
                    }
                    risk_level = 'MEDIUM'

            # 3. 波动率止损检查
            volatility_stop = self._check_volatility_stop(position, current_data)
            if volatility_stop['should_stop']:
                risk_score += 25
                should_act = True
                action = {
                    'symbol': symbol,
                    'action': 'VOLATILITY_STOP',
                    'reason': volatility_stop['reason'],
                    'quantity': position.quantity,
                    'urgency': volatility_stop['urgency']
                }
                risk_level = max(risk_level, volatility_stop['risk_level'])

            # 4. 技术面转弱检查
            technical_risk = self._check_technical_risk(symbol, current_data)
            risk_score += technical_risk['score']
            if technical_risk['should_act'] and not should_act:
                should_act = True
                action = {
                    'symbol': symbol,
                    'action': 'TECHNICAL_EXIT',
                    'reason': technical_risk['reason'],
                    'quantity': int(position.quantity * 0.5),  # 减半仓
                    'urgency': 'LOW'
                }
                risk_level = max(risk_level, technical_risk['risk_level'])

            return {
                'should_act': should_act,
                'action': action,
                'risk_score': min(risk_score, 50),
                'risk_level': risk_level
            }

        except Exception as e:
            self.logger.error(f"分析 {position.symbol} 风险异常: {e}")
            return {
                'should_act': False,
                'action': None,
                'risk_score': 15,
                'risk_level': 'LOW'
            }

    def _calculate_trailing_stop_price(self, position: Any, current_price: float) -> float:
        """计算移动止损价"""
        # 简单的移动止损：最高回撤不超过设定比例
        if not hasattr(position, 'highest_price'):
            position.highest_price = current_price

        # 更新最高价
        if current_price > position.highest_price:
            position.highest_price = current_price

        # 计算移动止损价
        return position.highest_price * (1 - self.risk_parameters['trailing_stop_ratio'])

    def _check_volatility_stop(self, position: Any, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """检查波动率止损"""
        try:
            symbol = position.symbol
            current_price = market_data.get('price', 0)

            # 获取历史数据计算ATR
            if self.broker:
                hist_data = self.broker.get_history_kline(symbol, ktype="K_DAY", max_count=20)
                if hist_data is not None and len(hist_data) >= 14:
                    highs = hist_data['high'].values
                    lows = hist_data['low'].values
                    closes = hist_data['close'].values

                    atr = calculate_atr(highs, lows, closes)
                    atr_stop_price = position.cost_price - (atr * self.risk_parameters['volatility_stop_multiplier'])

                    if current_price <= atr_stop_price:
                        return {
                            'should_stop': True,
                            'reason': f'波动率止损触发，ATR倍数: {self.risk_parameters["volatility_stop_multiplier"]}',
                            'urgency': 'HIGH',
                            'risk_level': 'HIGH'
                        }

            return {
                'should_stop': False,
                'reason': '',
                'urgency': 'LOW',
                'risk_level': 'LOW'
            }

        except Exception as e:
            self.logger.error(f"波动率止损检查异常 {position.symbol}: {e}")
            return {
                'should_stop': False,
                'reason': '',
                'urgency': 'LOW',
                'risk_level': 'LOW'
            }

    def _check_technical_risk(self, symbol: str, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """检查技术面风险"""
        try:
            if self.broker:
                hist_data = self.broker.get_history_kline(symbol, ktype="K_DAY", max_count=50)
                if hist_data is not None and len(hist_data) >= 20:
                    closes = hist_data['close'].values

                    # 趋势分析
                    trend_data = calculate_trend_strength(closes)

                    if trend_data['trend'] == 'bearish' and trend_data['strength'] > 50:
                        return {
                            'should_act': True,
                            'reason': '技术面转弱，趋势强度较高',
                            'score': 20,
                            'risk_level': 'MEDIUM'
                        }
                    elif trend_data['direction'] == -1:
                        return {
                            'should_act': False,
                            'reason': '技术面偏弱',
                            'score': 10,
                            'risk_level': 'LOW'
                        }

            return {
                'should_act': False,
                'reason': '技术面正常',
                'score': 5,
                'risk_level': 'LOW'
            }

        except Exception as e:
            self.logger.error(f"技术面风险检查异常 {symbol}: {e}")
            return {
                'should_act': False,
                'reason': '检查失败',
                'score': 5,
                'risk_level': 'LOW'
            }

    def _check_portfolio_risks(self, portfolio: Any, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """检查组合级风险"""
        risk_actions = []
        risk_score = 0

        try:
            # 1. 组合亏损检查
            portfolio_profit = self._calculate_portfolio_profit(portfolio, market_data)
            if portfolio_profit <= -self.risk_parameters['max_portfolio_loss_ratio']:
                risk_score += 30
                risk_actions.append({
                    'action': 'PORTFOLIO_STOP',
                    'reason': f'组合亏损达到{abs(portfolio_profit):.1%}，超过阈值',
                    'urgency': 'HIGH'
                })

            # 2. 回撤检查
            drawdown = self._calculate_portfolio_drawdown(portfolio)
            if drawdown >= self.risk_parameters['max_drawdown_limit']:
                risk_score += 25
                risk_actions.append({
                    'action': 'REDUCE_EXPOSURE',
                    'reason': f'组合回撤达到{drawdown:.1%}，超过限制',
                    'urgency': 'HIGH'
                })

            # 3. 集中度检查
            concentration_risk = self._check_concentration_risk(portfolio)
            risk_score += concentration_risk['score']
            if concentration_risk['should_act']:
                risk_actions.extend(concentration_risk['actions'])

            return {
                'actions': risk_actions,
                'risk_score': risk_score
            }

        except Exception as e:
            self.logger.error(f"组合风险检查异常: {e}")
            return {'actions': [], 'risk_score': 15}

    def _calculate_portfolio_profit(self, portfolio: Any, market_data: Dict[str, Any]) -> float:
        """计算组合盈亏比例"""
        try:
            total_cost = 0
            total_value = 0

            for symbol, position in portfolio.positions.items():
                current_price = market_data.get(symbol, {}).get('price', 0)
                if current_price > 0:
                    total_cost += position.cost_price * position.quantity
                    total_value += current_price * position.quantity

            if total_cost > 0:
                return (total_value - total_cost) / total_cost
            return 0

        except Exception:
            return 0

    def _calculate_portfolio_drawdown(self, portfolio: Any) -> float:
        """计算组合回撤"""
        # 简化实现，实际应该跟踪组合历史最高值
        try:
            if hasattr(portfolio, 'peak_value') and portfolio.peak_value > 0:
                current_value = portfolio.total_assets
                return (portfolio.peak_value - current_value) / portfolio.peak_value
            return 0
        except Exception:
            return 0

    def _check_concentration_risk(self, portfolio: Any) -> Dict[str, Any]:
        """
        检查集中度风险
        
        注意：此方法只用于风险提示，不触发自动减仓。
        如果持仓因股价上涨超过20%，不需要自动减仓。
        只有在触发止损条件时，才执行减仓操作。
        """
        try:
            if len(portfolio.positions) == 0:
                return {'should_act': False, 'actions': [], 'score': 0}

            # 计算每个持仓的比例（使用当前市值，而不是成本价）
            total_value = portfolio.total_assets
            position_ratios = {}
            max_position_ratio = 0
            max_position_symbol = None

            for symbol, position in portfolio.positions.items():
                # 使用当前市值计算持仓比例
                current_price = getattr(position, 'current_price', position.cost_price)
                position_value = current_price * position.quantity
                position_ratio = position_value / total_value if total_value > 0 else 0
                position_ratios[symbol] = position_ratio
                if position_ratio > max_position_ratio:
                    max_position_ratio = position_ratio
                    max_position_symbol = symbol

            score = 0
            actions = []
            should_act = False

            # 检查是否超过集中度限制（默认20%）
            # 注意：这里只记录风险提示，不触发自动减仓
            concentration_limit = self.risk_parameters.get('position_concentration_limit', 0.2)
            
            if max_position_ratio > concentration_limit and max_position_symbol:
                # 只增加风险评分，不触发自动减仓动作
                score = 10  # 降低风险评分，因为只是提示
                should_act = False  # 不触发自动减仓
                
                # 只记录风险提示，不执行减仓
                self.logger.info(
                    f"⚠️ 持仓集中度提示: {max_position_symbol} 持仓比例 {max_position_ratio:.1%} "
                    f"超过限制 {concentration_limit:.1%}（因股价上涨导致，不自动减仓）"
                )
                
                # 不添加任何action，因为不需要自动减仓
                # 只有在止损条件触发时才会执行减仓

            return {
                'should_act': should_act,  # 始终为False，不触发自动减仓
                'actions': actions,  # 始终为空，不执行减仓动作
                'score': score
            }

        except Exception as e:
            self.logger.error(f"集中度风险检查异常: {e}")
            return {'should_act': False, 'actions': [], 'score': 5}

    def _check_market_risks(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """检查市场风险"""
        risk_actions = []
        risk_score = 0

        try:
            # 1. 市场整体走势
            market_trend = market_data.get('market_trend', {})
            if market_trend.get('direction', 0) < 0:
                risk_score += 15
                risk_actions.append({
                    'action': 'REDUCE_LEVERAGE',
                    'reason': '市场整体走弱，降低风险暴露',
                    'urgency': 'MEDIUM'
                })

            # 2. 市场波动率
            market_volatility = market_data.get('volatility', 0)
            if market_volatility > self.risk_parameters['high_volatility_threshold']:
                risk_score += 20
                risk_actions.append({
                    'action': 'INCREASE_CASH',
                    'reason': f'市场波动率{market_volatility:.1%}过高，增加现金比例',
                    'urgency': 'HIGH'
                })

            return {
                'actions': risk_actions,
                'risk_score': risk_score
            }

        except Exception as e:
            self.logger.error(f"市场风险检查异常: {e}")
            return {'actions': [], 'risk_score': 10}

    def _check_time_risks(self, portfolio: Any) -> Dict[str, Any]:
        """检查时间维度风险"""
        risk_actions = []
        risk_score = 0

        try:
            current_time = datetime.now()

            for symbol, position in portfolio.positions.items():
                # 检查持仓时间
                if hasattr(position, 'purchase_time'):
                    holding_days = (current_time - position.purchase_time).days

                    if holding_days > self.risk_parameters['position_holding_limit']:
                        risk_score += 15
                        risk_actions.append({
                            'symbol': symbol,
                            'action': 'TIME_EXIT',
                            'reason': f'持仓{holding_days}天超过时间限制',
                            'quantity': position.quantity,
                            'urgency': 'LOW'
                        })

                # 盈利保护期检查
                if hasattr(position, 'profit_protection_start') and position.profit_protection_start:
                    protection_days = (current_time - position.profit_protection_start).days
                    if protection_days < self.risk_parameters['profit_protection_time']:
                        # 在盈利保护期内，降低止损阈值
                        pass

            return {
                'actions': risk_actions,
                'risk_score': risk_score
            }

        except Exception as e:
            self.logger.error(f"时间风险检查异常: {e}")
            return {'actions': [], 'risk_score': 5}

    def _calculate_overall_risk(self, risk_scores: Dict[str, float], action_count: int) -> tuple:
        """计算总体风险等级"""
        try:
            # 加权计算总风险分数
            weights = {
                'individual': 0.4,  # 个股风险权重40%
                'portfolio': 0.3,  # 组合风险权重30%
                'market': 0.2,  # 市场风险权重20%
                'time': 0.1  # 时间风险权重10%
            }

            total_score = 0
            for risk_type, score in risk_scores.items():
                total_score += score * weights.get(risk_type, 0.25)

            # 根据行动数量调整风险等级
            if action_count > 3:
                total_score = min(total_score + 20, 100)
            elif action_count > 1:
                total_score = min(total_score + 10, 100)

            # 确定风险等级
            if total_score >= 70 or action_count > 3:
                return 'CRITICAL', total_score
            elif total_score >= 50:
                return 'HIGH', total_score
            elif total_score >= 30:
                return 'MEDIUM', total_score
            else:
                return 'LOW', total_score

        except Exception as e:
            self.logger.error(f"计算总体风险异常: {e}")
            return 'UNKNOWN', 50

    def should_stop_loss(self, position: Any, market_data: Dict[str, Any]) -> bool:
        """判断是否应该止损 - 简化接口"""
        try:
            risk_analysis = self._analyze_position_risk(position, market_data)
            return risk_analysis['should_act'] and risk_analysis['action'] is not None

        except Exception as e:
            self.logger.error(f"止损判断异常: {e}")
            return False

    def set_risk_parameters(self, parameters: Dict[str, Any]):
        """更新风控参数"""
        self.risk_parameters.update(parameters)
        self.logger.info(f"🔄 高级风控策略参数已更新")

    def get_risk_report(self) -> Dict[str, Any]:
        """获取风险报告 - 增强版本"""
        base_report = {
            'strategy': self.name,
            'current_risk_level': self.risk_state['overall_risk_level'],
            'parameters': self.risk_parameters,
            'last_check': self.risk_state['last_market_check'],
            'position_risks': self.risk_state['position_risks']
        }

        # 添加分级仓位相关信息
        if self.risk_parameters['scaling_enabled']:
            base_report.update({
                'scaling_enabled': True,
                'last_batch_check': self.risk_state.get('last_batch_check'),
                'batch_risks': self.risk_state.get('batch_risks', {}),
                'scaling_config': self.scaling_config
            })
        else:
            base_report['scaling_enabled'] = False

        return base_report

    def execute(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """实现抽象方法 execute"""
        portfolio = data.get("portfolio")
        market_data = data.get("market_data")
        #self.check_risk(portfolio, market_data)
        #return {"status": "ok"}
        if portfolio is None:
            self.logger.error("❌ 风控执行失败: 未传入有效的 portfolio 对象")
            return {"status": "error", "message": "missing portfolio"}

        if market_data is None:
            self.logger.error("⚠️ 风控执行警告: 未传入 market_data，将跳过市场风险检查")
            market_data = {}

        return self.check_risk(portfolio, market_data)

    def _load_scaling_config(self) -> Dict[str, Any]:
        """加载分级仓位配置"""
        default_config = {
            'enabled': True,
            'levels': {
                1: {'stop_loss_ratio': 0.08, 'trailing_stop_ratio': 0.05},
                2: {'stop_loss_ratio': 0.04, 'trailing_stop_ratio': 0.04},
                3: {'stop_loss_ratio': 0.03, 'trailing_stop_ratio': 0.03}
            }
        }

        try:
            if (self.config and hasattr(self.config, 'position_scaling_enabled') and
                    self.config.position_scaling_enabled):

                scaling_config = {}
                scaling_config['enabled'] = True

                # 从配置中读取各级别参数
                levels_config = {}
                for level in [1, 2, 3]:
                    level_config = self.config.get_scaling_level_config(level)
                    if level_config:
                        levels_config[level] = {
                            'stop_loss_ratio': getattr(level_config, 'stop_loss_ratio', 0.08),
                            'trailing_stop_ratio': getattr(level_config, 'trailing_stop_ratio', 0.03)
                        }

                scaling_config['levels'] = levels_config
                return scaling_config

        except Exception as e:
            self.logger.warning(f"加载分级仓位配置失败，使用默认配置: {e}")

        return default_config

    def _check_batch_risks(self, portfolio: Any, market_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        检查批次级别风险
        每个仓位批次独立进行风控检查
        """
        batch_actions = []

        try:
            # 检查是否需要执行批次风控检查
            if not self._should_check_batch_risks():
                return batch_actions

            # 遍历所有股票的活跃批次
            for symbol, position in portfolio.positions.items():
                current_data = market_data.get(symbol, {})
                current_price = current_data.get('price', 0)

                if current_price <= 0:
                    continue

                # 获取该股票的所有活跃批次
                active_batches = self._get_active_batches(portfolio, symbol)

                for batch in active_batches:
                    batch_risk = self._analyze_batch_risk(batch, current_price, current_data)

                    if batch_risk['should_act']:
                        batch_actions.append(batch_risk['action'])

                        # 更新批次风险状态
                        self.risk_state['batch_risks'][batch.batch_id] = {
                            'risk_level': batch_risk['risk_level'],
                            'last_check': datetime.now(),
                            'action_taken': batch_risk['action']['action']
                        }

            return batch_actions

        except Exception as e:
            self.logger.error(f"批次风险检查异常: {e}")
            return []

    def _analyze_batch_risk(self, batch: Any, current_price: float, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        分析单个批次的风险
        """
        try:
            # 获取该批次级别的风控参数
            level_config = self.scaling_config['levels'].get(batch.level, {})
            stop_loss_ratio = level_config.get('stop_loss_ratio', 0.08)
            trailing_stop_ratio = level_config.get('trailing_stop_ratio', 0.03)

            # 计算批次盈亏
            batch_profit_ratio = (current_price - batch.entry_price) / batch.entry_price

            risk_score = 0
            should_act = False
            action = None
            risk_level = 'LOW'

            # 1. 批次级别止损检查
            if batch_profit_ratio <= -stop_loss_ratio:
                risk_score += 35
                should_act = True
                action = {
                    'symbol': batch.symbol,
                    'action': 'BATCH_STOP_LOSS',
                    'reason': f'批次L{batch.level}亏损达到{abs(batch_profit_ratio):.1%}，超过阈值{stop_loss_ratio:.1%}',
                    'quantity': batch.quantity,
                    'batch_id': batch.batch_id,
                    'batch_level': batch.level,
                    'urgency': 'HIGH'
                }
                risk_level = 'HIGH'

            # 2. 批次移动止损检查
            elif batch_profit_ratio > 0:
                # 更新批次最高价和移动止损
                if current_price > batch.highest_price:
                    batch.highest_price = current_price

                trailing_stop_price = batch.highest_price * (1 - trailing_stop_ratio)

                if current_price <= trailing_stop_price:
                    risk_score += 25
                    should_act = True
                    action = {
                        'symbol': batch.symbol,
                        'action': 'BATCH_TRAILING_STOP',
                        'reason': f'批次L{batch.level}触发移动止损，保护盈利{batch_profit_ratio:.1%}',
                        'quantity': batch.quantity,
                        'batch_id': batch.batch_id,
                        'batch_level': batch.level,
                        'urgency': 'MEDIUM'
                    }
                    risk_level = 'MEDIUM'

            # 3. 批次波动率止损检查
            volatility_stop = self._check_batch_volatility_stop(batch, current_price, market_data)
            if volatility_stop['should_stop']:
                risk_score += 20
                should_act = True
                action = {
                    'symbol': batch.symbol,
                    'action': 'BATCH_VOLATILITY_STOP',
                    'reason': volatility_stop['reason'],
                    'quantity': batch.quantity,
                    'batch_id': batch.batch_id,
                    'batch_level': batch.level,
                    'urgency': volatility_stop['urgency']
                }
                risk_level = max(risk_level, volatility_stop['risk_level'])

            return {
                'should_act': should_act,
                'action': action,
                'risk_score': min(risk_score, 40),  # 批次风险分数上限较低
                'risk_level': risk_level
            }

        except Exception as e:
            self.logger.error(f"分析批次风险异常 {getattr(batch, 'batch_id', 'unknown')}: {e}")
            return {
                'should_act': False,
                'action': None,
                'risk_score': 10,
                'risk_level': 'LOW'
            }

    def _should_check_batch_risks(self) -> bool:
        """判断是否需要执行批次风控检查"""
        if not self.risk_parameters['scaling_enabled']:
            return False

        last_check = self.risk_state.get('last_batch_check')
        if not last_check:
            return True

        if isinstance(last_check, str):
            from datetime import datetime
            last_check = datetime.fromisoformat(last_check)

        check_interval = self.risk_parameters.get('batch_risk_check_interval', 300)
        return (datetime.now() - last_check).total_seconds() >= check_interval

    def _get_active_batches(self, portfolio: Any, symbol: str) -> List[Any]:
        """获取指定股票的活跃批次"""
        try:
            if hasattr(portfolio, 'get_active_batches'):
                return portfolio.get_active_batches(symbol)
            elif hasattr(portfolio, 'batch_manager'):
                return portfolio.batch_manager.get_active_batches_by_symbol(symbol)
            else:
                return []
        except Exception as e:
            self.logger.error(f"获取活跃批次异常 {symbol}: {e}")
            return []

    def _check_batch_volatility_stop(self, batch: Any, current_price: float, market_data: Dict[str, Any]) -> Dict[
        str, Any]:
        """检查批次波动率止损"""
        try:
            symbol = batch.symbol

            # 获取历史数据计算ATR
            if self.broker:
                hist_data = self.broker.get_history_kline(symbol, ktype="K_DAY", max_count=20)
                if hist_data is not None and len(hist_data) >= 14:
                    highs = hist_data['high'].values
                    lows = hist_data['low'].values
                    closes = hist_data['close'].values

                    atr = calculate_atr(highs, lows, closes)

                    # 根据批次级别调整ATR倍数
                    level_multipliers = {1: 2.0, 2: 1.5, 3: 1.2}
                    multiplier = level_multipliers.get(batch.level, 2.0)

                    atr_stop_price = batch.entry_price - (atr * multiplier)

                    if current_price <= atr_stop_price:
                        return {
                            'should_stop': True,
                            'reason': f'批次L{batch.level}波动率止损触发，ATR倍数: {multiplier}',
                            'urgency': 'HIGH',
                            'risk_level': 'HIGH'
                        }

            return {
                'should_stop': False,
                'reason': '',
                'urgency': 'LOW',
                'risk_level': 'LOW'
            }

        except Exception as e:
            self.logger.error(f"批次波动率止损检查异常 {getattr(batch, 'batch_id', 'unknown')}: {e}")
            return {
                'should_stop': False,
                'reason': '',
                'urgency': 'LOW',
                'risk_level': 'LOW'
            }

# 导出类
__all__ = ['AdvancedRiskStrategy']