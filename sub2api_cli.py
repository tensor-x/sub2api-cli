#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import curses
import hashlib
import json
import os
import pathlib
import sys
import textwrap
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


DEFAULT_BASE_URL = "https://sub2api.seei.app"
DEFAULT_PROXY_URL = "http://127.0.0.1:7890"
CONFIG_PATH = pathlib.Path.home() / ".config" / "sub2api-cli" / "config.json"
CODEX_AUTH_PATH = pathlib.Path.home() / ".codex" / "auth.json"


@dataclass
class Group:
    id: int
    name: str
    platform: str
    status: str
    account_count: int = 0
    active_account_count: int = 0


@dataclass
class APIKey:
    id: int
    name: str
    key: str
    group_id: int | None
    status: str


@dataclass
class Account:
    id: int
    name: str
    platform: str
    account_type: str
    status: str
    schedulable: bool
    priority: int
    concurrency: int
    current_concurrency: int
    last_used_at: str
    error_message: str


def mask_token(token: str) -> str:
    if len(token) <= 12:
        return "*" * len(token)
    return f"{token[:8]}...{token[-4:]}"


def token_sha(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]


def load_json_file(path: pathlib.Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise RuntimeError(f"配置文件格式不正确: {path}")
    return data


def save_config(config: dict[str, Any]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.chmod(CONFIG_PATH, 0o600)


def load_config() -> dict[str, Any]:
    cfg = load_json_file(CONFIG_PATH)
    if "base_url" not in cfg:
        cfg["base_url"] = DEFAULT_BASE_URL
    if "proxy_url" not in cfg:
        cfg["proxy_url"] = DEFAULT_PROXY_URL
    return cfg


def load_codex_token(auth_path: pathlib.Path = CODEX_AUTH_PATH) -> str:
    data = load_json_file(auth_path)
    token = str(data.get("OPENAI_API_KEY") or "").strip()
    if not token:
        raise RuntimeError(f"没有在 {auth_path} 找到 OPENAI_API_KEY")
    return token


def unwrap_response(payload: Any) -> Any:
    if isinstance(payload, dict) and payload.get("code") in (0, "0") and "data" in payload:
        return payload["data"]
    return payload


class Sub2APIClient:
    def __init__(self, base_url: str, admin_token: str, proxy_url: str = DEFAULT_PROXY_URL, timeout: float = 15) -> None:
        self.base_url = base_url.rstrip("/")
        self.admin_token = admin_token
        self.proxy_url = proxy_url.strip()
        self.timeout = timeout
        if self.proxy_url:
            self.opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({"http": self.proxy_url, "https": self.proxy_url})
            )
        else:
            self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(self, method: str, path: str, data: Any | None = None, query: dict[str, Any] | None = None) -> Any:
        url = self.base_url + path
        if query:
            clean_query = {k: v for k, v in query.items() if v is not None and v != ""}
            if clean_query:
                url += "?" + urllib.parse.urlencode(clean_query)

        body = None
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/147.0.0.0 Safari/537.36"
            ),
            "x-api-key": self.admin_token,
        }
        if data is not None:
            body = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with self.opener.open(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"{method} {path} 失败: HTTP {exc.code} {detail[:300]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"{method} {path} 失败: {exc.reason}") from exc

        if not raw:
            return {}
        payload = json.loads(raw)
        if isinstance(payload, dict) and payload.get("code") not in (None, 0, "0"):
            raise RuntimeError(f"{method} {path} 失败: {payload.get('message') or payload}")
        return unwrap_response(payload)

    def groups(self) -> list[Group]:
        data = self.request("GET", "/api/v1/admin/groups/all")
        return [
            Group(
                id=int(item["id"]),
                name=str(item.get("name") or ""),
                platform=str(item.get("platform") or ""),
                status=str(item.get("status") or ""),
                account_count=int(item.get("account_count") or 0),
                active_account_count=int(item.get("active_account_count") or 0),
            )
            for item in (data or [])
        ]

    def group_api_keys(self, group_id: int) -> list[APIKey]:
        items = self._paged_items(f"/api/v1/admin/groups/{group_id}/api-keys")
        return [api_key_from_item(item) for item in items]

    def accounts(self, group_id: int) -> list[Account]:
        items = self._paged_items(
            "/api/v1/admin/accounts",
            {"group": group_id, "sort_by": "priority", "sort_order": "asc", "lite": "true"},
        )
        return [account_from_item(item) for item in items]

    def set_api_key_group(self, api_key_id: int, group_id: int) -> APIKey:
        data = self.request("PUT", f"/api/v1/admin/api-keys/{api_key_id}", {"group_id": group_id})
        api_key = data.get("api_key") if isinstance(data, dict) else None
        if not isinstance(api_key, dict):
            raise RuntimeError("切换分组成功但响应格式不包含 api_key")
        return api_key_from_item(api_key)

    def set_account_schedulable(self, account_id: int, schedulable: bool) -> Account:
        data = self.request(
            "POST",
            f"/api/v1/admin/accounts/{account_id}/schedulable",
            {"schedulable": schedulable},
        )
        return account_from_item(data)

    def usage_logs(self, limit: int) -> list[dict[str, Any]]:
        data = self.request(
            "GET",
            "/api/v1/admin/usage",
            query={
                "page": 1,
                "page_size": limit,
                "sort_by": "created_at",
                "sort_order": "desc",
                "exact_total": "false",
            },
        )
        if not isinstance(data, dict):
            return []
        items = data.get("items") or []
        return [item for item in items if isinstance(item, dict)]

    def _paged_items(self, path: str, query: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        page = 1
        result: list[dict[str, Any]] = []
        while True:
            params = dict(query or {})
            params.update({"page": page, "page_size": 100})
            data = self.request("GET", path, query=params)
            if not isinstance(data, dict):
                return []
            items = data.get("items") or []
            if not isinstance(items, list):
                return []
            result.extend(item for item in items if isinstance(item, dict))
            total = int(data.get("total") or len(result))
            if len(result) >= total or not items:
                return result
            page += 1


def api_key_from_item(item: dict[str, Any]) -> APIKey:
    group_id = item.get("group_id")
    return APIKey(
        id=int(item["id"]),
        name=str(item.get("name") or ""),
        key=str(item.get("key") or ""),
        group_id=int(group_id) if group_id is not None else None,
        status=str(item.get("status") or ""),
    )


def account_from_item(item: dict[str, Any]) -> Account:
    acc = item.get("account") if isinstance(item.get("account"), dict) else item
    return Account(
        id=int(acc["id"]),
        name=str(acc.get("name") or ""),
        platform=str(acc.get("platform") or ""),
        account_type=str(acc.get("type") or ""),
        status=str(acc.get("status") or ""),
        schedulable=bool(acc.get("schedulable")),
        priority=int(acc.get("priority") or 0),
        concurrency=int(acc.get("concurrency") or 0),
        current_concurrency=int(item.get("current_concurrency") or 0),
        last_used_at=str(acc.get("last_used_at") or ""),
        error_message=str(acc.get("error_message") or ""),
    )


def find_current_api_key(client: Sub2APIClient, groups: list[Group], codex_token: str) -> APIKey | None:
    for group in groups:
        for api_key in client.group_api_keys(group.id):
            if api_key.key == codex_token:
                return api_key
    return None


def print_status(client: Sub2APIClient, codex_token: str) -> None:
    groups = client.groups()
    api_key = find_current_api_key(client, groups, codex_token)
    group_by_id = {group.id: group for group in groups}
    current_group = group_by_id.get(api_key.group_id) if api_key else None

    print(f"Codex token: {mask_token(codex_token)} sha256:{token_sha(codex_token)}")
    if api_key and current_group:
        print(f"当前 API key: {api_key.name} #{api_key.id} -> {current_group.name} #{current_group.id}")
        accounts = client.accounts(current_group.id)
        print(f"当前分组账号: {len(accounts)} 个")
        for account in accounts:
            mark = "on" if account.schedulable else "off"
            detail = f"#{account.id} {mark:3} prio={account.priority:<3} conc={account.current_concurrency}/{account.concurrency}"
            print(f"  {detail} {account.name} [{account.status}]")
    else:
        print("当前 Codex token 未在任何分组 API key 中找到")


def print_logs(client: Sub2APIClient, limit: int) -> None:
    logs = client.usage_logs(limit)
    if not logs:
        print("暂无日志")
        return
    for item in logs:
        account = item.get("account") if isinstance(item.get("account"), dict) else {}
        model = item.get("model") or "-"
        upstream_model = item.get("upstream_model")
        if upstream_model and upstream_model != model:
            model = f"{model}->{upstream_model}"
        tokens = f"{item.get('input_tokens') or 0}/{item.get('output_tokens') or 0}"
        latency = item.get("duration_ms")
        latency_text = f"{latency}ms" if latency is not None else "-"
        cost = item.get("total_cost")
        cost_text = f"${float(cost):.6f}" if cost is not None else "-"
        endpoint = item.get("inbound_endpoint") or "-"
        account_name = account.get("name") or f"account#{item.get('account_id') or '-'}"
        created_at = str(item.get("created_at") or "").replace("T", " ").replace("Z", "")
        print(
            f"#{item.get('id')} {created_at[:19]} "
            f"key={item.get('api_key_id') or '-'} group={item.get('group_id') or '-'} "
            f"acct={account_name} model={model} tokens={tokens} cost={cost_text} "
            f"lat={latency_text} {endpoint}"
        )


def configure(args: argparse.Namespace) -> None:
    cfg = load_config()
    if args.base_url:
        cfg["base_url"] = args.base_url.rstrip("/")
    if args.proxy_url is not None:
        cfg["proxy_url"] = args.proxy_url.strip()
    if args.admin_token is not None:
        cfg["admin_token"] = args.admin_token.strip()
    save_config(cfg)
    print(f"已写入配置: {CONFIG_PATH}")


class TUI:
    def __init__(self, client: Sub2APIClient, codex_token: str) -> None:
        self.client = client
        self.codex_token = codex_token
        self.groups: list[Group] = []
        self.accounts: list[Account] = []
        self.api_key: APIKey | None = None
        self.selected_group = 0
        self.selected_account = 0
        self.focus = "groups"
        self.message = ""
        self.accounts_by_group: dict[int, list[Account]] = {}

    @staticmethod
    def is_enter(key: int) -> bool:
        return key in (10, 13, curses.KEY_ENTER, ord("\n"), ord("\r"))

    def reload(self) -> None:
        self.groups = self.client.groups()
        self.accounts_by_group = {}
        api_keys_by_group: dict[int, list[APIKey]] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, max(1, len(self.groups) * 2))) as executor:
            futures: dict[concurrent.futures.Future[Any], tuple[str, int]] = {}
            for group in self.groups:
                futures[executor.submit(self.client.accounts, group.id)] = ("accounts", group.id)
                futures[executor.submit(self.client.group_api_keys, group.id)] = ("api_keys", group.id)
            for future in concurrent.futures.as_completed(futures):
                kind, group_id = futures[future]
                if kind == "accounts":
                    self.accounts_by_group[group_id] = future.result()
                else:
                    api_keys_by_group[group_id] = future.result()
        self.api_key = None
        for group in self.groups:
            for api_key in api_keys_by_group.get(group.id, []):
                if api_key.key == self.codex_token:
                    self.api_key = api_key
                    break
            if self.api_key:
                break
        if self.api_key and self.api_key.group_id is not None:
            for idx, group in enumerate(self.groups):
                if group.id == self.api_key.group_id:
                    self.selected_group = idx
                    break
        self.load_accounts()

    def load_accounts(self) -> None:
        if not self.groups:
            self.accounts = []
            return
        self.selected_group = max(0, min(self.selected_group, len(self.groups) - 1))
        self.accounts = self.accounts_by_group.get(self.groups[self.selected_group].id, [])
        self.selected_account = max(0, min(self.selected_account, max(0, len(self.accounts) - 1)))

    def run(self, stdscr: Any) -> None:
        curses.curs_set(0)
        stdscr.keypad(True)
        self.init_colors()
        self.draw_loading(stdscr, "⏳ 正在加载 sub2api 数据...")
        self.reload()
        while True:
            self.draw(stdscr)
            key = stdscr.getch()
            if key in (ord("q"), 27):
                return
            try:
                if key == ord("r"):
                    self.draw_loading(stdscr, "⏳ 正在刷新 sub2api 数据...")
                self.handle_key(key)
            except Exception as exc:
                self.message = str(exc)

    def handle_key(self, key: int) -> None:
        if key in (curses.KEY_LEFT, curses.KEY_RIGHT, 9):
            self.focus = "accounts" if self.focus == "groups" else "groups"
            return
        if key == ord("r"):
            self.reload()
            self.message = "已刷新"
            return

        if self.focus == "groups":
            if key == curses.KEY_UP:
                self.selected_group = max(0, self.selected_group - 1)
                self.load_accounts()
            elif key == curses.KEY_DOWN:
                self.selected_group = min(len(self.groups) - 1, self.selected_group + 1)
                self.load_accounts()
            elif self.is_enter(key) and self.groups and self.api_key:
                group = self.groups[self.selected_group]
                self.api_key = self.client.set_api_key_group(self.api_key.id, group.id)
                self.message = f"Codex token 已切到分组: {group.name}"
        else:
            if key == curses.KEY_UP:
                self.selected_account = max(0, self.selected_account - 1)
            elif key == curses.KEY_DOWN:
                self.selected_account = min(len(self.accounts) - 1, self.selected_account + 1)
            elif self.is_enter(key) or key in (ord(" "), ord("o"), ord("x")):
                if self.accounts:
                    old = self.accounts[self.selected_account]
                    schedulable = not old.schedulable
                    if key == ord("o"):
                        schedulable = True
                    elif key == ord("x"):
                        schedulable = False
                    updated = self.client.set_account_schedulable(old.id, schedulable)
                    self.accounts[self.selected_account] = updated
                    self.accounts_by_group[self.groups[self.selected_group].id] = self.accounts
                    self.message = f"{updated.name} 调度已{'开启' if updated.schedulable else '关闭'}"

    @staticmethod
    def init_colors() -> None:
        if not curses.has_colors():
            return
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_WHITE, -1)
        curses.init_pair(2, curses.COLOR_CYAN, -1)
        curses.init_pair(3, curses.COLOR_GREEN, -1)
        curses.init_pair(4, curses.COLOR_RED, -1)
        curses.init_pair(5, curses.COLOR_YELLOW, -1)
        curses.init_pair(6, curses.COLOR_BLACK, curses.COLOR_CYAN)
        curses.init_pair(7, curses.COLOR_MAGENTA, -1)

    @staticmethod
    def color(pair: int, fallback: int = 0) -> int:
        if not curses.has_colors():
            return fallback
        return curses.color_pair(pair) | fallback

    def draw(self, stdscr: Any) -> None:
        stdscr.bkgd(" ", self.color(1))
        stdscr.erase()
        height, width = stdscr.getmaxyx()
        left_w = max(32, width // 3)
        current_group_id = self.api_key.group_id if self.api_key else None

        header = f"⚙️  sub2api-cli | 🔑 Codex {mask_token(self.codex_token)} sha256:{token_sha(self.codex_token)}"
        self.add(stdscr, 0, 0, header[: width - 1], self.color(2, curses.A_BOLD))
        key_line = "🔐 API key: 未找到"
        if self.api_key:
            key_line = f"🔐 API key: {self.api_key.name} #{self.api_key.id} -> 📦 group #{self.api_key.group_id}"
        self.add(stdscr, 1, 0, key_line[: width - 1], self.color(5))

        self.add(stdscr, 3, 0, "📦 分组  Enter切换", self.color(2, curses.A_BOLD if self.focus == "groups" else 0))
        self.add(stdscr, 3, left_w, "👤 账号  Enter/Space开关 o开 x关", self.color(2, curses.A_BOLD if self.focus == "accounts" else 0))

        for idx, group in enumerate(self.groups[: max(0, height - 7)]):
            marker = ">" if idx == self.selected_group and self.focus == "groups" else " "
            current = "⭐" if group.id == current_group_id else "  "
            status_icon = "✅" if group.status == "active" else "⚠️ "
            line = f"{marker}{current} #{group.id:<3} {group.name:<20} {group.platform:<8} {status_icon} {group.status}"
            attr = self.color(6) if idx == self.selected_group and self.focus == "groups" else self.color(3 if group.status == "active" else 4)
            self.add(stdscr, 4 + idx, 0, line[: left_w - 1], attr)

        account_limit = max(0, height - 7)
        for idx, account in enumerate(self.accounts[:account_limit]):
            marker = ">" if idx == self.selected_account and self.focus == "accounts" else " "
            state = "🟢 on " if account.schedulable else "🔴 off"
            status_icon = "✅" if account.status == "active" else "⚠️ "
            line = (
                f"{marker} #{account.id:<4} {state} prio={account.priority:<3} "
                f"{account.current_concurrency}/{account.concurrency:<3} {account.name} {status_icon} [{account.status}]"
            )
            if idx == self.selected_account and self.focus == "accounts":
                attr = self.color(6)
            elif not account.schedulable:
                attr = self.color(4)
            elif account.status != "active":
                attr = self.color(5)
            else:
                attr = self.color(3)
            self.add(stdscr, 4 + idx, left_w, line[: max(1, width - left_w - 1)], attr)

        help_line = "⌨️  ↑↓选择 | ←→切换面板 | Enter操作 | 账号: Space/o/x | r刷新 | q退出"
        self.add(stdscr, height - 2, 0, help_line[: width - 1], self.color(7, curses.A_DIM))
        if self.message:
            self.add(stdscr, height - 1, 0, self.message[: width - 1], self.color(5))
        stdscr.refresh()

    def draw_loading(self, stdscr: Any, message: str) -> None:
        stdscr.bkgd(" ", self.color(1))
        stdscr.erase()
        height, width = stdscr.getmaxyx()
        title = "⚙️  sub2api-cli"
        hint = "首次加载会请求分组、API key 和账号列表，请稍等"
        y = max(0, height // 2 - 1)
        self.add(stdscr, y, max(0, (width - len(title)) // 2), title, self.color(2, curses.A_BOLD))
        self.add(stdscr, y + 1, max(0, (width - len(message)) // 2), message, self.color(5, curses.A_BOLD))
        self.add(stdscr, y + 3, max(0, (width - len(hint)) // 2), hint, self.color(7, curses.A_DIM))
        stdscr.refresh()

    @staticmethod
    def add(stdscr: Any, y: int, x: int, text: str, attr: int = 0) -> None:
        height, width = stdscr.getmaxyx()
        if y >= height or x >= width:
            return
        try:
            stdscr.addstr(y, x, text[: max(0, width - x - 1)], attr)
        except curses.error:
            pass


def build_client() -> tuple[Sub2APIClient, str]:
    cfg = load_config()
    admin_token = str(cfg.get("admin_token") or "").strip()
    if not admin_token:
        raise RuntimeError(f"未配置 seei/sub2api 管理 token，请先执行: sub2api-cli config --admin-token <token>")
    return (
        Sub2APIClient(
            str(cfg.get("base_url") or DEFAULT_BASE_URL),
            admin_token,
            str(cfg.get("proxy_url") or ""),
        ),
        load_codex_token(),
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="sub2api-cli",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="查看 Codex token 所在 sub2api 分组，并快速切换分组/账号调度。",
        epilog=textwrap.dedent(
            """\
            常用:
              sub2api-cli config --admin-token <seei-admin-token>
              sub2api-cli          # 进入方向键交互选择器
              sub2api-cli ui       # 同上
              sub2api-cli status
              sub2api-cli logs     # 最新 20 条请求日志
            """
        ),
    )
    sub = parser.add_subparsers(dest="command")

    config_cmd = sub.add_parser("config", help="写入 seei/sub2api 管理配置")
    config_cmd.add_argument("--base-url", default=None, help=f"默认 {DEFAULT_BASE_URL}")
    config_cmd.add_argument("--proxy-url", default=None, help=f"默认 {DEFAULT_PROXY_URL}；传空字符串可禁用代理")
    config_cmd.add_argument("--admin-token", default=None, help="sub2api Admin API Key，不是 Codex token")

    sub.add_parser("status", help="一行命令展示当前 token、分组和账号")
    sub.add_parser("ui", help="进入方向键交互选择器")
    logs_cmd = sub.add_parser("logs", help="查看请求日志，默认最新 20 条")
    logs_cmd.add_argument("-n", "--limit", type=int, default=20, help="日志条数，默认 20")
    args = parser.parse_args()

    try:
        if args.command == "config":
            configure(args)
            return 0

        client, codex_token = build_client()
        if args.command == "status":
            print_status(client, codex_token)
            return 0
        if args.command == "logs":
            print_logs(client, max(1, args.limit))
            return 0

        curses.wrapper(TUI(client, codex_token).run)
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
