from typing import Optional


class UserAgentService:
    """Service for parsing User-Agent headers into structured device metadata."""

    @staticmethod
    def parse(ua_string: Optional[str]) -> tuple[str, str, str]:
        """Parse User-Agent string into (device_name, browser, os)."""
        if not ua_string:
            return "Unknown Device", "Unknown Browser", "Unknown OS"

        ua = ua_string.lower()

        # OS detection
        if "macintosh" in ua or "mac os" in ua:
            os_name = "macOS"
        elif "iphone" in ua or "ipad" in ua:
            os_name = "iOS"
        elif "android" in ua:
            os_name = "Android"
        elif "windows" in ua:
            os_name = "Windows"
        elif "linux" in ua:
            os_name = "Linux"
        else:
            os_name = "Unknown OS"

        # Browser detection
        if "edg/" in ua or "edge" in ua:
            browser_name = "Edge"
        elif "chrome" in ua and "safari" in ua and "edg" not in ua:
            browser_name = "Chrome"
        elif "firefox" in ua:
            browser_name = "Firefox"
        elif "safari" in ua and "chrome" not in ua:
            browser_name = "Safari"
        elif "opera" in ua or "opr/" in ua:
            browser_name = "Opera"
        else:
            browser_name = "Browser"

        device_name = f"{browser_name} on {os_name}"
        return device_name, browser_name, os_name


def parse_user_agent(ua_string: Optional[str]) -> tuple[str, str, str]:
    """Helper alias for UserAgentService.parse."""
    return UserAgentService.parse(ua_string)
