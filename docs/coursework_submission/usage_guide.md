# 使用方法

## 环境准备

推荐环境：

- Python 3.11+
- Node.js 20+
- PowerShell
- 项目虚拟环境 `.venv`

安装依赖：

```powershell
cd E:\agent\gis_agent_web_only_builtin_shp_v1
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium

cd ui_next
npm install
cd ..
```

配置本地环境：

```powershell
Copy-Item .env.example .env
```

`.env` 中的 API key、token、cookie 和 storage_state 不应提交到仓库。

## 启动系统

启动后端：

```powershell
.\start_backend_api.ps1
```

启动前端：

```powershell
.\start_web_ui.ps1
```

默认访问地址：

- 前端：`http://localhost:5173`
- 后端：`http://127.0.0.1:8765`

## 基本使用流程

1. 打开前端页面。
2. 上传地理数据，例如 Shapefile、GeoJSON、TIFF 或 CSV。
3. 等待系统识别数据类型、字段、坐标系和范围。
4. 在对话框中输入中文任务。
5. 查看地图预览、结果面板和分析说明。
6. 下载生成的 artifact、地图或报告产物。

## 可演示任务示例

```text
帮我查看这个矢量数据的基本信息，并在地图上预览。
```

```text
请把这个表格里的经纬度字段转换为点图层，并生成地图结果。
```

```text
请检查这个数据的坐标系和空间范围。
```

```text
根据当前上传的数据生成一份分析摘要。
```

## 验证命令

后端测试：

```powershell
.\.venv\Scripts\python.exe -m unittest discover tests
```

前端测试和构建：

```powershell
cd ui_next
npm test
npm run build
```

关键 gate：

```powershell
pwsh -File .\scripts\run_soil_moisture_gcp_smoke.ps1
pwsh -File .\scripts\run_agent_runtime_staging10_observation_gate.ps1
```
