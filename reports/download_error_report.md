# AlphaPulse-A 数据下载错误报告

> 生成时间：2026-05-18

## 当前状态

- **已下载**: 269 只股票（外接硬盘 `/Volumes/Mac-480g外接/quantan_data/day/`）
- **未完成**: ~4500 只

## 网络诊断

| 数据源 | 目标服务器 | 状态 |
|--------|-----------|------|
| akshare | push2.eastmoney.com | ❌ 连接被重置（RemoteDisconnected） |
| baostock API | 非标准端口 | ❌ login() 超时无响应 |
| baostock 网站 | baostock.com | ✅ HTTP 301 可达 |

## 诊断结论

你的网络环境存在限制，阻断了到东方财富（EastMoney）和 baostock API 端口的连接。可能原因：

1. **公司/VPN 防火墙**：企业网络常阻断金融数据 API
2. **运营商限制**：部分 ISP 限制非标准端口的出站连接
3. **地理位置**：某些地区的网络策略限制金融数据源访问

## 解决步骤（请依次尝试）

### 方案 A：切换网络
```bash
# 1. 断开公司 VPN
# 2. 切换到手机热点
# 3. 重试下载
cd "/Users/qiushixuan/cc/quantan trade"
source .venv/bin/activate
python scripts/download_a_share_data.py --sample 50
```

### 方案 B：使用代理
```bash
# 如果你有可用的 HTTP 代理，设置后重试
export http_proxy=http://你的代理地址:端口
export https_proxy=http://你的代理地址:端口
python scripts/download_a_share_data.py --sample 50
```

### 方案 C：从有数据的环境拷贝
```bash
# 如果你有 Windows 电脑安装了通达信
# 将 vipdoc/sh/lday/*.day 和 vipdoc/sz/lday/*.day 拷贝过来
# 然后用 parse_tdx_data.py 解析
python scripts/parse_tdx_data.py --source /path/to/vipdoc
```

### 方案 D：手动断续下载
```bash
# 每次网络通畅时下载一批
python scripts/download_a_share_data.py --sample 100
# 利用断点续传功能，下次运行自动跳过已下载的
```

## 临时方案

当前已有 **269 只股票**数据，可运行回测：

```bash
python scripts/run_backtest.py --strategy ALL --sample 100
```

---
*本报告在每次下载失败时自动生成。*
