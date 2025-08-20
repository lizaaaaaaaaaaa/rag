# ====================
# utils/notification.py
# ====================

import asyncio
import aiohttp
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, List, Optional, Any
from datetime import datetime
import json
import logging
from config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

class NotificationManager:
    """通知管理クラス"""
    
    async def send_webhook_notification(
        self,
        webhook_url: str,
        data: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None
    ) -> bool:
        """Webhook通知の送信"""
        try:
            default_headers = {"Content-Type": "application/json"}
            if headers:
                default_headers.update(headers)
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    webhook_url,
                    json=data,
                    headers=default_headers,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status == 200:
                        logger.info(f"Webhook notification sent successfully to {webhook_url}")
                        return True
                    else:
                        logger.error(f"Webhook notification failed: {response.status}")
                        return False
                        
        except Exception as e:
            logger.error(f"Failed to send webhook notification: {e}")
            return False
    
    async def send_slack_notification(
        self,
        message: str,
        channel: Optional[str] = None,
        username: str = "RAG System",
        icon_emoji: str = ":robot_face:"
    ) -> bool:
        """Slack通知の送信"""
        if not settings.slack_webhook_url:
            logger.warning("Slack webhook URL not configured")
            return False
        
        payload = {
            "text": message,
            "username": username,
            "icon_emoji": icon_emoji
        }
        
        if channel:
            payload["channel"] = channel
        
        return await self.send_webhook_notification(settings.slack_webhook_url, payload)
    
    async def send_email_notification(
        self,
        to_emails: List[str],
        subject: str,
        body: str,
        is_html: bool = False
    ) -> bool:
        """メール通知の送信"""
        if not all([settings.email_smtp_server, settings.email_username, settings.email_password]):
            logger.warning("Email settings not configured")
            return False
        
        try:
            msg = MIMEMultipart()
            msg['From'] = settings.email_username
            msg['To'] = ", ".join(to_emails)
            msg['Subject'] = subject
            
            msg.attach(MIMEText(body, 'html' if is_html else 'plain'))
            
            # SMTP接続はブロッキング操作なので、別スレッドで実行
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._send_email_sync, msg, to_emails)
            
            logger.info(f"Email notification sent to {to_emails}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send email notification: {e}")
            return False
    
    def _send_email_sync(self, msg: MIMEMultipart, to_emails: List[str]):
        """同期的なメール送信（内部使用）"""
        with smtplib.SMTP(settings.email_smtp_server, 587) as server:
            server.starttls()
            server.login(settings.email_username, settings.email_password)
            server.send_message(msg, to_addrs=to_emails)
    
    async def send_compliance_alert(
        self,
        alert_type: str,
        details: Dict[str, Any],
        severity: str = "medium"
    ) -> bool:
        """コンプライアンス警告の送信"""
        timestamp = datetime.utcnow().isoformat()
        
        message = f"""
        🚨 Compliance Alert - {alert_type.upper()}
        
        Severity: {severity.upper()}
        Time: {timestamp}
        
        Details:
        {json.dumps(details, indent=2)}
        """
        
        # Slack通知
        slack_sent = await self.send_slack_notification(
            message,
            channel="#compliance-alerts"
        )
        
        # Webhook通知
        webhook_data = {
            "alert_type": alert_type,
            "severity": severity,
            "timestamp": timestamp,
            "details": details
        }
        
        webhook_sent = False
        if settings.notification_webhook_url:
            webhook_sent = await self.send_webhook_notification(
                settings.notification_webhook_url,
                webhook_data
            )
        
        return slack_sent or webhook_sent
    
    async def send_audit_notification(
        self,
        action: str,
        user_id: str,
        resource: str,
        details: Optional[Dict[str, Any]] = None
    ) -> bool:
        """監査通知の送信"""
        timestamp = datetime.utcnow().isoformat()
        
        audit_data = {
            "type": "audit_event",
            "action": action,
            "user_id": user_id,
            "resource": resource,
            "timestamp": timestamp,
            "details": details or {}
        }
        
        message = f"""
        📋 Audit Event: {action}
        
        User: {user_id}
        Resource: {resource}
        Time: {timestamp}
        """
        
        if details:
            message += f"\nDetails: {json.dumps(details, indent=2)}"
        
        # 重要な監査イベントの場合はSlackとWebhookの両方に送信
        critical_actions = ["DELETE", "BULK_DELETE", "ADMIN_ACCESS", "PRIVILEGE_ESCALATION"]
        
        if action in critical_actions:
            slack_sent = await self.send_slack_notification(
                message,
                channel="#audit-alerts"
            )
        else:
            slack_sent = True  # 重要でない場合はSlackをスキップ
        
        webhook_sent = False
        if settings.notification_webhook_url:
            webhook_sent = await self.send_webhook_notification(
                settings.notification_webhook_url,
                audit_data
            )
        
        return slack_sent and webhook_sent

# シングルトンインスタンス
notification_manager = NotificationManager()

# 便利関数
async def send_compliance_alert(alert_type: str, details: Dict[str, Any], severity: str = "medium") -> bool:
    """コンプライアンス警告送信（便利関数）"""
    return await notification_manager.send_compliance_alert(alert_type, details, severity)

async def send_audit_notification(action: str, user_id: str, resource: str, details: Optional[Dict[str, Any]] = None) -> bool:
    """監査通知送信（便利関数）"""
    return await notification_manager.send_audit_notification(action, user_id, resource, details)