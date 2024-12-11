import os
import telegram
import asyncio
from datetime import datetime
from typing import Dict
import json
from pathlib import Path

class NotificationHandler:
    def __init__(self):
        print("\n=== Notification Handler Initialization ===")
        self.bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.chat_id = os.getenv('TELEGRAM_CHAT_ID')
        
        print(f"Bot token exists: {bool(self.bot_token)}")
        print(f"Chat ID exists: {bool(self.chat_id)}")
        print(f"Chat ID value: {self.chat_id}")  # Print actual chat ID
        
        if not self.bot_token or not self.chat_id:
            print("ERROR: Missing Telegram credentials!")
            self.bot = None
        else:
            try:
                self.bot = telegram.Bot(token=self.bot_token)
                print("Successfully created Telegram bot instance")
                
                # Try to get bot info
                asyncio.run(self.verify_bot())
            except Exception as e:
                print(f"Failed to create Telegram bot: {str(e)}")
                self.bot = None

    async def verify_bot(self):
        """Verify bot credentials"""
        try:
            bot_info = await self.bot.get_me()
            print(f"Bot verification successful: @{bot_info.username}")
        except Exception as e:
            print(f"Bot verification failed: {str(e)}")

    async def send_notification(self, message: str):
        """Send a Telegram message"""
        if not self.bot:
            print("ERROR: No Telegram bot available")
            return
        
        try:
            print(f"Attempting to send message to chat ID: {self.chat_id}")
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode='HTML'
            )
            print("Message sent successfully")
        except Exception as e:
            print(f"Failed to send notification: {str(e)}")
            print(f"Full error: {traceback.format_exc()}")

    def send_opportunity(self, opportunity: Dict):
        """Send arbitrage opportunity notification"""
        print("\n=== Sending Opportunity ===")
        if not self.bot:
            print("ERROR: No Telegram bot available")
            return
            
        try:
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
            
            print("Message prepared, attempting to send...")
            asyncio.run(self.send_notification(message))
        except Exception as e:
            print(f"Error in send_opportunity: {str(e)}")
            import traceback
            print(f"Full error: {traceback.format_exc()}")
