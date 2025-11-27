# Binance 集成配置指南

## 一、安装依赖

首先需要安装 `python-binance` 库：

```bash
pip install python-binance
```

## 二、获取 Binance API 密钥

1. 登录 [Binance](https://www.binance.com/) 账户
2. 进入 **API 管理** 页面
3. 创建新的 API Key
4. 记录 **API Key** 和 **Secret Key**

⚠️ **安全提示**：
- 建议使用测试网进行开发测试
- 生产环境请启用 IP 白名单
- 限制 API Key 权限（只授予必要的权限）

## 三、配置方式

### 方式1：配置文件（推荐）

编辑 `config/market.yaml` 文件，添加或修改 `crypto` 市场配置：

```yaml
markets:
  crypto:
    market_type: "crypto"
    broker_type: "binance"
    enabled: true
    currency: "USDT"
    parameters:
      api_key: "your_binance_api_key_here"
      secret_key: "your_binance_secret_key_here"
      testnet: true  # 使用测试网（推荐用于开发）
      # testnet: false  # 生产环境
    trading_hours:
      timezone: "UTC"
      regular_hours:
        - start: "00:00"
          end: "24:00"  # 7x24小时交易
    min_trade_amount: 10.0
    price_precision: 8
    amount_precision: 8
```

### 方式2：环境变量

设置环境变量：

```bash
export BINANCE_API_KEY="your_api_key"
export BINANCE_SECRET_KEY="your_secret_key"
```

然后在配置文件中设置 `testnet` 参数：

```yaml
markets:
  crypto:
    market_type: "crypto"
    broker_type: "binance"
    enabled: true
    parameters:
      testnet: true  # 或 false
```

## 四、测试网配置

Binance 提供测试网用于开发测试：

- **测试网地址**: https://testnet.binance.vision
- **测试网 API 文档**: https://testnet.binance.vision/

测试网特点：
- 使用虚拟资金
- 不影响真实账户
- 适合开发和测试

## 五、使用示例

### 1. 切换市场

在系统启动时，选择加密货币市场：

```python
# 系统会自动检测配置并支持 Binance
```

### 2. 查看账户信息

系统会自动获取：
- 总资产（USDT）
- 可用资金
- 持仓市值
- 持仓列表

### 3. 查看市场数据

支持的主流交易对：
- BTCUSDT, ETHUSDT, BNBUSDT
- SOLUSDT, XRPUSDT, ADAUSDT
- 等更多交易对

## 六、注意事项

### 1. API 限制

Binance API 有频率限制：
- 现货：1200 requests/min
- 系统已实现自动频率控制

### 2. 精度处理

加密货币需要高精度：
- 价格精度：8位小数
- 数量精度：8位小数
- 系统已自动处理

### 3. 交易对格式

Binance 使用格式：`BTCUSDT`（无分隔符）
- 系统统一使用此格式
- 无需转换

### 4. 时区

Binance 使用 UTC 时区
- 系统自动处理时区转换
- 显示时使用本地时区

## 七、故障排查

### 问题1：连接失败

**错误**: `API Key 或 Secret Key 未配置`

**解决**:
1. 检查配置文件中的 `api_key` 和 `secret_key`
2. 或设置环境变量
3. 确保密钥正确无误

### 问题2：导入错误

**错误**: `python-binance 库未安装`

**解决**:
```bash
pip install python-binance
```

### 问题3：权限错误

**错误**: `API Key 权限不足`

**解决**:
1. 检查 API Key 权限设置
2. 确保已启用必要的权限（读取、交易等）
3. 检查 IP 白名单设置

### 问题4：测试网连接失败

**错误**: `无法连接到测试网`

**解决**:
1. 确认 `testnet: true` 配置正确
2. 检查网络连接
3. 测试网地址：https://testnet.binance.vision

## 八、安全建议

1. **使用测试网开发**
   - 开发阶段使用测试网
   - 避免误操作影响真实资金

2. **限制 API 权限**
   - 只授予必要的权限
   - 禁用不需要的功能

3. **启用 IP 白名单**
   - 限制 API Key 只能从指定 IP 访问
   - 提高安全性

4. **定期更换密钥**
   - 定期更换 API Key
   - 发现异常立即撤销

5. **不要泄露密钥**
   - 不要将密钥提交到代码仓库
   - 使用环境变量或加密配置

## 九、下一步

基础功能已实现，后续可以：
1. 实现 WebSocket 实时行情订阅
2. 完善订单管理功能
3. 支持期货交易
4. 添加更多交易对支持

