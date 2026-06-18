# 中文与 UTF-8 编码规范

本项目的源码、配置、脚本、文档和前后端传输统一使用 UTF-8。不要依赖 Windows 默认代码页，也不要让 Python、PowerShell、浏览器或构建工具自行猜测中文编码。

## Python 文本读写

- 文本读取使用 `open(..., encoding="utf-8")` 或 `Path.read_text(encoding="utf-8")`。
- 文本写入使用 `open(..., encoding="utf-8")` 或 `Path.write_text(..., encoding="utf-8")`。
- 面向用户的 JSON 使用 `json.dumps(..., ensure_ascii=False)`。
- CSV 面向 Excel 下载时优先使用 `utf-8-sig`，内部纯文本交换可使用 `utf-8`。
- `pandas.read_csv` 和 `DataFrame.to_csv` 必须显式传入 `encoding`。
- 日志文件处理器使用 `logging.FileHandler(..., encoding="utf-8")`。
- 需要读取子进程文本输出时，使用 `text=True, encoding="utf-8", errors="replace"`。

## Windows 与 PowerShell

PowerShell 启动脚本应设置：

```powershell
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
```

不要通过 `echo 中文 | python script.py`、`Get-Content 中文文件 | python script.py` 或 `type file | python script.py` 传递中文源码、中文常量或中文提示词。推荐把文件路径传给 Python，由 Python 使用显式 UTF-8 读取。

## 文件名与下载名

上传文件内部存储应使用 UUID 或安全文件名，展示层保留 `original_filename`。下载响应需要同时提供 ASCII fallback `filename=` 和 RFC 5987 `filename*=`，以兼容中文文件名。

## VS Code 设置

建议工作区设置：

```json
{
  "files.encoding": "utf8",
  "files.autoGuessEncoding": false,
  "files.eol": "\r\n"
}
```

## 乱码处理

出现 `???`、`锟斤拷`、`�`、`Ã`、`å`、`æ`、`ä` 等内容后，很多情况下原始中文已经不可逆丢失。不能凭空猜测原文。只有能从上下文、历史、测试或同类文案确认时才恢复；无法确认时标注 `TODO_ENCODING_REVIEW` 并列入人工确认清单。

## 检查建议

- 用 UTF-8 解码扫描源码和文档。
- 搜索高风险乱码标记。
- 搜索未显式编码的 `open`、`read_text`、`write_text`、`pd.read_csv`、`to_csv`、`FileHandler`、`subprocess`。
- 在 Windows 下运行中文文件名、中文字段名、中文路径和中文 JSON 的回归测试。
