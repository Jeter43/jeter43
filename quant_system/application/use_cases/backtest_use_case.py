# trading_system/application/use_cases/backtest_use_case.py
"""
回测用例 - 集成新的回测引擎
"""

import sys
import os
from typing import List, Dict, Any, Optional
import json
from datetime import datetime

# 添加项目根目录到Python路径
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from quant_system.utils.logger import get_logger
from quant_system.core.config import ConfigManager
from quant_system.domain.strategies.strategy_factory import StrategyFactory
from .backtest_engine import BacktestEngine, BacktestResult


class BacktestUseCase:
    """回测用例 - 完整实现"""

    def __init__(self, config: ConfigManager, strategy_factory: StrategyFactory):
        self.config = config
        self.strategy_factory = strategy_factory
        self.logger = get_logger()
        self.backtest_engine: Optional[BacktestEngine] = None

    def run(self, symbols: Optional[List[str]] = None):
        """
        运行回测

        Args:
            symbols: 指定回测的股票列表，如果为None则使用默认股票池
        """
        self.logger.info("🚀 启动回测模式")

        try:
            # 检查并设置回测配置
            if not hasattr(self.config, 'backtest') or not self.config.backtest:
                self.logger.warning("⚠️ 回测配置不存在，使用默认配置")
                from quant_system.core.config import BacktestConfig
                self.config.backtest = BacktestConfig()

            # 确保有开始和结束日期
            if not hasattr(self.config.backtest, 'start_date') or not self.config.backtest.start_date:
                from datetime import datetime, timedelta
                end_date = datetime.now()
                start_date = end_date - timedelta(days=30)  # 默认30天
                self.config.backtest.start_date = start_date.strftime('%Y-%m-%d')
                self.logger.info(f"📅 使用默认开始日期: {self.config.backtest.start_date}")

            if not hasattr(self.config.backtest, 'end_date') or not self.config.backtest.end_date:
                from datetime import datetime
                self.config.backtest.end_date = datetime.now().strftime('%Y-%m-%d')
                self.logger.info(f"📅 使用默认结束日期: {self.config.backtest.end_date}")

            # 初始化回测引擎
            self.backtest_engine = BacktestEngine(self.config, self.strategy_factory)

            # 确定回测股票池
            if symbols is None:
                symbols = self._get_default_stock_universe()

            self.logger.info(f"📊 回测股票池: {len(symbols)} 只股票")

            # 加载历史数据
            self.backtest_engine.load_historical_data(
                symbols=symbols,
                start_date=self.config.backtest.start_date,
                end_date=self.config.backtest.end_date
            )

            # 运行回测
            result = self.backtest_engine.run_backtest(symbols)

            # 生成报告
            report = self.backtest_engine.generate_report(result)

            # 显示结果
            self._display_results(report, result)

            # 保存结果
            self._save_results(result, report)

            # 绘制图表
            self._generate_charts(result)

            self.logger.info("✅ 回测用例执行完成")

        except Exception as e:
            self.logger.error(f"回测执行失败: {e}")
            import traceback
            self.logger.error(f"详细错误: {traceback.format_exc()}")
            print(f"\n❌ 回测执行失败: {e}")
            print(f"详细错误请查看日志文件")
            raise

    def _get_default_stock_universe(self) -> List[str]:
        """获取默认股票池"""
        # 这里可以配置常用的港股标的
        default_stocks = [
            'HK.00700',  # 腾讯
            'HK.00941',  # 中国移动
            'HK.00005',  # 汇丰
            'HK.02318',  # 中国平安
            'HK.01299',  # 友邦保险
            'HK.00388',  # 港交所
            'HK.02628',  # 中国人寿
            'HK.03988',  # 中国银行
            'HK.00939',  # 建设银行
            'HK.01398',  # 工商银行
            'HK.00883',  # 中国海洋石油
            'HK.00175',  # 吉利汽车
            'HK.00669',  # 创科实业
            'HK.01113',  # 长实集团
            'HK.00001',  # 长和
        ]

        # 如果配置中有监控股票，优先使用
        if hasattr(self.config.system, 'monitored_stocks') and self.config.system.monitored_stocks:
            return self.config.system.monitored_stocks

        return default_stocks

    def _display_results(self, report: Dict[str, Any], result: BacktestResult):
        """显示回测结果"""
        print("\n" + "=" * 60)
        print("📊 回测结果报告")
        print("=" * 60)

        # 显示摘要
        print("\n🎯 绩效摘要:")
        for key, value in report['summary'].items():
            print(f"   {key}: {value}")

        # 显示交易统计
        print("\n📈 交易统计:")
        for key, value in report['trading'].items():
            print(f"   {key}: {value}")

        # 显示风险指标
        print("\n🛡️ 风险指标:")
        for key, value in report['risk_metrics'].items():
            print(f"   {key}: {value}")

        # 显示策略表现
        if hasattr(result, 'strategy_performance') and result.strategy_performance:
            print("\n🔧 策略表现:")
            for strategy, performance in result.strategy_performance.items():
                print(f"   {strategy}: {performance}")

    def _save_results(self, result: BacktestResult, report: Dict[str, Any]):
        """保存回测结果"""
        try:
            # 创建结果目录
            results_dir = "backtest_results"
            os.makedirs(results_dir, exist_ok=True)

            # 生成文件名
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"backtest_{timestamp}"

            # 保存详细结果 (JSON)
            result_data = {
                'timestamp': timestamp,
                'parameters': {
                    'start_date': self.config.backtest.start_date,
                    'end_date': self.config.backtest.end_date,
                    'initial_capital': self.config.backtest.initial_capital,
                    'strategies': {
                        'selection': [s.value for s in self.config.system.selection_strategies],
                        'risk': [s.value for s in self.config.system.risk_strategies]
                    }
                },
                'results': report,
                'trades_count': len(result.trades),
                'daily_records_count': len(result.daily_portfolio)
            }

            with open(f"{results_dir}/{filename}.json", 'w', encoding='utf-8') as f:
                json.dump(result_data, f, indent=2, ensure_ascii=False)

            # 保存交易记录 (CSV)
            if result.trades:
                trades_data = []
                for trade in result.trades:
                    trades_data.append({
                        'timestamp': trade.timestamp.isoformat(),
                        'symbol': trade.symbol,
                        'action': trade.action,
                        'quantity': trade.quantity,
                        'price': trade.price,
                        'commission': trade.commission,
                        'remark': trade.remark
                    })

                import pandas as pd
                trades_df = pd.DataFrame(trades_data)
                trades_df.to_csv(f"{results_dir}/{filename}_trades.csv", index=False, encoding='utf-8-sig')

            self.logger.info(f"💾 回测结果已保存到: {results_dir}/{filename}.*")

        except Exception as e:
            self.logger.error(f"保存回测结果失败: {e}")

    def _generate_charts(self, result: BacktestResult):
        """生成绩效图表"""
        try:
            charts_dir = "backtest_results/charts"
            os.makedirs(charts_dir, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            chart_path = f"{charts_dir}/performance_{timestamp}.png"

            if self.backtest_engine:
                self.backtest_engine.plot_performance(result, chart_path)

        except Exception as e:
            self.logger.error(f"生成图表失败: {e}")

    def run_quick_test(self):
        """快速测试回测功能"""
        self.logger.info("🧪 运行快速回测测试...")

        # 使用少量股票进行快速测试
        test_symbols = ['HK.00700', 'HK.00941', 'HK.00005']

        try:
            # 设置快速测试的日期范围（最近7天）
            from datetime import datetime, timedelta
            end_date = datetime.now()
            start_date = end_date - timedelta(days=7)
            
            # 临时设置回测日期
            if not hasattr(self.config, 'backtest') or not self.config.backtest:
                from quant_system.core.config import BacktestConfig
                self.config.backtest = BacktestConfig()
            
            original_start = getattr(self.config.backtest, 'start_date', None)
            original_end = getattr(self.config.backtest, 'end_date', None)
            
            self.config.backtest.start_date = start_date.strftime('%Y-%m-%d')
            self.config.backtest.end_date = end_date.strftime('%Y-%m-%d')
            
            self.logger.info(f"📅 快速测试日期范围: {self.config.backtest.start_date} 至 {self.config.backtest.end_date}")
            
            self.run(symbols=test_symbols)
            
            # 恢复原始日期（如果存在）
            if original_start:
                self.config.backtest.start_date = original_start
            if original_end:
                self.config.backtest.end_date = original_end
                
            return True
        except Exception as e:
            self.logger.error(f"快速测试失败: {e}")
            import traceback
            self.logger.error(f"详细错误: {traceback.format_exc()}")
            print(f"\n❌ 快速测试失败: {e}")
            print(f"详细错误请查看日志文件")
            return False

    def run_stress_test(self):
        """压力测试回测功能"""
        self.logger.info("🧪 运行压力测试...")

        # 使用更多股票和更长的周期进行压力测试
        stress_symbols = self._get_default_stock_universe()[:10]  # 使用前10只股票

        try:
            # 设置压力测试的日期范围（最近30天）
            from datetime import datetime, timedelta
            end_date = datetime.now()
            start_date = end_date - timedelta(days=30)
            
            # 临时设置回测日期
            if not hasattr(self.config, 'backtest') or not self.config.backtest:
                from quant_system.core.config import BacktestConfig
                self.config.backtest = BacktestConfig()
            
            original_start = getattr(self.config.backtest, 'start_date', None)
            original_end = getattr(self.config.backtest, 'end_date', None)
            
            self.config.backtest.start_date = start_date.strftime('%Y-%m-%d')
            self.config.backtest.end_date = end_date.strftime('%Y-%m-%d')
            
            self.logger.info(f"📅 压力测试日期范围: {self.config.backtest.start_date} 至 {self.config.backtest.end_date}")
            self.logger.info(f"📊 压力测试股票池: {len(stress_symbols)} 只股票")
            
            self.run(symbols=stress_symbols)
            
            # 恢复原始日期（如果存在）
            if original_start:
                self.config.backtest.start_date = original_start
            if original_end:
                self.config.backtest.end_date = original_end
                
            return True
        except Exception as e:
            self.logger.error(f"压力测试失败: {e}")
            import traceback
            self.logger.error(f"详细错误: {traceback.format_exc()}")
            print(f"\n❌ 压力测试失败: {e}")
            print(f"详细错误请查看日志文件")
            return False


# 导出类
__all__ = ['BacktestUseCase']