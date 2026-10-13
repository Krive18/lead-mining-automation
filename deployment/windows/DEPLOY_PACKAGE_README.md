# 精准客户采集系统 Windows 部署包说明

## 适用场景

这份部署包面向“新电脑没有 Python、Node.js、前端依赖、后端依赖”的情况。目标电脑只需要：

- Windows 10/11
- 可以访问互联网
- 能运行 PowerShell

默认使用项目内置 SQLite 数据库，首次启动会自动创建数据库文件，不要求目标电脑安装 MySQL。

## 给别人安装时怎么做

1. 先完整解压部署包，不要在压缩包预览窗口里直接双击 bat。推荐右键 zip，选择“全部解压”。
2. 双击根目录的 `一键配置环境.bat`。
3. 等待脚本自动下载免安装 Python、免安装 Node.js、Python 依赖、前端依赖和 Playwright 浏览器。
4. 双击 `start_project.bat` 或 `一键启动项目.bat`。
5. 浏览器访问 `http://127.0.0.1:5173/`。

如果看到 `The argument ... setup_env.ps1 ... does not exist`，基本就是还没有完整解压部署包。请先关闭窗口，重新把 zip 解压到桌面或其他普通文件夹，再运行 `一键配置环境.bat`。

## 数据和导出文件在哪里

- 免安装 Python：`.runtime/python`
- 免安装 Node.js：`.runtime/node`
- 本地数据库：`backend/data/lead_mining.db`
- Excel 导出：`backend/exports`
- 运行日志：`runtime_logs`
- 后端日志：`backend/logs`

这些目录不会被打进新的部署包里，避免把你本机的客户数据发给别人。

## 如果要重新生成部署包

在项目根目录双击 `生成部署包.bat`，或执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File deployment\windows\build_deploy_package.ps1
```

生成的 zip 会放在 `release` 目录。

## 下载压缩包损坏时怎么办

如果配置环境时报 `End of Central Directory record could not be found`，说明 Python 或 Node 的 zip 下载到一半损坏了，或者被网络代理替换成了非 zip 内容。新版脚本会自动删除坏缓存并重试下载。

如果你正在使用旧部署包，可以手动删除这些文件后重新双击 `一键配置环境.bat`：

```text
.runtime\downloads\python-3.12.4-embed-amd64.zip
.runtime\downloads\node-v20.15.1-win-x64.zip
```

如果连续重试仍失败，优先检查目标电脑网络、代理、杀毒软件或公司网关是否拦截 `python.org` / `nodejs.org` 下载。

## 如果必须切换 MySQL

部署包默认不安装 MySQL，因为 SQLite 已经能满足单机部署，安装步骤也最少。若目标电脑必须使用 MySQL，需要先额外安装 MySQL 8，然后修改 `backend/.env`：

```text
LEAD_DATABASE_DRIVER=mysql
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=你的数据库密码
MYSQL_DATABASE=lead_mining
MYSQL_CHARSET=utf8mb4
```

后端启动时会自动创建数据库和业务表。
