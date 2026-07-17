import requests
import json
import os
import time
import logging
from enum import Enum
from typing import Dict, List, Optional, Tuple, Union
from dataclasses import dataclass, asdict
from common import LogEmoji, PushService, logger


class SmzdmCheckinStatus(Enum):
    """什么值得买签到状态"""

    SUCCESS = 0
    REPEAT = 1
    FAILURE = -2


class SmzdmConfig:
    """什么值得买配置"""

    ENV_COOKIES = "SMZDM_COOKIES"
    ENV_PUSH_KEY = "PUSHDEER_SENDKEY"

    """什么值得买域名"""
    DOMAIN = "zhiyou.smzdm.com"

    """什么值得买主页"""
    REFERER = "https://www.smzdm.com/"

    def __init__(self):
        self.push_key: str = ""
        self.cookies_list: List[str] = []
        self._load_config()

    def _load_config(self) -> None:
        """加载配置"""
        push_key_env: Optional[str] = os.environ.get(self.ENV_PUSH_KEY)
        raw_cookies_env: Optional[str] = os.environ.get(self.ENV_COOKIES)

        if not push_key_env:
            logger.warning(f"{LogEmoji.WARNING} 环境变量 '{self.ENV_PUSH_KEY}' 未设置。")
            self.push_key = ""
        else:
            self.push_key = push_key_env

        if not raw_cookies_env:
            logger.warning(f"{LogEmoji.WARNING} 环境变量 '{self.ENV_COOKIES}' 未设置。")
            self.cookies_list = []
        else:
            self.cookies_list = [cookie.strip() for cookie in raw_cookies_env.split("&") if cookie.strip()]
            if not self.cookies_list:
                raise ValueError(f"环境变量 '{self.ENV_COOKIES}' 已设置，但未包含任何有效的 Cookie。")

        logger.info(f"{LogEmoji.INFO} 什么值得买共加载了 {len(self.cookies_list)} 个 Cookie 用于签到。")
        logger.info(f"{LogEmoji.INFO} 当前 {self.ENV_PUSH_KEY} {'已设置' if push_key_env else '未设置'}。")


