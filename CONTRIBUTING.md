# 参与贡献

感谢你愿意改进 Lead Mining Automation。本项目欢迎错误修复、采集稳定性改进、数据清洗规则、测试、文档和合规能力方面的贡献。

## 开始之前

请先确认你的贡献符合以下边界：

- 只处理贡献者有权访问和使用的公开信息。
- 不提交真实客户名单、联系人、电话号码、导出文件、数据库或浏览器用户目录。
- 不提交密码、Cookie、访问令牌、API 密钥或其他凭据。
- 不实现登录绕过、验证码破解、设备指纹伪造或其他平台安全机制规避能力。
- 尊重目标平台的服务条款、访问频率限制、robots 规则和适用法律。
- 引入新依赖时，应说明必要性及其开源许可证。

不符合上述边界的 Issue 或 Pull Request 可能会被关闭。

## 本地开发

后端：

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

前端：

```powershell
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

## 提交流程

1. Fork 本仓库并从 `main` 创建短期分支，例如 `fix/export-filter`。
2. 每个提交只解决一个逻辑问题，并使用清晰的提交说明。
3. 为行为变更增加或更新测试。
4. 提交前完成后端测试和前端构建。
5. 在 Pull Request 中说明问题、方案、验证结果和潜在的数据合规影响。

建议使用以下提交类型：

- `feat:` 新功能
- `fix:` 错误修复
- `docs:` 文档
- `test:` 测试
- `refactor:` 不改变行为的重构
- `chore:` 构建或维护工作

## 验证命令

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q

cd ..\frontend
npm run build
npm audit --omit=dev
```

## Pull Request 检查清单

- [ ] 修改范围聚焦，没有混入无关重构。
- [ ] 测试和前端构建通过。
- [ ] 没有包含真实线索、个人信息、密钥或登录态。
- [ ] 新增采集逻辑包含超时、频率控制和失败处理。
- [ ] 不会绕过目标平台的访问控制或安全机制。
- [ ] 文档已经同步更新。

## 贡献许可

提交贡献即表示你确认自己有权提供相关代码或文档，并同意该贡献按照本项目的 `AGPL-3.0-only` 许可证发布。请勿提交来源不明、无权再许可或与 AGPL-3.0 不兼容的内容。

参与社区互动时，请同时遵守 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。安全问题请按照 [SECURITY.md](SECURITY.md) 私密报告。
