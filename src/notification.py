import os
import telegram
import asyncio
from datetime import datetime
from typing import Dict
import json
from pathlib import Path

class NotificationHandler:
    def __init__(self):
        self.bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.chat_id = os.getenv('TELEGRAM_CHAT_ID')
        
        print("Initializing NotificationHandler:")
        print(f"Bot token exists: {bool(self.bot_token)}")
        print(f"Chat ID exists: {bool(self.chat_id)}")
        
        if not self.bot_token or not self.chat_id:
            print("WARNING: Missing Telegram credentials!")
            self.bot = None
        else:
            try:
                self.bot = telegram.Bot(token=self.bot_token)
                print("Successfully created Telegram bot instance")
            except Exception as e:
                print(f"Failed to create Telegram bot: {str(e)}")
                self.bot = None

    async def send_notification(self, message: str):
        """Send a Telegram message"""
        if not self.bot:
            return
        
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode='HTML'
            )
        except Exception as e:
            print(f"Failed to send notification: {str(e)}")

    def send_opportunity(self, opportunity: Dict):
        """Send arbitrage opportunity notification"""
        if not self.bot:
            print("No Telegram bot available")
            return
            
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        message = (
            f"🔥 New Arbitrage Opportunity! ({timestamp})\n\n"
            f"Pair: {opportunity['symbol']}\n"
            f"Direction: {opportunity['direction']}\n"
            f"Spread: {opportunity['best_spread']}%\n"
            f"Executable Volume: {opportunity['executable_volume']} USDT\n\n"
            f"Bitget: {opportunity['bitget_ask']}/{opportunity['bitget_bid']}\n"
            f"MEXC: {opportunity['mexc_ask']}/{opportunity['mexc_bid']}\n\n"
            f"Networks: {', '.join(opportunity['supported_networks'])}\n"
            f"Min Liquidity Score: {opportunity['min_liquidity_score']}"
        )
        
        asyncio.run(self.send_notification(message))