class SmzdmAPI:
    """什么值得买 API"""

    CHECKIN_URL = "/user/checkin/jsonp_checkin"

    def __init__(self, cookie_index: int = 0):
        self.cookie_index: int = cookie_index
        self.domain: str = SmzdmConfig.DOMAIN
        self.referer: str = SmzdmConfig.REFERER
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/102.0.0.0 Safari/537.36",
            }
        )

    def __del__(self):
        """关闭 session"""
        self.close()

    def close(self) -> None:
        """关闭 session"""
        if hasattr(self, "session"):
            try:
                self.session.close()
            except Exception as e:
                logger.error(f"{LogEmoji.ERROR} 关闭 session 时发生错误: {e}")

    def __enter__(self):
        """进入上下文管理器"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """退出上下文管理器"""
        self.close()
        return False

    def _log(self, level: str, emoji: str, message: str, force: bool = False) -> None:
        """统一日志输出方法"""
        log_message = f"{LogEmoji.COOKIE}[{self.cookie_index}] {LogEmoji.DOMAIN}[{self.domain}] {emoji} {message}"

        if force:
            if level == "info":
                logger.info(log_message)
            elif level == "warning":
                logger.warning(log_message)
            elif level == "error":
                logger.error(log_message)

    def _get_full_url(self, path: str) -> str:
        """获取完整 URL"""
        return f"https://{self.domain}{path}"

    def checkin(self, cookie: str) -> Dict[str, Union[str, SmzdmCheckinStatus]]:
        """执行签到"""
        timestamp = round(int(time.time() * 1000))
        url = f"{self._get_full_url(self.CHECKIN_URL)}?_={timestamp}"

        headers = {
            "Cookie": cookie,
            "Referer": self.referer,
        }

        result = {
            "status": "签到失败",
            "points": "0",
            "add_point": "0",
            "checkin_num": "",
            "continue_days": "",
            "message": "",
            "code": SmzdmCheckinStatus.FAILURE,
        }

        try:
            response = self.session.get(url, headers=headers, timeout=(60, 120))

            if not response.ok:
                self._log("warning", LogEmoji.WARNING, f"签到请求失败，状态码 {response.status_code}", force=True)
                result["message"] = f"HTTP 状态码 {response.status_code}"
                return result

            data = response.json()
            error_code = data.get("error_code", -2)
            error_msg = data.get("error_msg", "无消息字段")

            if error_code == SmzdmCheckinStatus.SUCCESS.value:
                # error_code == 0 时，需进一步通过 add_point 区分首次签到和重复签到
                checkin_data = data.get("data", {})
                add_point = int(checkin_data.get("add_point", 0))
                checkin_num = str(checkin_data.get("checkin_num", ""))
                continue_days = str(checkin_data.get("continue_checkin_days", ""))
                point = str(checkin_data.get("point", 0))

                result["checkin_num"] = checkin_num
                result["continue_days"] = continue_days
                result["add_point"] = str(add_point)

                if add_point > 0:
                    # 首次签到成功，获得了新积分
                    self._log("info", LogEmoji.SUCCESS, f"签到成功, 新增 {add_point} 积分, 连续 {continue_days} 天, 总签到 {checkin_num} 次", force=True)
                    result["code"] = SmzdmCheckinStatus.SUCCESS
                    result["status"] = "签到成功"
                    result["points"] = str(add_point)
                    result["message"] = f"新增{add_point}积分, 连续{continue_days}天"
                else:
                    # 重复签到（今日已领过积分）
                    self._log("info", LogEmoji.REPEAT, f"重复签到, 连续 {continue_days} 天, 总签到 {checkin_num} 次", force=True)
                    result["code"] = SmzdmCheckinStatus.REPEAT
                    result["status"] = "重复签到"
                    result["points"] = "0"
                    result["message"] = f"连续{continue_days}天, 总签到{checkin_num}次"
            else:
                # error_code 非 0，签到失败
                self._log("info", LogEmoji.FAIL, f"签到失败: error_code={error_code}, error_msg={error_msg}", force=True)
                result["code"] = SmzdmCheckinStatus.FAILURE
                result["status"] = "签到失败"
                result["message"] = f"error_code={error_code}, {error_msg}"

        except requests.exceptions.RequestException as e:
            self._log("error", LogEmoji.ERROR, f"签到请求网络错误: {e}", force=True)
            result["message"] = f"网络请求失败: {e}"
        except (json.JSONDecodeError, ValueError) as e:
            self._log("error", LogEmoji.ERROR, f"签到响应解析失败: {e}", force=True)
            result["message"] = f"响应解析失败: {e}"

        return result


@dataclass()
class SmzdmCheckinResult:
    """什么值得买签到结果"""

    cookie_index: int
    status: str = "签到失败"
    points: str = "0"
    checkin_num: str = ""
    continue_days: str = ""
    message: str = ""
    code: SmzdmCheckinStatus = SmzdmCheckinStatus.FAILURE

    def to_dict(self) -> Dict[str, Union[str, SmzdmCheckinStatus]]:
        result_dict = asdict(self)
        return result_dict


class SmzdmChecker:
    """什么值得买签到"""

    def __init__(self, config: SmzdmConfig):
        self.config = config
        self.results: List[SmzdmCheckinResult] = []

    def checkin_all(self):
        """执行所有签到任务"""
        cookie_count = len(self.config.cookies_list)
        logger.info(f"{LogEmoji.INFO} 什么值得买共 {cookie_count} 个任务")

        for cookie_idx, cookie in enumerate(self.config.cookies_list, 1):
            logger.info(f"{LogEmoji.START} ========== 开始处理什么值得买 Cookie {cookie_idx} ==========")

            with SmzdmAPI(cookie_idx) as api:
                checkin_result = api.checkin(cookie)

            result = SmzdmCheckinResult(
                cookie_index=cookie_idx,
                status=checkin_result["status"],
                points=checkin_result["points"],
                checkin_num=checkin_result.get("checkin_num", ""),
                continue_days=checkin_result.get("continue_days", ""),
                message=checkin_result["message"],
                code=checkin_result.get("code", SmzdmCheckinStatus.FAILURE),
            )
            self.results.append(result)

            emoji = LogEmoji.SUCCESS if result.code == SmzdmCheckinStatus.SUCCESS else (
                LogEmoji.REPEAT if result.code == SmzdmCheckinStatus.REPEAT else LogEmoji.WARNING
            )
            logger.info(f"{LogEmoji.COOKIE}[{cookie_idx}] {emoji} {result.status}")

    def get_results(self) -> List[Dict]:
        """获取所有结果"""
        return [result.to_dict() for result in self.results]

    def format_results(self) -> Tuple[str, str, str]:
        """格式化结果"""
        results = self.get_results()

        success_count = sum(1 for r in results if r["code"] == SmzdmCheckinStatus.SUCCESS)
        repeat_count = sum(1 for r in results if r["code"] == SmzdmCheckinStatus.REPEAT)
        fail_count = sum(1 for r in results if r["code"] == SmzdmCheckinStatus.FAILURE)

        title = f"什么值得买签到, 成功{success_count}, 失败{fail_count}, 重复{repeat_count}"

        send_content_lines = []
        log_content_lines = []
        for i, res in enumerate(results, 1):
            line = f"#{i} P:{res['points']} 连续:{res['continue_days']}天 总:{res['checkin_num']}次 | {res['status']} | {res['message']}"
            send_content_lines.append(line)
            log_content_lines.append(f"#{i} {res['status']}")

        content = "\n".join(send_content_lines)
        log_content = "\n".join(log_content_lines)
        return title, content, log_content


def main():
    """主函数"""
    try:
        # 1. 加载配置
        logger.info(f"{LogEmoji.START} 步骤 1: 加载什么值得买配置")
        config = SmzdmConfig()

        if not config.cookies_list:
            logger.error(f"{LogEmoji.ERROR} 未找到有效的什么值得买 Cookie, 退出程序。")
            title, content = "# 未找到什么值得买 cookies!", ""
        else:
            # 2. 执行签到
            logger.info(f"{LogEmoji.START} 步骤 2: 执行什么值得买签到")
            checker = SmzdmChecker(config)
            checker.checkin_all()

            # 3. 格式化结果
            logger.info(f"{LogEmoji.START} 步骤 3: 格式化什么值得买结果")
            title, content, log_content = checker.format_results()
            logger.info(f"\n{LogEmoji.END}========== 什么值得买签到总结 ==========\n{title}\n{log_content}")

    except Exception as e:
        logger.error(f"{LogEmoji.ERROR} 什么值得买主程序执行过程中发生未预期的错误: {e}")
        title, content, log_content = "# 什么值得买脚本执行出错", str(e), str(e)

    # 4. 发送推送
    logger.info(f"{LogEmoji.START} 步骤 4: 发送什么值得买推送")
    push_key = config.push_key if "config" in locals() else ""
    push_service = PushService(push_key)
    push_service.send(title, content)
    logger.info(f"{LogEmoji.END} 什么值得买签到完成")


if __name__ == "__main__":
    main()
