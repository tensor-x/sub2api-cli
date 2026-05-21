# sub2api-cli

一个面向 Codex + sub2api 的终端管理工具。它会读取本机 Codex 正在使用的 token，定位该 token 在 sub2api 中绑定的分组，并提供方向键交互界面，用来快速切换分组、开关账号调度、查看最近请求日志。

> [!IMPORTANT]
> `sub2api-cli` 不会打印完整 Codex token，只展示脱敏后的短指纹。配置时填写的是 sub2api Admin API Key，不是 Codex token。

## 功能

- 自动读取 `~/.codex/auth.json` 中的 Codex API Key
- 定位当前 Codex token 所在的 sub2api 分组
- 在终端 UI 中切换 Codex token 的分组
- 查看分组内账号，并快速开启或关闭账号调度
- 查看最新请求日志，默认 20 条
- 默认通过 `http://127.0.0.1:7890` 代理请求 sub2api
- 配置文件写入 `~/.config/sub2api-cli/config.json`，权限自动设置为 `0600`

## 准备工作

你需要准备：

- Python 3.10 或更高版本
- 支持 `curses` 的终端
- sub2api Admin API Key
- 本机存在 Codex 登录文件：`~/.codex/auth.json`

本工具只使用 Python 标准库，不需要安装第三方依赖。

## 快速开始

克隆仓库：

```bash
git clone https://github.com/tensor-x/sub2api-cli.git
cd sub2api-cli
chmod +x sub2api_cli.py
```

可选：安装为全局命令。

```bash
ln -sf "$PWD/sub2api_cli.py" /usr/local/bin/sub2api-cli
```

配置 sub2api Admin API Key：

```bash
sub2api-cli config --admin-token '<your-sub2api-admin-api-key>'
```

启动交互界面：

```bash
sub2api-cli
```

## 配置

默认服务地址是：

```text
https://sub2api.seei.app
```

如需修改：

```bash
sub2api-cli config --base-url https://sub2api.seei.app
```

默认代理地址是：

```text
http://127.0.0.1:7890
```

如需修改：

```bash
sub2api-cli config --proxy-url http://127.0.0.1:7890
```

如需禁用代理：

```bash
sub2api-cli config --proxy-url ''
```

> [!NOTE]
> 如果你之前配置过旧地址，配置文件中的值会优先生效。执行 `sub2api-cli config --base-url ...` 即可覆盖。

## 常用命令

进入终端 UI：

```bash
sub2api-cli
```

或显式进入 UI：

```bash
sub2api-cli ui
```

查看当前 Codex token 状态：

```bash
sub2api-cli status
```

查看最新 20 条请求日志：

```bash
sub2api-cli logs
```

查看指定数量的日志：

```bash
sub2api-cli logs -n 50
```

## 交互快捷键

| 按键 | 作用 |
| --- | --- |
| `↑` / `↓` | 上下移动选择 |
| `←` / `→` | 在分组面板和账号面板之间切换 |
| `Enter`，分组面板 | 将当前 Codex token 切换到选中分组 |
| `Enter`，账号面板 | 开启或关闭选中账号调度 |
| `Space`，账号面板 | 开启或关闭选中账号调度 |
| `o`，账号面板 | 开启选中账号调度 |
| `x`，账号面板 | 关闭选中账号调度 |
| `r` | 刷新数据 |
| `q` / `Esc` | 退出 |

## 工作方式

`sub2api-cli` 使用 sub2api Admin API 完成管理操作，Admin API Key 会通过请求头传递：

```text
x-api-key: <your-admin-api-key>
```

当前使用的接口包括：

- `GET /api/v1/admin/groups/all`
- `GET /api/v1/admin/groups/:id/api-keys`
- `GET /api/v1/admin/accounts?group=:id`
- `PUT /api/v1/admin/api-keys/:id`
- `POST /api/v1/admin/accounts/:id/schedulable`
- `GET /api/v1/admin/usage`

> [!TIP]
> 启动 UI 时会先加载分组、API key 和账号数据。如果网络较慢，界面会先显示加载提示；后续上下移动只使用本地缓存，不会每次移动都请求接口。

## 安全说明

- 不要公开 `~/.config/sub2api-cli/config.json`
- 不要公开 `~/.codex/auth.json`
- 不要把 sub2api Admin API Key 当作 Codex token 使用
- 工具会对 Codex token 做脱敏展示，但配置文件仍需要你自己妥善保管
