"""09 集成：OAuth2 Provider 客户端（蓝图 09 oauth 段）。

OAuthProvider 基类 + Google/Outlook 子类；build_auth_url / fetch_token / refresh / revoke。
HTTP 走 12 HttpClient（超时/重试/熔断），token 端点表单编码（data）。
"""

from urllib.parse import urlencode

from pydantic import BaseModel

from app.core.config import get_settings
from app.core.exceptions import AppException, ErrorCode
from app.core.http_client import HttpClient


class TokenData(BaseModel):
    """OAuth token 交换结果（蓝图 09）。"""

    access_token: str
    refresh_token: str | None = None
    expires_in: int
    scope: str | None = None
    account_identifier: str


class OAuthProvider:
    """OAuth2 协议客户端基类，按 provider 子类化。"""

    authorization_endpoint: str = ""
    token_endpoint: str = ""
    revocation_endpoint: str | None = None
    userinfo_endpoint: str = ""
    scopes: list[str] = []

    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret

    def build_auth_url(self, state: str, redirect_uri: str) -> str:
        """构造授权 URL（redirect_uri 原样透传，不回跳）。"""
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.scopes),
            "state": state,
            "access_type": "offline",
        }
        return f"{self.authorization_endpoint}?{urlencode(params)}"

    async def fetch_token(self, code: str, redirect_uri: str) -> TokenData:
        """授权码 → access token + 账号标识（userinfo）。"""
        data = await self._token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }
        )
        return self._to_token_data(data)

    async def refresh(self, refresh_token: str) -> TokenData:
        """refresh_token → 新 access token。"""
        data = await self._token_request(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }
        )
        return self._to_token_data(data)

    async def revoke(self, token: str) -> None:
        """撤销 access token（无 revocation 端点则跳过）。"""
        if not self.revocation_endpoint:
            return
        await HttpClient().request(
            "POST", self.revocation_endpoint,
            data={"token": token},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            fallback=lambda: None,
        )

    async def _token_request(self, form: dict) -> dict:
        resp = await HttpClient().request(
            "POST", self.token_endpoint,
            data=form,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15, retries=1, fallback=lambda: None,
        )
        if resp is None:
            raise AppException(ErrorCode.EXTERNAL_SERVICE_ERROR, "OAuth 授权服务器不可达", status_code=502)
        body = resp.json()
        if "error" in body or "access_token" not in body:
            raise AppException(
                ErrorCode.INTEGRATION_INVALID,
                f"授权失败: {body.get('error_description') or body.get('error', 'unknown')}",
            )
        return body

    def _to_token_data(self, body: dict) -> TokenData:
        return TokenData(
            access_token=body["access_token"],
            refresh_token=body.get("refresh_token"),
            expires_in=int(body.get("expires_in", 3600)),
            scope=body.get("scope"),
            account_identifier=self._account_identifier(body),
        )

    def _account_identifier(self, body: dict) -> str:
        """默认用 token 端点响应里的可辨识字段；子类可覆盖为 userinfo 调用。"""
        return body.get("email") or body.get("sub") or body.get("user_id") or "unknown"


class GoogleOAuthProvider(OAuthProvider):
    authorization_endpoint = "https://accounts.google.com/o/oauth2/v2/auth"
    token_endpoint = "https://oauth2.googleapis.com/token"
    revocation_endpoint = "https://oauth2.googleapis.com/revoke"
    scopes = ["openid", "email", "profile"]


class OutlookOAuthProvider(OAuthProvider):
    authorization_endpoint = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
    token_endpoint = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
    scopes = ["User.Read"]


def get_provider(name: str) -> OAuthProvider:
    """按 provider 名实例化（client_id/secret 从 settings 读，蓝图 09 PROVIDERS 注册表）。"""
    s = get_settings()
    if name == "google":
        return GoogleOAuthProvider(s.google_oauth_client_id, s.google_oauth_client_secret)
    if name == "outlook":
        return OutlookOAuthProvider(s.outlook_oauth_client_id, s.outlook_oauth_client_secret)
    raise AppException(ErrorCode.NOT_FOUND, f"不支持的 provider: {name}", status_code=404)
