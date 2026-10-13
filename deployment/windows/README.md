# Windows 部署说明

## 1. 新电脑先安装

- Python 3.9 或以上，安装时勾选 `Add python.exe to PATH`
- Node.js 18 或以上
- MySQL 8，确认数据库账号和密码可用
- Microsoft Edge

## 2. 安装项目依赖

解压部署包后，双击：

```text
deployment\windows\install.bat
```

安装脚本会完成：

- 创建后端虚拟环境 `backend\.venv`
- 安装 Python 依赖
- 安装 Playwright Edge 驱动
- 安装前端依赖
- 构建前端
- 如果没有 `backend\.env`，会从 `backend\.env.example` 创建

## 3. 配置数据库

打开：

```text
backend\.env
```

确认这些配置和新电脑 MySQL 一致：

```text
LEAD_DATABASE_DRIVER=mysql
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=你的数据库密码
MYSQL_DATABASE=lead_mining
```

把 `MYSQL_PASSWORD` 改成当前 MySQL 账号的实际密码，不要将真实密码提交到版本库。

## 4. 启动项目

双击：

```text
deployment\windows\start.bat
```

启动后访问：

```text
http://127.0.0.1:5173/
```

后端健康检查：

```text
http://127.0.0.1:8000/api/health
```

## 5. 停止项目

双击：

```text
deployment\windows\stop.bat
```

## 6. 运行日志

日志目录：

```text
runtime_logs
```

如果启动失败，优先查看：

```text
runtime_logs\backend.err.log
runtime_logs\frontend.err.log
```

## 7. 1688 反证注意事项

- 反证只搜索 1688 结果页，不进入详情页。
- 如果搜索页有结果但未解析到企业名，会标记为 `未确认`，避免误判为不存在。
- Excel 结果会保存在 `backend\exports`。
