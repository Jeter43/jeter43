# trading_system/domain/analysis/multi_dimension_scorer.py
import pandas as pd
import numpy as np
from typing import Dict, Any, List
import sys
import os

# 添加项目根目录到Python路径
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)


from quant_system.utils.logger import get_logger
from quant_system.utils.indicators import (
    calculate_trend_strength, calculate_macd, calculate_rsi,
    calculate_volume_indicators, calculate_atr, calculate_bollinger_bands,
    calculate_kdj
)


class MultiDimensionScorer:
    """多维度评分系统 - 融合实时数据增强"""

    def __init__(self, broker=None):
        self.broker = broker
        self.logger = get_logger()

    def calculate_comprehensive_score(self, symbol: str, kline_data: pd.DataFrame,
                                      realtime_data: Dict) -> Dict[str, Any]:
        """
        计算综合技术评分

        Args:
            symbol: 股票代码
            kline_data: 历史K线数据
            realtime_data: 实时行情数据

        Returns:
            Dict: 评分结果和详细分析
        """
        try:
            base_score = 50.0  # 基础分
            components = {}
            reasons = []

            # 1. 实时技术分析（原有系统条件）
            condition_analysis = self._analyze_trading_conditions(kline_data, realtime_data)
            base_score += condition_analysis['score']
            components['条件分析'] = condition_analysis['score']
            reasons.extend(condition_analysis['reasons'])

            # 2. 趋势强度分析
            trend_analysis = self._analyze_trend_strength(kline_data)
            base_score += trend_analysis['score']
            components['趋势强度'] = trend_analysis['score']
            reasons.extend(trend_analysis['reasons'])

            # 3. 动量指标分析
            momentum_analysis = self._analyze_momentum_indicators(kline_data)
            base_score += momentum_analysis['score']
            components['动量指标'] = momentum_analysis['score']
            reasons.extend(momentum_analysis['reasons'])

            # 4. 成交量分析
            volume_analysis = self._analyze_volume_indicators(kline_data)
            base_score += volume_analysis['score']
            components['成交量'] = volume_analysis['score']
            reasons.extend(volume_analysis['reasons'])

            # 5. 波动率分析
            volatility_analysis = self._analyze_volatility(kline_data)
            base_score += volatility_analysis['score']
            components['波动率'] = volatility_analysis['score']
            reasons.extend(volatility_analysis['reasons'])

            # 最终分数调整
            final_score = min(100.0, max(0.0, base_score))

            return {
                'final_score': final_score,
                'components': components,
                'reasons': reasons,
                'detailed_analysis': {
                    'condition_analysis': condition_analysis,
                    'trend_analysis': trend_analysis,
                    'momentum_analysis': momentum_analysis,
                    'volume_analysis': volume_analysis,
                    'volatility_analysis': volatility_analysis
                }
            }

        except Exception as e:
            self.logger.error(f"综合评分计算异常 {symbol}: {e}")
            return {
                'final_score': 45.0,
                'components': {},
                'reasons': ["评分计算异常"],
                'detailed_analysis': {}
            }

    def _analyze_trading_conditions(self, kline_data: pd.DataFrame, realtime_data: Dict) -> Dict[str, Any]:
        """分析交易条件 - 融合实时数据"""
        score = 0
        reasons = []

        try:
            current_price = realtime_data.get('last_price', 0)
            current_change = realtime_data.get('change_rate', 0)

            if len(kline_data) < 5:
                return {'score': 0, 'reasons': reasons}

            # 实时价格与均线关系
            ma_reasons = self._analyze_realtime_ma(kline_data, current_price)
            score += ma_reasons['score']
            reasons.extend(ma_reasons['reasons'])

            # 实时涨跌幅分析
            momentum_reasons = self._analyze_realtime_momentum(current_change, kline_data)
            score += momentum_reasons['score']
            reasons.extend(momentum_reasons['reasons'])

            # 跳空缺口分析
            yesterday_close = float(kline_data['close'].iloc[-1])
            gap_reasons = self._analyze_gap_effect(current_price, yesterday_close)
            score += gap_reasons['score']
            reasons.extend(gap_reasons['reasons'])

        except Exception as e:
            self.logger.debug(f"交易条件分析异常: {e}")

        return {'score': score, 'reasons': reasons}

    def _analyze_realtime_ma(self, kline_data: pd.DataFrame, current_price: float) -> Dict[str, Any]:
        """分析实时价格与均线关系"""
        score = 0
        reasons = []

        try:
            closes = kline_data['close']

            if len(closes) >= 5:
                ma5 = float(closes.rolling(5).mean().iloc[-1])
                if current_price > ma5:
                    score += 8
                    reasons.append("站上5日线")

            if len(closes) >= 10:
                ma10 = float(closes.rolling(10).mean().iloc[-1])
                if current_price > ma10:
                    score += 6
                    reasons.append("站上10日线")

            if len(closes) >= 20:
                ma20 = float(closes.rolling(20).mean().iloc[-1])
                if current_price > ma20:
                    score += 4
                    reasons.append("站上20日线")

            # 均线多头排列加分
            if (len(closes) >= 20 and
                    current_price > ma5 > ma10 > ma20):
                score += 5
                reasons.append("均线多头排列")

        except Exception as e:
            self.logger.debug(f"实时均线分析异常: {e}")

        return {'score': score, 'reasons': reasons}

    def _analyze_realtime_momentum(self, current_change: float, kline_data: pd.DataFrame) -> Dict[str, Any]:
        """分析实时动量"""
        score = 0
        reasons = []

        try:
            # 实时涨跌幅分析
            if current_change > 0.03:  # 涨幅超过3%
                score += 8
                reasons.append(f"强势上涨{current_change * 100:.1f}%")
            elif current_change > 0.01:  # 涨幅1-3%
                score += 5
                reasons.append(f"温和上涨{current_change * 100:.1f}%")
            elif current_change > 0:
                score += 3
                reasons.append(f"微幅上涨{current_change * 100:.1f}%")
            elif current_change < -0.03:  # 跌幅超过3%
                score -= 5  # 大幅减分
                reasons.append(f"大幅下跌{abs(current_change) * 100:.1f}%")

            # 结合历史动量
            if len(kline_data) >= 6:
                closes = kline_data['close']
                price_5_days_ago = float(closes.iloc[-6])
                if price_5_days_ago > 0:
                    historical_momentum = (closes.iloc[-1] - price_5_days_ago) / price_5_days_ago
                    if historical_momentum > 0.02 and current_change > 0:
                        score += 5
                        reasons.append("动量持续向上")

        except Exception as e:
            self.logger.debug(f"实时动量分析异常: {e}")

        return {'score': score, 'reasons': reasons}

    def _analyze_gap_effect(self, current_price: float, yesterday_close: float) -> Dict[str, Any]:
        """分析跳空缺口效应"""
        score = 0
        reasons = []

        try:
            if yesterday_close > 0:
                gap_ratio = (current_price - yesterday_close) / yesterday_close

                if gap_ratio > 0.03:  # 跳空高开3%以上
                    score += 6
                    reasons.append("跳空高开强势")
                elif gap_ratio > 0.01:  # 跳空高开1-3%
                    score += 3
                    reasons.append("跳空高开")
                elif gap_ratio < -0.03:  # 跳空低开3%以上
                    score -= 4  # 减分
                    reasons.append("跳空低开弱势")
                elif gap_ratio < -0.01:  # 跳空低开1-3%
                    score -= 2  # 小幅减分
                    reasons.append("跳空低开")

        except Exception as e:
            self.logger.debug(f"跳空分析异常: {e}")

        return {'score': score, 'reasons': reasons}

    def _analyze_trend_strength(self, kline_data: pd.DataFrame) -> Dict[str, Any]:
        """分析趋势强度"""
        score = 0
        reasons = []

        try:
            if len(kline_data) < 20:
                return {'score': 0, 'reasons': reasons}

            closes = kline_data['close'].values
            highs = kline_data['high'].values
            lows = kline_data['low'].values

            # 使用工具函数计算趋势强度
            trend_data = calculate_trend_strength(closes)

            if trend_data['trend'] == 'bullish':
                base_score = 15
                strength_bonus = trend_data['strength'] * 0.15
                score = base_score + strength_bonus
                reasons.append(f"上升趋势(强度:{trend_data['strength']:.2f})")
            elif trend_data['trend'] == 'bearish':
                score = 5
                reasons.append("下降趋势")
            else:
                score = 8
                reasons.append("震荡趋势")

        except Exception as e:
            self.logger.debug(f"趋势强度分析异常: {e}")

        return {'score': score, 'reasons': reasons}

    def _analyze_momentum_indicators(self, kline_data: pd.DataFrame) -> Dict[str, Any]:
        """分析动量指标"""
        score = 0
        reasons = []

        try:
            if len(kline_data) < 20:
                return {'score': 0, 'reasons': reasons}

            closes = kline_data['close'].values
            highs = kline_data['high'].values
            lows = kline_data['low'].values

            # MACD分析
            macd_data = calculate_macd(closes)
            if macd_data['dif'] > macd_data['dea'] and macd_data['macd'] > 0:
                score += 6
                reasons.append("MACD金叉向上")

            # RSI分析
            rsi = calculate_rsi(closes)
            if 30 <= rsi <= 70:  # 正常区间
                score += 4
                reasons.append(f"RSI正常({rsi:.1f})")
            elif rsi < 30:  # 超卖，可能反弹
                score += 3
                reasons.append(f"RSI超卖({rsi:.1f})")

            # KDJ分析
            kdj_data = calculate_kdj(highs, lows, closes)
            if kdj_data['k'] > kdj_data['d'] and kdj_data['k'] < 80:
                score += 4
                reasons.append("KDJ金叉")

        except Exception as e:
            self.logger.debug(f"动量指标分析异常: {e}")

        return {'score': score, 'reasons': reasons}

    def _analyze_volume_indicators(self, kline_data: pd.DataFrame) -> Dict[str, Any]:
        """分析成交量指标"""
        score = 0
        reasons = []

        try:
            if len(kline_data) < 10:
                return {'score': 0, 'reasons': reasons}

            volumes = kline_data['volume'].values
            closes = kline_data['close'].values

            # 量比分析
            volume_data = calculate_volume_indicators(volumes, closes)
            volume_ratio = volume_data['volume_ratio']

            if volume_ratio > 1.5:
                score += 6
                reasons.append(f"明显放量(量比:{volume_ratio:.2f})")
            elif volume_ratio > 1.2:
                score += 4
                reasons.append(f"温和放量(量比:{volume_ratio:.2f})")
            elif volume_ratio > 0.8:
                score += 2
                reasons.append(f"量能正常(量比:{volume_ratio:.2f})")

            # OBV能量潮
            obv_trend = self._analyze_obv_trend(volume_data['obv'])
            score += obv_trend['score']
            reasons.extend(obv_trend['reasons'])

        except Exception as e:
            self.logger.debug(f"成交量分析异常: {e}")

        return {'score': score, 'reasons': reasons}

    def _analyze_obv_trend(self, obv_value: float) -> Dict[str, Any]:
        """分析OBV趋势"""
        score = 0
        reasons = []

        try:
            if obv_value > 0:
                score += 3
                reasons.append("资金流入(OBV)")
            else:
                score += 1
                reasons.append("资金流出(OBV)")
        except:
            pass

        return {'score': score, 'reasons': reasons}

    def _analyze_volatility(self, kline_data: pd.DataFrame) -> Dict[str, Any]:
        """分析波动率"""
        score = 0
        reasons = []

        try:
            if len(kline_data) < 20:
                return {'score': 0, 'reasons': reasons}

            highs = kline_data['high'].values
            lows = kline_data['low'].values
            closes = kline_data['close'].values
            current_price = float(closes[-1])

            # ATR波动率分析
            atr = calculate_atr(highs, lows, closes)
            atr_value = float(atr[-1]) if hasattr(atr, '__len__') else float(atr)

            if atr_value > 0 and current_price > 0:
                atr_ratio = atr_value / current_price

                if atr_ratio < 0.025:  # 低波动
                    score += 3
                    reasons.append("低波动")
                elif atr_ratio < 0.04:  # 适中波动 (最佳)
                    score += 5
                    reasons.append("波动适中")
                elif atr_ratio < 0.06:  # 较高波动
                    score += 2
                    reasons.append("波动较高")

            # 布林带位置分析
            bb_score = self._calculate_bollinger_bands_score(closes, current_price)
            score += bb_score['score']
            reasons.extend(bb_score['reasons'])

        except Exception as e:
            self.logger.debug(f"波动率分析异常: {e}")

        return {'score': score, 'reasons': reasons}

    def _calculate_bollinger_bands_score(self, closes: List[float], current_price: float) -> Dict[str, Any]:
        """计算布林带位置得分"""
        score = 0
        reasons = []

        try:
            bb_data = calculate_bollinger_bands(closes)

            if isinstance(bb_data, dict):
                upper = float(bb_data.get('upper', 0))
                lower = float(bb_data.get('lower', 0))
            else:
                upper = float(bb_data.upper[-1]) if hasattr(bb_data, 'upper') else 0
                lower = float(bb_data.lower[-1]) if hasattr(bb_data, 'lower') else 0

            if upper <= lower:
                return {'score': 0, 'reasons': reasons}

            # 计算当前位置
            bb_position = (current_price - lower) / (upper - lower)

            # 布林带位置评分
            if bb_position < 0.2:  # 接近下轨，超卖
                score += 3
                reasons.append("布林带下轨")
            elif 0.3 <= bb_position <= 0.7:  # 中轨区域 (最佳)
                score += 4
                reasons.append("布林带中轨")
            elif bb_position < 0.8:  # 上轨附近
                score += 2
                reasons.append("布林带上轨")

        except Exception as e:
            self.logger.debug(f"布林带评分计算异常: {e}")

        return {'score': score, 'reasons': reasons}


# 导出类
__all__ = ['MultiDimensionScorer']