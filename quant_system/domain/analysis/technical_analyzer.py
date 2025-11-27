# trading_system/domain/analysis/technical_analyzer.py
"""
TechnicalAnalyzer - 技术分析引擎（兼容富途/缺失 volume）
修复点：
- 兼容富途返回的 volume/turnover 差异，确保生成 VOLUME_RATIO / V_MA20
- 增强异常保护，避免吞掉关键字段导致后续分析失败
- 保持原有三个核心条件与输出格式
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, List
import sys
import os
import logging

# 添加项目根目录到Python路径（与你项目结构兼容）
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from quant_system.utils.logger import get_logger


class TechnicalAnalyzer:
    """技术分析引擎 - 融合原有系统逻辑，增强数据兼容性"""

    def __init__(self):
        # get_logger 支持传入 name，也允许无参调用
        try:
            self.logger = get_logger(__name__)
        except Exception:
            self.logger = logging.getLogger(__name__)

    def analyze_conditions(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        分析技术条件 - 返回结构兼容原系统
        Args:
            df: 包含OHLCV数据的DataFrame（索引可为时间）
        Returns:
            Dict: 分析结果（见原格式）
        """
        try:
            # 数据预处理与字段兼容
            df = self._prepare_data(df)

            # 计算关键技术指标（含成交量兼容）
            df = self._calculate_technical_indicators(df)

            # 检查三个核心条件
            cond1 = self._check_condition_red_volume_low(df)
            cond2 = self._check_condition_convergence_volume(df)
            cond3 = self._check_condition_simple_breakout(df)

            # 计算基础分数（与原逻辑保持兼容）
            base_score = 0
            if cond1:
                base_score += 40
            if cond2:
                base_score += 40
            if cond3:
                base_score += 40

            # 计算各项加成
            volume_bonus = self._calculate_volume_bonus(df)
            trend_bonus = self._calculate_trend_bonus(df)
            performance_bonus = self._calculate_performance_bonus(df)

            total_score = base_score + volume_bonus + trend_bonus + performance_bonus

            # 构造返回 technical_indicators 保留原有字段名
            technical_indicators = {}
            try:
                technical_indicators = {
                    'current_price': float(df['close'].iloc[-1]) if 'close' in df.columns and len(df) > 0 else 0.0,
                    'volume_ratio': float(df['VOLUME_RATIO'].iloc[-1]) if 'VOLUME_RATIO' in df.columns and not pd.isna(df['VOLUME_RATIO'].iloc[-1]) else 0.0,
                    'conv_degree': float(df['CONV'].iloc[-1]) if 'CONV' in df.columns and not pd.isna(df['CONV'].iloc[-1]) else 0.0,
                    'close_vs_ma5': float((df['close'].iloc[-1] / df['MA_5'].iloc[-1] - 1) * 100) if 'MA_5' in df.columns and df['MA_5'].iloc[-1] != 0 else 0.0,
                    'close_vs_ma20': float((df['close'].iloc[-1] / df['MA_20'].iloc[-1] - 1) * 100) if 'MA_20' in df.columns and df['MA_20'].iloc[-1] != 0 else 0.0
                }
            except Exception as e:
                self.logger.debug(f"构建 technical_indicators 时异常: {e}")
                technical_indicators = {}

            return {
                'selected': base_score > 0,
                'condition_count': int(sum([cond1, cond2, cond3])),
                'total_score': float(total_score),
                'base_score': float(base_score),
                'volume_bonus': float(volume_bonus),
                'trend_bonus': float(trend_bonus),
                'performance_bonus': float(performance_bonus),
                'conditions_detail': {
                    '阳线放量低位': bool(cond1),
                    '均线收敛启动': bool(cond2),
                    '简单突破': bool(cond3)
                },
                'technical_indicators': technical_indicators
            }

        except Exception as e:
            self.logger.error(f"技术分析异常: {e}")
            self.logger.debug("", exc_info=True)
            return {
                'selected': False,
                'total_score': 0,
                'condition_count': 0,
                'conditions_detail': {},
                'technical_indicators': {}
            }

    def _prepare_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """数据预处理：类型转换、列名兼容、索引处理"""
        df = df.copy()
        # 先统一列小写（避免大小写不一致）
        df.columns = [c.lower() for c in df.columns]

        # 常见列可能的别名映射（便于兼容外部数据）
        col_map = {
            'date': 'time_key',
            'time_key': 'time_key',
            'open': 'open',
            'high': 'high',
            'low': 'low',
            'close': 'close',
            'volume': 'volume',
            'turnover': 'turnover',
            'total_market_val': 'total_market_val'
        }

        # 强制保留需要的列（若不存在，后续计算取默认/填充）
        for col in ['open', 'high', 'low', 'close', 'volume', 'turnover']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        # 保证最后至少包含 close 列
        if 'close' not in df.columns:
            df['close'] = pd.Series([np.nan] * len(df))

        # 若没有明确的时间索引，保持现有顺序
        return df

    def _calculate_technical_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        计算技术指标并确保成交量相关字段可用：
        - 生成 VOLUME（兼容 volume 或由 turnover / close 估计）
        - 计算 V_MA20, VOLUME_RATIO 等
        - 其它均线/EMA/MACD 指标保持原实现
        """
        try:
            # 1) 成交量兼容处理
            # 优先使用 volume 字段且其总和 > 0
            if 'volume' in df.columns and df['volume'].notna().sum() > 0 and df['volume'].sum() > 0:
                vol = df['volume'].fillna(0).astype(float)
            elif 'turnover' in df.columns and 'close' in df.columns and df['close'].replace(0, np.nan).notna().sum() > 0:
                # turnover / price -> 近似成交量（当 volume 缺失时）
                with np.errstate(divide='ignore', invalid='ignore'):
                    vol_est = df['turnover'].astype(float) / df['close'].replace(0, np.nan).astype(float)
                    vol = vol_est.fillna(0).astype(float)
            else:
                # 最后退化为 0 向量
                vol = pd.Series([0.0] * len(df), index=df.index, dtype=float)

            df['VOLUME'] = vol

            # 2) V_MA20 与 VOLUME_RATIO 计算（避免除0/NaN）
            df['V_MA20'] = df['VOLUME'].rolling(20, min_periods=1).mean()
            # 若 V_MA20 为 0 -> 设置为 NaN 避免 inf
            df.loc[df['V_MA20'] == 0, 'V_MA20'] = np.nan

            with np.errstate(divide='ignore', invalid='ignore'):
                df['VOLUME_RATIO'] = (df['VOLUME'] / df['V_MA20']).replace([np.inf, -np.inf], np.nan).fillna(0.0)

            # 3) 均线与EMA（使用原有的 EMA 实现风格）
            df['EMA_MID'] = self._EMA(df['close'], 55)
            df['EMA_20'] = self._EMA(df['close'], 20)

            for n in [5, 10, 20, 30]:
                df[f'MA_{n}'] = self._EMA(df['close'], n)

            # 均线群聚合：均值和收敛度（CONV）
            ma_columns = [f'MA_{n}' for n in [5, 10, 20, 30]]
            # 若某些 MA 列因为数据不足出现 NaN，mean 会自动处理
            df['MA_MEAN'] = df[ma_columns].mean(axis=1)
            # 防止除以0
            df['CONV'] = (df[ma_columns].std(axis=1) / df['MA_MEAN'].replace(0, np.nan)) * 100
            df['CONV'] = df['CONV'].fillna(0.0)

            # 4) MACD 计算（DIF, DEA, MACD）
            df['DIF'] = self._EMA(df['close'], 12) - self._EMA(df['close'], 26)
            df['DEA'] = self._EMA(df['DIF'], 9)
            df['MACD'] = (df['DIF'] - df['DEA']) * 2
            df['MACD_GOLDEN'] = (df['DIF'] > df['DEA']) & (df['DIF'].shift(1) <= df['DEA'].shift(1))

            # 5) V_MA20 已存在，VOLUME_RATIO 已计算
            df['V_MA20'] = df['V_MA20'].fillna(0.0)
            # K线颜色和位置
            df['IS_RED'] = df['close'] > df.get('open', df['close'])  # 若 open 缺失，IS_RED False
            df['IS_GREEN'] = df['close'] < df.get('open', df['close'])
            # 相对低位：使用 low 与 10 日均低价对比（若 low 缺失则 False）
            if 'low' in df.columns:
                df['RELATIVE_LOW'] = df['low'] <= df['low'].rolling(10, min_periods=1).mean()
            else:
                df['RELATIVE_LOW'] = False

            return df

        except Exception as e:
            self.logger.error(f"技术指标计算异常: {e}")
            self.logger.debug("", exc_info=True)
            return df

    def _EMA(self, series: pd.Series, n: int) -> pd.Series:
        """计算指数移动平均，支持 series 中含 NaN"""
        try:
            return series.ewm(span=n, adjust=False).mean()
        except Exception:
            # 退化实现（当 series 包含非数值导致失败时）
            s = pd.to_numeric(series, errors='coerce').fillna(method='ffill').fillna(0.0)
            return s.ewm(span=n, adjust=False).mean()

    def _check_condition_red_volume_low(self, df: pd.DataFrame) -> bool:
        """条件1: 阳线 + 放量 + 相对低位（兼容缺量数据）"""
        try:
            if len(df) < 2:
                return False

            is_red = bool(df['IS_RED'].iloc[-1]) if 'IS_RED' in df.columns else False
            vol_ratio = float(df['VOLUME_RATIO'].iloc[-1]) if 'VOLUME_RATIO' in df.columns else 0.0
            relative_low = bool(df['RELATIVE_LOW'].iloc[-1]) if 'RELATIVE_LOW' in df.columns else False

            return (
                is_red and
                (vol_ratio > 1.2) and
                relative_low
            )
        except Exception:
            return False

    def _check_condition_convergence_volume(self, df: pd.DataFrame) -> bool:
        """条件2: 均线收敛 + 放量 + 多头趋势"""
        try:
            if len(df) < 2:
                return False

            conv = float(df['CONV'].iloc[-1]) if 'CONV' in df.columns else np.inf
            vol_ratio = float(df['VOLUME_RATIO'].iloc[-1]) if 'VOLUME_RATIO' in df.columns else 0.0
            ma_mean = float(df['MA_MEAN'].iloc[-1]) if 'MA_MEAN' in df.columns else 0.0
            ema_mid = float(df['EMA_MID'].iloc[-1]) if 'EMA_MID' in df.columns else 0.0

            return (
                conv < 10 and
                (vol_ratio > 1.2) and
                (ma_mean > ema_mid)
            )
        except Exception:
            return False

    def _check_condition_simple_breakout(self, df: pd.DataFrame) -> bool:
        """条件3: 简单突破模式"""
        try:
            if len(df) < 2:
                return False

            close = float(df['close'].iloc[-1]) if 'close' in df.columns else 0.0
            ma20 = float(df['MA_20'].iloc[-1]) if 'MA_20' in df.columns else 0.0
            volume = float(df['VOLUME'].iloc[-1]) if 'VOLUME' in df.columns else 0.0
            prev_close = float(df['close'].iloc[-2]) if 'close' in df.columns and len(df) >= 2 else 0.0

            return (
                (ma20 > 0 and close > ma20) and
                (volume > 0 and volume > float(df['V_MA20'].iloc[-1] if 'V_MA20' in df.columns else 0)) and
                (close > prev_close)
            )
        except Exception:
            return False

    def _calculate_volume_bonus(self, df: pd.DataFrame) -> float:
        """计算成交量加成"""
        try:
            if 'VOLUME_RATIO' not in df.columns:
                return 0.0
            volume_ratio = float(df['VOLUME_RATIO'].iloc[-1])
            bonus = min(max((volume_ratio - 1) * 10, 0.0), 15.0)
            return float(bonus)
        except Exception:
            return 0.0

    def _calculate_trend_bonus(self, df: pd.DataFrame) -> float:
        """计算趋势加成"""
        try:
            bonus = 0.0
            if 'MA_MEAN' in df.columns and 'EMA_MID' in df.columns:
                if df['MA_MEAN'].iloc[-1] > df['EMA_MID'].iloc[-1]:
                    bonus += 10.0
            if 'close' in df.columns and 'EMA_20' in df.columns:
                if df['close'].iloc[-1] > df['EMA_20'].iloc[-1]:
                    bonus += 10.0
            return float(bonus)
        except Exception:
            return 0.0

    def _calculate_performance_bonus(self, df: pd.DataFrame) -> float:
        """计算近期表现加成"""
        try:
            bonus = 0.0
            recent_gain_5d = self._calculate_recent_gains(df, 5)
            recent_gain_10d = self._calculate_recent_gains(df, 10)
            if recent_gain_5d > 0:
                bonus += min(recent_gain_5d, 10.0)
            if recent_gain_10d > 0:
                bonus += min(recent_gain_10d, 10.0)
            return float(bonus)
        except Exception:
            return 0.0

    def _calculate_recent_gains(self, df: pd.DataFrame, days: int) -> float:
        """计算近期涨幅"""
        try:
            if 'close' not in df.columns:
                return 0.0
            if len(df) < days + 1:
                return 0.0
            current_close = float(df['close'].iloc[-1])
            past_close = float(df['close'].iloc[-(days + 1)])
            if past_close == 0:
                return 0.0
            return float((current_close - past_close) / past_close * 100.0)
        except Exception:
            return 0.0


# 导出类
__all__ = ['TechnicalAnalyzer']
