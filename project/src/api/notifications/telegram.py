"""Telegram notifications for critical alerts."""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Send notifications to Telegram."""

    def __init__(self):
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self.enabled = bool(self.bot_token and self.chat_id)

        if not self.enabled:
            logger.warning(
                "Telegram notifications disabled: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set"
            )

    async def send_message(
        self,
        message: str,
        parse_mode: str = "HTML",
        disable_notification: bool = False,
    ) -> bool:
        """Send message to Telegram."""
        if not self.enabled:
            logger.debug(f"Telegram disabled, would send: {message}")
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(
                    url,
                    json={
                        "chat_id": self.chat_id,
                        "text": message,
                        "parse_mode": parse_mode,
                        "disable_notification": disable_notification,
                    }
                )
                response.raise_for_status()
                logger.info("Telegram message sent successfully")
                return True

        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False

    async def send_q21_alert(
        self,
        q21_current: float,
        q21_forecast: float | None,
        exceedance_probability: float | None,
        timestamp: datetime,
    ):
        """Send Q21 alert to Telegram."""
        message = f"""🚨 <b>НЕФТЕКОД АЛЕРТ</b>

⚠️ Q21 превысил предел 10 ppm

📊 <b>Текущие показатели:</b>
• Q21: <b>{q21_current:.2f} ppm</b> (предел: 10.0)
• Прогноз +1ч: <b>{q21_forecast:.2f} ppm</b> {f'({q21_forecast - q21_current:+.2f})' if q21_forecast else ''}
• Вероятность превышения: <b>{exceedance_probability * 100:.0f}%</b> {'' if exceedance_probability else ''}

🕐 Время: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}

🔍 <b>Рекомендуется:</b>
• Проверить анализатор Q21
• Проверить режим установки
• Оценить корректирующие действия
"""
        await self.send_message(message)

    async def send_anomaly_alert(
        self,
        description: str,
        anomaly_score: float,
        suspicious_signals: list[str],
        timestamp: datetime,
    ):
        """Send anomaly detection alert."""
        signals_text = "\n".join([f"  • {sig}" for sig in suspicious_signals[:5]])

        message = f"""⚠️ <b>АНОМАЛИЯ ОБНАРУЖЕНА</b>

📉 {description}

Оценка аномалии: <b>{anomaly_score:.2f}</b>

<b>Подозрительные сигналы:</b>
{signals_text}

🕐 {timestamp.strftime('%Y-%m-%d %H:%M:%S')}

💡 Рекомендуется проверить показания датчиков
"""
        await self.send_message(message)

    async def send_system_status(
        self,
        status: str,
        details: str,
    ):
        """Send system status notification."""
        emoji = "✅" if status == "ok" else "🔴"
        message = f"""{emoji} <b>Статус системы</b>

{details}

🕐 {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}
"""
        await self.send_message(message, disable_notification=(status == "ok"))


# Global notifier instance
_notifier = TelegramNotifier()


def get_telegram_notifier() -> TelegramNotifier:
    """Get global Telegram notifier."""
    return _notifier
