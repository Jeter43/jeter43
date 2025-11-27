# quant_system/domain/services/stock_pool_manager.py
"""
股票池管理服务
负责管理多个股票池，为策略提供股票数据源
"""

import yaml
from typing import Dict, List, Optional, Any
from pathlib import Path
from dataclasses import dataclass
from quant_system.utils.logger import get_logger


@dataclass
class StockPool:
    """股票池数据类"""
    name: str
    description: str
    stocks: List[str]
    category: str = "general"


class StockPoolManager:
    """股票池管理器"""

    def __init__(self, config_path: str = "config/stocks.yaml"):
        self.logger = get_logger(__name__)
        self.config_path = Path(config_path)
        self.stock_pools: Dict[str, StockPool] = {}
        self._load_stock_pools()

    def _load_stock_pools(self):
        """加载股票池配置"""
        try:
            if not self.config_path.exists():
                self.logger.warning(f"股票池配置文件不存在: {self.config_path}")
                self._create_default_stock_pools()
                return

            with open(self.config_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)

            watchlists = data.get('watchlists', {})
            for pool_id, pool_data in watchlists.items():
                self.stock_pools[pool_id] = StockPool(
                    name=pool_data.get('name', pool_id),
                    description=pool_data.get('description', ''),
                    stocks=pool_data.get('stocks', [])
                )

            self.logger.info(f"✅ 加载股票池完成: {len(self.stock_pools)} 个股票池")

            # 打印加载的股票池信息
            for pool_id, pool in self.stock_pools.items():
                self.logger.debug(f"   📊 {pool.name}: {len(pool.stocks)} 只股票")

        except Exception as e:
            self.logger.error(f"❌ 加载股票池失败: {e}")
            self._create_default_stock_pools()

    def _create_default_stock_pools(self):
        """创建默认股票池"""
        self.stock_pools = {
            'default': StockPool(
                name="默认股票池",
                description="系统默认股票池",
                stocks=['HK.00700', 'HK.00005', 'HK.00941']
            ),
            'hk_blue_chip': StockPool(
                name="港股蓝筹股",
                description="恒生指数成分股",
                stocks=['HK.00700', 'HK.00005', 'HK.00941', 'HK.01299', 'HK.00388']
            )
        }
        self.logger.info("✅ 创建默认股票池")

    def get_stock_pool(self, pool_id: str) -> Optional[StockPool]:
        """获取指定股票池"""
        return self.stock_pools.get(pool_id)

    def get_all_pools(self) -> Dict[str, StockPool]:
        """获取所有股票池"""
        return self.stock_pools

    def get_stocks_from_pool(self, pool_id: str) -> List[str]:
        """获取股票池中的股票列表"""
        pool = self.get_stock_pool(pool_id)
        return pool.stocks if pool else []

    def add_stock_to_pool(self, pool_id: str, stock_code: str):
        """添加股票到股票池"""
        if pool_id in self.stock_pools:
            if stock_code not in self.stock_pools[pool_id].stocks:
                self.stock_pools[pool_id].stocks.append(stock_code)
                self.logger.info(f"✅ 添加股票 {stock_code} 到 {pool_id}")

    def remove_stock_from_pool(self, pool_id: str, stock_code: str):
        """从股票池移除股票"""
        if pool_id in self.stock_pools:
            if stock_code in self.stock_pools[pool_id].stocks:
                self.stock_pools[pool_id].stocks.remove(stock_code)
                self.logger.info(f"✅ 从 {pool_id} 移除股票 {stock_code}")

    def create_stock_pool(self, pool_id: str, name: str, description: str = "", stocks: List[str] = None):
        """创建新的股票池"""
        if pool_id not in self.stock_pools:
            self.stock_pools[pool_id] = StockPool(
                name=name,
                description=description,
                stocks=stocks or []
            )
            self.logger.info(f"✅ 创建股票池: {name} ({pool_id})")
            return True
        else:
            self.logger.warning(f"股票池已存在: {pool_id}")
            return False

    def save_config(self):
        """保存配置到文件"""
        try:
            data = {'watchlists': {}}
            for pool_id, pool in self.stock_pools.items():
                data['watchlists'][pool_id] = {
                    'name': pool.name,
                    'description': pool.description,
                    'stocks': pool.stocks
                }

            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(data, f, allow_unicode=True, indent=2)

            self.logger.info(f"✅ 股票池配置已保存: {self.config_path}")
            return True

        except Exception as e:
            self.logger.error(f"❌ 保存股票池配置失败: {e}")
            return False

    def list_available_pools(self) -> Dict[str, Any]:
        """列出所有可用股票池的详细信息"""
        pools_info = {}
        for pool_id, pool in self.stock_pools.items():
            pools_info[pool_id] = {
                'name': pool.name,
                'description': pool.description,
                'stock_count': len(pool.stocks),
                'stocks_sample': pool.stocks[:5]  # 只显示前5只股票作为样例
            }
        return pools_info


# 导出类
__all__ = ['StockPoolManager', 'StockPool']