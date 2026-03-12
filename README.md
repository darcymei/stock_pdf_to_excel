# 富途证券月结单 PDF → Excel 转换工具

一个 Web 应用，用于读取富途证券月结单 PDF，自动提取交易明细并生成 Excel 文件。

## 功能

- 解析富途证券月结单 PDF（文本型 PDF，使用 pdfplumber 提取）
- 提取"交易-股票和股票期權"区段的所有交易记录
- 提取"資產進出"区段的港股 IPO 公開發售记录
- 同一股票、同一天、同一方向的交易自动合并为一行
- 生成格式化的 Excel 文件，包含日期、股票代码、名称、交易所、数量、单价、方向、费用、货币、总净额

## 支持的交易所

| 货币 | 交易所（PDF） | 输出 |
|------|--------------|------|
| HKD | SEHK, FUTU OTC | HKG |
| USD | ARCX, CDED, JNST, EDGX | US |

## 技术栈

- Python 3
- FastAPI + Uvicorn
- pdfplumber（PDF 文本提取）
- openpyxl（Excel 生成）

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 启动服务
python3 -m uvicorn app:app --host 0.0.0.0 --port 8001
```

浏览器访问 `http://<服务器IP>:8001/`，上传 PDF 即可下载 Excel。

## 项目结构

```
app.py              # FastAPI 入口 + 路由
parser.py           # PDF 解析核心（状态机 + 正则）
excel_writer.py     # Excel 生成
models.py           # 数据类定义
templates/
  index.html        # 上传页面
static/
  style.css         # 样式
requirements.txt    # 依赖
```
